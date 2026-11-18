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
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .server import ApiError

LANGS = ("vi", "en", "ja")
OPEN = ("offered", "running", "needs-input")
ACTIVE = ("queued", *OPEN)
FINISHED = ("done", "failed", "cancelled")
TRANSITIONS = {
    ("queued", "offered"), ("queued", "cancelled"), ("queued", "failed"),
    ("offered", "queued"), ("offered", "running"), ("offered", "failed"),
    ("running", "needs-input"), ("running", "done"), ("running", "failed"),
    ("needs-input", "running"), ("needs-input", "failed"),
}
FAIL_REASONS = ("server-stopped", "session-lost", "not-closed", "marked", "revision-moved", "agent")

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
        if not isinstance(pages, list):
            raise bad("confirm-diff preview needs pages")
        clean_pages = []
        for p in pages:
            if not isinstance(p, dict) or not isinstance(p.get("diff"), str):
                raise bad("every confirm-diff page needs a diff")
            clean_pages.append({"name": data_text(p.get("name"), "page name", cap=500),
                                "exists": bool(p.get("exists")), "updated": p.get("updated"),
                                "diff": data_text(p.get("diff"), "diff")})
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
    raise bad("ask type must be questions, review-rows, confirm-diff or paste-pages")


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
    raise bad("unknown ask type")


# kind checks ----------------------------------------------------------------------------------
class Context:
    """What the kind checks read: config, the ticket listing, templates and git. Injected."""

    def __init__(self, *, cfg: Callable[[], dict], ticket_rx: Callable[[dict], re.Pattern],
                 latest: Callable[[str], dict | None], templates: Callable[[], dict],
                 workbooks: Callable[[str], list[str]], row_ids: Callable[[str], set[str]],
                 usable_repo: Callable[[Any], Path | None]) -> None:
        self.cfg = cfg
        self.ticket_rx = ticket_rx
        self.latest = latest
        self.templates = templates
        self.workbooks = workbooks
        self.row_ids = row_ids
        self.usable_repo = usable_repo


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
    if report_lang not in LANGS:
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
    names = [t["name"] for t in listing.get("templates", [])]
    template = body.get("template")
    if template is not None and template not in names:
        raise bad("template is not registered", "unknown-template")
    if template is None and (mode == "trace" or len(names) > 1):
        raise bad("choose a template", "template-required")
    if not names:
        raise bad("register a template first", "template-required")
    params: dict[str, Any] = {"mode": mode, "template": template or listing.get("default")}
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


