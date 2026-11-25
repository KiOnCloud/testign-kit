"""Web test runs in the console: read routes, the tester's answers and results, images, finish.

Runs live in ``<output_dir>/webtest/<run-id>/``. The CLI writes them while a job runs; the server
writes ``run.json`` only to create a run from a suite (``suite_api``) and to change its export
columns while no job is working on it (``put_columns``). The tester's
decisions live in ``~/.testign-kit/webtest/runs/<run-id>/answers.json`` (owner-only), written by
this module only::

    {"answers": {"<row>-a<attempt>": {"action", "preconditions"?, "at", "by"}},
     "results": {"<row>-r<attempt>": {"verdict", "actual", "image"?, "at", "by"}},
     "applied": ["<id>", ...],
     "finish":  {"ts", "at", "by"} | null}

One direction only: the server never reads its answers back into a decision on ``run.json``; the
CLI (``webtest-resolve``, ``webtest-export --apply-pending``) applies them and marks them applied.
Run ids and file names from a request are matched against a pattern and resolved by listing.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from .. import config, fsutil, login_scenarios, templates, webtest, webtest_export
from .server import ApiError, Response

ANSWER_CAP = 2000
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_cache: dict[str, tuple[tuple, int]] = {}
COLUMNS_LOCK = threading.Lock()


def now_iso() -> str:
    return login_scenarios.now_iso()


# locations ------------------------------------------------------------------------------------
def runs_root(state) -> Path:
    from . import readapi  # noqa: PLC0415 - readapi imports the server module too

    return webtest.runs_root(readapi.load_config(state))


def run_folder(state, run_id: Any) -> Path:
    try:
        return webtest.find_run(runs_root(state), run_id)
    except webtest.WebtestError:
        raise ApiError(404, "not-found", "no such run") from None


def load_run(folder: Path) -> dict:
    try:
        return webtest.load(folder)
    except webtest.WebtestError:
        raise ApiError(409, "run-unreadable", "run.json cannot be read") from None


def server_dir(home: Path | None, run_id: str, create: bool = False) -> Path:
    """``~/.testign-kit/webtest/runs/<run-id>``; ``run_id`` was matched and found by listing first."""
    root = config.config_dir(home) / "webtest" / "runs"
    try:
        found = next((p for p in root.iterdir() if p.is_dir() and p.name == run_id), None)
    except OSError:
        found = None
    if found is None:
        found = root / run_id
        if create:
            login_scenarios.ensure_store(home)
            fsutil.owner_only_dirs(found, found / "images")
    return found


def _empty() -> dict:
    return {"answers": {}, "results": {}, "applied": [], "finish": None}


def read_answers(home: Path | None, run_id: str) -> dict:
    path = server_dir(home, run_id) / "answers.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    for key in ("answers", "results"):
        if isinstance(data.get(key), dict):
            out[key] = data[key]
    if isinstance(data.get("applied"), list):
        out["applied"] = [a for a in data["applied"] if isinstance(a, str)]
    if isinstance(data.get("finish"), dict):
        out["finish"] = data["finish"]
    return out


def write_answers(home: Path | None, run_id: str, data: dict) -> None:
    folder = server_dir(home, run_id, create=True)
    fsutil.atomic_write_bytes(folder / "answers.json",
                              (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), mode=0o600)


# what the bridge reads --------------------------------------------------------------------------
def finished(state, run_id: str) -> bool:
    """The tester ended the run after its newest job was queued."""
    bridge = getattr(state, "bridge", None)
    finish = read_answers(state.home, run_id).get("finish") or {}
    since = bridge.run_created_ts(run_id) if bridge is not None else None
    ts = finish.get("ts")
    return isinstance(ts, (int, float)) and (since is None or ts >= since)


def _waiting_on_tester(run: dict, answers: dict) -> int:
    count = 0
    for case in run["cases"]:
        if case["state"] == "parked" and (case.get("question") or {}).get("id") not in answers["answers"]:
            count += 1
        elif case["state"] == "awaiting-tester" and webtest.result_id(case) not in answers["results"]:
            count += 1
    return count


def needs_input(state) -> int:
    """Open run questions and rows awaiting a tester result, over the runs that are not closed."""
    total = 0
    for run_id, folder in webtest.list_runs(runs_root(state)).items():
        answers_path = server_dir(state.home, run_id) / "answers.json"
        try:
            key = ((folder / "run.json").stat().st_mtime_ns,
                   answers_path.stat().st_mtime_ns if answers_path.exists() else 0)
        except OSError:
            continue
        cached = _cache.get(str(folder))
        if cached and cached[0] == key:
            total += cached[1]
            continue
        try:
            run = webtest.load(folder)
        except webtest.WebtestError:
            continue
        count = 0 if run.get("closed") else _waiting_on_tester(run, read_answers(state.home, run_id))
        _cache[str(folder)] = (key, count)
        total += count
    return total


# views ------------------------------------------------------------------------------------------
def _summary(run_id: str, folder: Path) -> dict:
    try:
        run = webtest.load(folder)
    except webtest.WebtestError:
        return {"id": run_id, "readable": False}
    return {"id": run_id, "readable": True, "name": run.get("name"), "created_at": run.get("created_at"),
            "source": run.get("source"), "suite": run.get("suite"), "base_url": run.get("base_url"),
            "tester": run.get("tester"), "project": run.get("project"), "ticket": run.get("ticket"),
            "confirmed": bool(run.get("confirmed")), "closed": run.get("closed"), "halted": bool(run.get("halted")),
            "counts": webtest.counts(run), "open": webtest.open_rows(run),
            "exports": [{k: e.get(k) for k in ("at", "workbook", "report")} for e in run.get("exports") or []]}


def list_runs(state) -> dict:
    runs = [_summary(run_id, folder) for run_id, folder in webtest.list_runs(runs_root(state)).items()]
    runs.sort(key=lambda r: r["id"], reverse=True)
    return {"runs": runs}


CASE_VIEW = ("row", "content", "creator", "type", "capture", "screen", "viewport", "mobile_method", "kind", "class",
             "reason", "scenario", "runner", "preconditions", "steps", "expected", "state", "attempt", "not_run_reason",
             "question", "questions", "result", "evidence", "class_changed", "last_requeue")


def run_view(state, run_id: Any, session: str | None = None) -> dict:
    """The run for a browser tab; ``can_act`` says whether this tab may answer on the run screen."""
    folder = run_folder(state, run_id)
    run = load_run(folder)
    answers = read_answers(state.home, run["id"])
    cases = []
    for case in run["cases"]:
        view = {k: case.get(k) for k in CASE_VIEW if k in case}
        qid = (case.get("question") or {}).get("id")
        if case["state"] == "parked" and qid in answers["answers"]:
            view["answer"] = answers["answers"][qid]  # stored, not yet applied by the agent
        rid = webtest.result_id(case)
        if case["state"] == "awaiting-tester" and rid in answers["results"]:
            view["tester_result"] = answers["results"][rid]
        cases.append(view)
    bridge = getattr(state, "bridge", None)
    from .jobs import tab_can_answer  # noqa: PLC0415 - jobs imports this module

    jobs = []
    can_act = True
    if bridge is not None:
        with bridge.cond:
            jobs = [bridge.summary(j) for j in sorted(bridge.jobs.values(), key=lambda j: j["created_at"],
                                                      reverse=True) if j.get("run") == run["id"]]
            can_act = tab_can_answer(bridge.run_cutoff(run["id"]), state.session_created(session))
    keep = ("id", "name", "created_at", "source", "suite", "tester", "base_url", "project", "hosts", "template", "ticket",
            "report_lang", "confirmed", "columns", "signed_in", "halted", "closed", "exports", "import")
    return {**{k: run.get(k) for k in keep}, "counts": webtest.counts(run), "open": webtest.open_rows(run),
            "cases": cases, "jobs": jobs, "finish": answers["finish"], "can_act": can_act,
            "waiting_on_tester": _waiting_on_tester(run, answers)}


def _file(folder: Path, sub: str, name: Any) -> Response:
    if not isinstance(name, str) or "/" in name or "\\" in name or name.startswith("."):
        raise ApiError(404, "not-found", "no such file")
    try:
        found = next((p for p in (folder / sub).iterdir() if p.is_file() and p.name == name), None)
    except OSError:
        found = None
    ctype = IMAGE_TYPES.get(found.suffix.lower()) if found else None
    if found is None or ctype is None:
        raise ApiError(404, "not-found", "no such file")
    try:
        data = found.read_bytes()
    except OSError:
        raise ApiError(404, "not-found", "no such file") from None
    return Response(200, raw=data, content_type=ctype, headers={"Cache-Control": "no-cache"})


# tester actions -----------------------------------------------------------------------------------
def _by(session: str | None) -> str | None:
    from .jobs import fingerprint  # noqa: PLC0415

    return fingerprint(session)


def _tester_action(state, run_id: Any, session: str | None):
    """Common checks: the run exists, and the tab is older than the run's queued or open job."""
    folder = run_folder(state, run_id)
    run = load_run(folder)
    bridge = state.bridge
    bridge.check_run_session(run["id"], state.session_created(session))
    return folder, run


