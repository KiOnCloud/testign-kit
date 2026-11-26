"""Web test suites: a case list kept apart from runs, filled from one source, then run many times.

A suite lives in ``<output_dir>/webtest/suites/<suite-id>/``::

    suite.json          name, project, source, state, cases
    source/             captures (<case>.png|.jpg) and the copied Excel file of an excel source

States::

    generating ──finish_generate / stop_generating──▶ review ──confirm──▶ ready
                                                        ▲                  │
                                                        └──── any edit ────┘

A suite case keeps only design fields; run-time fields (state, attempt, result, evidence,
questions) live in the runs made from it. Each case save runs the per-case run rules, so
``confirm`` only checks the whole list. Suite ids are matched against a strict pattern and resolved
by listing the suites folder; a path is never accepted.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import fsutil, webtest, webtest_sources
from .webtest import WebtestError

VERSION = 1
SUITE_ID_RE = re.compile(r"^S\d{8}-\d{4}-[a-z0-9-]{1,40}$")
CASE_ID_RE = re.compile(r"^c\d{1,4}$")
TRACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
STATES = ("generating", "review", "ready")
CASE_LANGS = ("ja", "en", "vi")
MAX_CASES = 2000
NAME_CAP = 120

CASE_KEYS = {
    "case", "trace", "source", "content", "preconditions", "steps", "expected", "screen", "viewport",
    "mobile_method", "kind", "class", "reason", "runner", "scenario", "creator", "type", "capture",
}
EDIT_KEYS = CASE_KEYS - {"case", "capture"}
BULK_KEYS = {"class", "runner", "scenario"}
DIGEST_KEYS = ("content", "kind", "steps", "expected", "preconditions", "screen", "class", "runner", "scenario",
               "viewport", "mobile_method", "trace")
CHOICE_BY_AGENT = "only the tester delegates a choice case; offer it with runner tester"
CHOICE_NEEDS_PRECONDITIONS = "a delegated choice case needs preconditions"
DEVICE_IS_THE_TESTERS = "phone-width cases on a real device go to the tester"


class CaseError(WebtestError):
    """A case breaks the run rules; ``errors`` maps each field to its message."""

    def __init__(self, errors: dict[str, str], case: str | None = None) -> None:
        self.errors = errors
        self.case = case
        first = next(iter(errors.items()))
        super().__init__(f"{case + ': ' if case else ''}{first[0]}: {first[1]}")


# folders --------------------------------------------------------------------------------------
def suites_root(runs_root: Path) -> Path:
    return runs_root / "suites"


def list_suites(runs_root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    try:
        children = list(suites_root(runs_root).iterdir())
    except OSError:
        return found
    for child in children:
        try:
            if child.is_dir() and SUITE_ID_RE.match(child.name) and not webtest._is_link(child):
                found[child.name] = child
        except OSError:
            continue
    return found


def find_suite(runs_root: Path, suite_id: Any) -> Path:
    if not isinstance(suite_id, str) or not SUITE_ID_RE.match(suite_id):
        raise WebtestError("no such suite")
    folder = list_suites(runs_root).get(suite_id)
    if folder is None:
        raise WebtestError(f"no such suite: {suite_id}")
    return folder


def new_suite_id(name: str, taken: Iterable[str], when: datetime | None = None) -> str:
    stem = (when or datetime.now()).strftime("S%Y%m%d-%H%M-")
    base = webtest.slug(name)
    if base == "run":
        base = "suite"
    taken = set(taken)
    if stem + base not in taken:
        return stem + base
    for n in range(2, 1000):
        candidate = f"{stem}{base[:36].strip('-')}-{n}"
        if candidate not in taken:
            return candidate
    raise WebtestError("too many suites with this name this minute")


# one case -------------------------------------------------------------------------------------
def _screen(value: Any) -> dict | None:
    """A screen path on the run's base URL; the host comes from the run."""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = {"url": value, "name": "", "confidence": "high"}
    url = value.get("url") if isinstance(value, dict) else None
    if url not in (None, "") and not (isinstance(url, str) and url.startswith("/") and not url.startswith("//")):
        raise WebtestError("screen must be a path on the run's base URL, such as /office/edit")
    screen = webtest._check_screen(value, [], "screen")
    return screen if screen and (screen.get("url") or screen.get("name")) else None


