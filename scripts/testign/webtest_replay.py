"""Replay a run's queued rows from the suite's reviewed spec, headless, without a model
(``webtest-run`` job, ``mode: replay``), and check a spec against a run's environment.

Each row replays in a fresh browser context, signed in from its scenario's Login Recipe; every
scenario signs in once at the start of the replay. A row's outcome:

* every step passed: ``pass``, with a screenshot of the page;
* an ``expect_`` check failed: ``fail``, with the failing step and a screenshot (a defect draft follows);
* a locator found nothing or several elements: ``not-run: spec-error`` (record the row again, or run
  it in Chrome);
* the page opened on the sign-in page, or the sign-in failed: ``not-run: session-expired``;
* the page tried to leave the run's hosts: the navigation is aborted and the row fails.

Rows without a reviewed spec case (a changed case, a choice case, a phone-width case ...) stay
queued for a run in Chrome.
"""

from __future__ import annotations

from pathlib import Path

from . import config, webtest, webtest_live, webtest_record, webtest_spec, webtest_suite
from .login_recipe import RecipeError
from .webtest import WebtestError


def _suite(run: dict) -> tuple[Path, dict]:
    suite_id = (run.get("suite") or {}).get("id")
    if not suite_id:
        raise WebtestError("this run was not made from a suite; only a suite's runs are replayed")
    folder = webtest_suite.find_suite(webtest.runs_root(config.load()), suite_id)
    return folder, webtest_suite.load(folder)


def plan(folder: Path) -> dict:
    """Which queued rows a replay would run, and why the others would not."""
    run = webtest.load(folder)
    suite_folder, _suite_data = _suite(run)
    spec = webtest_spec.load(suite_folder)
    rows, left = [], []
    for case in run["cases"]:
        if case["state"] != "queued":
            continue
        body = webtest_spec.replayable(spec, case, webtest_spec.row_case_id(case["row"]))
        if body:
            rows.append({"row": case["row"], "scenario": body.get("scenario") or "none", "steps": len(body["steps"])})
        else:
            left.append({"row": case["row"], "why": _why_left(spec, case)})
    return {"run": run["id"], "spec": "reviewed" if webtest_spec.is_reviewed(spec) else ("draft" if spec else "missing"),
            "rows": rows, "left": left}


def _why_left(spec: dict | None, case: dict) -> str:
    if spec is None:
        return "the suite has no spec"
    if not webtest_spec.is_reviewed(spec):
        return "the spec is not reviewed"
    reason = webtest_spec.why_not_eligible(case)
    if reason:
        return reason
    body = spec["cases"].get(webtest_spec.row_case_id(case["row"]))
    if body is None:
        return "the case was not recorded"
    return "the case changed since it was recorded"


def replay(folder: Path, job: str | None, home: Path | None = None) -> dict:
    run = webtest.load(folder)
    suite_folder, _suite_data = _suite(run)
    spec = webtest_spec.load(suite_folder)
    todo = plan(folder)
    if not todo["rows"]:
        return {**todo, "results": []}
    results = []
    sessions: dict[str, dict | str] = {}
    for scenario in sorted({r["scenario"] for r in todo["rows"]}):
        try:
            sessions[scenario] = webtest_live.session_for(home, run["project"], scenario, run["hosts"], fresh=True)
        except webtest_live.EngineUnavailable:
            raise
        except RecipeError as exc:
            sessions[scenario] = str(exc)
    with webtest_live.playwright() as p:
        browser = webtest_live.launch(p)
        try:
            for item in todo["rows"]:
                row = item["row"]
                session = sessions[item["scenario"]]
                if isinstance(session, str):
                    results.append(webtest.replay_not_run(folder, row, "session-expired", session))
                    continue
                case = webtest.case_of(webtest.load(folder), row)
                if case["state"] != "queued":
                    results.append({"row": row, "state": "skipped", "note": "the row is no longer queued"})
                    continue
                body = spec["cases"][webtest_spec.row_case_id(row)]
                shot = folder / "evidence" / f".replay-{row}.png"
                outcome = webtest_live.run_case(
                    browser, base_url=run["base_url"], hosts=run["hosts"], steps=body["steps"],
                    expected=case.get("expected") or "", storage=session["storage"], login_url=session["login_url"],
                    secrets=session["secrets"], screenshot=shot)
                results.append(webtest_record._write_result(folder, row, outcome, job, "replay", shot))
        finally:
            browser.close()
    return {**todo, "results": results}


def check(folder: Path, home: Path | None = None) -> dict:
    """Replay every case of the suite's spec on this run's environment and keep the outcome as the
    spec's check (needed before the tester can review it). Writes nothing into the run."""
    run = webtest.load(folder)
    suite_folder, suite = _suite(run)
    spec = webtest_spec.load(suite_folder)
    if spec is None:
        raise WebtestError("the suite has no spec yet")
    spec_hash = webtest_spec.content_hash(spec)
    by_id = {c["case"]: c for c in suite["cases"]}
    results: dict[str, dict] = {}
    sessions: dict[str, dict | str] = {}
    with webtest_live.playwright() as p:
        browser = webtest_live.launch(p)
        try:
            for case_id, body in spec["cases"].items():
                scenario = body.get("scenario") or "none"
                if scenario not in sessions:
                    try:
                        sessions[scenario] = webtest_live.session_for(home, run["project"], scenario, run["hosts"],
                                                                      fresh=True)
                    except RecipeError as exc:
                        sessions[scenario] = str(exc)
                session = sessions[scenario]
                if isinstance(session, str):
                    results[case_id] = {"result": webtest_live.SESSION_EXPIRED, "step": None, "error": session[:300]}
                    continue
                expected = (by_id.get(case_id) or {}).get("expected") or ""
                out = webtest_live.run_case(browser, base_url=run["base_url"], hosts=run["hosts"], steps=body["steps"],
                                            expected=expected, storage=session["storage"],
                                            login_url=session["login_url"], secrets=session["secrets"])
                results[case_id] = {k: out.get(k) for k in ("result", "step", "error")}
        finally:
            browser.close()
    webtest_spec.store_check(suite_folder, results, f"spec check on {run['id']}", spec_hash)
    return webtest_spec.view(suite_folder, suite)