def answer_question(state, run_id: Any, question: Any, body: Any, session: str | None) -> dict:
    if not isinstance(body, dict) or body.get("action") not in webtest.ACTIONS:
        raise ApiError(400, "bad-request", "action must be delegate, self-run or skip")
    with state.bridge.cond:
        _, run = _tester_action(state, run_id, session)
        case = next((c for c in run["cases"] if c["state"] == "parked"
                     and (c.get("question") or {}).get("id") == question), None)
        if case is None:
            raise ApiError(409, "conflict", "this question is not open in the run; reload")
        entry: dict[str, Any] = {"action": body["action"], "at": now_iso(), "by": _by(session)}
        if body["action"] == "delegate":
            pre = body.get("preconditions")
            if not isinstance(pre, str) or not pre.strip():
                raise ApiError(400, "preconditions-required",
                               "delegating a row to the agent needs its preconditions")
            if len(pre) > ANSWER_CAP:
                raise ApiError(400, "too-long", f"preconditions must be at most {ANSWER_CAP} characters")
            entry["preconditions"] = pre.strip()
        answers = read_answers(state.home, run["id"])
        answers["answers"][question] = entry
        write_answers(state.home, run["id"], answers)
        state.bridge.run_changed()
        return {"ok": True, "question": question, "answer": entry}