def _source_block(value: Any) -> dict:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or "kind" in value or "trace" in value or len(value) > 20:
        raise WebtestError("source must be an object of short values (no kind or trace)")
    out = {}
    for key, item in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z_]{1,30}", key):
            raise WebtestError("source has a bad key")
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise WebtestError(f"source.{key} must be text or a number")
        out[key] = str(item)
        if len(out[key]) > webtest_sources.SOURCE_VALUE_CAP:
            raise WebtestError(f"source.{key} is too long")
    return out


def _trace(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [v for v in re.split(r"[\s,]+", value) if v]
    if not isinstance(value, list) or len(value) > 50 or not all(isinstance(v, str) and TRACE_RE.match(v)
                                                                   for v in value):
        raise WebtestError("trace must be a list of row ids such as B4 or R1")
    return list(dict.fromkeys(value))


def check_case(data: Any, *, by: str = "tester", case_id: str | None = None) -> dict:
    """One suite case with the run rules applied; raises ``CaseError`` with every field's message.

    ``by`` is ``agent`` for cases the agent stages: it may not switch a case to emulation or
    delegate a choice case, as in the review table today.
    """
    if not isinstance(data, dict):
        raise CaseError({"case": "a case must be a JSON object"}, case_id)
    extra = set(data) - CASE_KEYS
    if extra:
        raise CaseError({sorted(extra)[0]: "unknown field"}, case_id)
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}

    def take(key: str, fn) -> None:
        try:
            out[key] = fn(data.get(key))
        except WebtestError as exc:
            errors[key] = str(exc).split(": ", 1)[-1] if ": " in str(exc) else str(exc)

    for key, cap in (("content", webtest.TEXT_CAP), ("steps", webtest.TEXT_CAP), ("expected", webtest.TEXT_CAP),
                     ("preconditions", 2000), ("reason", 500), ("type", 100), ("creator", 200)):
        take(key, lambda v, key=key, cap=cap: webtest._text(v, key, cap))
    take("trace", _trace)
    take("source", _source_block)
    take("screen", _screen)
    take("scenario", lambda v: webtest._check_scenario(v, "scenario"))
    for key, allowed in (("kind", webtest.KINDS), ("class", webtest.CLASSES), ("runner", webtest.RUNNERS),
                         ("viewport", webtest.VIEWPORTS), ("mobile_method", webtest.MOBILE_METHODS)):
        value = data.get(key)
        if value in (None, ""):
            out[key] = None
        elif value not in allowed:
            errors[key] = f"must be one of {', '.join(allowed)}"
        else:
            out[key] = value
    out["viewport"] = out.get("viewport") or "pc"
    if not errors:
        if out["class"] == "not-web":
            if out["runner"] not in (None, "none"):
                errors["runner"] = webtest.NOT_WEB_RUNNER
            out["runner"] = "none"
        if out["mobile_method"] is not None and out["viewport"] != "mobile":
            errors["mobile_method"] = webtest.PC_METHOD
        if by == "agent" and out["mobile_method"] == "emulation":
            errors["mobile_method"] = webtest.EMULATION_IS_THE_TESTERS
        out["mobile_method"] = webtest.mobile_method(out["viewport"], out["mobile_method"])
        if out["runner"] == "agent" and not webtest.agent_may_run(out["viewport"], out["mobile_method"]):
            errors["runner"] = DEVICE_IS_THE_TESTERS
        if out["class"] == "choice" and out["runner"] == "agent":
            if by == "agent":
                errors["runner"] = CHOICE_BY_AGENT
            elif not out["preconditions"].strip():
                errors["preconditions"] = CHOICE_NEEDS_PRECONDITIONS
    if errors:
        raise CaseError(errors, case_id)
    out["creator"] = out["creator"] or by
    if isinstance(data.get("capture"), str):
        out["capture"] = data["capture"]
    return out


