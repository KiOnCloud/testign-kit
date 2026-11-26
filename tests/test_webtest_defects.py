"""Defect drafts for failed rows: built from the row, edited, sent with a tracker key or not a defect."""

import os
import stat
import time

import pytest

openpyxl = pytest.importorskip("openpyxl")

from console_helpers import InProcessServer, call  # noqa: E402
from make_webtest_run import BASE_URL, FakeConsole, build  # noqa: E402

from testign import login_scenarios, webtest, webtest_defects, webtest_export  # noqa: E402
from testign.console import server as srv  # noqa: E402
from testign.webtest_defects import DefectError  # noqa: E402

from test_console_webtest_api import make_state  # noqa: E402


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    login_scenarios.save_project(home, "demo", ["dev.example.test"])
    return home


@pytest.fixture
def run_id(home):
    return build(home / "Downloads" / "webtest", FakeConsole())


@pytest.fixture
def folder(home, run_id):
    folder = webtest.find_run(home / "Downloads" / "webtest", run_id)
    run = webtest.load(folder)
    for case in run["cases"]:
        if case["row"] == "r01":
            case.update(state="fail", attempt=1, result={"verdict": "fail", "actual": "The link still reads 予約確認",
                                                         "url": BASE_URL + "/mypage", "evidence": ["evidence/r01-a1-1.png"],
                                                         "by": "agent"})
        if case["row"] == "r02":
            case.update(state="pass", attempt=1, result={"verdict": "pass", "actual": "", "url": BASE_URL, "evidence": [],
                                                         "by": "agent"})
    webtest.save(folder, run)
    return folder


@pytest.fixture
def console(home, folder):
    server = InProcessServer(make_state(home))
    token = server.session()
    created = server.state.session_created(token)
    while time.time() <= created:
        time.sleep(0.001)
    server.headers = {srv.SESSION_HEADER: token}
    yield server
    server.close()


def browser(console, method, path, body=None):
    return call(console.port, method, path, headers=console.headers, body=body)


def test_a_failed_row_has_a_draft_built_from_it(folder):
    run = webtest.load(folder)
    defects = webtest_defects.for_run(run, {})
    assert list(defects) == ["r01"]
    d = defects["r01"]
    assert d["status"] == "draft" and d["saved"] is False and d["title"] == "予約確認 → 予約履歴 on the header link"
    assert d["actual"] == "The link still reads 予約確認" and d["evidence"] == ["evidence/r01-a1-1.png"]
    assert d["expected"] == "The header link reads 予約履歴" and d["url"].endswith("/mypage")


@pytest.mark.parametrize("body, message", [
    ({"status": "sent", "title": "x"}, "tracker key"),
    ({"status": "not-a-defect", "title": "x"}, "reason"),
    ({"status": "draft", "title": ""}, "title"),
    ({"status": "closed", "title": "x"}, "status"),
    ({"status": "draft", "title": "x" * 201}, "200"),
])
def test_what_each_status_needs(body, message):
    with pytest.raises(DefectError, match=message):
        webtest_defects.check(body)


def test_save_keeps_the_row_facts_and_refuses_a_passing_row(folder, tmp_path):
    run = webtest.load(folder)
    store = tmp_path / "store"
    store.mkdir()
    saved = webtest_defects.save(store, run, "r01", {"status": "sent", "title": "Header link not renamed",
                                                    "tracker": "DEMO-42", "reason": "ignored"}, at="t", by="b")
    assert saved["tracker"] == "DEMO-42" and saved["reason"] == "" and saved["stale"] is False
    assert saved["evidence"] == ["evidence/r01-a1-1.png"] and saved["attempt"] == 1
    with pytest.raises(DefectError, match="failed row"):
        webtest_defects.save(store, run, "r02", {"status": "draft", "title": "x"}, at="t", by="b")
    if os.name == "posix":
        assert stat.S_IMODE((store / "defects.json").stat().st_mode) == 0o600
    # The row passes on a re-run: the saved defect stays, marked stale.
    for case in run["cases"]:
        if case["row"] == "r01":
            case.update(state="pass", attempt=2, result={"verdict": "pass", "evidence": []})
    again = webtest_defects.for_run(run, webtest_defects.read(store))
    assert again["r01"]["status"] == "sent" and again["r01"]["stale"] is True
    assert webtest_defects.counts(again) == {"draft": 0, "sent": 1, "not-a-defect": 0}


def test_console_routes_save_and_list(console, run_id, home):
    status, _, run = browser(console, "GET", f"/api/webtest/runs/{run_id}")
    assert status == 200
    by_row = {c["row"]: c for c in run["cases"]}
    assert by_row["r01"]["defect"]["status"] == "draft" and "defect" not in by_row["r02"]
    assert run["defect_counts"] == {"draft": 1, "sent": 0, "not-a-defect": 0}
    status, _, out = browser(console, "PUT", f"/api/webtest/runs/{run_id}/defects/r01",
                             {"status": "not-a-defect", "title": "Header", "reason": "The suite expected the old label"})
    assert status == 200 and out["defect"]["status"] == "not-a-defect"
    status, _, bad = browser(console, "PUT", f"/api/webtest/runs/{run_id}/defects/r01", {"status": "sent", "title": "x"})
    assert status == 400 and "tracker" in bad["error"]["message"]
    status, _, listing = browser(console, "GET", "/api/webtest/defects")
    assert status == 200 and listing["counts"] == {"draft": 0, "sent": 0, "not-a-defect": 1}
    entry = listing["defects"][0]
    assert entry["run"] == run_id and entry["row"] == "r01" and entry["saved"] is True
    store = home / ".testign-kit" / "webtest" / "runs" / run_id / "defects.json"
    assert store.is_file()


def test_the_export_report_lists_defects_and_fixed_rows(folder):
    run = webtest.load(folder)
    defects = webtest_defects.for_run(run, {})
    marks = {"r02": {"previous": {"run": "W1", "name": "round 1", "verdict": "fail"}, "fixed": True}}
    text = webtest_export.report_markdown(run, "book.xlsx", {}, marks, defects)
    assert "## Fixed since the previous run" in text and "round 1" in text
    assert "## Defects" in text and "| r01 |" in text.split("## Defects")[1].split("##")[0]