def tester_result(state, run_id: Any, row: Any, body: Any, session: str | None) -> dict:
    if not isinstance(body, dict) or body.get("verdict") not in ("pass", "fail"):
        raise ApiError(400, "bad-request", 'verdict must be "pass" or "fail"')
    actual = body.get("actual") or ""
    if not isinstance(actual, str) or len(actual) > webtest.TEXT_CAP:
        raise ApiError(400, "bad-request", "actual is too long")
    image = body.get("image")
    with state.bridge.cond:
        _, run = _tester_action(state, run_id, session)
        case = next((c for c in run["cases"] if c["row"] == row), None)
        if case is None or case["state"] != "awaiting-tester":
            raise ApiError(409, "conflict", "this row is not waiting for a tester result; reload")
        entry: dict[str, Any] = {"verdict": body["verdict"], "actual": actual.strip(), "at": now_iso(),
                                 "by": _by(session)}
        if image is not None:
            images = server_dir(state.home, run["id"]) / "images"
            if not isinstance(image, str) or not webtest.IMAGE_ID_RE.match(image) or not _has_image(images, image):
                raise ApiError(400, "bad-request", "no such image; upload it first")
            entry["image"] = image
        rid = webtest.result_id(case)
        answers = read_answers(state.home, run["id"])
        answers["results"][rid] = entry
        write_answers(state.home, run["id"], answers)
        state.bridge.run_changed()
        return {"ok": True, "result": rid}