def confirm_errors(case: dict) -> dict[str, str]:
    """What a case still lacks before its suite can be run."""
    errors = {}
    if not (case.get("content") or "").strip():
        errors["content"] = "is required"
    if not case.get("class"):
        errors["class"] = "is required"
    if case.get("runner") == "agent" and case.get("class") != "not-web":
        # A run marks an agent case without these not-run at once, so the tester sets them here.
        if not (case.get("screen") or {}).get("url"):
            errors["screen"] = "an agent case needs a screen path"
        if not case.get("scenario"):
            errors["scenario"] = "an agent case needs a login scenario (none for a public page)"
    return errors


# the suite file -------------------------------------------------------------------------------
def check_suite(suite: Any) -> dict:
    if not isinstance(suite, dict) or suite.get("version") != VERSION:
        raise WebtestError("suite.json is not a web test suite of this version")
    if not isinstance(suite.get("id"), str) or not SUITE_ID_RE.match(suite["id"]):
        raise WebtestError("suite.json has a bad id")
    if suite.get("state") not in STATES:
        raise WebtestError("suite.json has an unknown state")
    source = suite.get("source")
    if not isinstance(source, dict) or source.get("kind") not in webtest_sources.kinds():
        raise WebtestError("suite.json has an unknown source")
    cases = suite.get("cases")
    if not isinstance(cases, list) or len(cases) > MAX_CASES:
        raise WebtestError("suite.json cases must be a list")
    seen = set()
    for case in cases:
        cid = case.get("case") if isinstance(case, dict) else None
        if not isinstance(cid, str) or not CASE_ID_RE.match(cid) or cid in seen:
            raise WebtestError("suite.json has a bad or repeated case id")
        seen.add(cid)
        capture = case.get("capture")
        if capture is not None and capture not in (f"source/{cid}.png", f"source/{cid}.jpg"):
            raise WebtestError(f"suite.json: {cid}.capture is not the case's file in the suite's source folder")
        check_case({k: v for k, v in case.items() if k != "case"}, by="tester", case_id=cid)
    return suite


def load(folder: Path) -> dict:
    try:
        data = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WebtestError(f"cannot read suite.json of {folder.name}: {type(exc).__name__}") from None
    return check_suite(data)


