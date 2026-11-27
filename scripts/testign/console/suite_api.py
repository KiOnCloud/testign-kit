"""Web test suites in the console: list, create from a source, edit cases, confirm, export, runs.

Suites live in ``<output_dir>/webtest/suites/<suite-id>/`` (``webtest_suite``). The tester edits
them here; the agent writes the cases of a ``generating`` suite through the agent routes, only from
the claimed ``suite-generate`` job of that suite. Every suite change made through this server runs
under ``LOCK``, so a tester edit and an agent write never interleave; the command line writes the
suite file directly (``webtest-table`` from the claimed job, the ``suite-*`` commands). Suite ids from a request are matched against a
pattern and resolved by listing.
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .. import config, coverage_rules, templates, webtest, webtest_history, webtest_sources, webtest_spec, webtest_suite
from . import templates_api
from .server import ApiError, Response

LOCK = threading.Lock()
# A suite created from the chat waits this long for its generate job before the tester may edit it.
UNCLAIMED_GENERATE = 600.0
UI_LANGS = ("en", "ja")


def _cfg(state) -> dict:
    from . import readapi  # noqa: PLC0415 - readapi imports the server module too

    return readapi.load_config(state)


def runs_root(state) -> Path:
    return webtest.runs_root(_cfg(state))


def env(state) -> webtest_sources.Env:
    return webtest_sources.Env.from_config(_cfg(state), state.home)


def suite_folder(state, suite_id: Any) -> Path:
    try:
        return webtest_suite.find_suite(runs_root(state), suite_id)
    except webtest.WebtestError:
        raise ApiError(404, "not-found", "no such suite") from None


def _error(exc: Exception) -> ApiError:
    """A store error as the console's error; a broken case rule carries every field's message."""
    if isinstance(exc, webtest_suite.CoverageError):
        return ApiError(409, "coverage-missing", str(exc), {"missing": exc.missing, "problems": exc.problems})
    if isinstance(exc, webtest_suite.CaseError):
        return ApiError(400, "case-rules", str(exc), {"errors": exc.errors, "case": exc.case,
                                                      "problems": getattr(exc, "problems", None)})
    if isinstance(exc, webtest_sources.SourceError):
        return ApiError(400, exc.code, str(exc))
    if isinstance(exc, webtest.TargetError):
        return ApiError(400, exc.code, str(exc))
    return ApiError(409, "conflict", str(exc))


def _do(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (webtest.WebtestError, webtest_sources.SourceError) as exc:
        raise _error(exc) from None


# reconcile ------------------------------------------------------------------------------------
def _reconcile(state, folder: Path, suite: dict) -> dict:
    """A ``generating`` suite whose job ended (or never came) goes to review with what was staged."""
    if suite["state"] != "generating":
        return suite
    bridge = getattr(state, "bridge", None)
    if bridge is None:
        return suite
    if suite.get("generate_job"):
        if bridge.suite_job_active(suite["id"]):
            return suite
    else:
        try:
            age = time.time() - (folder / "suite.json").stat().st_ctime
        except OSError:
            age = 0
        if bridge.suite_job_active(suite["id"]) or age < UNCLAIMED_GENERATE:
            return suite
    with LOCK:
        webtest_suite.stop_generating(folder)
        return webtest_suite.load(folder)


def _load(state, folder: Path) -> dict:
    try:
        suite = webtest_suite.load(folder)
    except webtest.WebtestError:
        raise ApiError(409, "suite-unreadable", "suite.json cannot be read") from None
    return _reconcile(state, folder, suite)


def _generate_view(state, suite: dict) -> dict | None:
    bridge = getattr(state, "bridge", None)
    job_id = suite.get("generate_job")
    if bridge is None or not job_id:
        return None
    with bridge.cond:
        job = bridge.jobs.get(job_id)
        if job is None:
            return {"id": job_id, "state": "gone"}
        return {"id": job_id, "state": job["state"], "reason": job.get("reason"),
                "progress": (job.get("progress") or [])[-1:]}


# views ----------------------------------------------------------------------------------------
def list_suites(state) -> dict:
    root = runs_root(state)
    runs: dict[str, int] = {}
    for _rid, folder in webtest.list_runs(root).items():
        try:
            sid = (webtest.load(folder).get("suite") or {}).get("id")
        except webtest.WebtestError:
            continue
        if sid:
            runs[sid] = runs.get(sid, 0) + 1
    out = []
    for sid, folder in sorted(webtest_suite.list_suites(root).items(), reverse=True):
        try:
            suite = _load(state, folder)
        except ApiError:
            out.append({"id": sid, "readable": False})
            continue
        out.append({**webtest_suite.summary(suite), "readable": True, "runs": runs.get(sid, 0)})
    return {"suites": out}


def suite_view(state, suite_id: Any) -> dict:
    folder = suite_folder(state, suite_id)
    suite = _load(state, folder)
    return {**webtest_suite.summary(suite), "cases": suite["cases"], "suite_digest": suite.get("suite_digest"),
            "coverage": webtest_suite.coverage(suite, env(state), folder),
            "runs": webtest_suite.runs_of(runs_root(state), suite["id"]),
            "results": webtest_history.suite_results(runs_root(state), suite["id"], suite["cases"]),
            "spec": webtest_spec.view(folder, suite),
            "checks": coverage_rules.view(suite),
            "generate": _generate_view(state, suite)}


def review_spec(state, suite_id: Any, body: Any, session: str | None) -> dict:
    """The tester marks the spec they looked at reviewed (its hash); later edits clear it."""
    from .jobs import fingerprint  # noqa: PLC0415

    folder = suite_folder(state, suite_id)
    suite = _load(state, folder)
    spec_hash = body.get("hash") if isinstance(body, dict) else None
    try:
        webtest_spec.review(folder, spec_hash, fingerprint(session))
    except webtest_spec.SpecError as exc:
        raise ApiError(409, "spec-not-ready", str(exc)) from None
    return webtest_spec.view(folder, suite)


def remove_spec_cases(state, suite_id: Any, body: Any) -> dict:
    folder = suite_folder(state, suite_id)
    suite = _load(state, folder)
    try:
        webtest_spec.remove_cases(folder, body.get("cases") if isinstance(body, dict) else None)
    except webtest_spec.SpecError as exc:
        raise ApiError(400, "bad-request", str(exc)) from None
    return webtest_spec.view(folder, suite)


def sources(_state) -> dict:
    return {"sources": webtest_sources.listing()}


# create ---------------------------------------------------------------------------------------
def upload(state, filename_header: str | None, data: Any) -> dict:
    """An Excel file for a new suite, kept like a template upload: checked, owner-only, one hour."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ApiError(400, "bad-request", "send the workbook as the request body")
    name = templates_api.decode_filename(filename_header)
    templates_api.check_zip(bytes(data))
    import secrets  # noqa: PLC0415

    upload_id = secrets.token_hex(8)
    folder = templates_api.uploads_dir(state.home) / upload_id
    folder.mkdir(mode=0o700, parents=True)
    from . import lifecycle  # noqa: PLC0415

    lifecycle.write_secure(folder / name, bytes(data))
    return {"upload": upload_id, "name": name, "size": len(data)}


