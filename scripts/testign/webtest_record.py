"""The first run of a suite: the agent walks each eligible row in a Playwright browser, one step at a
time, and only steps that passed there go into the suite's spec (``webtest-run`` job, ``mode: record``).

The engine holds the browser and the sign-in (the scenario's Login Recipe), so the agent never sees a
password or a cookie. Each ``step`` replays the row's recorded steps in a fresh signed-in context and
then tries the new one, so the steps that end up in the spec replay the way a later run replays them.

A submit is not sent twice while recording: the first time a step passes, the app's replies to the
data-changing requests it sent (POST, PUT, PATCH, DELETE) are kept, and later replays of that step get
the kept reply instead of reaching the app. Eligible rows are ``sure`` and change no data, so this is a
second safety net. Kept replies may hold the app's data: they live in the tester's private store
(``~/.testign-kit/webtest/runs/<run>/record-replies.json``, 0600) and are dropped when the record ends.

Outcomes of a step: ``ok`` (recorded), ``spec_error`` (the locator found nothing or several elements:
try another), ``failed`` (an action on a found element failed: nothing recorded), ``fail`` (an
``expect_`` check failed: recorded, the row closes as fail). Expected results come from the suite;
the agent cannot change them.

``finish`` saves the closed rows into the spec (with the first-run outcome as its check) and writes
each recorded row's result into the run, with a screenshot: pass, fail, or a given-up row left queued
for a run in Chrome.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import config, fsutil, login_scenarios, webtest, webtest_live, webtest_spec, webtest_suite
from .webtest import WebtestError

FILE = "spec.record.json"
REPLIES = "record-replies.json"
OPEN, OK, FAIL, GAVE_UP = "recording", "ok", "fail", "gave-up"
MAX_LOG = 100


def _path(folder: Path) -> Path:
    return folder / FILE


def load(folder: Path) -> dict | None:
    try:
        data = json.loads(_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("rows"), dict) else None


def _save(folder: Path, rec: dict) -> None:
    fsutil.atomic_write_bytes(_path(folder), (json.dumps(rec, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _need(folder: Path) -> dict:
    rec = load(folder)
    if rec is None:
        raise WebtestError("no record of this run has started; run webtest-record-start first")
    return rec


def _replies_path(home: Path | None, run_id: str, create: bool = False) -> Path | None:
    root = login_scenarios.store_dir(home) / "runs"
    folder = login_scenarios._child(root, run_id) if root.is_dir() else None
    if folder is None:
        if not create:
            return None
        fsutil.owner_only_dirs(root, root / run_id)
        folder = root / run_id
    return folder / REPLIES


def _replies(home: Path | None, run_id: str, row: str) -> list:
    p = _replies_path(home, run_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p is not None and p.is_file() else {}
    except (OSError, ValueError):
        data = {}
    return list((data or {}).get(row) or [])


def _set_replies(home: Path | None, run_id: str, row: str, replies: list | None) -> None:
    p = _replies_path(home, run_id, create=bool(replies))
    if p is None:
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        data = {}
    if replies:
        data[row] = replies
    else:
        data.pop(row, None)
    if data:
        fsutil.atomic_write_bytes(p, json.dumps(data).encode("utf-8"), mode=0o600)
    else:
        p.unlink(missing_ok=True)


def _sent_brief(replies: list) -> list:
    """What the agent and the log see of kept replies: no bodies, no headers."""
    from urllib.parse import urlsplit  # noqa: PLC0415
    return [{"step": r["step"], "method": r["method"], "path": urlsplit(r["url"]).path or "/", "status": r["status"]}
            for r in replies]


def _log(row: dict, text: str) -> None:
    row.setdefault("log", []).append({"at": webtest.now_iso(), "text": text[:300]})
    row["log"] = row["log"][-MAX_LOG:]


def _suite_folder(run: dict) -> Path:
    suite_id = (run.get("suite") or {}).get("id")
    if not suite_id:
        raise WebtestError("this run was not made from a suite; only a suite's runs are recorded")
    return webtest_suite.find_suite(webtest.runs_root(config.load()), suite_id)


def eligible_rows(run: dict) -> list[dict]:
    return [c for c in run["cases"] if c["state"] == "queued" and not webtest_spec.why_not_eligible(c)]


def start(folder: Path, home: Path | None = None) -> dict:
    """Begin (or resume) the record: sign in once per scenario (so a broken recipe fails here), list
    the rows to walk."""
    run = webtest.load(folder)
    suite_folder = _suite_folder(run)
    rows = eligible_rows(run)
    if not rows:
        raise WebtestError("no queued row of this run can be recorded (sure, agent, pc, label/element/behaviour)")
    for scenario in sorted({c.get("scenario") or "none" for c in rows}):
        webtest_live.session_for(home, run["project"], scenario, run["hosts"], fresh=True)
    rec = load(folder)
    if rec is None or rec.get("base_url") != run["base_url"]:
        _set_replies_all_dropped(home, run["id"])
        rec = {"run": run["id"], "suite": suite_folder.name, "base_url": run["base_url"], "started": webtest.now_iso(),
               "rows": {}}
    for case in rows:
        rec["rows"].setdefault(case["row"], {"row": case["row"], "case": webtest_spec.row_case_id(case["row"]),
                                             "status": OPEN, "steps": [], "result": None, "attempts": 0,
                                             "restarts": 0, "log": []})
    _save(folder, rec)
    return {"run": run["id"], "suite": rec["suite"], "base_url": rec["base_url"],
            "rows": [_brief(r) for r in rec["rows"].values()]}


def _set_replies_all_dropped(home: Path | None, run_id: str) -> None:
    p = _replies_path(home, run_id)
    if p is not None:
        p.unlink(missing_ok=True)


def _brief(row: dict) -> dict:
    return {"row": row["row"], "case": row["case"], "status": row["status"], "steps": len(row["steps"])}


def _row(rec: dict, row: str) -> dict:
    found = rec["rows"].get(row)
    if found is None:
        raise WebtestError(f"{row} is not a row of this record")
    return found


def _context(run: dict, row: str, home: Path | None) -> tuple[dict, dict]:
    case = webtest.case_of(run, row)
    session = webtest_live.session_for(home, run["project"], case.get("scenario"), run["hosts"], fresh=False)
    return case, session


def _replay(run: dict, row: str, steps: list, home: Path | None, *, trying: int | None = None,
            snapshot: bool = True, screenshot: Path | None = None) -> dict:
    case, session = _context(run, row, home)
    with webtest_live.playwright() as p:
        browser = webtest_live.launch(p)
        try:
            return webtest_live.run_case(
                browser, base_url=run["base_url"], hosts=run["hosts"], steps=steps, expected=case.get("expected") or "",
                storage=session["storage"], login_url=session["login_url"], snapshot=snapshot,
                secrets=session["secrets"], answers=_replies(home, run["id"], row), capture_from=trying,
                screenshot=screenshot)
        finally:
            browser.close()


def _detail(run: dict, row: dict, outcome: dict | None = None) -> dict:
    case = webtest.case_of(run, row["row"])
    out = {"row": row["row"], "case": row["case"], "status": row["status"], "steps": row["steps"],
           "content": case.get("content") or "", "screen": (case.get("screen") or {}).get("url"),
           "preconditions": case.get("preconditions") or "", "case_steps": case.get("steps") or "",
           "expected": case.get("expected") or "", "scenario": case.get("scenario") or "none",
           "warnings": webtest_live.assertion_warnings(row["steps"], case.get("expected") or "")}
    if row.get("sent"):
        out["sent"] = row["sent"]
    if outcome:
        out.update({k: outcome[k] for k in ("url", "snapshot") if k in outcome})
        if outcome.get("resent"):
            out["resent"] = [{**r, "note": "no kept reply: this request reached the app again"} for r in outcome["resent"]]
    return out


def open_row(folder: Path, row: str, restart: bool = False, home: Path | None = None) -> dict:
    """The row, its recorded steps replayed, and a snapshot of where they leave the page."""
    rec = _need(folder)
    run = webtest.load(folder)
    entry = _row(rec, row)
    if restart:
        _log(entry, f"restarted (was {entry['status']} with {len(entry['steps'])} steps)")
        entry.update({"status": OPEN, "steps": [], "result": None, "restarts": entry["restarts"] + 1, "sent": []})
        _set_replies(home, run["id"], row, None)
    rec["current"] = {"row": row, "at": time.time()}
    _save(folder, rec)
    screen = (webtest.case_of(run, row).get("screen") or {}).get("url") or run["base_url"]
    first = [{"action": "goto", "value": _path_of(screen, run["base_url"])}]
    outcome = _replay(run, row, entry["steps"] or first, home)
    detail = _detail(run, entry, outcome)
    if entry["steps"] and outcome["result"] != webtest_live.OK and entry["status"] == OPEN:
        detail["replay"] = {"result": outcome["result"], "error": outcome["error"]}
    if outcome["result"] == webtest_live.SESSION_EXPIRED:
        detail["replay"] = {"result": outcome["result"], "error": outcome["error"]}
    return detail


def _path_of(url: str, base_url: str) -> str:
    """A screen URL as the path a ``goto`` step takes."""
    from urllib.parse import urlsplit  # noqa: PLC0415
    parts = urlsplit(url)
    if not parts.scheme:
        return url or "/"
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def step(folder: Path, row: str, raw: Any, home: Path | None = None) -> dict:
    rec = _need(folder)
    run = webtest.load(folder)
    entry = _row(rec, row)
    if entry["status"] != OPEN:
        raise WebtestError(f"{row} is closed as {entry['status']}; open it with --restart to record it again")
    problems: list[str] = []
    new = webtest_spec.check_step(raw, f"{row} step {len(entry['steps']) + 1}", problems)
    if problems:
        raise WebtestError("; ".join(problems))
    if len(entry["steps"]) >= webtest_spec.MAX_STEPS:
        raise WebtestError(f"{row}: a row has at most {webtest_spec.MAX_STEPS} steps")
    n = len(entry["steps"]) + 1
    outcome = _replay(run, row, entry["steps"] + [new], home, trying=n)
    sent = outcome.get("sent") or []
    if outcome["result"] != webtest_live.OK and outcome["step"] is not None and outcome["step"] < n:
        result, error = "replay_failed", f"the recorded steps no longer replay: {outcome['error']}; open the row with --restart"
    elif outcome["result"] == webtest_live.OK:
        result, error = "ok", None
    elif outcome["result"] in (webtest_live.SPEC_ERROR, webtest_live.OFF_SITE, webtest_live.SESSION_EXPIRED):
        result, error = outcome["result"], outcome["error"]
    elif new["action"].startswith("expect_"):
        result, error = "fail", outcome["error"]
    else:
        result, error = "failed", outcome["error"]
    rec = _need(folder)
    entry = _row(rec, row)
    entry["attempts"] += 1
    if result in ("ok", "fail"):
        entry["steps"].append(new)
        if sent:
            _set_replies(home, run["id"], row, _replies(home, run["id"], row) + sent)
            entry["sent"] = (entry.get("sent") or []) + _sent_brief(sent)
    if result == "fail":
        entry["status"] = FAIL
        entry["result"] = {"result": "fail", "step": n, "error": error}
    _log(entry, f"step {n} {webtest_live.describe(new)}: {result}{' - ' + error if error else ''}")
    rec["current"] = {"row": row, "at": time.time()}
    _save(folder, rec)
    detail = _detail(run, entry, outcome)
    detail.update({"result": result, "error": error})
    if sent:
        detail["this_step_sent"] = _sent_brief(sent)
        if result not in ("ok", "fail"):
            detail["this_step_sent_note"] = "the app received this although the step was not recorded"
    return detail


def done(folder: Path, row: str) -> dict:
    rec = _need(folder)
    entry = _row(rec, row)
    if entry["status"] != OPEN:
        raise WebtestError(f"{row} is already closed as {entry['status']}")
    if not any(s["action"].startswith("expect_") for s in entry["steps"]):
        raise WebtestError(f"{row}: record at least one expect_ check of the expected result first")
    entry["status"] = OK
    entry["result"] = {"result": "ok", "step": None, "error": None}
    _log(entry, "done")
    _save(folder, rec)
    return _detail(webtest.load(folder), entry)


def give_up(folder: Path, row: str, reason: str) -> dict:
    """No working locator was found: the row stays out of the spec and stays queued for Chrome."""
    reason = (reason or "").strip()
    if not reason:
        raise WebtestError("say why the row cannot be recorded")
    rec = _need(folder)
    entry = _row(rec, row)
    if entry["status"] != OPEN:
        raise WebtestError(f"{row} is already closed as {entry['status']}")
    entry["status"] = GAVE_UP
    entry["result"] = {"result": "spec_error", "step": None, "error": reason[:300]}
    _log(entry, f"gave up: {reason}")
    _save(folder, rec)
    return _detail(webtest.load(folder), entry)


def finish(folder: Path, job: str | None, home: Path | None = None) -> dict:
    """Save the recorded rows into the suite's spec and their results into the run."""
    rec = _need(folder)
    still = [k for k, r in rec["rows"].items() if r["status"] == OPEN]
    if still:
        raise WebtestError(f"{len(still)} rows are still open: {', '.join(still[:10])}; close each with done or give-up")
    run = webtest.load(folder)
    suite_folder = _suite_folder(run)
    suite = webtest_suite.load(suite_folder)
    recorded = {r["case"]: r for r in rec["rows"].values() if r["status"] in (OK, FAIL)}
    if recorded:
        check = {k: {"result": r["result"]["result"], "step": r["result"]["step"], "error": r["result"]["error"]}
                 for k, r in recorded.items()}
        webtest_spec.save(suite_folder, suite, {k: {"steps": r["steps"]} for k, r in recorded.items()},
                          by="first run", check=check)
    results = []
    for entry in rec["rows"].values():
        if entry["status"] not in (OK, FAIL):
            results.append({"row": entry["row"], "state": "queued", "note": "left for a run in Chrome"})
            continue
        if webtest.case_of(webtest.load(folder), entry["row"])["state"] != "queued":
            results.append({"row": entry["row"], "state": "skipped", "note": "the row is no longer queued"})
            continue
        shot = folder / "evidence" / f".record-{entry['row']}.png"
        outcome = _replay(run, entry["row"], entry["steps"], home, snapshot=False, screenshot=shot)
        results.append(_write_result(folder, entry["row"], outcome, job, "record", shot))
    _set_replies_all_dropped(home, run["id"])
    _path(folder).unlink(missing_ok=True)
    return {"run": run["id"], "suite": suite_folder.name, "spec": webtest_spec.view(suite_folder, suite)["status"],
            "rows": results}


