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

from . import config, webtest, webtest_live, webtest_spec, webtest_suite
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


RETRY = (webtest_live.FAIL, webtest_live.SPEC_ERROR)


def replay(folder: Path, job: str | None, home: Path | None = None) -> dict:
    """Replay the queued rows that have a reviewed spec case, in every browser of the run.

    ``job`` is the console job of ``mode: replay``, or None for a replay with nobody at the console
    (a scheduler): then no row may be running, so it never races a job on the same run. A row that
    fails or cannot run is tried once more in that browser; passing the second time marks it flaky.
    """
    run = webtest.load(folder)
    if job is None:
        running = [c["row"] for c in run["cases"] if c["state"] == "running"]
        if running:
            raise WebtestError(f"{running[0]} is running in a console job; replay this run when that job ends")
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
    names = webtest.run_browsers(run)
    with webtest_live.playwright() as p:
        launched: dict[str, object] = {}
        try:
            for name in names:
                try:
                    launched[name] = webtest_live.launch(p, browser=name)
                except webtest_live.EngineUnavailable as exc:
                    launched[name] = str(exc)
            if all(_is_missing(b) for b in launched.values()):
                raise webtest_live.EngineUnavailable("; ".join(launched.values()))
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
                results.append(_replay_row(folder, run, row, case, body, session, launched, job))
        finally:
            for b in launched.values():
                if not _is_missing(b):
                    b.close()
    return {**todo, "browsers": names, "results": results}


def _replay_row(folder: Path, run: dict, row: str, case: dict, body: dict, session: dict, launched: dict,
                job: str | None) -> dict:
    per: dict[str, dict] = {}
    shots: list[tuple[str, bytes]] = []
    outcomes: dict[str, dict] = {}
    for name, browser in launched.items():
        if _is_missing(browser):
            per[name] = {"verdict": "pending", "error": browser[:300]}
            continue
        shot = folder / "evidence" / f".replay-{row}-{name}.png"
        flaky = False
        out = _run(browser, run, case, body, session, shot)
        if out["result"] in RETRY:
            again = _run(browser, run, case, body, session, shot)
            flaky = again["result"] == webtest_live.OK
            out = again
        outcomes[name] = out
        per[name] = {"verdict": VERDICT[out["result"]], "error": out.get("error"), **({"flaky": True} if flaky else {})}
        try:
            if out.get("screenshot"):
                shots.append((name, shot.read_bytes()))
        except OSError:
            pass
        finally:
            shot.unlink(missing_ok=True)
    found = {o["result"] for o in outcomes.values()}
    errors = "\n".join(f"{n}: {o['error']}" for n, o in outcomes.items() if o.get("error"))
    single = len(launched) == 1
    note = errors if not single else next(iter(outcomes.values())).get("error") or ""
    url = next((o.get("url") for o in outcomes.values() if o.get("url")), "")
    browsers = None if single else per
    if webtest_live.SESSION_EXPIRED in found:
        return webtest.replay_not_run(folder, row, "session-expired", note, browsers)
    if found & {webtest_live.FAIL, webtest_live.OFF_SITE}:
        return webtest.replay_result(folder, row, job=job, verdict="fail", actual=note, url=url or "",
                                     screenshot=None, screenshots=shots, by="replay", browsers=browsers)
    if webtest_live.SPEC_ERROR in found:
        return webtest.replay_not_run(folder, row, "spec-error", note, browsers)
    return webtest.replay_result(folder, row, job=job, verdict="pass", actual="", url=url or "",
                                 screenshot=None, screenshots=shots, by="replay", browsers=browsers,
                                 flaky=any(v.get("flaky") for v in per.values()))


def _is_missing(browser) -> bool:
    """A browser that could not start is kept as its error message."""
    return isinstance(browser, str)


VERDICT = {webtest_live.OK: "pass", webtest_live.FAIL: "fail", webtest_live.SPEC_ERROR: "spec-error",
           webtest_live.SESSION_EXPIRED: "session-expired", webtest_live.OFF_SITE: "off-site"}


def _run(browser, run: dict, case: dict, body: dict, session: dict, shot: Path) -> dict:
    return webtest_live.run_case(
        browser, base_url=run["base_url"], hosts=run["hosts"], steps=body["steps"],
        expected=case.get("expected") or "", storage=session["storage"], login_url=session["login_url"],
        secrets=session["secrets"], screenshot=shot)


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