def create(state, body: Any) -> dict:
    if not isinstance(body, dict):
        raise ApiError(400, "bad-request", "the suite must be an object")
    kind = body.get("kind")
    try:
        entry = webtest_sources.get(kind)
    except webtest_sources.SourceError as exc:
        raise _error(exc) from None
    ui_lang = body.get("ui_lang") or "en"
    if ui_lang not in UI_LANGS:
        raise ApiError(400, "bad-request", "ui_lang must be en or ja")
    payload = {k: body[k] for k in ("figma_url", "ticket", "revision", "template", "sheet", "note") if k in body}
    upload_path = None
    upload_folder = None
    if entry.extract is not None:
        upload_path = templates_api._upload_file(state.home, body.get("upload"))
        upload_folder = upload_path.parent
        payload["file_name"] = upload_path.name
    root = runs_root(state)
    with LOCK:
        made = _do(webtest_suite.new_suite, root, name=body.get("name"), kind=kind, payload=payload,
                   env=env(state), project=body.get("project"), case_lang=body.get("case_lang"),
                   upload=upload_path, depth=body.get("depth"))
    if upload_folder is not None:
        shutil.rmtree(upload_folder, ignore_errors=True)
    job = None
    if entry.needs_agent:
        try:
            job = state.bridge.create({"kind": "suite-generate", "suite": made["id"], "ui_lang": ui_lang})
        except BaseException:
            folder = webtest_suite.list_suites(root).get(made["id"])
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
            raise
    return {"suite": made["id"], "state": made["state"], "cases": len(made["cases"]), "job": job}


# tester edits ---------------------------------------------------------------------------------
def _edit(state, suite_id: Any, fn, *args) -> Any:
    folder = suite_folder(state, suite_id)
    _load(state, folder)
    with LOCK:
        return _do(fn, folder, *args)


def patch(state, suite_id: Any, body: Any) -> dict:
    body = body if isinstance(body, dict) else {}
    project = body["project"] if "project" in body else ...
    return _edit(state, suite_id, webtest_suite.rename, body.get("name"), project)


