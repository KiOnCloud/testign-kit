"""Sequential job queue between the console (tester) and the attached Claude Code session (agent).

States::

    queued ──wait──▶ offered ──claim──▶ running ◀──answer── needs-input
       │                │                  │  └──ask──────────▲
       │                │                  └──done──▶ done | failed
       │                └─(not claimed in time, or its held call was replaced)─▶ queued
       ├──cancel──▶ cancelled
       └──(server start)──▶ failed: server-stopped

Any other transition is refused with 409. A failed job is never resumed. Only one job is open
(offered, running or needs-input) at a time. The agent's held calls (``wait`` and ``ask``) are
replaced by a newer call from the same session; a job offered to a replaced call goes back to the
queue. Records live in ``~/.testign-kit/console/jobs/<id>.json`` (mode 0600).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .. import decisions, webtest
from .server import ApiError

# The report language may still be Vietnamese; the console itself speaks English or Japanese.
REPORT_LANGS = ("vi", "en", "ja")
UI_LANGS = ("en", "ja")
OPEN = ("offered", "running", "needs-input")
CAPABILITIES = ("chrome", "figma", "backlog")
ACTIVE = ("queued", *OPEN)
FINISHED = ("done", "failed", "cancelled")
TRANSITIONS = {
    ("queued", "offered"), ("queued", "cancelled"), ("queued", "failed"),
    ("offered", "queued"), ("offered", "running"), ("offered", "failed"),
    ("running", "needs-input"), ("running", "done"), ("running", "failed"),
    ("needs-input", "running"), ("needs-input", "failed"),
}
FAIL_REASONS = ("server-stopped", "session-lost", "not-closed", "marked", "revision-moved", "agent", "not-confirmed")
# Jobs that count tab age from their creation, because the agent may queue them itself.
WEB_KINDS = ("webtest-run", "suite-generate")
# The kinds the agent may queue from the chat (``console queue``).
AGENT_KINDS = ("suite-generate", "webtest-run")
STALE_PROGRESS = 120.0

OFFER_TIMEOUT = 60.0
SILENT_NO_JOB = 60.0
SILENT_WITH_JOB = 15 * 60.0
HELD_DEFAULT = 100.0
HELD_MAX = 540.0
PRUNE_AGE = 7 * 24 * 3600.0
KEEP_FINISHED = 50
TEXT_CAP = 8000
DATA_CAP = 200_000

_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")
_BIDI = re.compile("[‪-‮⁦-⁩‎‏؜]")
_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SESSION = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_SLUG = re.compile(r"^[\w-]{1,80}$", re.UNICODE)
_ROW_ID = re.compile(r"^[BRQ]\d+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_job_id() -> str:
    return "j" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def bad(message: str, code: str = "bad-request") -> ApiError:
    return ApiError(400, code, message)


def fingerprint(token: str | None) -> str | None:
    """A short, stable label for a browser session; the token itself is never stored."""
    return hashlib.sha256(token.encode()).hexdigest()[:12] if token else None


# text checks ----------------------------------------------------------------------------------
def agent_text(value: Any, field: str, *, cap: int = TEXT_CAP, required: bool = True) -> str | None:
    """Agent-authored text: bounded, no control characters except newline, no bidi controls."""
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise bad(f"{field} must be non-empty text")
    if len(value) > cap:
        raise bad(f"{field} is longer than {cap} characters")
    if _CONTROL.search(value) or _BIDI.search(value):
        raise bad(f"{field} holds control or bidi characters")
    return value


def data_text(value: Any, field: str, *, cap: int = DATA_CAP) -> str:
    """Quotes, decisions, anchors and diff text are data: only type and size are checked."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise bad(f"{field} must be text")
    if len(value) > cap:
        raise bad(f"{field} is too long")
    return value


def _str_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise bad(f"{field} must be a list of text")
    return [data_text(v, field) for v in value]


# asks -----------------------------------------------------------------------------------------
def validate_ask(ask: Any) -> dict:
    if not isinstance(ask, dict):
        raise bad("ask must be an object")
    kind = ask.get("type")
    ask_id = ask.get("id")
    if not isinstance(ask_id, str) or not _ID.match(ask_id):
        raise bad("ask id must be 1 to 64 letters, digits, dot, dash or underscore")
    if kind == "questions":
        questions = ask.get("questions")
        if not isinstance(questions, list) or not 1 <= len(questions) <= 4:
            raise bad("questions must hold 1 to 4 questions")
        clean = []
        for i, q in enumerate(questions, 1):
            if not isinstance(q, dict):
                raise bad(f"question {i} must be an object")
            options = q.get("options")
            if not isinstance(options, list) or not 2 <= len(options) <= 4:
                raise bad(f"question {i} needs 2 to 4 options")
            opts = []
            for o in options:
                if not isinstance(o, dict):
                    raise bad(f"question {i} has an option that is not an object")
                opts.append({"label": agent_text(o.get("label"), "option label", cap=200),
                             "description": agent_text(o.get("description"), "option description",
                                                       required=False) or ""})
            labels = [o["label"] for o in opts]
            if len(set(labels)) != len(labels):
                raise bad(f"question {i} has duplicate option labels")
            clean.append({
                "question": agent_text(q.get("question"), "question"),
                "header": agent_text(q.get("header"), "header", cap=40, required=False) or "",
                "options": opts,
                "multiSelect": bool(q.get("multiSelect")),
                "other": q.get("other") if q.get("other") in ("line", "multiline") else "line",
            })
        return {"type": kind, "id": ask_id, "body": agent_text(ask.get("body"), "body", required=False),
                "questions": clean}
    if kind == "review-rows":
        rows = ask.get("rows")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
            raise bad("rows must hold 1 to 200 rows")
        clean, seen = [], set()
        for r in rows:
            if not isinstance(r, dict):
                raise bad("every row must be an object")
            row_id = r.get("row")
            if not isinstance(row_id, str) or not _ID.match(row_id) or row_id in seen:
                raise bad("every row needs a unique row id")
            seen.add(row_id)
            clean.append({
                "row": row_id,
                "q": r.get("q") if isinstance(r.get("q"), str) and _ID.match(r["q"]) else None,
                "class": data_text(r.get("class"), "class", cap=200),
                "feature": data_text(r.get("feature"), "feature", cap=500),
                "page": data_text(r.get("page"), "page", cap=500),
                "anchors": _str_list(r.get("anchors"), "anchors"),
                "decision": data_text(r.get("decision"), "decision"),
                "quote": data_text(r.get("quote"), "quote"),
                "quote_lang": r.get("quote_lang") if r.get("quote_lang") in ("ja", "vi", "en") else None,
                "source": data_text(r.get("source"), "source", cap=2000),
                "decided_by": data_text(r.get("decided_by"), "decided_by", cap=200),
                "date": data_text(r.get("date"), "date", cap=40),
            })
        return {"type": kind, "id": ask_id, "body": agent_text(ask.get("body"), "body", required=False),
                "rows": clean}
    if kind == "confirm-diff":
        preview = ask.get("preview")
        if not isinstance(preview, dict) or not isinstance(preview.get("approval"), str):
            raise bad("confirm-diff needs the preview JSON with its approval")
        pages = preview.get("pages")
        if not isinstance(pages, list) or not pages:
            raise bad("confirm-diff preview needs pages")
        clean_pages, writes = [], []
        for p in pages:
            if not isinstance(p, dict) or not all(isinstance(p.get(k), str) for k in ("name", "old_content", "new_content")):
                raise bad("every confirm-diff page needs name, old_content and new_content from wiki-append-preview")
            updated = p.get("updated") if isinstance(p.get("updated"), str) else None
            name = data_text(p["name"], "page name", cap=500)
            old, new = data_text(p["old_content"], "old_content"), data_text(p["new_content"], "new_content")
            writes.append((name, updated, new))
            # The tester sees the diff the server computed from the contents the approval hash covers.
            clean_pages.append({"name": name, "exists": bool(p.get("exists")), "updated": updated,
                                "diff": decisions.page_diff(name, old, new)})
        if not hmac.compare_digest(decisions.approval_hash(writes), preview["approval"]):
            raise bad("the preview's approval does not match its pages; run wiki-append-preview again",
                      "approval-mismatch")
        lists = {k: preview.get(k) if isinstance(preview.get(k), list) else [] for k in
                 ("added", "skipped", "superseded", "index_repaired")}
        return {"type": kind, "id": ask_id, "body": agent_text(ask.get("body"), "body", required=False),
                "preview": {"pages": clean_pages, **lists, "approval": preview["approval"]}}
    if kind == "paste-pages":
        pages = ask.get("pages")
        if not isinstance(pages, list) or not pages:
            raise bad("paste-pages needs pages")
        clean_pages = []
        for p in pages:
            if not isinstance(p, dict):
                raise bad("every page must be an object")
            clean_pages.append({"name": data_text(p.get("name"), "page name", cap=500),
                                "new_content": data_text(p.get("new_content"), "new_content")})
        return {"type": kind, "id": ask_id, "body": agent_text(ask.get("body"), "body", required=False),
                "pages": clean_pages}
    if kind == "sign-in":
        scenario = ask.get("scenario")
        if not isinstance(scenario, str) or not webtest.NAME_RE.match(scenario) or scenario == webtest.NO_SCENARIO:
            raise bad("sign-in needs the scenario's name")
        switching = ask.get("switching_from")
        if switching is not None and (not isinstance(switching, str) or not webtest.NAME_RE.match(switching)):
            raise bad("switching_from must be a scenario name")
        return {"type": kind, "id": ask_id, "body": agent_text(ask.get("body"), "body", required=False),
                "scenario": scenario, "switching_from": switching}
    raise bad("ask type must be questions, review-rows, confirm-diff, paste-pages or sign-in")