def _write_result(folder: Path, row: str, outcome: dict, job: str | None, by: str, shot: Path) -> dict:
    """The replay outcome as the row's result: pass, fail, or not run with the reason."""
    try:
        data = shot.read_bytes() if outcome.get("screenshot") else None
    except OSError:
        data = None
    finally:
        shot.unlink(missing_ok=True)
    result = outcome["result"]
    if result == webtest_live.OK:
        return webtest.replay_result(folder, row, job=job, verdict="pass", actual="", url=outcome.get("url") or "",
                                     screenshot=data, by=by)
    if result == webtest_live.FAIL:
        return webtest.replay_result(folder, row, job=job, verdict="fail", actual=outcome.get("error") or "",
                                     url=outcome.get("url") or "", screenshot=data, by=by)
    if result == webtest_live.SESSION_EXPIRED:
        return webtest.replay_not_run(folder, row, "session-expired", outcome.get("error") or "")
    if result == webtest_live.OFF_SITE:
        return webtest.replay_result(folder, row, job=job, verdict="fail", actual=outcome.get("error") or "",
                                     url=outcome.get("url") or "", screenshot=data, by=by)
    return webtest.replay_not_run(folder, row, "spec-error", outcome.get("error") or "")


def progress(folder: Path) -> dict | None:
    rec = load(folder)
    if rec is None:
        return None
    rows = list(rec["rows"].values())
    count = lambda status: sum(1 for r in rows if r.get("status") == status)  # noqa: E731
    current = rec["rows"].get((rec.get("current") or {}).get("row"))
    return {"total": len(rows), "closed": len(rows) - count(OPEN), "ok": count(OK), "fail": count(FAIL),
            "gave_up": count(GAVE_UP),
            "current": {"row": current["row"], "steps": len(current["steps"])} if current and current["status"] == OPEN else None}