def duplicate(state, suite_id: Any, body: Any) -> dict:
    folder = suite_folder(state, suite_id)
    _load(state, folder)
    with LOCK:
        return _do(webtest_suite.duplicate, runs_root(state), folder, (body or {}).get("name") if isinstance(body, dict)
                   else None)


def delete(state, suite_id: Any) -> dict:
    folder = suite_folder(state, suite_id)
    suite = _load(state, folder)
    if suite["state"] == "generating":
        raise ApiError(409, "suite-generating", "the agent is still writing the cases of this suite")
    open_runs = [r["id"] for r in webtest_suite.runs_of(runs_root(state), suite["id"]) if r["open"]]
    with LOCK:
        return _do(webtest_suite.remove, folder, open_runs)


def add_case(state, suite_id: Any, body: Any) -> dict:
    return _edit(state, suite_id, webtest_suite.add_case, body if isinstance(body, dict) else None)


def update_case(state, suite_id: Any, case_id: Any, body: Any) -> dict:
    return _edit(state, suite_id, webtest_suite.update_case, case_id, body)


def bulk(state, suite_id: Any, body: Any) -> dict:
    body = body if isinstance(body, dict) else {}
    ids = body.get("cases")
    if body.get("delete"):
        return _edit(state, suite_id, webtest_suite.delete_cases, ids)
    return _edit(state, suite_id, webtest_suite.bulk_update, ids, body.get("fields"))


def confirm(state, suite_id: Any, body: Any, session: str | None) -> dict:
    """Review → ready; ``by`` is the tester name the tab has in Preferences, else the tab's fingerprint."""
    from .jobs import fingerprint  # noqa: PLC0415

    by = body.get("by") if isinstance(body, dict) and isinstance(body.get("by"), str) else None
    return _edit(state, suite_id, webtest_suite.confirm, (by or "").strip()[:100] or fingerprint(session))


def set_depth(state, suite_id: Any, body: Any) -> dict:
    """Change the test depth. With ``extend`` and checks still missing, the suite goes back to
    ``generating`` and a generate job adds the cases the new depth needs (Figma and Backlog suites)."""
    body = body if isinstance(body, dict) else {}
    folder = suite_folder(state, suite_id)
    suite = _load(state, folder)
    with LOCK:
        out = _do(webtest_suite.set_depth, folder, body.get("depth"))
        suite = webtest_suite.load(folder)
        missing = bool(coverage_rules.missing(suite))
        entry = webtest_sources.get(suite["source"]["kind"])
        can_extend = missing and entry.needs_agent
        job = None
        if body.get("extend") and can_extend:
            _do(webtest_suite.start_extend, folder)
    if body.get("extend") and can_extend:
        ui_lang = body.get("ui_lang") if body.get("ui_lang") in UI_LANGS else "en"
        try:
            job = state.bridge.create({"kind": "suite-generate", "suite": suite["id"], "ui_lang": ui_lang,
                                       "extend": True})
        except BaseException:
            with LOCK:
                webtest_suite.stop_generating(folder)
            raise
    return {**out, "missing": missing, "can_extend": can_extend, "job": job,
            "checks": coverage_rules.view(webtest_suite.load(folder))}


def set_skip(state, suite_id: Any, body: Any, session: str | None) -> dict:
    """Leave one required check out with a reason, or take the skip back (empty reason)."""
    from .jobs import fingerprint  # noqa: PLC0415

    body = body if isinstance(body, dict) else {}
    by = body.get("by") if isinstance(body.get("by"), str) and body["by"].strip() else fingerprint(session)
    return _edit(state, suite_id, webtest_suite.set_skip, body.get("rule"), body.get("about"), body.get("reason"),
                 str(by)[:100])


def capture(state, suite_id: Any, name: Any) -> Response:
    folder = suite_folder(state, suite_id)
    try:
        path = webtest_suite.capture_path(folder, name)
        data = path.read_bytes()
    except (webtest.WebtestError, OSError):
        raise ApiError(404, "not-found", "no such capture") from None
    ctype = "image/png" if path.suffix == ".png" else "image/jpeg"
    return Response(200, raw=data, content_type=ctype, headers={"Cache-Control": "no-cache"})


def export(state, suite_id: Any, body: Any) -> dict:
    folder = suite_folder(state, suite_id)
    suite = _load(state, folder)
    name = (body or {}).get("template") if isinstance(body, dict) else None
    try:
        entry = templates.resolve(name, state.home)
    except templates.TemplateError as exc:
        raise ApiError(400, "unknown-template", str(exc)) from None
    with LOCK:
        out = _do(webtest_suite.export_workbook, folder, suite, entry)
    return {"name": out["name"], "folder": str(folder), "rows": out["rows"]}