def validate_answer(ask: dict, answer: Any) -> Any:
    kind = ask["type"]
    if kind == "questions":
        if not isinstance(answer, list) or len(answer) != len(ask["questions"]):
            raise bad("answer every question")
        out = []
        for q, a in zip(ask["questions"], answer):
            if not isinstance(a, dict):
                raise bad("every answer must be an object")
            selected = a.get("selected") or []
            if not isinstance(selected, list) or not all(isinstance(s, str) for s in selected):
                raise bad("selected must be a list of labels")
            labels = {o["label"] for o in q["options"]}
            if any(s not in labels for s in selected):
                raise bad("selected holds a label that is not an option")
            if not q["multiSelect"] and len(selected) > 1:
                raise bad("this question takes one choice")
            other = a.get("other")
            if other is not None:
                if not isinstance(other, str) or len(other) > 50_000:
                    raise bad("other must be text")
                if q["other"] == "line":
                    other = other.replace("\r", " ").replace("\n", " ")
            if not selected and not (other and other.strip()):
                raise bad("choose an option or write an answer")
            out.append({"selected": selected, **({"other": other} if other else {})})
        return out
    if kind == "review-rows":
        rows = answer.get("rows") if isinstance(answer, dict) else None
        if not isinstance(rows, dict):
            raise bad("answer rows must be an object keyed by row id")
        ids = [r["row"] for r in ask["rows"]]
        if set(rows) != set(ids):
            raise bad("answer every row, and only the rows asked")
        out = {}
        for row_id in ids:
            a = rows[row_id]
            if not isinstance(a, dict) or a.get("action") not in ("write", "skip", "edit"):
                raise bad("every row needs write, skip or edit")
            item: dict[str, Any] = {"action": a["action"]}
            if a["action"] == "edit":
                if "decision" in a:
                    item["decision"] = data_text(a["decision"], "decision")
                if "anchors" in a:
                    item["anchors"] = _str_list(a["anchors"], "anchors")
                if "page" in a:
                    item["page"] = data_text(a["page"], "page", cap=500)
                if len(item) == 1:
                    raise bad("an edited row needs a decision, anchors or page")
            out[row_id] = item
        return {"rows": out}
    if kind == "confirm-diff":
        if not isinstance(answer, dict) or not isinstance(answer.get("confirm"), bool):
            raise bad("answer confirm with true or false")
        return {"confirm": answer["confirm"]}
    if kind == "paste-pages":
        if not isinstance(answer, dict) or answer.get("done") is not True:
            raise bad("answer done: true after pasting the pages")
        return {"done": True}
    if kind == "sign-in":
        if not isinstance(answer, dict) or answer.get("choice") not in ("signed-in", "skip"):
            raise bad("answer signed-in or skip")
        return {"choice": answer["choice"]}
    raise bad("unknown ask type")


# kind checks ----------------------------------------------------------------------------------
class Context:
    """What the kind checks read: config, the ticket listing, templates and git. Injected."""

    def __init__(self, *, cfg: Callable[[], dict], ticket_rx: Callable[[dict], re.Pattern],
                 latest: Callable[[str], dict | None], templates: Callable[[], dict],
                 workbooks: Callable[[str], list[str]], row_ids: Callable[[str], set[str]],
                 usable_repo: Callable[[Any], Path | None],
                 projects: Callable[[], dict] = dict,
                 run_info: Callable[[str], dict | None] = lambda run: None,
                 scenario: Callable[[str, str], dict | None] = lambda project, name: None,
                 scenarios: Callable[[str], list[dict]] = lambda project: [],
                 run_needs_input: Callable[[], int] = lambda: 0,
                 run_finish: Callable[[str], bool] = lambda run: False,
                 suite_info: Callable[[str], dict | None] = lambda suite: None,
                 attach_suite: Callable[[str, str], None] = lambda suite, job: None) -> None:
        self.cfg = cfg
        self.ticket_rx = ticket_rx
        self.latest = latest
        self.templates = templates
        self.workbooks = workbooks
        self.row_ids = row_ids
        self.usable_repo = usable_repo
        # Web test runs: the tester's projects, a run's summary, login scenarios, run-scoped answers.
        self.projects = projects
        self.run_info = run_info
        self.scenario = scenario
        self.scenarios = scenarios
        self.run_needs_input = run_needs_input
        self.run_finish = run_finish
        # Web test suites: a suite's summary, and recording the job that generates its cases.
        self.suite_info = suite_info
        self.attach_suite = attach_suite


def _latest_name(ctx: Context, ticket: Any) -> str:
    if not isinstance(ticket, str) or not ticket:
        raise bad("ticket is required")
    latest = ctx.latest(ticket)
    if latest is None:
        raise ApiError(404, "not-found", "no such ticket, or it has no consistent readable revision")
    return latest["name"]