def _has_image(images: Path, image_id: str) -> bool:
    try:
        return any(p.is_file() and p.stem == image_id for p in images.iterdir())
    except OSError:
        return False


def upload_image(state, run_id: Any, data: Any, session: str | None) -> dict:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ApiError(400, "bad-request", "send the image as the request body")
    ext = ".png" if data.startswith(webtest.PNG_SIG) else ".jpg" if data.startswith(webtest.JPEG_SIG) else None
    if ext is None:
        raise ApiError(415, "not-an-image", "the file must be a PNG or JPEG image")
    if len(data) > webtest.IMAGE_CAP:
        raise ApiError(413, "too-large", "the image must be under 20 MB")
    with state.bridge.cond:
        _, run = _tester_action(state, run_id, session)
        folder = server_dir(state.home, run["id"], create=True)
        image_id = secrets.token_hex(8)
        fsutil.atomic_write_bytes(folder / "images" / f"{image_id}{ext}", bytes(data), mode=0o600)
        return {"image": image_id}


def finish(state, run_id: Any, session: str | None) -> dict:
    with state.bridge.cond:
        _, run = _tester_action(state, run_id, session)
        answers = read_answers(state.home, run["id"])
        answers["finish"] = {"ts": time.time(), "at": now_iso(), "by": _by(session)}
        write_answers(state.home, run["id"], answers)
        ended = state.bridge.finish_sign_in(run["id"], session)
        state.bridge.run_changed()
        return {"ok": True, "sign_in_ended": ended}


# agent reads ---------------------------------------------------------------------------------------
def columns(state, run_id: Any) -> dict:
    """The run's export columns, with the headers of its template for the editor on the run page."""
    folder = run_folder(state, run_id)
    run = load_run(folder)
    plan = run.get("columns")
    if not plan:
        raise ApiError(409, "conflict", "this run has no export columns yet")
    try:
        facts = webtest_export.sheet_facts(webtest_export._entry(plan.get("template") or run.get("template"),
                                                                 state.home))
    except webtest.WebtestError as exc:
        raise ApiError(409, "conflict", str(exc)) from None
    return {"plan": plan, "headers": facts["headers"], "last_column": webtest_export._letter(max(facts["last"], 1)),
            "fields": list(webtest_export.CASE_FIELDS),
            "templates": [t["name"] for t in templates.list_templates(state.home)["templates"]
                          if templates.purpose_of(t) == "webtest"]}


def put_columns(state, run_id: Any, body: Any) -> dict:
    """Replace the export columns (and verdict labels) of a run; refused while a job works on it."""
    folder = run_folder(state, run_id)
    bridge = getattr(state, "bridge", None)
    # The job queue stays locked through the write, so no job can be queued or claimed in between.
    with COLUMNS_LOCK, (bridge.cond if bridge is not None else contextlib.nullcontext()):
        if bridge is not None and any(j.get("run") == folder.name and j["state"] in ("queued", "offered", "running", "needs-input")
                                      for j in bridge.jobs.values()):
            raise ApiError(409, "run-busy", "a job is working on this run; change the columns when it ends")
        run = load_run(folder)
        try:
            run["columns"] = webtest_export.replace_plan(run, body, state.home)
            webtest.save(folder, run)
        except webtest.WebtestError as exc:
            raise ApiError(400, "bad-columns", str(exc)) from None
    return {"ok": True, "plan": run["columns"]}


def _pending(state, run_id: str) -> dict:
    answers = read_answers(state.home, run_id)
    done = set(answers["applied"])
    return {"answers": {k: v for k, v in answers["answers"].items() if k not in done},
            "results": {k: v for k, v in answers["results"].items() if k not in done},
            "finish": finished(state, run_id)}