# runs -----------------------------------------------------------------------------------------
def create_run(state, body: Any, session: str | None) -> dict:
    body = body if isinstance(body, dict) else {}
    cfg = _cfg(state)
    tester = body.get("tester")
    with LOCK:
        made = _do(webtest_suite.create_run, runs_root(state), body.get("suite"), name=body.get("name"),
                   base_url=body.get("base_url"), project=body.get("project"), template=body.get("template"),
                   tester=tester, home=state.home, report_lang=cfg.get("lang"), browsers=body.get("browsers"))
    made.pop("folder", None)
    return made


# agent writes ---------------------------------------------------------------------------------
def _agent_folder(state, suite_id: Any, body: dict) -> Path:
    folder = suite_folder(state, suite_id)
    with state.bridge.cond:
        state.bridge.suite_job(body.get("job"), body.get("session"), folder.name)
    return folder


def _changed(state) -> None:
    with state.bridge.cond:
        state.bridge.run_changed()


def agent_stage(state, suite_id: Any, body: Any) -> dict:
    body = body if isinstance(body, dict) else {}
    folder = _agent_folder(state, suite_id, body)
    with LOCK:
        out = _do(webtest_suite.stage_generated, folder, body.get("cases"), body.get("job"))
    _changed(state)
    return out


def agent_generated(state, suite_id: Any, body: Any) -> dict:
    body = body if isinstance(body, dict) else {}
    folder = _agent_folder(state, suite_id, body)
    with LOCK:
        out = _do(webtest_suite.finish_generate, folder, body.get("job"))
    _changed(state)
    return out


# routes ---------------------------------------------------------------------------------------
def install(state) -> None:
    r = state.router
    r.add("GET", "/api/webtest/sources", "browser", lambda q: sources(state))
    r.add("GET", "/api/webtest/suites", "browser", lambda q: list_suites(state))
    r.add("POST", "/api/webtest/suites", "browser", lambda q: create(state, q.body))
    r.add("POST", "/api/webtest/suites/uploads", "browser",
          lambda q: upload(state, q.headers.get("X-Filename"), q.body), body="binary",
          max_body=templates_api.UPLOAD_CAP)
    r.add("GET", "/api/webtest/suites/:suite", "browser", lambda q: suite_view(state, q.params["suite"]))
    r.add("PATCH", "/api/webtest/suites/:suite", "browser", lambda q: patch(state, q.params["suite"], q.body))
    r.add("POST", "/api/webtest/suites/:suite/duplicate", "browser",
          lambda q: duplicate(state, q.params["suite"], q.body))
    r.add("DELETE", "/api/webtest/suites/:suite", "browser", lambda q: delete(state, q.params["suite"]))
    r.add("POST", "/api/webtest/suites/:suite/cases", "browser", lambda q: add_case(state, q.params["suite"], q.body))
    r.add("POST", "/api/webtest/suites/:suite/cases/bulk", "browser", lambda q: bulk(state, q.params["suite"], q.body))
    r.add("PUT", "/api/webtest/suites/:suite/cases/:case", "browser",
          lambda q: update_case(state, q.params["suite"], q.params["case"], q.body))
    r.add("POST", "/api/webtest/suites/:suite/confirm", "browser",
          lambda q: confirm(state, q.params["suite"], q.body, q.session))
    r.add("POST", "/api/webtest/suites/:suite/depth", "browser", lambda q: set_depth(state, q.params["suite"], q.body))
    r.add("POST", "/api/webtest/suites/:suite/skips", "browser",
          lambda q: set_skip(state, q.params["suite"], q.body, q.session))
    r.add("GET", "/api/webtest/suites/:suite/captures/:name", "browser",
          lambda q: capture(state, q.params["suite"], q.params["name"]))
    r.add("POST", "/api/webtest/suites/:suite/export", "browser", lambda q: export(state, q.params["suite"], q.body))
    r.add("POST", "/api/webtest/suites/:suite/spec/review", "browser",
          lambda q: review_spec(state, q.params["suite"], q.body, q.session))
    r.add("POST", "/api/webtest/suites/:suite/spec/remove", "browser",
          lambda q: remove_spec_cases(state, q.params["suite"], q.body))
    r.add("POST", "/api/webtest/runs", "browser", lambda q: create_run(state, q.body, q.session))
    r.add("POST", "/agent/suites/:suite/stage", "agent", lambda q: agent_stage(state, q.params["suite"], q.body),
          max_body=4 * 1024 * 1024)
    r.add("POST", "/agent/suites/:suite/generated", "agent",
          lambda q: agent_generated(state, q.params["suite"], q.body))