def _check_survey(ctx: Context, body: dict) -> dict:
    cfg = ctx.cfg()
    ticket = body.get("ticket")
    if not isinstance(ticket, str) or not ctx.ticket_rx(cfg).fullmatch(ticket):
        raise bad("ticket does not match ticket_id_regex")
    repo = ctx.usable_repo(body.get("repo"))
    if repo is None:
        raise bad("repo must be the absolute path of a local git clone")
    params: dict[str, Any] = {"repo": str(repo)}
    for key in ("master_ref", "develop_ref"):
        value = body.get(key)
        if value not in (None, ""):
            if not isinstance(value, str) or not _REF.match(value):
                raise bad(f"{key} is not a valid ref")
            params[key] = value
    if not isinstance(body.get("fetch", False), bool):
        raise bad("fetch must be true or false")
    params["fetch"] = bool(body.get("fetch", False))
    feature = body.get("feature")
    if feature not in (None, ""):
        if not isinstance(feature, str) or not _SLUG.match(feature):
            raise bad("feature must be a short name of letters, digits and dashes")
        params["feature"] = feature
    report_lang = body.get("report_lang") or cfg.get("lang") or "vi"
    if report_lang not in REPORT_LANGS:
        raise bad("report_lang must be vi, ja or en")
    return {"ticket": ticket, "base_revision": None, "params": params, "report_lang": report_lang}


def _check_close(ctx: Context, body: dict) -> dict:
    base = _latest_name(ctx, body.get("ticket"))
    tester = body.get("tester")
    if not isinstance(tester, str) or not tester.strip() or len(tester) > 100 or _CONTROL.search(tester):
        raise bad("tester must be a name of 1 to 100 characters (set it in Settings)", "tester-required")
    return {"ticket": body["ticket"], "base_revision": base, "params": {"tester": tester.strip()}}


def _check_testcase(ctx: Context, body: dict) -> dict:
    ticket = body.get("ticket")
    base = _latest_name(ctx, ticket)
    mode = body.get("mode")
    if mode not in ("write", "trace"):
        raise bad("mode must be write or trace")
    listing = ctx.templates()
    # Only test case templates: a web test template may have no trace column.
    names = [t["name"] for t in listing.get("templates", []) if (t.get("purpose") or "testcase") == "testcase"]
    template = body.get("template")
    if template is not None and template not in names:
        raise bad("template is not registered", "unknown-template")
    if template is None and (mode == "trace" or len(names) > 1):
        raise bad("choose a template", "template-required")
    if not names:
        raise bad("register a template first", "template-required")
    default = listing.get("default") if listing.get("default") in names else names[0]
    params: dict[str, Any] = {"mode": mode, "template": template or default}
    workbook = body.get("workbook")
    if workbook is not None:
        if workbook not in ctx.workbooks(ticket):
            raise bad("workbook is not in the ticket folder", "unknown-workbook")
        params["workbook"] = workbook
    elif mode == "trace":
        raise bad("trace needs a workbook", "workbook-required")
    focus = body.get("focus")
    if focus is not None:
        if not isinstance(focus, list) or not focus or not all(isinstance(f, str) and _ROW_ID.match(f) for f in focus):
            raise bad("focus must be a list of row ids")
        known = ctx.row_ids(ticket)
        if any(f not in known for f in focus):
            raise bad("focus names a row id that is not in the report", "unknown-row")
        params["focus"] = list(dict.fromkeys(focus))
    return {"ticket": ticket, "base_revision": base, "params": params}


def _report_lang(ctx: Context, body: dict) -> str:
    report_lang = body.get("report_lang") or ctx.cfg().get("lang") or "vi"
    if report_lang not in REPORT_LANGS:
        raise bad("report_lang must be vi, ja or en")
    return report_lang


def run_target(ctx: Context, body: dict) -> dict:
    """Base URL, project, hosts and template of a new run, as the console's error codes."""
    try:
        return webtest.check_run_target(ctx.projects(), ctx.templates(), body.get("base_url"), body.get("project"),
                                        body.get("template"))
    except webtest.TargetError as exc:
        raise bad(str(exc), exc.code) from None


def _check_webtest_run(ctx: Context, body: dict) -> dict:
    run = body.get("run")
    info = ctx.run_info(run) if isinstance(run, str) and webtest.RUN_ID_RE.match(run) else None
    if info is None:
        raise bad("no such run", "unknown-run")
    if not info.get("confirmed"):
        raise bad("the run's plan is not confirmed yet", "plan-not-confirmed")
    tester = body.get("tester")
    if not isinstance(tester, str) or not tester.strip() or len(tester) > 100 or _CONTROL.search(tester):
        raise bad("tester must be a name of 1 to 100 characters (set it in Settings)", "tester-required")
    mode = body.get("mode") or "run"
    if mode not in ("run", "export"):
        raise bad("mode must be run or export")
    return {"ticket": info.get("ticket"), "base_revision": None,
            "params": {"run": run, "tester": tester.strip(), "mode": mode},
            "report_lang": info.get("report_lang") or _report_lang(ctx, body)}


def _check_suite_generate(ctx: Context, body: dict) -> dict:
    """The agent writes the cases of a suite born ``generating`` from a Figma table or a survey report."""
    suite = body.get("suite")
    info = ctx.suite_info(suite) if isinstance(suite, str) else None
    if info is None:
        raise bad("no such suite", "unknown-suite")
    if info.get("state") != "generating":
        raise bad("the suite is not waiting for generated cases", "suite-not-generating")
    if info.get("generate_job_active"):
        raise bad("another job is already generating this suite", "suite-busy")
    source = info.get("source") or {}
    if source.get("kind") not in ("figma", "backlog"):
        raise bad("only Figma and Backlog suites are generated by the agent", "bad-source")
    params: dict[str, Any] = {"suite": suite, "source": source}
    ticket = source.get("ticket") if source.get("kind") == "backlog" else None
    # The source names its report revision itself, so a later survey of the ticket does not stop the job.
    return {"ticket": ticket, "base_revision": None, "params": params, "report_lang": _report_lang(ctx, body)}


# One entry per job kind: the parameter check. Adding a kind adds one entry here.
KINDS: dict[str, Callable[[Context, dict], dict]] = {
    "survey": _check_survey,
    "close": _check_close,
    "testcase": _check_testcase,
    "webtest-run": _check_webtest_run,
    "suite-generate": _check_suite_generate,
}


# store ----------------------------------------------------------------------------------------
class FileStore:
    def __init__(self, folder: Path, writer: Callable[[Path, str], None]) -> None:
        self.folder = folder
        self.writer = writer

    def load_all(self) -> list[dict]:
        jobs = []
        try:
            files = sorted(self.folder.glob("j*.json"))
        except OSError:
            return jobs
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("id") == path.stem:
                jobs.append(data)
        return jobs

    def save(self, job: dict) -> None:
        self.writer(self.folder / f"{job['id']}.json", json.dumps(job, ensure_ascii=False, indent=2) + "\n")

    def delete(self, job_id: str) -> None:
        try:
            (self.folder / f"{job_id}.json").unlink()
        except OSError:
            pass


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def load_all(self) -> list[dict]:
        return [json.loads(json.dumps(j)) for j in self.data.values()]

    def save(self, job: dict) -> None:
        self.data[job["id"]] = json.loads(json.dumps(job))

    def delete(self, job_id: str) -> None:
        self.data.pop(job_id, None)


# tab age --------------------------------------------------------------------------------------
NO_OLDER_TAB = "no console tab is older than this job, so no one can answer it; queue the job again"


