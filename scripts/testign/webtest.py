"""Web test runs: the run folder, the normalised case list, row states and the queue.

A run lives in ``<output_dir>/webtest/<run-id>/``::

    run.json            source, project, hosts, column plan, cases, states, questions, results
    source/             the import as received, one file per row plus captures; never re-fetched
    evidence/           <row>-a<attempt>-<n>.png or .jpg

Only the CLI commands write ``run.json``; the console server reads it. Every command loads the run
through ``load`` (which validates it) and writes it through ``save`` (an atomic replace). Run ids
are matched against a strict pattern and resolved by listing ``<output_dir>/webtest``; a path is
never accepted and an id is never joined into a path unchecked.

Row states::

    draft ──plan──▶ queued | awaiting-tester | manual | not-applicable | not-run
    queued ──next──▶ running ──row──▶ pass | fail | not-run (off-site)
       ▲                ├──park──▶ parked ──answer──▶ queued | awaiting-tester | not-run
       └──requeue / recover──┘
    awaiting-tester ──result──▶ self-run
    queued, parked, awaiting-tester ──close──▶ not-run

A tester decision reaches a run only through the console server (``ConsoleReader``), never
through a file the agent wrote.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from . import config, fsutil

VERSION = 1
RUN_ID_RE = re.compile(r"^W\d{8}-\d{4}-[a-z0-9-]{1,40}$")
ROW_RE = re.compile(r"^r\d{1,4}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
HOST_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)*$")
IMAGE_ID_RE = re.compile(r"^[0-9a-f]{16}$")

KINDS = ("label", "element", "visual", "behaviour", "data-rule", "motion", "design-only")
CLASSES = ("sure", "choice", "not-web")
RUNNERS = ("agent", "tester", "none")
VIEWPORTS = ("pc", "mobile")
# How a phone-width row is checked: on a real phone by the tester (the default), or by the agent in a
# phone-width frame of the tester's Chrome.
MOBILE_METHODS = ("device", "emulation")
EMULATION_IS_THE_TESTERS = "only the tester switches a phone-width row to emulation, in the review table"
CONFIDENCE = ("high", "low", "none")
STATES = ("draft", "queued", "running", "parked", "awaiting-tester",
          "pass", "fail", "manual", "not-applicable", "self-run", "not-run")
OPEN_STATES = ("queued", "running", "parked", "awaiting-tester")
FINAL_STATES = ("pass", "fail", "manual", "not-applicable", "self-run", "not-run")
REASONS = ("unanswered", "no-result", "no-scenario", "off-site", "no-screen", "stopped", "skipped")
ACTIONS = ("delegate", "self-run", "skip")
NO_SCENARIO = "none"  # public pages: no sign-in needed
HALT_AFTER = 3

TRANSITIONS: dict[str, set[str]] = {
    "draft": {"queued", "awaiting-tester", "manual", "not-applicable", "not-run"},
    "queued": {"running", "not-run"},
    "running": {"pass", "fail", "not-run", "parked", "queued"},
    "parked": {"queued", "awaiting-tester", "not-run"},
    "awaiting-tester": {"self-run", "not-run"},
}

TEXT_CAP = 4000
IMAGE_CAP = 20 * 1024 * 1024
PNG_SIG = b"\x89PNG\r\n\x1a\n"
JPEG_SIG = b"\xff\xd8\xff"

CASE_KEYS = {
    "row", "source", "type", "content", "creator", "capture", "screen", "viewport", "kind", "class",
    "reason", "scenario", "runner", "preconditions", "steps", "expected", "state", "attempt",
    "owner_job", "question", "questions", "decided_by", "result", "evidence", "not_run_reason",
    "class_changed", "started_at", "last_requeue", "mobile_method",
}
STAGED_KEYS = {"row", "source", "type", "content", "creator"}
TRIAGE_KEYS = {"kind", "class", "reason", "viewport", "steps", "expected", "screen", "scenario", "runner",
               "preconditions", "mobile_method"}
SOURCE_KINDS = ("figma", "workbook")


class WebtestError(ValueError):
    """A web test command cannot go on; the message is one line for the tester."""


class ConsoleReader(Protocol):
    """What the commands read from the console server. The real one is in ``console.client``."""

    def job(self, job: str, session: str) -> dict: ...
    def attach_run(self, job: str, session: str, run: str) -> dict: ...
    def review(self, job: str, session: str) -> dict | None: ...
    def job_open(self, job: str) -> bool: ...
    def signed_in(self, job: str, session: str) -> dict | None: ...
    def pending(self, run: str, job: str, session: str, wait: float | None) -> dict: ...
    def applied(self, run: str, job: str, session: str, ids: list[str]) -> dict: ...


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# names and hosts ------------------------------------------------------------------------------
def slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:40].strip("-")
    return text or "run"


def new_run_id(name: str, when: datetime | None = None) -> str:
    return (when or datetime.now()).strftime("W%Y%m%d-%H%M-") + slug(name)


def idna(host: str) -> str | None:
    host = (host or "").strip().rstrip(".").lower()
    if not host:
        return None
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def check_host(host: Any) -> str:
    """A host name as the tester typed it: no scheme, port, path or wildcard."""
    value = idna(host) if isinstance(host, str) else None
    if value is None or not HOST_RE.match(value):
        raise WebtestError(f"{host!r} is not a host name")
    return value


def url_on_hosts(url: Any, hosts: list[str]) -> bool:
    """http or https, and a host equal to one of ``hosts`` after IDNA encoding; no suffix match.

    A backslash, whitespace, a control character, user info or an escaped host is refused: browsers
    read such URLs differently from ``urlsplit`` (``https://a\\@b/`` goes to ``a`` in Chrome).
    """
    if not isinstance(url, str) or not url:
        return False
    if "\\" in url or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host or "@" in parts.netloc or "%" in parts.netloc:
        return False
    want = {idna(h) for h in hosts}
    return idna(host) in want - {None}


def screen_url_ok(url: Any, hosts: list[str]) -> bool:
    """A screen URL: empty, a path on the base URL (``/x``, never ``//x``), or absolute on a run host."""
    if url in (None, ""):
        return True
    if not isinstance(url, str) or len(url) > 2000:
        return False
    if url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return True
    return url_on_hosts(url, hosts)


# run folders ----------------------------------------------------------------------------------
def runs_root(cfg: dict | None = None) -> Path:
    cfg = cfg if cfg is not None else config.load()
    return Path(str(cfg["output_dir"])).expanduser() / "webtest"


def list_runs(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    try:
        children = list(root.iterdir())
    except OSError:
        return found
    for child in children:
        try:
            if child.is_dir() and RUN_ID_RE.match(child.name):
                found[child.name] = child
        except OSError:
            continue
    return found


def find_run(root: Path, run_id: Any) -> Path:
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise WebtestError("no such run")
    folder = list_runs(root).get(run_id)
    if folder is None:
        raise WebtestError(f"no such run: {run_id}")
    return folder


def _text(value: Any, field: str, cap: int = TEXT_CAP, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise WebtestError(f"{field} must be text")
    if required and not value.strip():
        raise WebtestError(f"{field} is required")
    if len(value) > cap:
        raise WebtestError(f"{field} is longer than {cap} characters")
    return value


def _check_source(source: Any, where: str) -> dict:
    if not isinstance(source, dict) or source.get("kind") not in SOURCE_KINDS:
        raise WebtestError(f"{where}: source.kind must be one of {', '.join(SOURCE_KINDS)}")
    out = {}
    for key, value in source.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z_]{1,30}", key):
            raise WebtestError(f"{where}: source has a bad key")
        if value is not None and not isinstance(value, (str, int)):
            raise WebtestError(f"{where}: source.{key} must be text or a number")
        out[key] = str(value) if isinstance(value, int) else value
        if isinstance(out[key], str) and len(out[key]) > 500:
            raise WebtestError(f"{where}: source.{key} is too long")
    return out


def _check_screen(screen: Any, hosts: list[str], where: str) -> dict | None:
    if screen is None:
        return None
    if not isinstance(screen, dict) or set(screen) - {"url", "name", "confidence"}:
        raise WebtestError(f"{where}: screen must be {{url, name, confidence}}")
    url = screen.get("url") or ""
    if not screen_url_ok(url, hosts):
        raise WebtestError(f"{where}: screen.url is not on the run's hosts")
    confidence = screen.get("confidence") or ("none" if not url else "low")
    if confidence not in CONFIDENCE:
        raise WebtestError(f"{where}: screen.confidence must be high, low or none")
    return {"url": url, "name": _text(screen.get("name"), f"{where}: screen.name", 200), "confidence": confidence}


def _check_scenario(value: Any, where: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise WebtestError(f"{where}: scenario must be a short lowercase name")
    return value


def check_staged(case: Any) -> dict:
    """An imported row as the importer hands it over: row id, source, the row's own text."""
    if not isinstance(case, dict):
        raise WebtestError("a case must be a JSON object")
    row = case.get("row")
    if not isinstance(row, str) or not ROW_RE.match(row):
        raise WebtestError("case row must look like r02")
    extra = set(case) - STAGED_KEYS
    if extra:
        raise WebtestError(f"{row}: unknown keys {', '.join(sorted(extra))}")
    return {
        "row": row,
        "source": _check_source(case.get("source"), row),
        "type": _text(case.get("type"), f"{row}: type", 100),
        "content": _text(case.get("content"), f"{row}: content", required=True),
        "creator": _text(case.get("creator"), f"{row}: creator", 200),
    }


def check_triage(row: str, fields: Any, hosts: list[str]) -> dict:
    """The agent's draft for one case before the review table: kind, class, screen, steps."""
    if not isinstance(fields, dict):
        raise WebtestError(f"{row}: triage must be an object")
    extra = set(fields) - TRIAGE_KEYS
    if extra:
        raise WebtestError(f"{row}: unknown keys {', '.join(sorted(extra))}")
    out: dict[str, Any] = {}
    for key, allowed in (("kind", KINDS), ("class", CLASSES), ("viewport", VIEWPORTS), ("runner", RUNNERS),
                         ("mobile_method", MOBILE_METHODS)):
        if key in fields:
            if fields[key] not in allowed:
                raise WebtestError(f"{row}: {key} must be one of {', '.join(allowed)}")
            out[key] = fields[key]
    for key, cap in (("reason", 500), ("steps", TEXT_CAP), ("expected", TEXT_CAP), ("preconditions", 2000)):
        if key in fields:
            out[key] = _text(fields[key], f"{row}: {key}", cap)
    if "screen" in fields:
        out["screen"] = _check_screen(fields["screen"], hosts, row)
    if "scenario" in fields:
        out["scenario"] = _check_scenario(fields["scenario"], row)
    return out


def mobile_method(viewport: Any, method: Any) -> str | None:
    """The check method of a row: none on pc rows, ``device`` on a phone-width row that names none."""
    if viewport != "mobile":
        return None
    return method if method in MOBILE_METHODS else "device"


def agent_may_run(viewport: Any, method: Any) -> bool:
    """A phone-width row reaches the agent only as an emulation; a real phone is the tester's."""
    return mobile_method(viewport, method) in (None, "emulation")


def check_case(case: Any, hosts: list[str]) -> None:
    """A whole case as stored in ``run.json``; called on every load."""
    staged = {k: case.get(k) for k in STAGED_KEYS if k in case} if isinstance(case, dict) else case
    check_staged(staged)
    row = case["row"]
    extra = set(case) - CASE_KEYS
    if extra:
        raise WebtestError(f"run.json: {row} has unknown keys {', '.join(sorted(extra))}")
    check_triage(row, {k: case[k] for k in TRIAGE_KEYS if k in case and case[k] is not None}, hosts)
    if case.get("state") not in STATES:
        raise WebtestError(f"run.json: {row} has an unknown state")
    if not isinstance(case.get("attempt", 0), int) or case.get("attempt", 0) < 0:
        raise WebtestError(f"run.json: {row} has a bad attempt count")
    if case.get("runner") == "agent" and not agent_may_run(case.get("viewport"), case.get("mobile_method")):
        raise WebtestError(f"run.json: {row}: phone-width rows on a real device go to the tester")
    if case["state"] == "not-run" and case.get("not_run_reason") not in REASONS:
        raise WebtestError(f"run.json: {row} is not-run without a known reason")
    for key in ("question", "result", "decided_by"):
        if case.get(key) is not None and not isinstance(case[key], dict):
            raise WebtestError(f"run.json: {row}.{key} must be an object")
    if not isinstance(case.get("evidence", []), list):
        raise WebtestError(f"run.json: {row}.evidence must be a list")


def check_run(run: Any) -> dict:
    if not isinstance(run, dict) or run.get("version") != VERSION:
        raise WebtestError("run.json is not a web test run of this version")
    if not isinstance(run.get("id"), str) or not RUN_ID_RE.match(run["id"]):
        raise WebtestError("run.json has a bad id")
    hosts = run.get("hosts")
    if not isinstance(hosts, list) or not hosts or not all(isinstance(h, str) for h in hosts):
        raise WebtestError("run.json has no hosts")
    cases = run.get("cases")
    if not isinstance(cases, list):
        raise WebtestError("run.json cases must be a list")
    seen = set()
    for case in cases:
        check_case(case, hosts)
        if case["row"] in seen:
            raise WebtestError(f"run.json: {case['row']} appears twice")
        seen.add(case["row"])
    running = [c["row"] for c in cases if c["state"] == "running"]
    if len(running) > 1:
        raise WebtestError("run.json has more than one running row")
    staged = (run.get("import") or {}).get("staged")
    if not isinstance(staged, list) or not all(isinstance(r, str) and ROW_RE.match(r) for r in staged):
        raise WebtestError("run.json has a bad list of staged rows")
    return run


def load(folder: Path) -> dict:
    try:
        data = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WebtestError(f"cannot read run.json of {folder.name}: {type(exc).__name__}") from None
    return check_run(data)


def save(folder: Path, run: dict) -> None:
    check_run(run)
    fsutil.atomic_write_bytes(folder / "run.json",
                              (json.dumps(run, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def case_of(run: dict, row: Any) -> dict:
    for case in run["cases"]:
        if case["row"] == row:
            return case
    raise WebtestError(f"no row {row} in this run")


def move(case: dict, to: str, **fields: Any) -> None:
    if to not in TRANSITIONS.get(case["state"], set()):
        raise WebtestError(f"{case['row']} is {case['state']} and cannot become {to}")
    case["state"] = to
    case.update(fields)


def not_run(case: dict, reason: str) -> None:
    move(case, "not-run", not_run_reason=reason, owner_job=None)


# queue order ----------------------------------------------------------------------------------
def _source_key(case: dict) -> tuple:
    no = str(case.get("source", {}).get("no") or "")
    digits = re.match(r"\d+", no)
    return (int(digits.group()) if digits else 10**9, no, int(case["row"][1:]))


def queue_order(cases: list[dict], signed_in: str | None) -> list[dict]:
    """Scenario, then screen, then source order; the signed-in scenario and public pages first."""
    def key(case: dict) -> tuple:
        scenario = case.get("scenario") or ""
        first = 0 if scenario in (NO_SCENARIO, signed_in) else 1
        return (first, scenario, (case.get("screen") or {}).get("url") or "", _source_key(case))
    return sorted(cases, key=key)


def counts(run: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for case in run["cases"]:
        out[case["state"]] = out.get(case["state"], 0) + 1
    return out


def open_rows(run: dict) -> int:
    return sum(1 for c in run["cases"] if c["state"] in OPEN_STATES)


DIGEST_KEYS = ("content", "kind", "steps", "expected")
PLAN_LINE_KEYS = ("row", "class", "runner", "scenario", "viewport", "mobile_method", "preconditions", "screen")


def cases_digest(run: dict) -> str:
    """Each case's text, kind, steps and expected, in order.

    Works on the run's cases and on the review table's lines alike, so the server can hash what
    the tester was shown and the CLI can compare it with the run.
    """
    items = [[c["row"], *(c.get(k) or "" for k in DIGEST_KEYS)] for c in run["cases"]]
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()


# commands -------------------------------------------------------------------------------------
def _need_job(server: ConsoleReader, job: str, session: str, kind: str) -> dict:
    view = server.job(job, session)
    if view.get("kind") != kind or view.get("state") not in ("running", "needs-input"):
        raise WebtestError(f"job {job} is not an open {kind} job of this session")
    return view


def _need_run_job(server: ConsoleReader, job: str, session: str, run: dict) -> dict:
    view = _need_job(server, job, session, "webtest-run")
    if (view.get("params") or {}).get("run") != run["id"]:
        raise WebtestError(f"job {job} runs another run")
    return view


def new_run(root: Path, server: ConsoleReader, job: str, session: str, name: str | None,
            when: datetime | None = None) -> dict:
    view = _need_job(server, job, session, "webtest-plan")
    if view.get("run"):
        raise WebtestError(f"job {job} already has run {view['run']}")
    params = view.get("params") or {}
    run_id = new_run_id(name or params.get("name") or "run", when)
    if run_id in list_runs(root):
        raise WebtestError(f"run {run_id} already exists; wait a minute or choose another name")
    folder = root / run_id
    root.mkdir(parents=True, exist_ok=True)
    folder.mkdir()
    (folder / "source").mkdir()
    (folder / "evidence").mkdir()
    run = {
        "version": VERSION,
        "id": run_id,
        "name": name or params.get("name") or run_id,
        "created_at": now_iso(),
        "source": params.get("source") or {},
        "base_url": params.get("base_url"),
        "project": params.get("project"),
        "hosts": list(params.get("hosts") or []),
        "template": params.get("template"),
        "ticket": view.get("ticket") or params.get("ticket"),
        "report_lang": view.get("report_lang") or "vi",
        "ui_lang": view.get("ui_lang") or "vi",
        "plan_job": job,
        "jobs": {"current": job, "session": session},
        "signed_in": None,
        "import": {"staged": [], "complete": False},
        "digest": None,
        "confirmed": None,
        "columns": None,
        "cases": [],
        "halted": False,
        "requeues_in_a_row": 0,
        "closed": None,
        "exports": [],
    }
    save(folder, run)
    server.attach_run(job, session, run_id)
    return {"run": run_id, "folder": str(folder), "hosts": run["hosts"], "project": run["project"]}


def find_source(root: Path, file_key: str, node: str) -> list[dict]:
    out = []
    for run_id, folder in sorted(list_runs(root).items()):
        try:
            run = load(folder)
        except WebtestError:
            continue
        src = run.get("source") or {}
        if src.get("file") == file_key and src.get("node") == node:
            out.append({"run": run_id, "complete": run["import"]["complete"],
                        "staged": len(run["import"]["staged"]), "confirmed": bool(run.get("confirmed"))})
    return out


def _image_ext(data: bytes) -> str | None:
    if data.startswith(PNG_SIG):
        return ".png"
    if data.startswith(JPEG_SIG):
        return ".jpg"
    return None


def _staged_capture(folder: Path, row: str) -> Path | None:
    return next((p for p in (folder / "source" / f"{row}{ext}" for ext in (".png", ".jpg")) if p.exists()), None)


def stage(folder: Path, case_data: Any, capture: Path | None = None) -> dict:
    run = load(folder)
    if run["import"]["complete"]:
        raise WebtestError("the import of this run is complete")
    case = check_staged(case_data)
    row = case["row"]
    target = folder / "source" / f"{row}.json"
    text = json.dumps(case, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    data = ext = None
    if capture is not None:
        data = Path(capture).read_bytes()
        ext = _image_ext(data)
        if ext is None or len(data) > IMAGE_CAP:
            raise WebtestError("the capture must be a PNG or JPEG under 20 MB")
    if target.exists():
        if target.read_text(encoding="utf-8") != text:
            raise WebtestError(f"{row} is already staged with other content")
        again = {"row": row, "staged": len(run["import"]["staged"]), "again": True}
        if data is None:
            return again
        stored = _staged_capture(folder, row)
        if stored is None:
            # A row first staged without its capture takes the capture now instead of dropping it.
            fsutil.atomic_write_bytes(folder / "source" / f"{row}{ext}", data)
            return {**again, "capture_added": True}
        if stored.read_bytes() != data:
            raise WebtestError(f"{row} is already staged with another capture")
        return again
    if data is not None:
        fsutil.atomic_write_bytes(folder / "source" / f"{row}{ext}", data)
    fsutil.atomic_write_bytes(target, text.encode("utf-8"))
    run["import"]["staged"] = sorted(set(run["import"]["staged"]) | {row}, key=lambda r: int(r[1:]))
    save(folder, run)
    return {"row": row, "staged": len(run["import"]["staged"]), "again": False}


def import_staged(folder: Path) -> dict:
    run = load(folder)
    if run["import"]["complete"]:
        raise WebtestError("this run was already imported")
    cases = []
    for row in run["import"]["staged"]:
        data = json.loads((folder / "source" / f"{row}.json").read_text(encoding="utf-8"))
        case = check_staged(data)
        if case["row"] != row:
            raise WebtestError(f"source/{row}.json names another row")
        stored = _staged_capture(folder, row)
        capture = f"source/{stored.name}" if stored else None
        cases.append({**case, "capture": capture, "screen": None, "viewport": "pc", "kind": None, "class": None,
                      "reason": "", "scenario": None, "runner": None, "preconditions": "", "steps": "",
                      "expected": "", "state": "draft", "attempt": 0, "owner_job": None, "question": None,
                      "questions": [], "decided_by": None, "result": None, "evidence": []})
    if not cases:
        raise WebtestError("nothing is staged")
    run["cases"] = sorted(cases, key=_source_key)
    run["import"]["complete"] = True
    run["import"]["completed_at"] = now_iso()
    save(folder, run)
    return {"run": run["id"], "cases": len(cases)}


def triage(folder: Path, rows: Any) -> dict:
    """Store the agent's draft fields per case; only while the plan is not confirmed."""
    run = load(folder)
    if run.get("confirmed"):
        raise WebtestError("the plan of this run is confirmed; the draft cannot change")
    if not run["import"]["complete"]:
        raise WebtestError("import the run first")
    if not isinstance(rows, dict) or not rows:
        raise WebtestError('the triage file must be {"<row>": {...}, ...}')
    changed = []
    for row, fields in rows.items():
        case = case_of(run, row)
        if isinstance(fields, dict) and fields.get("mobile_method") == "emulation":
            raise WebtestError(f"{row}: {EMULATION_IS_THE_TESTERS}")
        case.update(check_triage(row, fields, run["hosts"]))
        case["mobile_method"] = mobile_method(case.get("viewport"), case.get("mobile_method"))
        changed.append(row)
    save(folder, run)
    return {"run": run["id"], "changed": changed}


def _initial_state(case: dict, decided: dict | None) -> None:
    """Draft → its first state at confirmation."""
    if case.get("class") == "not-web":
        case["runner"] = "none"
        move(case, "not-applicable" if case.get("kind") == "design-only" else "manual")
    elif case.get("runner") == "tester":
        move(case, "awaiting-tester")
    elif case.get("runner") == "agent":
        if case.get("class") == "choice":
            case["decided_by"] = decided
        if not case.get("scenario"):
            not_run(case, "no-scenario")
        elif not (case.get("screen") or {}).get("url"):
            not_run(case, "no-screen")
        else:
            move(case, "queued")
    else:
        case["runner"] = "none"
        not_run(case, "skipped" if case.get("class") == "sure" else "unanswered")


def apply_plan(folder: Path, server: ConsoleReader, job: str, session: str,
               check_columns: Callable[[dict, dict], dict] | None = None) -> dict:
    """Store the review table the tester confirmed, as the server holds it."""
    run = load(folder)
    if run.get("confirmed"):
        raise WebtestError("the plan of this run is already confirmed")
    _need_job(server, job, session, "webtest-plan")
    review = server.review(job, session)
    if not review or not isinstance(review.get("answer"), dict):
        raise WebtestError("the tester has not confirmed a review table in this job")
    lines = {line["row"]: line for line in review.get("lines") or [] if isinstance(line, dict) and "row" in line}
    for row, line in lines.items():
        if line.get("class") == "choice" and line.get("runner") == "agent":
            raise WebtestError(f"{row}: only the tester delegates a choice row; offer it with runner tester")
    if set(lines) != {c["row"] for c in run["cases"]}:
        raise WebtestError("the confirmed review table lists other rows than this run")
    if review.get("digest") != cases_digest(run):
        raise WebtestError("the cases changed after the review table was asked; ask again")
    answer = review["answer"]
    decided = {"by": review.get("answered_by"), "at": review.get("answered_at")}
    for case in run["cases"]:
        line = {**lines[case["row"]], **(answer.get("rows") or {}).get(case["row"], {})}
        fields = {k: line[k] for k in ("class", "runner", "scenario", "viewport", "mobile_method", "preconditions",
                                       "screen") if k in line}
        if fields.get("mobile_method") is None:
            fields.pop("mobile_method", None)
        if isinstance(fields.get("screen"), str):
            current = case.get("screen") or {}
            if fields["screen"] == current.get("url"):
                fields["screen"] = current or None
            else:  # set by the tester in the review table
                fields["screen"] = {"url": fields["screen"], "name": "",
                                    "confidence": "high" if fields["screen"] else "none"}
        fields = check_triage(case["row"], fields, run["hosts"])
        if fields.get("class") == "choice" and fields.get("runner") == "agent" and not fields.get("preconditions", "").strip():
            raise WebtestError(f"{case['row']}: a delegated choice row needs preconditions")
        viewport = fields.get("viewport", case.get("viewport"))
        method = mobile_method(viewport, fields.get("mobile_method"))
        if fields.get("runner") == "agent" and not agent_may_run(viewport, method):
            raise WebtestError(f"{case['row']}: phone-width rows on a real device go to the tester")
        before = case.get("class")
        case.update(fields)
        case["mobile_method"] = method
        if before and case.get("class") != before:
            case["class_changed"] = {"from": before, "to": case["class"], "at": now_iso(), "by": "review"}
        _initial_state(case, decided)
    columns = {"columns": answer.get("columns"), "verdict_labels": answer.get("verdict_labels"),
               "template": review.get("template") or run.get("template")}
    run["columns"] = check_columns(run, columns) if check_columns else columns
    run["confirmed"] = {"at": decided["at"] or now_iso(), "by": decided["by"], "job": job}
    run["digest"] = review.get("digest")
    save(folder, run)
    return {"run": run["id"], "counts": counts(run)}


def recover(folder: Path, server: ConsoleReader, job: str, session: str) -> dict:
    run = load(folder)
    _need_run_job(server, job, session, run)
    requeued = []
    for case in run["cases"]:
        if case["state"] != "running":
            continue
        owner = case.get("owner_job")
        if owner == job or (owner and server.job_open(owner)):
            raise WebtestError(f"{case['row']} is running in job {owner}, which is still open")
        move(case, "queued", owner_job=None)
        requeued.append(case["row"])
    run["signed_in"] = None
    run["halted"] = False
    run["requeues_in_a_row"] = 0
    run["jobs"] = {"current": job, "session": session}
    run["closed"] = None
    save(folder, run)
    return {"run": run["id"], "requeued": requeued, "counts": counts(run)}


def next_row(folder: Path, server: ConsoleReader, job: str, session: str) -> dict:
    """The next queued row the agent may run in ``job``.

    A scenario counts as signed in only when the tester confirmed it in this same job; a sign-in
    left in ``run.json`` by an earlier job is ignored.
    """
    run = load(folder)
    _need_run_job(server, job, session, run)
    if not run.get("confirmed"):
        raise WebtestError("the plan of this run is not confirmed")
    if any(c["state"] == "running" for c in run["cases"]):
        raise WebtestError("a row is already running; record its result first")
    if run.get("halted"):
        return {"row": None, "halted": True}
    run["jobs"] = {"current": job, "session": session}
    current = run.get("signed_in") or {}
    signed = current.get("scenario") if current.get("job") == job else None
    ready = [c for c in run["cases"] if c["state"] == "queued" and c.get("runner") == "agent" and c.get("scenario")]
    for case in queue_order(ready, signed):
        if case["scenario"] in (NO_SCENARIO, signed):
            case["attempt"] = int(case.get("attempt") or 0) + 1
            move(case, "running", owner_job=job, started_at=now_iso())
            save(folder, run)
            return {"row": case["row"], "attempt": case["attempt"], "case": worker_view(run, case)}
        save(folder, run)
        return {"row": None, "need": case["scenario"], "signed_in": signed}
    save(folder, run)
    return {"row": None}


def worker_view(run: dict, case: dict) -> dict:
    """The one row a worker gets, and nothing else of the run."""
    screen = case.get("screen") or {}
    url = screen.get("url") or ""
    if url.startswith("/"):
        url = (run.get("base_url") or "").rstrip("/") + url
    return {
        "row": case["row"], "url": url, "screen": screen.get("name") or "", "viewport": case.get("viewport"),
        "mobile_method": mobile_method(case.get("viewport"), case.get("mobile_method")),
        "kind": case.get("kind"), "steps": case.get("steps"), "expected": case.get("expected"),
        "preconditions": case.get("preconditions"), "capture": case.get("capture"),
        "hosts": list(run["hosts"]), "delegated": case.get("class") == "choice", "scenario": case.get("scenario"),
    }


def _current_evidence(case: dict) -> list[str]:
    return [e["file"] for e in case.get("evidence") or [] if e.get("attempt") == case.get("attempt")]


def record_row(folder: Path, row: str, result: Any) -> dict:
    run = load(folder)
    case = case_of(run, row)
    if case["state"] != "running":
        raise WebtestError(f"{row} is not running")
    if not isinstance(result, dict) or result.get("verdict") not in ("pass", "fail"):
        raise WebtestError('the result needs verdict "pass" or "fail"')
    actual = _text(result.get("actual"), "actual")
    url = _text(result.get("url"), "url", 2000)
    out = {"verdict": result["verdict"], "actual": actual, "url": url, "evidence": [],
           "executed_at": now_iso(), "by": "agent"}
    if not url_on_hosts(url, run["hosts"]):
        case["result"] = {**out, "verdict": "off-site"}
        not_run(case, "off-site")
        run["requeues_in_a_row"] = 0
        save(folder, run)
        return {"row": row, "state": "not-run", "reason": "off-site"}
    files = _current_evidence(case)
    if not files:
        raise WebtestError(f"{row} has no evidence for attempt {case['attempt']}; run webtest-evidence first")
    out["evidence"] = files
    case["result"] = out
    move(case, result["verdict"], owner_job=None)
    run["requeues_in_a_row"] = 0
    save(folder, run)
    return {"row": row, "state": case["state"], "evidence": files}


def add_evidence(folder: Path, row: str, data: bytes, source: str) -> dict:
    run = load(folder)
    case = case_of(run, row)
    if case["state"] not in ("running", "awaiting-tester"):
        raise WebtestError(f"{row} is {case['state']}; evidence goes to a running or awaiting-tester row")
    ext = _image_ext(data)
    if ext is None or len(data) > IMAGE_CAP:
        raise WebtestError("evidence must be a PNG or JPEG under 20 MB")
    attempt = int(case.get("attempt") or 0)
    taken = {p.name for p in (folder / "evidence").iterdir()} if (folder / "evidence").is_dir() else set()
    n = 1
    while any(name.startswith(f"{row}-a{attempt}-{n}.") for name in taken):
        n += 1
    name = f"{row}-a{attempt}-{n}{ext}"
    (folder / "evidence").mkdir(exist_ok=True)
    fsutil.atomic_write_bytes(folder / "evidence" / name, data)
    case.setdefault("evidence", []).append({"file": f"evidence/{name}", "attempt": attempt, "source": source})
    save(folder, run)
    return {"row": row, "file": f"evidence/{name}", "attempt": attempt}


def requeue(folder: Path, row: str, reason: str, signed_out: bool = False) -> dict:
    run = load(folder)
    case = case_of(run, row)
    if case["state"] != "running":
        raise WebtestError(f"{row} is not running")
    move(case, "queued", owner_job=None, last_requeue={"reason": _text(reason, "reason", 500), "at": now_iso()})
    run["requeues_in_a_row"] = int(run.get("requeues_in_a_row") or 0) + 1
    if run["requeues_in_a_row"] >= HALT_AFTER:
        run["halted"] = True
    if signed_out:
        if run.get("signed_in"):
            run["spent_sign_in"] = run["signed_in"].get("at")
        run["signed_in"] = None
    save(folder, run)
    return {"row": row, "state": "queued", "halted": run["halted"], "in_a_row": run["requeues_in_a_row"]}


def result_id(case: dict) -> str:
    """The id of a tester result for the row's current attempt: ``<row>-r<attempt>``.

    Distinct from a question id (``<row>-a<attempt>``): a row parked and then run by the tester has
    both in the same attempt, and the server keeps one list of applied ids.
    """
    return f"{case['row']}-r{int(case.get('attempt') or 0)}"


def park(folder: Path, row: str, question: Any) -> dict:
    run = load(folder)
    case = case_of(run, row)
    if case["state"] != "running":
        raise WebtestError(f"{row} is not running")
    body = question.get("body") if isinstance(question, dict) else question
    body = _text(body, "question", 2000, required=True)
    qid = f"{row}-a{case['attempt']}"
    if case.get("class") != "choice":
        case["class_changed"] = {"from": case.get("class"), "to": "choice", "at": now_iso(), "by": "park"}
        case["class"] = "choice"
    move(case, "parked", owner_job=None, question={"id": qid, "body": body, "asked_at": now_iso()})
    run["requeues_in_a_row"] = 0
    save(folder, run)
    return {"row": row, "state": "parked", "question": qid}


def _copy_tester_image(folder: Path, images: Path, image_id: str, case: dict) -> str | None:
    if not isinstance(image_id, str) or not IMAGE_ID_RE.match(image_id):
        return None
    try:
        found = [p for p in images.iterdir() if p.is_file() and p.stem == image_id]
    except OSError:
        return None
    if len(found) != 1:
        return None
    data = found[0].read_bytes()
    ext = _image_ext(data)
    if ext is None:
        return None
    attempt = int(case.get("attempt") or 0)
    n = 1
    while (folder / "evidence" / f"{case['row']}-a{attempt}-{n}{ext}").exists():
        n += 1
    name = f"evidence/{case['row']}-a{attempt}-{n}{ext}"
    (folder / "evidence").mkdir(exist_ok=True)
    fsutil.atomic_write_bytes(folder / name, data)
    case.setdefault("evidence", []).append({"file": name, "attempt": attempt, "source": "tester"})
    return name


def apply_pending(folder: Path, run: dict, pending: dict, images: Path) -> tuple[list[str], list[str]]:
    """Apply the tester's answers and results to ``run`` in memory; returns (applied, ignored) ids."""
    applied, ignored = [], []
    by_question = {c["question"]["id"]: c for c in run["cases"] if c["state"] == "parked" and c.get("question")}
    for qid, answer in sorted((pending.get("answers") or {}).items()):
        case = by_question.get(qid)
        action = answer.get("action") if isinstance(answer, dict) else None
        if case is None or action not in ACTIONS:
            ignored.append(qid)
            continue
        case["questions"] = [*(case.get("questions") or []), {**case["question"], "answer": action,
                                                             "answered_at": answer.get("at")}]
        if action == "delegate":
            pre = str(answer.get("preconditions") or "").strip()
            if not pre:
                ignored.append(qid)
                continue
            move(case, "queued", question=None, runner="agent", preconditions=pre[:2000],
                 decided_by={"by": answer.get("by"), "at": answer.get("at")})
        elif action == "self-run":
            move(case, "awaiting-tester", question=None, runner="tester")
        else:
            move(case, "not-run", question=None, runner="none", not_run_reason="skipped")
        applied.append(qid)
    for rid, result in sorted((pending.get("results") or {}).items()):
        row = rid.rpartition("-r")[0]
        case = next((c for c in run["cases"] if c["row"] == row), None)
        if (case is None or case["state"] != "awaiting-tester" or result_id(case) != rid
                or not isinstance(result, dict) or result.get("verdict") not in ("pass", "fail")):
            ignored.append(rid)
            continue
        files = []
        if result.get("image"):
            name = _copy_tester_image(folder, images, result["image"], case)
            if name:
                files.append(name)
        case["result"] = {"verdict": result["verdict"], "actual": str(result.get("actual") or "")[:TEXT_CAP],
                          "url": "", "evidence": files, "executed_at": result.get("at") or now_iso(),
                          "by": f"tester:{result.get('by') or ''}"}
        move(case, "self-run")
        applied.append(rid)
    return applied, ignored


def resolve(folder: Path, server: ConsoleReader, job: str, session: str, images: Path,
            wait: float | None = None) -> dict:
    run = load(folder)
    pending = server.pending(run["id"], job, session, wait)
    applied, ignored = apply_pending(folder, run, pending, images)
    if applied:
        save(folder, run)
    if applied or ignored:
        server.applied(run["id"], job, session, applied + ignored)
    return {"run": run["id"], "applied": applied, "ignored": ignored, "finish": bool(pending.get("finish")),
            "open": open_rows(run), "counts": counts(run)}


def signed_in(folder: Path, server: ConsoleReader, job: str, session: str, scenario: str) -> dict:
    run = load(folder)
    _need_run_job(server, job, session, run)
    answer = server.signed_in(job, session)
    if not answer or answer.get("scenario") != scenario:
        raise WebtestError(f"the tester has not answered the sign-in question for {scenario} in this job")
    if answer.get("choice") == "signed-in" and run.get("spent_sign_in") and answer.get("at") == run["spent_sign_in"]:
        raise WebtestError("the session was signed out after this sign-in; ask the tester to sign in again")
    if answer.get("choice") == "signed-in":
        run["signed_in"] = {"scenario": scenario, "job": job, "at": answer.get("at")}
        save(folder, run)
        return {"run": run["id"], "signed_in": scenario}
    skipped = []
    for case in run["cases"]:
        if case["state"] == "queued" and case.get("scenario") == scenario:
            not_run(case, "no-scenario")
            skipped.append(case["row"])
    save(folder, run)
    return {"run": run["id"], "signed_in": None, "skipped": skipped, "finish": answer.get("choice") == "finish"}


def close(folder: Path, job_open: Callable[[str], bool], stopped: bool = False) -> dict:
    run = load(folder)
    for case in run["cases"]:
        if case["state"] == "running" and case.get("owner_job") and job_open(case["owner_job"]):
            raise WebtestError(f"{case['row']} is running in job {case['owner_job']}, which is still open")
    closed = []
    for case in run["cases"]:
        state = case["state"]
        if state not in OPEN_STATES:
            continue
        if stopped or state in ("queued", "running"):
            reason = "stopped"
        else:
            reason = "unanswered" if state == "parked" else "no-result"
        not_run(case, reason)
        closed.append(case["row"])
    run["closed"] = {"at": now_iso(), "stopped": bool(stopped)}
    save(folder, run)
    return {"run": run["id"], "closed": closed, "counts": counts(run)}


def status(folder: Path) -> dict:
    run = load(folder)
    return {
        "run": run["id"], "name": run.get("name"), "project": run.get("project"), "hosts": run["hosts"],
        "confirmed": bool(run.get("confirmed")), "halted": bool(run.get("halted")),
        "signed_in": (run.get("signed_in") or {}).get("scenario"), "closed": run.get("closed"),
        "counts": counts(run), "open": open_rows(run), "jobs": run.get("jobs"),
        "rows": [{"row": c["row"], "state": c["state"], "class": c.get("class"), "runner": c.get("runner"),
                  "scenario": c.get("scenario"), **({"reason": c["not_run_reason"]} if c["state"] == "not-run" else {})}
                 for c in run["cases"]],
    }


def server_images_dir(home: Path | None, run_id: str) -> Path:
    """Where the console stores the images a tester uploaded for a run (resolved by listing)."""
    root = config.config_dir(home) / "webtest" / "runs"
    try:
        match = next((p for p in root.iterdir() if p.is_dir() and p.name == run_id), None)
    except OSError:
        match = None
    return (match / "images") if match else root / "-missing-"


def copy_file_evidence(folder: Path, row: str, path: Path) -> dict:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise WebtestError(f"cannot read the image: {type(exc).__name__}") from None
    return add_evidence(folder, row, data, "agent")