def save(folder: Path, suite: dict) -> None:
    suite["updated_at"] = webtest.now_iso()
    check_suite(suite)
    fsutil.atomic_write_bytes(folder / "suite.json",
                              (json.dumps(suite, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def suite_digest(suite: dict) -> str:
    """Each case's design fields, in order; a run records it to tell which version it copied."""
    items = [[c["case"], *(c.get(k) or "" for k in DIGEST_KEYS)] for c in suite["cases"]]
    return hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _name(value: Any) -> str:
    name = webtest._text(value, "name", NAME_CAP, required=True).strip()
    if re.search(r"[\x00-\x1f\x7f]", name):
        raise WebtestError("name has control characters")
    return name


def _project(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not webtest.NAME_RE.match(value):
        raise WebtestError("project must be a short lowercase name")
    return value


def _case_lang(value: Any) -> str:
    value = value or "ja"
    if value not in CASE_LANGS:
        raise WebtestError(f"case_lang must be one of {', '.join(CASE_LANGS)}")
    return value


def _next_case_id(suite: dict) -> str:
    top = max((int(c["case"][1:]) for c in suite["cases"]), default=0)
    if top >= 9999 or len(suite["cases"]) >= MAX_CASES:
        raise WebtestError(f"a suite holds at most {MAX_CASES} cases")
    return f"c{top + 1}"


def _edited(suite: dict) -> None:
    """Any edit of a ready suite sends it back to review."""
    if suite["state"] == "generating":
        raise WebtestError("the agent is still writing the cases of this suite")
    if suite["state"] == "ready":
        suite["state"] = "review"
        suite["confirmed_at"] = None
        suite["confirmed_by"] = None
        suite["suite_digest"] = None


def new_suite(runs_root: Path, *, name: Any, kind: Any, payload: Any, env: webtest_sources.Env,
              project: Any = None, case_lang: Any = None, upload: Path | None = None,
              when: datetime | None = None) -> dict:
    """Create a suite from one source. Excel cases are read now, Figma and Backlog wait for the agent."""
    entry = webtest_sources.get(kind)
    payload = dict(payload or {})
    name = _name(name)
    project = _project(project)
    case_lang = _case_lang(case_lang)
    source = webtest_sources.check(kind, payload, env)
    if entry.extract is not None and upload is None:
        raise WebtestError("this source needs its file")
    if upload is not None:
        webtest_sources.check_workbook_file(Path(upload))
    root = suites_root(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    suite_id = new_suite_id(name, list_suites(runs_root), when)
    folder = root / suite_id
    folder.mkdir()
    try:
        (folder / "source").mkdir()
        now = webtest.now_iso()
        suite = {
            "version": VERSION, "id": suite_id, "name": name, "project": project, "case_lang": case_lang,
            "created_at": now, "updated_at": now, "source": source,
            "state": "generating" if entry.needs_agent else "review",
            "generate_job": None, "confirmed_at": None, "confirmed_by": None, "suite_digest": None, "cases": [],
        }
        if entry.extract is not None:
            fsutil.atomic_write_bytes(folder / "source" / source["file"], Path(upload).read_bytes())
            for n, item in enumerate(entry.extract(source, env, folder), start=1):
                suite["cases"].append({"case": f"c{n}", **check_case(item, by="tester", case_id=f"c{n}"),
                                       "creator": "import"})
        save(folder, suite)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return show(folder, env)


def summary(suite: dict) -> dict:
    source = suite["source"]
    return {"id": suite["id"], "name": suite["name"], "project": suite.get("project"),
            "kind": source["kind"], "source": source, "state": suite["state"], "cases": len(suite["cases"]),
            "generate_job": suite.get("generate_job"), "case_lang": suite.get("case_lang"),
            "created_at": suite.get("created_at"), "updated_at": suite.get("updated_at"),
            "confirmed_at": suite.get("confirmed_at")}


def coverage(suite: dict, env: webtest_sources.Env | None, folder: Path | None = None) -> dict:
    """For a ``generate`` source: every source row with the cases that trace to it, the rows no case
    traces to, and the cases whose trace names no row. Every B* and R* row counts, not only the
    rows the survey marks as needing a case."""
    entry = webtest_sources.get(suite["source"]["kind"])
    if entry.mode != "generate" or env is None:
        return {"mode": entry.mode, "rows": [], "uncovered": [], "orphans": []}
    try:
        rows = entry.rows(suite["source"], env, folder)
    except webtest_sources.SourceError as exc:
        return {"mode": entry.mode, "rows": [], "uncovered": [], "orphans": [], "error": str(exc)}
    by_row: dict[str, list[str]] = {r["id"]: [] for r in rows}
    orphans = []
    for case in suite["cases"]:
        hits = [t for t in case.get("trace") or [] if t in by_row]
        for t in hits:
            by_row[t].append(case["case"])
        if not hits:
            orphans.append(case["case"])
    return {"mode": entry.mode,
            "rows": [{**r, "cases": by_row[r["id"]]} for r in rows],
            "uncovered": [r["id"] for r in rows if not by_row[r["id"]]],
            "orphans": orphans}


def show(folder: Path, env: webtest_sources.Env | None = None) -> dict:
    suite = load(folder)
    return {**summary(suite), "cases": suite["cases"], "coverage": coverage(suite, env, folder)}


# tester edits ---------------------------------------------------------------------------------
def rename(folder: Path, name: Any = None, project: Any = ...) -> dict:
    suite = load(folder)
    if name is not None:
        suite["name"] = _name(name)
    if project is not ...:
        suite["project"] = _project(project)
    save(folder, suite)
    return summary(suite)


def add_case(folder: Path, fields: Any, by: str = "tester") -> dict:
    suite = load(folder)
    _edited(suite)
    case_id = _next_case_id(suite)
    if isinstance(fields, dict) and set(fields) & {"case", "capture"}:
        raise CaseError({"case": "the case id and capture are set by the suite"}, case_id)
    case = {"case": case_id, **check_case(fields or {}, by=by, case_id=case_id)}
    suite["cases"].append(case)
    save(folder, suite)
    return {"suite": suite["id"], "state": suite["state"], "case": case}


def update_case(folder: Path, case_id: Any, fields: Any, by: str = "tester") -> dict:
    suite = load(folder)
    _edited(suite)
    case = next((c for c in suite["cases"] if c["case"] == case_id), None)
    if case is None:
        raise WebtestError(f"no case {case_id} in this suite")
    if not isinstance(fields, dict) or set(fields) - EDIT_KEYS:
        raise CaseError({sorted(set(fields) - EDIT_KEYS)[0] if isinstance(fields, dict) else "case":
                         "cannot be changed"}, case_id)
    merged = {k: v for k, v in {**case, **fields}.items() if k != "case"}
    case.clear()
    case.update({"case": case_id, **check_case(merged, by=by, case_id=case_id)})
    save(folder, suite)
    return {"suite": suite["id"], "state": suite["state"], "case": case}


def delete_cases(folder: Path, case_ids: Any) -> dict:
    suite = load(folder)
    _edited(suite)
    ids = set(case_ids) if isinstance(case_ids, list) else set()
    known = {c["case"] for c in suite["cases"]}
    if not ids or ids - known:
        raise WebtestError("name cases of this suite to delete")
    for case in suite["cases"]:
        if case["case"] in ids and case.get("capture"):
            try:
                (folder / case["capture"]).unlink()
            except OSError:
                pass
    suite["cases"] = [c for c in suite["cases"] if c["case"] not in ids]
    save(folder, suite)
    return {"suite": suite["id"], "state": suite["state"], "deleted": sorted(ids, key=lambda c: int(c[1:]))}


def bulk_update(folder: Path, case_ids: Any, fields: Any) -> dict:
    """Change class, runner or scenario of many cases; nothing is saved when one case breaks a rule."""
    suite = load(folder)
    _edited(suite)
    if not isinstance(fields, dict) or not fields or set(fields) - BULK_KEYS:
        raise WebtestError("a bulk edit changes class, runner or scenario")
    ids = set(case_ids) if isinstance(case_ids, list) else set()
    if not ids or ids - {c["case"] for c in suite["cases"]}:
        raise WebtestError("name cases of this suite to change")
    updates = {}
    for case in suite["cases"]:
        if case["case"] in ids:
            merged = {k: v for k, v in {**case, **fields}.items() if k != "case"}
            updates[case["case"]] = check_case(merged, by="tester", case_id=case["case"])
    for case in suite["cases"]:
        if case["case"] in updates:
            cid = case["case"]
            case.clear()
            case.update({"case": cid, **updates[cid]})
    save(folder, suite)
    return {"suite": suite["id"], "state": suite["state"], "changed": sorted(updates, key=lambda c: int(c[1:]))}


def confirm(folder: Path, by: Any = None) -> dict:
    """Review → ready, when every case can be run."""
    suite = load(folder)
    if suite["state"] == "generating":
        raise WebtestError("the agent is still writing the cases of this suite")
    if not suite["cases"]:
        raise WebtestError("a suite needs at least one case")
    problems = {}
    for case in suite["cases"]:
        errors = confirm_errors(case)
        try:
            check_case({k: v for k, v in case.items() if k != "case"}, by="tester", case_id=case["case"])
        except CaseError as exc:
            errors = {**exc.errors, **errors}
        if errors:
            problems[case["case"]] = errors
    if problems:
        first = next(iter(problems))
        err = CaseError(problems[first], first)
        err.problems = problems  # type: ignore[attr-defined]
        raise err
    suite["state"] = "ready"
    suite["confirmed_at"] = webtest.now_iso()
    suite["confirmed_by"] = str(by)[:100] if isinstance(by, str) and by.strip() else None
    suite["suite_digest"] = suite_digest(suite)
    save(folder, suite)
    return {**summary(suite), "suite_digest": suite["suite_digest"]}


def duplicate(runs_root: Path, folder: Path, name: Any = None, when: datetime | None = None) -> dict:
    suite = load(folder)
    if suite["state"] == "generating":
        raise WebtestError("the agent is still writing the cases of this suite")
    name = _name(name if name not in (None, "") else f"{suite['name']} (copy)"[:NAME_CAP])
    new_id = new_suite_id(name, list_suites(runs_root), when)
    target = suites_root(runs_root) / new_id
    target.mkdir()
    try:
        (target / "source").mkdir()
        for child in (folder / "source").iterdir():
            if child.is_file() and not webtest._is_link(child):
                shutil.copyfile(child, target / "source" / child.name)
        copy = {**json.loads(json.dumps(suite)), "id": new_id, "name": name, "created_at": webtest.now_iso(),
                "state": "review", "generate_job": None, "confirmed_at": None, "confirmed_by": None,
                "suite_digest": None}
        save(target, copy)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return summary(copy)


def remove(folder: Path, open_runs: list[str]) -> dict:
    """Delete a suite; refused while a run made from it is still open."""
    suite = load(folder)
    if open_runs:
        raise WebtestError(f"run {open_runs[0]} made from this suite is still open; close it first")
    shutil.rmtree(folder)
    return {"suite": suite["id"], "removed": True}


# agent writes ---------------------------------------------------------------------------------
def _need_generating(suite: dict, job: Any) -> None:
    if suite["state"] != "generating":
        raise WebtestError("this suite is not waiting for generated cases")
    if suite.get("generate_job") and job != suite["generate_job"]:
        raise WebtestError(f"job {job} does not generate this suite")


def attach_job(folder: Path, job: str, replace: bool = False) -> dict:
    """Record the ``suite-generate`` job of a suite that is waiting for one.

    ``replace`` lets a new job take over from one that ended; the caller checked that no other job
    generating this suite is still active.
    """
    suite = load(folder)
    if suite["state"] != "generating":
        raise WebtestError("this suite is not waiting for generated cases")
    if not replace and suite.get("generate_job") not in (None, job):
        raise WebtestError(f"suite {suite['id']} is already generated by job {suite['generate_job']}")
    suite["generate_job"] = job
    save(folder, suite)
    return summary(suite)


def _store_capture(folder: Path, case_id: str, capture: Path) -> str:
    try:
        if webtest._is_link(Path(capture)) or Path(capture).stat().st_size > webtest.IMAGE_CAP:
            raise OSError
        data = Path(capture).read_bytes()
    except OSError:
        raise WebtestError("the capture must be a PNG or JPEG under 20 MB") from None
    ext = webtest._image_ext(data)
    if ext is None or len(data) > webtest.IMAGE_CAP:
        raise WebtestError("the capture must be a PNG or JPEG under 20 MB")
    for other in (".png", ".jpg"):
        if other != ext:
            (folder / "source" / f"{case_id}{other}").unlink(missing_ok=True)
    fsutil.atomic_write_bytes(folder / "source" / f"{case_id}{ext}", data)
    return f"source/{case_id}{ext}"


def stage_generated(folder: Path, items: Any, job: Any) -> dict:
    """The agent's cases while the suite is ``generating``: new ones, or fields of earlier ones.

    Each item is a case; with ``case`` it updates that case, without it adds one. Every item is
    checked before anything is written.
    """
    suite = load(folder)
    _need_generating(suite, job)
    if not isinstance(items, list) or not items:
        raise WebtestError('the stage file must be a list of cases: [{"content": ...}, ...]')
    by_id = {c["case"]: c for c in suite["cases"]}
    planned = []
    work = {"cases": list(suite["cases"])}
    for item in items:
        if not isinstance(item, dict) or "capture" in item:
            raise WebtestError("each staged case is an object without a capture")
        cid = item.get("case")
        if cid is not None:
            if cid not in by_id:
                raise WebtestError(f"no case {cid} in this suite")
            merged = {k: v for k, v in {**by_id[cid], **item}.items() if k != "case"}
            planned.append((cid, check_case(merged, by="agent", case_id=cid)))
        else:
            cid = _next_case_id(work)
            work["cases"].append({"case": cid})
            body = {k: v for k, v in item.items() if k != "case"}
            planned.append((cid, check_case(body, by="agent", case_id=cid)))
    for cid, case in planned:
        if cid in by_id:
            capture = by_id[cid].get("capture")
            by_id[cid].clear()
            by_id[cid].update({"case": cid, **case, **({"capture": capture} if capture else {})})
        else:
            suite["cases"].append({"case": cid, **case})
    save(folder, suite)
    return {"suite": suite["id"], "staged": [cid for cid, _ in planned], "cases": len(suite["cases"])}


def stage_rows(folder: Path, rows: list[dict], captures: Path | None, job: Any) -> dict:
    """Rows of a Figma table (``figma_table.parse``) as suite cases, one case per table row.

    A row already staged (same row layer) is skipped, or only takes its missing capture. Without
    ``captures``: the capture URLs still to download. With it: each row is staged with
    ``<captures>/<row>.png|.jpg``; when a needed capture is missing nothing is staged.
    """
    suite = load(folder)
    _need_generating(suite, job)
    staged = {(c.get("source") or {}).get("row_node"): c for c in suite["cases"]}
    todo, skipped = [], []
    for r in rows:
        done = staged.get(r["source"].get("row_node"))
        if done is None or (r.get("capture_url") and not done.get("capture")):
            todo.append(r)
        else:
            skipped.append(r["row"])
    if captures is None:
        return {"suite": suite["id"], "rows": [{"row": r["row"], "capture_url": r.get("capture_url")} for r in todo],
                "skipped": skipped, "numbered_by": rows[0].get("numbered_by") if rows else None}
    files = {r["row"]: next((p for p in (captures / f"{r['row']}{ext}" for ext in (".png", ".jpg")) if p.is_file()),
                            None) for r in todo}
    missing = [r["row"] for r in todo if r.get("capture_url") and files[r["row"]] is None]
    if missing:
        raise WebtestError(f"no capture for {', '.join(missing)} in {captures.name}; nothing was staged")
    added = []
    for r in todo:
        case = staged.get(r["source"].get("row_node"))
        if case is None:
            cid = _next_case_id(suite)
            block = {k: v for k, v in r["source"].items() if k not in ("kind", "file")}
            case = {"case": cid, **check_case({"source": block, "content": r["content"], "type": r.get("type"),
                                               "creator": r.get("creator") or "agent"}, by="agent", case_id=cid)}
            suite["cases"].append(case)
            staged[r["source"].get("row_node")] = case
        if r.get("capture_url") and files[r["row"]] is not None:
            case["capture"] = _store_capture(folder, case["case"], files[r["row"]])
        added.append(case["case"])
    suite["cases"].sort(key=lambda c: webtest._source_key({"source": c.get("source") or {}, "row": "r" + c["case"][1:]}))
    save(folder, suite)
    return {"suite": suite["id"], "staged": added, "skipped": skipped, "total": len(suite["cases"]),
            "without_capture": [r["row"] for r in todo if not r.get("capture_url")]}


def finish_generate(folder: Path, job: Any) -> dict:
    suite = load(folder)
    _need_generating(suite, job)
    if not suite["cases"]:
        raise WebtestError("no case was staged; stage the cases first")
    suite["state"] = "review"
    save(folder, suite)
    return summary(suite)


def stop_generating(folder: Path) -> dict:
    """The generate job ended without finishing: keep what was staged and let the tester review it."""
    suite = load(folder)
    if suite["state"] == "generating":
        suite["state"] = "review"
        save(folder, suite)
    return summary(suite)


def capture_path(folder: Path, name: Any) -> Path:
    """A capture file of the suite by its name (``c3.png``), refused when linked or unknown."""
    if not isinstance(name, str) or not re.fullmatch(r"c\d{1,4}\.(png|jpg)", name):
        raise WebtestError("no such capture")
    path = folder / "source" / name
    if webtest._is_link(folder / "source") or webtest._is_link(path) or not path.is_file():
        raise WebtestError("no such capture")
    return path


# export and runs --------------------------------------------------------------------------------
def trace_text(suite: dict, case: dict) -> str:
    """What the trace column shows for a case: its row ids, else what the source names it by."""
    if case.get("trace"):
        return ", ".join(case["trace"])
    entry = webtest_sources.REGISTRY.get(suite["source"].get("kind"))
    return entry.trace_value(case.get("source") or {}) if entry else ""


def export_workbook(folder: Path, suite: dict, entry: dict) -> dict:
    """The suite's cases in a new copy of a test case template (no, item, steps, expected, trace)."""
    from . import xlsx  # noqa: PLC0415

    if not suite["cases"]:
        raise WebtestError("the suite has no cases to export")
    columns = {role: letter for role, letter in (entry.get("columns") or {}).items()
               if role in ("no", "item", "steps", "expected", "trace")}
    if "item" not in columns:
        raise WebtestError("the template maps no item column")
    rows = []
    for n, case in enumerate(suite["cases"], start=1):
        steps = case.get("steps") or ""
        if case.get("preconditions"):
            steps = f"{case['preconditions']}\n{steps}".strip()
        rows.append({"no": (case.get("source") or {}).get("no") or n, "item": case.get("content") or "",
                     "steps": steps, "expected": case.get("expected") or "", "trace": trace_text(suite, case)})
    written = xlsx.fill_columns(Path(entry["path"]), entry["sheet"], int(entry["header_row"]), columns, rows,
                                folder / f"{suite['id']}-testcases.xlsx")
    return {"workbook": written["path"], "name": Path(written["path"]).name, "rows": len(rows)}


def runs_of(runs_root: Path, suite_id: str) -> list[dict]:
    """The runs made from a suite, newest first, with whether each is still open."""
    out = []
    for run_id, folder in sorted(webtest.list_runs(runs_root).items(), reverse=True):
        try:
            run = webtest.load(folder)
        except WebtestError:
            continue
        if (run.get("suite") or {}).get("id") != suite_id:
            continue
        out.append({"id": run_id, "name": run.get("name"), "created_at": run.get("created_at"),
                    "base_url": run.get("base_url"), "counts": webtest.counts(run), "closed": run.get("closed"),
                    "open": not run.get("closed") and webtest.open_rows(run) > 0,
                    "suite_digest": run["suite"].get("suite_digest")})
    return out


def create_run(runs_root: Path, suite_id: Any, *, name: Any, base_url: Any, project: Any, template: Any,
               tester: Any, home: Path | None = None, report_lang: Any = None, when: datetime | None = None,
               browsers: Any = None) -> dict:
    """A run copied from a ready suite onto one environment, with its first-guess column plan."""
    from . import login_scenarios, templates, webtest_export  # noqa: PLC0415

    folder = find_suite(runs_root, suite_id)
    suite = load(folder)
    target = webtest.check_run_target(login_scenarios.load_projects(home), templates.list_templates(home),
                                      base_url, project, template, browsers)
    try:
        entry = templates.resolve(target["template"], home)
    except templates.TemplateError as exc:
        raise WebtestError(str(exc)) from None
    return webtest.new_run_from_suite(runs_root, suite, folder, name=name, target=target, tester=tester,
                                      columns_for=lambda run: webtest_export.suite_plan(run, entry),
                                      report_lang=report_lang if report_lang in ("vi", "en", "ja") else "en",
                                      when=when)