def answer_cutoff(job: dict) -> float | None:
    """Tabs created at or after this time cannot answer the job: a web job counts from its creation
    (the agent can queue those itself), any other job from its start."""
    value = job.get("created_ts") if job["kind"] in WEB_KINDS else job.get("started_ts")
    return value if isinstance(value, (int, float)) else None


def tab_can_answer(cutoff: float | None, created: float | None) -> bool:
    """A tab created at ``created`` may answer what has the ``cutoff``; no cutoff, no limit."""
    return cutoff is None or (created is not None and created < cutoff)


# the bridge -----------------------------------------------------------------------------------
class Bridge:
    """Queue, sessions and held calls. Every method takes the lock; held calls wait on ``cond``."""

    def __init__(self, store, ctx: Context, *, clock: Callable[[], float] = time.monotonic,
                 on_change: Callable[[], None] | None = None) -> None:
        self.store = store
        self.ctx = ctx
        self.clock = clock
        self.cond = threading.Condition()
        self.jobs: dict[str, dict] = {}
        self.change = 0
        self.attached: str | None = None
        self.last_contact: float | None = None
        self.last_contact_iso: str | None = None
        self.held: dict[str, int] = {}  # session → token of its newest held call
        self._held_open: dict[str, int] = {}  # session → number of held calls still running
        self.waiting: set[int] = set()  # tokens of open held wait calls
        self.offered_to: dict[str, int] = {}  # job id → held token it was offered to
        self.offered_at: dict[str, float] = {}
        self._token = 0
        self._seq = 0
        self.released: set[str] = set()  # sessions the tester released or another session took over
        self.progress_at: dict[str, float] = {}  # web job id → clock of its claim or last progress line
        self.closed = False
        self.on_change = on_change
        # Creation times of the browser sessions; None when unknown (then nothing is refused for age).
        self.sessions: Callable[[], list[float]] | None = None
        # The tools the attached session said it has ({name: bool, "at"}); None until it reports them.
        self.capabilities: dict | None = None

    # persistence ------------------------------------------------------------------------------
    def startup(self) -> None:
        """Load records; open and queued jobs fail as ``server-stopped``; prune old ones."""
        with self.cond:
            for job in self.store.load_all():
                if job.get("state") in ACTIVE:
                    job["state"] = "failed"
                    # A kind the console no longer runs (the web test plan job) is named as such.
                    job["reason"] = "server-stopped" if job.get("kind") in KINDS else "retired-kind"
                    job["result"] = "failed"
                    job["finished_at"] = now_iso()
                    self.store.save(job)
                self.jobs[job["id"]] = job
            self._seq = max([j.get("seq") or 0 for j in self.jobs.values()] + [0])
            self._prune()

    def _prune(self) -> None:
        finished = sorted((j for j in self.jobs.values() if j.get("state") in FINISHED),
                          key=lambda j: (j.get("created_at") or "", j.get("seq") or 0), reverse=True)
        cutoff = datetime.now(timezone.utc).timestamp() - PRUNE_AGE
        for i, job in enumerate(finished):
            try:
                created = datetime.fromisoformat(job.get("finished_at") or job.get("created_at")).timestamp()
            except (TypeError, ValueError):
                created = 0
            if i >= KEEP_FINISHED or created < cutoff:
                self.jobs.pop(job["id"], None)
                self.store.delete(job["id"])

    def _save(self, job: dict) -> None:
        self.store.save(job)
        self.change += 1
        self.cond.notify_all()
        if self.on_change:
            self.on_change()

    def _move(self, job: dict, to: str, **fields: Any) -> None:
        if (job["state"], to) not in TRANSITIONS:
            raise ApiError(409, "conflict", f"a {job['state']} job cannot become {to}")
        job["state"] = to
        job.update(fields)
        if to in FINISHED:
            job["finished_at"] = now_iso()
            self.progress_at.pop(job["id"], None)
        if to != "offered":
            self.offered_to.pop(job["id"], None)
            self.offered_at.pop(job["id"], None)
        self._save(job)

    def _fail(self, job: dict, reason: str) -> None:
        if job["ask"] is not None:
            job["asked"].append({**self._ask_summary(job["ask"]), "outcome": "unanswered"})
            job["ask"] = None
        self._move(job, "failed", reason=reason, result="failed")

    # views ------------------------------------------------------------------------------------
    def busy(self) -> bool:
        with self.cond:
            return any(j["state"] in ACTIVE for j in self.jobs.values())

    def open_job(self) -> dict | None:
        return next((j for j in self.jobs.values() if j["state"] in OPEN), None)

    def _queued(self) -> list[dict]:
        return sorted((j for j in self.jobs.values() if j["state"] == "queued"), key=lambda j: j["created_at"])

    def _silence(self) -> float | None:
        if self.attached is None:
            return None
        if self._held_open.get(self.attached, 0) > 0:
            return 0.0
        return self.clock() - (self.last_contact or self.clock())

    def _job_silence(self, job: dict) -> float | None:
        """Seconds a running job has been quiet. A web job counts from its last progress line, so a
        long held call (a sign-in question, a wait for answers) does not hide a stalled run."""
        if job["kind"] in WEB_KINDS:
            at = self.progress_at.get(job["id"])
            return None if at is None else self.clock() - at
        return self._silence()

    def _silent(self, job: dict | None) -> bool:
        if job is None or job["state"] == "offered":
            return False
        silence = self._job_silence(job)
        return silence is not None and silence >= SILENT_WITH_JOB

    def _stale(self, job: dict | None) -> bool:
        if job is None or job["kind"] not in WEB_KINDS or job["state"] == "offered":
            return False
        silence = self._job_silence(job)
        return silence is not None and silence >= STALE_PROGRESS

    def state_view(self, sessions: list[float] | None = None) -> dict:
        with self.cond:
            self._tick()
            open_job = self.open_job()
            silence = self._silence()
            silent = self._silent(open_job)
            try:
                run_input = int(self.ctx.run_needs_input())
            except Exception:  # noqa: BLE001 - an unreadable run never breaks the state poll
                run_input = 0
            return {
                "agent": {
                    "attached": self.attached is not None,
                    "waiting": bool(self.waiting),
                    "last_contact": self.last_contact_iso,
                    "silent_seconds": int(silence) if silence is not None else None,
                    "capabilities": self.capabilities,
                },
                "queue": [self.summary(j) for j in self._queued()],
                "open": {**self.summary(open_job), "silent": silent,
                         "progress_stale": self._stale(open_job)} if open_job else None,
                "needs_input": sum(1 for j in self.jobs.values() if j["state"] == "needs-input") + run_input,
                "browser_sessions": [datetime.fromtimestamp(t, timezone.utc).astimezone().isoformat(timespec="seconds")
                                     for t in (sessions or [])],
                "change": self.change,
            }

    @staticmethod
    def summary(job: dict) -> dict:
        keys = ("id", "kind", "ticket", "base_revision", "ui_lang", "state", "created_at", "started_at",
                "finished_at", "reason", "result", "run", "suite", "queued_by", "opened", "queued_after")
        out = {k: job.get(k) for k in keys}
        out["ask"] = {"id": job["ask"]["id"], "type": job["ask"]["type"]} if job.get("ask") else None
        return out

    def list_jobs(self) -> list[dict]:
        with self.cond:
            jobs = sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)
            return [self.summary(j) for j in jobs[:100]]

    def get(self, job_id: str, *, opened: bool = False, session_created: float | None = None) -> dict:
        """The job for a browser tab; ``can_answer`` says whether this tab may answer it."""
        with self.cond:
            job = self.jobs.get(job_id)
            if job is None:
                raise ApiError(404, "not-found", "no such job")
            if opened and job.get("queued_by") == "agent" and not job.get("opened"):
                job["opened"] = True  # "queued from the chat" until the tester has looked at it
                self._save(job)
            out = json.loads(json.dumps(job))
            if out.get("ask"):
                out["ask"].pop("answer", None)
            out["silent"] = self.open_job() is job and self._silent(job)
            out["progress_stale"] = self.open_job() is job and self._stale(job)
            out["can_answer"] = tab_can_answer(answer_cutoff(job), session_created)
            return out

    # tester actions ---------------------------------------------------------------------------
    def agent_create(self, body: Any) -> dict:
        """Queue from the chat (``console queue``): web test kinds only, marked ``queued_by: agent``."""
        if not isinstance(body, dict) or body.get("kind") not in AGENT_KINDS:
            raise bad("the agent can queue suite-generate and webtest-run jobs only")
        if body.get("queued_after") not in (None, "no-older-tab"):
            raise bad("queued_after must be no-older-tab")
        if body.get("queued_after") and self.sessions is not None and not self.sessions():
            # No console tab at all (a restarted server, a tab that never opened): a job queued now
            # would fail the same way, and each failure would push real job history out.
            raise ApiError(409, "no-tab", "no console tab is open; ask the tester to open the console, then queue again")
        return self.create(body, queued_by="agent")

    def create(self, body: Any, queued_by: str = "tester") -> dict:
        if not isinstance(body, dict):
            raise bad("job must be an object")
        kind = body.get("kind")
        if kind not in KINDS:
            raise bad("kind must be survey, close, testcase, webtest-run or suite-generate")
        ui_lang = body.get("ui_lang")
        if ui_lang not in UI_LANGS:
            raise bad("ui_lang must be en or ja")
        checked = KINDS[kind](self.ctx, body)
        job = {
            "id": new_job_id(),
            "kind": kind,
            "ticket": checked["ticket"],
            "base_revision": checked["base_revision"],
            "params": checked["params"],
            "ui_lang": ui_lang,
            "report_lang": checked.get("report_lang"),
            "state": "queued",
            "seq": 0,
            "created_at": now_iso(), "offered_at": None, "started_at": None, "finished_at": None,
            "session": None,
            "progress": [],
            "ask": None,
            "asked": [],
            "confirmed_approval": None,
            "result": None,
            "summary": None,
            "reason": None,
        }
        if kind in WEB_KINDS:
            job.update(run=checked["params"].get("run"), queued_by=queued_by, opened=queued_by == "tester",
                       created_ts=time.time(), signed_in=None,
                       queued_after=body.get("queued_after") if queued_by == "agent" else None)
        if kind == "suite-generate":
            job["suite"] = checked["params"]["suite"]
        with self.cond:
            while job["id"] in self.jobs:
                job["id"] = new_job_id()
            if kind == "suite-generate":
                if any(j.get("suite") == job["suite"] and j["state"] in ACTIVE for j in self.jobs.values()):
                    raise bad("another job is already generating this suite", "suite-busy")
                self.ctx.attach_suite(job["suite"], job["id"])
            self._seq += 1
            job["seq"] = self._seq
            self.jobs[job["id"]] = job
            self._save(job)
            self._prune()
            return self.summary(job)

    def cancel(self, job_id: str) -> dict:
        with self.cond:
            job = self._job(job_id)
            if job["state"] != "queued":
                raise ApiError(409, "conflict", "only a queued job can be cancelled")
            self._move(job, "cancelled", result="cancelled")
            return self.summary(job)

    def mark_failed(self, job_id: str) -> dict:
        with self.cond:
            job = self._job(job_id)
            if job["state"] not in ("running", "needs-input") or not self._silent(job):
                raise ApiError(409, "conflict", "only a silent running job can be marked failed")
            self._fail(job, "marked")
            return self.summary(job)

    def release(self) -> dict:
        """The tester releases the attached session; its open job fails as ``session-lost``."""
        with self.cond:
            session = self.attached
            if session is None:
                return {"released": False}
            job = self.open_job()
            if job is not None and job["session"] == session:
                if job["state"] == "offered":
                    self._move(job, "queued", session=None, offered_at=None)
                else:
                    self._fail(job, "session-lost")
            self.attached = None
            self.released.add(session)
            self._replace(session)
            self.change += 1
            self.cond.notify_all()
            return {"released": True}

    def answer(self, job_id: str, body: Any, browser_session: str | None,
               session_created: float | None = None) -> dict:
        if not isinstance(body, dict):
            raise bad("answer must be an object")
        with self.cond:
            job = self._job(job_id)
            # A tab opened after the job started cannot answer it, so a session minted by the agent
            # during the job cannot approve its own questions.
            if session_created is not None and not tab_can_answer(answer_cutoff(job), session_created):
                raise ApiError(403, "session-too-new",
                               "this console tab was opened after the job started; answer from an older tab "
                               "or queue the job again")
            ask = job.get("ask")
            if job["state"] != "needs-input" or ask is None or "answer" in ask:
                raise ApiError(409, "conflict", "this job is not waiting for an answer")
            if body.get("ask_id") != ask["id"]:
                raise ApiError(409, "conflict", "this question was replaced; reload")
            answer = validate_answer(ask, body.get("answer"))
            ask["answer"] = answer
            ask["answered_at"] = now_iso()
            ask["answered_by"] = fingerprint(browser_session)
            if ask["type"] == "confirm-diff" and answer["confirm"]:
                job["confirmed_approval"] = ask["preview"]["approval"]
            if ask["type"] == "sign-in":
                job["signed_in"] = {"scenario": ask["scenario"], "choice": answer["choice"],
                                    "at": ask["answered_at"], "by": ask["answered_by"]}
            self._move(job, "running")
            return self.summary(job)

    def finish_sign_in(self, run_id: str, browser_session: str | None) -> bool:
        """The tester ended the run: an open sign-in question of its job is answered "finish"."""
        with self.cond:
            job = self.open_job()
            ask = job.get("ask") if job else None
            if job is None or job.get("run") != run_id or job["state"] != "needs-input" or not ask \
                    or ask["type"] != "sign-in" or "answer" in ask:
                return False
            ask.update(answer={"choice": "finish"}, answered_at=now_iso(), answered_by=fingerprint(browser_session))
            job["signed_in"] = {"scenario": ask["scenario"], "choice": "finish", "at": ask["answered_at"],
                                "by": ask["answered_by"]}
            self._move(job, "running")
            return True

    def check_run_session(self, run_id: str, session_created: float | None) -> None:
        """A tester action on a run needs a tab older than the run's queued or open job, if it has one.

        Called with ``cond`` held. With no job queued or open, the agent is not working on the run.
        """
        if not tab_can_answer(self.run_cutoff(run_id), session_created):
            raise ApiError(403, "session-too-new",
                           "this console tab was opened after the run's job was queued; answer from an older tab")

    def run_cutoff(self, run_id: str) -> float | None:
        """Creation time of the run's newest queued or open job. Called with ``cond`` held."""
        times = [j["created_ts"] for j in self.jobs.values()
                 if j.get("run") == run_id and j["state"] in ACTIVE and isinstance(j.get("created_ts"), (int, float))]
        return max(times) if times else None

    def refuse_without_older_tab(self, job: dict, cutoff: float | None) -> None:
        """Fail ``job`` as ``no-older-tab`` when no browser tab is older than ``cutoff``.

        Called with ``cond`` held, before the agent spends work or holds a call: tabs are only ever
        added, so a job no tab can answer now never becomes answerable.
        """
        if self.sessions is None or cutoff is None:
            return
        if any(tab_can_answer(cutoff, created) for created in self.sessions()):
            return
        if job["state"] in OPEN:
            self._fail(job, "no-older-tab")
        raise ApiError(409, "no-older-tab", NO_OLDER_TAB)

    def run_changed(self) -> None:
        """A tester action on a run: wake held calls and let open tabs refresh. Called with ``cond`` held."""
        self.change += 1
        self.cond.notify_all()
        if self.on_change:
            self.on_change()

    def run_created_ts(self, run_id: str) -> float | None:
        """Creation time of the newest web job of a run: run actions need a browser tab older than it."""
        times = [j["created_ts"] for j in self.jobs.values()
                 if j.get("run") == run_id and isinstance(j.get("created_ts"), (int, float))]
        return max(times) if times else None

    # agent actions ----------------------------------------------------------------------------
    def _job(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if job is None:
            raise ApiError(404, "not-found", "no such job")
        return job

    def _contact(self, session: Any) -> str:
        if not isinstance(session, str) or not _SESSION.match(session):
            raise bad("session id is missing or malformed")
        if session in self.released:
            raise ApiError(409, "session-replaced", "this session was released; start the console again")
        if self.attached is not None and session != self.attached:
            silence = self._silence() or 0.0
            job = self.open_job()
            limit = SILENT_WITH_JOB if job is not None and job["state"] != "offered" else SILENT_NO_JOB
            if silence < limit:
                raise ApiError(409, "session-refused", "another Claude Code session is attached to the console")
            old = self.attached
            self.released.add(old)
            if job is not None and job["session"] == old:
                if job["state"] == "offered":
                    self._move(job, "queued", session=None, offered_at=None)
                else:
                    self._fail(job, "session-lost")
            self._replace(old)
        if self.attached != session:
            self.capabilities = None  # a new session reports its own tools
        self.attached = session
        self.last_contact = self.clock()
        self.last_contact_iso = now_iso()
        return session

    def _owned(self, job_id: str, session: str) -> dict:
        job = self._job(job_id)
        if job["session"] != session:
            if job["state"] in OPEN and job["session"] is not None:
                raise ApiError(409, "session-replaced", "this job belongs to another session")
            raise ApiError(409, "conflict", "this job is not offered to this session")
        return job

    def _agent(self, session: Any) -> str:
        """Contact for calls other than ``wait``: the caller must be the attached session."""
        if not isinstance(session, str) or not _SESSION.match(session):
            raise bad("session id is missing or malformed")
        if session in self.released or (self.attached is not None and session != self.attached):
            raise ApiError(409, "session-replaced", "another session took over the console")
        return self._contact(session)

    def _begin_held(self, session: str) -> int:
        self._replace(session)
        self._token += 1
        self.held[session] = self._token
        self._held_open[session] = self._held_open.get(session, 0) + 1
        return self._token

    def _end_held(self, session: str) -> None:
        self._held_open[session] = max(0, self._held_open.get(session, 0) - 1)
        self.last_contact = self.clock()

    def _replace(self, session: str) -> None:
        """Answer the session's held call "nothing yet"; an offered job of that call goes back to the queue."""
        old = self.held.pop(session, None)
        if old is None:
            return
        for job_id, token in list(self.offered_to.items()):
            if token == old:
                job = self.jobs[job_id]
                if job["state"] == "offered":
                    self._move(job, "queued", session=None, offered_at=None)
        self.cond.notify_all()

    def _alive(self, session: str, token: int) -> bool:
        return not self.closed and self.held.get(session) == token

    def claim_implicit(self, job: dict) -> dict | None:
        """Offered → running, or failed ``revision-moved`` when the report moved on."""
        if job["state"] != "offered":
            return None
        if job["base_revision"]:
            latest = self.ctx.latest(job["ticket"])
            if latest is None or latest["name"] != job["base_revision"]:
                self._fail(job, "revision-moved")
                return {"ok": False, "reason": "revision-moved"}
        self._move(job, "running", started_at=now_iso(), started_ts=time.time())
        if job["kind"] in WEB_KINDS:
            self.progress_at[job["id"]] = self.clock()
        return None

    def wait(self, session: Any, timeout: Any) -> dict:
        seconds = self._timeout(timeout)
        with self.cond:
            session = self._contact(session)
            open_job = self.open_job()
            if open_job is not None and open_job["session"] == session:
                if open_job["state"] == "offered":
                    # Asking again without a claim means the offer never arrived (a killed client).
                    self._move(open_job, "queued", session=None, offered_at=None)
                else:
                    self._fail(open_job, "not-closed")
            token = self._begin_held(session)
            self.waiting.add(token)
            deadline = self.clock() + seconds
            try:
                while self._alive(session, token):
                    self._tick()
                    if self.open_job() is None:
                        queued = self._queued()
                        if queued:
                            job = queued[0]
                            self._move(job, "offered", session=session, offered_at=now_iso())
                            self.offered_to[job["id"]] = token
                            self.offered_at[job["id"]] = self.clock()
                            return {"session": session, "job": self._agent_view(job)}
                    left = deadline - self.clock()
                    if left <= 0:
                        break
                    self.cond.wait(min(left, 1.0))
                return {"session": session, "job": None}
            finally:
                self.waiting.discard(token)
                self._end_held(session)
                if self.held.get(session) == token:
                    self.held.pop(session, None)

    def claim(self, job_id: str, session: Any) -> dict:
        with self.cond:
            session = self._agent(session)
            job = self._owned(job_id, session)
            if job["state"] not in ("running", "needs-input"):
                moved = self.claim_implicit(job)
                if moved:
                    return moved
            self.refuse_without_older_tab(job, answer_cutoff(job))
            return {"ok": True}

    def _running(self, job_id: str, session: Any) -> tuple[str, dict]:
        session = self._agent(session)
        job = self._owned(job_id, session)
        moved = self.claim_implicit(job)
        if moved:
            raise ApiError(409, "revision-moved", "the report has a newer revision; the job failed")
        if job["state"] not in ("running", "needs-input"):
            raise ApiError(409, "conflict", f"the job is {job['state']}")
        return session, job

    def progress(self, job_id: str, session: Any, message: Any) -> dict:
        text = agent_text(message, "message", cap=2000)
        with self.cond:
            _, job = self._running(job_id, session)
            job["progress"].append({"at": now_iso(), "message": text})
            job["progress"] = job["progress"][-200:]
            if job["kind"] in WEB_KINDS:
                self.progress_at[job["id"]] = self.clock()
            self._save(job)
            return {"ok": True}

    def _web_ask(self, job: dict, clean: dict) -> dict:
        """Server facts for the web asks: the run's hosts and the scenarios come from the server, not the agent."""
        params = job.get("params") or {}
        if clean["type"] == "sign-in":
            if job["kind"] != "webtest-run":
                raise bad("a sign-in question belongs to a webtest-run job")
            info = self.ctx.run_info(job.get("run")) or {}
            project = info.get("project")
            scenario = self.ctx.scenario(project, clean["scenario"]) if project else None
            if not scenario or not scenario.get("approved"):
                raise bad("the scenario is missing or not approved by the tester", "scenario-not-approved")
            previous = self.ctx.scenario(project, clean["switching_from"]) if clean.get("switching_from") else None
            keep = ("name", "label", "login_url", "signout_url", "steps", "account_hint", "signed_in_check", "hash")
            clean["checklist"] = {k: scenario.get(k) for k in keep}
            clean["previous"] = {k: previous.get(k) for k in ("name", "label", "signout_url")} if previous else None
        return clean

    def ask(self, job_id: str, session: Any, ask: Any, timeout: Any) -> dict:
        seconds = self._timeout(timeout)
        clean = validate_ask(ask)
        with self.cond:
            session, job = self._running(job_id, session)
            if clean["type"] == "sign-in":
                clean = self._web_ask(job, clean)
            if not any(a["id"] == clean["id"] and a.get("outcome") == "answered" for a in job["asked"]):
                self.refuse_without_older_tab(job, answer_cutoff(job))
            current = job.get("ask")
            earlier = next((a for a in job["asked"] if a["id"] == clean["id"]), None)
            if earlier is not None:
                if earlier.get("outcome") == "answered":
                    # The answer may have gone to a call whose client had died; hand it out again.
                    return {"answers": earlier["answer"]}
                raise bad("this ask id was closed without an answer; use a new id")
            if current is not None and current["id"] != clean["id"]:
                raise bad("another question is still open on this job")
            if current is None:
                self._move(job, "needs-input", ask=clean)
            token = self._begin_held(session)
            deadline = self.clock() + seconds
            try:
                while self._alive(session, token):
                    current = job.get("ask")
                    if current is not None and "answer" in current:
                        answer = current["answer"]
                        job["asked"].append({**self._ask_summary(current), "outcome": "answered",
                                             "answered_at": current.get("answered_at"),
                                             "answered_by": current.get("answered_by"),
                                             "answer": answer})
                        job["ask"] = None
                        self._save(job)
                        return {"answers": answer}
                    if job["state"] not in OPEN:
                        raise ApiError(409, "conflict", f"the job is {job['state']}")
                    left = deadline - self.clock()
                    if left <= 0:
                        break
                    self.cond.wait(min(left, 1.0))
                return {"answers": None}
            finally:
                self._end_held(session)
                if self.held.get(session) == token:
                    self.held.pop(session, None)

    @staticmethod
    def _ask_summary(ask: dict) -> dict:
        return {"id": ask["id"], "type": ask["type"]}

    def done(self, job_id: str, session: Any, result: Any, summary: Any) -> dict:
        if result not in ("done", "failed"):
            raise bad("result must be done or failed")
        text = agent_text(summary, "report", cap=20_000, required=False)
        with self.cond:
            _, job = self._running(job_id, session)
            if job["state"] == "needs-input":
                if result == "done":
                    raise ApiError(409, "conflict", "a question is still open; answer it or finish as failed")
                self._fail(job, "agent")
                job["summary"] = text
                self._save(job)
                return {"ok": True}
            if result == "done" and job["kind"] == "webtest-run":
                info = self.ctx.run_info(job.get("run")) or {}
                if info.get("open") and not self.ctx.run_finish(job.get("run")):
                    raise ApiError(409, "open-rows", "the run still has open rows; wait for the tester or "
                                                     "close the run first")
            if result == "done":
                self._move(job, "done", result="done", summary=text)
            else:
                self._move(job, "failed", result="failed", reason="agent", summary=text)
            return {"ok": True}

    def approval(self, job_id: str, session: Any) -> dict:
        with self.cond:
            session = self._agent(session)
            job = self._owned(job_id, session)
            if job["state"] not in ("running", "needs-input"):
                return {"approval": None}
            return {"approval": job.get("confirmed_approval")}

    def _agent_view(self, job: dict) -> dict:
        keys = ("id", "kind", "ticket", "base_revision", "params", "ui_lang", "report_lang", "state")
        out = {k: job.get(k) for k in keys}
        if job["kind"] in WEB_KINDS:
            out["run"] = job.get("run")
            out["suite"] = job.get("suite")
        return out

    # web test reads (agent side) ----------------------------------------------------------------
    def _open_web(self, job_id: str, session: Any) -> dict:
        session = self._agent(session)
        job = self._owned(job_id, session)
        if job["kind"] not in WEB_KINDS or job["state"] not in ("running", "needs-input"):
            raise ApiError(409, "conflict", "not an open web test job of this session")
        return job

    def info(self, job_id: str, session: Any) -> dict:
        with self.cond:
            return self._agent_view(self._open_web(job_id, session))

    def signed_in_view(self, job_id: str, session: Any) -> dict:
        with self.cond:
            return {"signed_in": self._open_web(job_id, session).get("signed_in")}

    def is_open(self, job_id: str) -> dict:
        with self.cond:
            job = self.jobs.get(job_id)
            return {"open": bool(job and job["state"] in OPEN)}

    def run_job(self, job_id: Any, session: Any, run_id: str) -> dict:
        """The open web job of this session that works on ``run_id`` (for pending and applied)."""
        if not isinstance(job_id, str):
            raise bad("job id required")
        job = self._open_web(job_id, session)
        if job.get("run") != run_id:
            raise ApiError(409, "conflict", "this job works on another run")
        return job

    def report_capabilities(self, body: Any) -> dict:
        """The attached session's tools (Claude in Chrome, Figma MCP, Backlog MCP), for the Agent screen."""
        body = body if isinstance(body, dict) else {}
        with self.cond:
            self._contact(body.get("session"))
            caps = {}
            for name in CAPABILITIES:
                value = body.get(name)
                if not isinstance(value, bool):
                    raise bad(f"{name} must be true or false")
                caps[name] = value
            self.capabilities = {**caps, "at": now_iso()}
            self.change += 1
            self.cond.notify_all()
            return {"ok": True, "capabilities": self.capabilities}

    def suite_job(self, job_id: Any, session: Any, suite_id: str) -> dict:
        """The open generate job of this session that writes ``suite_id`` (for the agent's stage calls)."""
        if not isinstance(job_id, str):
            raise bad("job id required")
        job = self._open_web(job_id, session)
        if job["kind"] != "suite-generate" or job.get("suite") != suite_id:
            raise ApiError(409, "conflict", "this job does not generate this suite")
        return job

    def suite_job_active(self, suite_id: str) -> bool:
        with self.cond:
            return any(j.get("suite") == suite_id and j["state"] in ACTIVE for j in self.jobs.values())

    @staticmethod
    def _timeout(value: Any) -> float:
        if value is None:
            return HELD_DEFAULT
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise bad("timeout must be a number of seconds")
        return min(float(value), HELD_MAX)

    # timers -----------------------------------------------------------------------------------
    def _tick(self) -> None:
        """Offered jobs not claimed in time go back to the queue."""
        for job_id, at in list(self.offered_at.items()):
            if self.clock() - at >= OFFER_TIMEOUT:
                job = self.jobs.get(job_id)
                if job is not None and job["state"] == "offered":
                    self._move(job, "queued", session=None, offered_at=None)

    def tick(self) -> None:
        with self.cond:
            self._tick()

    def shutdown(self) -> None:
        """Release every held call; open and queued jobs fail as ``server-stopped``."""
        with self.cond:
            self.closed = True
            for job in list(self.jobs.values()):
                if job["state"] in OPEN:
                    self._fail(job, "server-stopped")
                elif job["state"] == "queued":
                    self._move(job, "failed", reason="server-stopped", result="failed")
            self.held.clear()
            self.cond.notify_all()


# routes ---------------------------------------------------------------------------------------
ASK_BODY_CAP = 4 * 1024 * 1024


def make_context(state) -> Context:
    from .. import templates  # noqa: PLC0415
    from . import readapi  # noqa: PLC0415 - readapi imports the server module too

    def cfg() -> dict:
        return readapi.load_config(state)

    def latest(ticket: str) -> dict | None:
        folders = readapi.ticket_folders(cfg())
        if ticket not in folders:
            return None
        found = readapi.latest_of(readapi.revision_files(folders[ticket], ticket))
        if found is None or found["state"] != "ok":
            return None
        return {"name": found["name"], "path": found["path"]}

    def workbooks(ticket: str) -> list[str]:
        folders = readapi.ticket_folders(cfg())
        return sorted(readapi.workbooks(folders[ticket])) if ticket in folders else []

    def row_ids(ticket: str) -> set[str]:
        from .. import report  # noqa: PLC0415

        found = latest(ticket)
        if found is None:
            return set()
        _, body = report.load(found["path"])
        return {r["id"] for r in report.behavior_rows(body) + report.regression_rows(body)}

    from .. import login_scenarios  # noqa: PLC0415
    from . import webtest_api  # noqa: PLC0415

    def run_info(run: str) -> dict | None:
        try:
            folder = webtest.find_run(webtest.runs_root(cfg()), run)
            data = webtest.load(folder)
        except (webtest.WebtestError, ApiError):
            return None
        return {"id": data["id"], "project": data.get("project"), "hosts": data.get("hosts"),
                "confirmed": bool(data.get("confirmed")), "ticket": data.get("ticket"),
                "report_lang": data.get("report_lang"), "open": webtest.open_rows(data)}

    def scenario(project: str, name: str) -> dict | None:
        try:
            return login_scenarios.get_scenario(state.home, project, name)
        except webtest.WebtestError:
            return None

    def scenarios(project: str) -> list[dict]:
        try:
            return login_scenarios.list_scenarios(state.home, project)
        except webtest.WebtestError:
            return []

    from .. import webtest_suite  # noqa: PLC0415

    def suite_folder(suite: str):
        return webtest_suite.find_suite(webtest.runs_root(cfg()), suite)

    def suite_info(suite: str) -> dict | None:
        try:
            data = webtest_suite.load(suite_folder(suite))
        except (webtest.WebtestError, ApiError):
            return None
        bridge = getattr(state, "bridge", None)
        active = bridge.suite_job_active(data["id"]) if bridge is not None else False
        return {"id": data["id"], "state": data["state"], "source": data["source"],
                "generate_job": data.get("generate_job"), "generate_job_active": active}

    def attach_suite(suite: str, job: str) -> None:
        try:
            webtest_suite.attach_job(suite_folder(suite), job, replace=True)
        except webtest.WebtestError as exc:
            raise bad(str(exc), "suite-busy") from None

    return Context(cfg=cfg, ticket_rx=readapi.ticket_rx, latest=latest,
                   templates=lambda: templates.list_templates(state.home), workbooks=workbooks,
                   row_ids=row_ids, usable_repo=readapi.usable_repo,
                   projects=lambda: login_scenarios.load_projects(state.home), run_info=run_info,
                   scenario=scenario, scenarios=scenarios,
                   run_needs_input=lambda: webtest_api.needs_input(state),
                   run_finish=lambda run: webtest_api.finished(state, run),
                   suite_info=suite_info, attach_suite=attach_suite)


def install(state, store=None) -> Bridge:
    from . import lifecycle  # noqa: PLC0415

    if store is None:
        folder = lifecycle.ensure_state_dirs(state.home) / "jobs"
        store = FileStore(folder, lifecycle.write_secure)
    bridge = Bridge(store, make_context(state))
    bridge.sessions = state.session_times
    bridge.startup()
    state.busy = bridge.busy
    state.shutdown_hooks.append(bridge.shutdown)

    def ticker() -> None:
        while not bridge.closed:
            time.sleep(1.0)
            try:
                bridge.tick()
            except Exception:  # noqa: BLE001 - keep offering timeouts going; nothing goes to stderr
                pass

    threading.Thread(target=ticker, daemon=True).start()

    def body(req) -> dict:
        return req.body if isinstance(req.body, dict) else {}

    def held(fn):
        def run(req):
            state.hold(+1)
            try:
                return fn(req)
            finally:
                state.hold(-1)
        return run

    r = state.router
    r.add("POST", "/agent/wait", "agent", held(lambda q: bridge.wait(body(q).get("session"), body(q).get("timeout"))))
    r.add("POST", "/agent/jobs/:id/claim", "agent", lambda q: bridge.claim(q.params["id"], body(q).get("session")))
    r.add("POST", "/agent/jobs/:id/progress", "agent",
          lambda q: bridge.progress(q.params["id"], body(q).get("session"), body(q).get("message")))
    r.add("POST", "/agent/jobs/:id/ask", "agent",
          held(lambda q: bridge.ask(q.params["id"], body(q).get("session"), body(q).get("ask"), body(q).get("timeout"))),
          max_body=ASK_BODY_CAP)
    r.add("POST", "/agent/jobs/:id/done", "agent",
          lambda q: bridge.done(q.params["id"], body(q).get("session"), body(q).get("result"), body(q).get("report")))
    r.add("GET", "/agent/jobs/:id/approval", "agent", lambda q: bridge.approval(q.params["id"], q.arg("session")))
    # Web test runs: queue from the chat, and what the run commands read back from the server.
    r.add("POST", "/agent/jobs", "agent", lambda q: bridge.agent_create(q.body))
    r.add("POST", "/agent/capabilities", "agent", lambda q: bridge.report_capabilities(q.body))
    r.add("GET", "/agent/jobs/:id/info", "agent", lambda q: bridge.info(q.params["id"], q.arg("session")))
    r.add("GET", "/agent/jobs/:id/open", "agent", lambda q: bridge.is_open(q.params["id"]))
    r.add("GET", "/agent/jobs/:id/signed-in", "agent",
          lambda q: bridge.signed_in_view(q.params["id"], q.arg("session")))

    r.add("GET", "/api/state", "browser", lambda q: bridge.state_view(state.session_times()))
    r.add("GET", "/api/jobs", "browser", lambda q: {"jobs": bridge.list_jobs()})
    r.add("POST", "/api/jobs", "browser", lambda q: bridge.create(q.body))
    r.add("GET", "/api/jobs/:id", "browser",
          lambda q: bridge.get(q.params["id"], opened=True, session_created=state.session_created(q.session)))
    r.add("POST", "/api/jobs/:id/answer", "browser",
          lambda q: bridge.answer(q.params["id"], q.body, q.session, state.session_created(q.session)))
    r.add("POST", "/api/jobs/:id/cancel", "browser", lambda q: bridge.cancel(q.params["id"]))
    r.add("POST", "/api/jobs/:id/fail", "browser", lambda q: bridge.mark_failed(q.params["id"]))
    r.add("POST", "/api/agent/release", "browser", lambda q: bridge.release())
    state.bridge = bridge
    return bridge