# One entry per job kind: the parameter check. Adding a kind adds one entry here.
KINDS: dict[str, Callable[[Context, dict], dict]] = {
    "survey": _check_survey,
    "close": _check_close,
    "testcase": _check_testcase,
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
        self.closed = False
        self.on_change = on_change

    # persistence ------------------------------------------------------------------------------
    def startup(self) -> None:
        """Load records; open and queued jobs fail as ``server-stopped``; prune old ones."""
        with self.cond:
            for job in self.store.load_all():
                if job.get("state") in ACTIVE:
                    job["state"] = "failed"
                    job["reason"] = "server-stopped"
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

    def state_view(self, sessions: list[float] | None = None) -> dict:
        with self.cond:
            self._tick()
            open_job = self.open_job()
            silence = self._silence()
            silent = bool(open_job and open_job["state"] != "offered" and silence is not None
                          and silence >= SILENT_WITH_JOB)
            return {
                "agent": {
                    "attached": self.attached is not None,
                    "waiting": bool(self.waiting),
                    "last_contact": self.last_contact_iso,
                    "silent_seconds": int(silence) if silence is not None else None,
                },
                "queue": [self.summary(j) for j in self._queued()],
                "open": {**self.summary(open_job), "silent": silent} if open_job else None,
                "needs_input": sum(1 for j in self.jobs.values() if j["state"] == "needs-input"),
                "browser_sessions": [datetime.fromtimestamp(t, timezone.utc).astimezone().isoformat(timespec="seconds")
                                     for t in (sessions or [])],
                "change": self.change,
            }

    @staticmethod
    def summary(job: dict) -> dict:
        keys = ("id", "kind", "ticket", "base_revision", "ui_lang", "state", "created_at", "started_at",
                "finished_at", "reason", "result")
        out = {k: job.get(k) for k in keys}
        out["ask"] = {"id": job["ask"]["id"], "type": job["ask"]["type"]} if job.get("ask") else None
        return out

    def list_jobs(self) -> list[dict]:
        with self.cond:
            jobs = sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)
            return [self.summary(j) for j in jobs[:100]]

    def get(self, job_id: str) -> dict:
        with self.cond:
            job = self.jobs.get(job_id)
            if job is None:
                raise ApiError(404, "not-found", "no such job")
            out = json.loads(json.dumps(job))
            if out.get("ask"):
                out["ask"].pop("answer", None)
            open_job = self.open_job()
            silence = self._silence()
            out["silent"] = bool(open_job is job and job["state"] != "offered" and silence is not None
                                 and silence >= SILENT_WITH_JOB)
            return out

    # tester actions ---------------------------------------------------------------------------
    def create(self, body: Any) -> dict:
        if not isinstance(body, dict):
            raise bad("job must be an object")
        kind = body.get("kind")
        if kind not in KINDS:
            raise bad("kind must be survey, close or testcase")
        ui_lang = body.get("ui_lang")
        if ui_lang not in LANGS:
            raise bad("ui_lang must be vi, en or ja")
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
        with self.cond:
            while job["id"] in self.jobs:
                job["id"] = new_job_id()
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
            silence = self._silence()
            if job["state"] not in ("running", "needs-input") or silence is None or silence < SILENT_WITH_JOB:
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

    def answer(self, job_id: str, body: Any, browser_session: str | None) -> dict:
        if not isinstance(body, dict):
            raise bad("answer must be an object")
        with self.cond:
            job = self._job(job_id)
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
            self._move(job, "running")
            return self.summary(job)

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
        self._move(job, "running", started_at=now_iso())
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
            if job["state"] in ("running", "needs-input"):
                return {"ok": True}
            moved = self.claim_implicit(job)
            return moved or {"ok": True}

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
            self._save(job)
            return {"ok": True}

    def ask(self, job_id: str, session: Any, ask: Any, timeout: Any) -> dict:
        seconds = self._timeout(timeout)
        clean = validate_ask(ask)
        with self.cond:
            session, job = self._running(job_id, session)
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
        return {k: job.get(k) for k in keys}

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

    return Context(cfg=cfg, ticket_rx=readapi.ticket_rx, latest=latest,
                   templates=lambda: templates.list_templates(state.home), workbooks=workbooks,
                   row_ids=row_ids, usable_repo=readapi.usable_repo)


def install(state, store=None) -> Bridge:
    from . import lifecycle  # noqa: PLC0415

    if store is None:
        folder = lifecycle.ensure_state_dirs(state.home) / "jobs"
        store = FileStore(folder, lifecycle.write_secure)
    bridge = Bridge(store, make_context(state))
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

    r.add("GET", "/api/state", "browser", lambda q: bridge.state_view(state.session_times()))
    r.add("GET", "/api/jobs", "browser", lambda q: {"jobs": bridge.list_jobs()})
    r.add("POST", "/api/jobs", "browser", lambda q: bridge.create(q.body))
    r.add("GET", "/api/jobs/:id", "browser", lambda q: bridge.get(q.params["id"]))
    r.add("POST", "/api/jobs/:id/answer", "browser", lambda q: bridge.answer(q.params["id"], q.body, q.session))
    r.add("POST", "/api/jobs/:id/cancel", "browser", lambda q: bridge.cancel(q.params["id"]))
    r.add("POST", "/api/jobs/:id/fail", "browser", lambda q: bridge.mark_failed(q.params["id"]))
    r.add("POST", "/api/agent/release", "browser", lambda q: bridge.release())
    state.bridge = bridge
    return bridge