def pending(state, run_id: Any, body: Any) -> dict:
    """Answers and results not applied yet. With ``wait``, held until one arrives or the tester finishes."""
    body = body if isinstance(body, dict) else {}
    bridge = state.bridge
    seconds = bridge._timeout(body.get("wait")) if body.get("wait") else 0.0
    folder = run_folder(state, run_id)
    run_id = folder.name
    with bridge.cond:
        job = bridge.run_job(body.get("job"), body.get("session"), run_id)
        if seconds:
            bridge.refuse_without_older_tab(job, bridge.run_cutoff(run_id))
        deadline = bridge.clock() + seconds
        while True:
            out = _pending(state, run_id)
            if out["answers"] or out["results"] or out["finish"] or bridge.closed:
                return out
            left = deadline - bridge.clock()
            if left <= 0:
                return out
            bridge.cond.wait(min(left, 1.0))
            job = bridge.jobs.get(body.get("job"))
            if job is None or job["state"] not in ("running", "needs-input"):
                return _pending(state, run_id)


def applied(state, run_id: Any, body: Any) -> dict:
    body = body if isinstance(body, dict) else {}
    ids = body.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) and len(i) <= 40 for i in ids):
        raise ApiError(400, "bad-request", "ids must be a list of question or result ids")
    folder = run_folder(state, run_id)
    with state.bridge.cond:
        state.bridge.run_job(body.get("job"), body.get("session"), folder.name)
        answers = read_answers(state.home, folder.name)
        known = set(answers["answers"]) | set(answers["results"])
        answers["applied"] = sorted(set(answers["applied"]) | (set(ids) & known))
        write_answers(state.home, folder.name, answers)
        state.bridge.run_changed()
        return {"ok": True, "applied": len(answers["applied"])}


# routes --------------------------------------------------------------------------------------------
def install(state) -> None:
    def held(fn):
        def run(req):
            state.hold(+1)
            try:
                return fn(req)
            finally:
                state.hold(-1)
        return run

    r = state.router
    r.add("GET", "/api/webtest/runs", "browser", lambda q: list_runs(state))
    r.add("GET", "/api/webtest/runs/:run", "browser", lambda q: run_view(state, q.params["run"], q.session))
    r.add("GET", "/api/webtest/runs/:run/evidence/:name", "browser",
          lambda q: _file(run_folder(state, q.params["run"]), "evidence", q.params["name"]))
    r.add("GET", "/api/webtest/runs/:run/captures/:name", "browser",
          lambda q: _file(run_folder(state, q.params["run"]), "source", q.params["name"]))
    r.add("POST", "/api/webtest/runs/:run/answers/:question", "browser",
          lambda q: answer_question(state, q.params["run"], q.params["question"], q.body, q.session))
    r.add("POST", "/api/webtest/runs/:run/rows/:row/result", "browser",
          lambda q: tester_result(state, q.params["run"], q.params["row"], q.body, q.session))
    r.add("PUT", "/api/webtest/runs/:run/images", "browser",
          lambda q: upload_image(state, q.params["run"], q.body, q.session), body="binary",
          max_body=webtest.IMAGE_CAP + 1)
    r.add("POST", "/api/webtest/runs/:run/finish", "browser", lambda q: finish(state, q.params["run"], q.session))
    r.add("GET", "/api/webtest/runs/:run/columns", "browser", lambda q: columns(state, q.params["run"]))
    r.add("PUT", "/api/webtest/runs/:run/columns", "browser", lambda q: put_columns(state, q.params["run"], q.body))
    r.add("POST", "/agent/webtest/runs/:run/pending", "agent", held(lambda q: pending(state, q.params["run"], q.body)))
    r.add("POST", "/agent/webtest/runs/:run/applied", "agent", lambda q: applied(state, q.params["run"], q.body))
