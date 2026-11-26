"""Results across the runs of a suite, and the Fixed mark."""

import json
from datetime import datetime

import pytest

openpyxl = pytest.importorskip("openpyxl")

from make_webtest_run import BASE_URL, HOSTS, ready_suite  # noqa: E402

from testign import login_scenarios, templates, webtest, webtest_export, webtest_history, webtest_suite  # noqa: E402

from test_webtest_runs_from_suites import SHIPPED_SAMPLE  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".testign-kit").mkdir()
    (tmp_path / ".testign-kit" / "config.json").write_text(
        json.dumps({"output_dir": str(tmp_path / "out"), "lang": "en"}), encoding="utf-8")
    templates.register(SHIPPED_SAMPLE, "sample", home=tmp_path, purpose="webtest")
    login_scenarios.save_project(tmp_path, "demo", HOSTS)
    login_scenarios.save_project(tmp_path, "other", HOSTS)
    return tmp_path


@pytest.fixture
def root(home):
    return home / "out" / "webtest"


def make_run(root, suite_folder, minute, project="demo"):
    target = webtest.check_run_target({project: {"hosts": HOSTS}}, templates.list_templates(), BASE_URL, project)
    suite = webtest_suite.load(suite_folder)
    made = webtest.new_run_from_suite(root, suite, suite_folder, name=f"round {minute}", target=target, tester="Kien",
                                      columns_for=lambda run: webtest_export.suite_plan(run),
                                      when=datetime(2026, 11, 25, 11, minute))
    return webtest.find_run(root, made["run"])


def set_rows(folder, **states):
    run = webtest.load(folder)
    for case in run["cases"]:
        if case["row"] in states:
            state = states[case["row"]]
            if state.startswith("self-"):
                case["state"] = "self-run"
                case["result"] = {"verdict": state[5:], "actual": "", "url": "", "evidence": [], "by": "tester:K"}
            else:
                case["state"] = state
                case["result"] = {"verdict": state, "actual": "x", "url": BASE_URL, "evidence": [], "by": "agent"}
    webtest.save(folder, run)
    return webtest.load(folder)


def test_verdict_of_agent_and_tester_rows():
    assert webtest_history.verdict({"state": "pass"}) == "pass"
    assert webtest_history.verdict({"state": "self-run", "result": {"verdict": "fail"}}) == "fail"
    assert webtest_history.verdict({"state": "manual"}) is None
    assert webtest_history.verdict({"state": "not-run"}) is None


def test_a_fail_then_a_pass_is_fixed(root):
    suite = ready_suite(root, kind="backlog")
    first = make_run(root, suite, 0)
    set_rows(first, r01="fail", r02="pass", r03="self-fail")
    second = make_run(root, suite, 5)
    run = set_rows(second, r01="pass", r02="fail", r03="self-pass")
    marks = webtest_history.run_marks(root, run)
    assert marks["r01"] == {"previous": {"run": first.name, "name": "round 0", "verdict": "fail"}, "fixed": True}
    assert marks["r02"]["fixed"] is False and marks["r02"]["previous"]["verdict"] == "pass"
    assert marks["r03"]["fixed"] is True
    assert "r04" not in marks  # manual in the earlier run: no verdict to compare
    # the earlier run has nothing before it
    assert webtest_history.run_marks(root, webtest.load(first)) == {}


def test_the_newest_earlier_run_with_a_verdict_counts(root):
    suite = ready_suite(root, kind="backlog")
    set_rows(make_run(root, suite, 0), r01="fail")
    set_rows(make_run(root, suite, 2), r01="pass")
    middle = make_run(root, suite, 4)  # r01 still queued: no verdict, skipped
    run = set_rows(make_run(root, suite, 6), r01="pass")
    prev = webtest_history.previous(root, run)["r01"]
    assert prev["name"] == "round 2" and prev["verdict"] == "pass"
    assert middle.name not in prev["run"]


def test_a_changed_case_or_another_project_is_not_compared(root):
    suite = ready_suite(root, kind="backlog")
    set_rows(make_run(root, suite, 0), r01="fail", r02="fail")
    set_rows(make_run(root, suite, 1, project="other"), r02="fail")
    webtest_suite.update_case(suite, "c1", {"content": "changed"})
    webtest_suite.confirm(suite, "Kien")
    run = set_rows(make_run(root, suite, 5), r01="pass", r02="pass")
    marks = webtest_history.run_marks(root, run)
    assert "r01" not in marks
    assert marks["r02"]["fixed"] is True and marks["r02"]["previous"]["name"] == "round 0"
    other = set_rows(make_run(root, suite, 7, project="other"), r02="pass")
    assert webtest_history.run_marks(root, other)["r02"]["previous"]["name"] == "round 1"


def test_suite_results_matrix(root):
    suite_folder = ready_suite(root, kind="backlog")
    first = make_run(root, suite_folder, 0)
    set_rows(first, r01="fail")
    second = make_run(root, suite_folder, 5)
    set_rows(second, r01="pass", r02="self-fail")
    suite = webtest_suite.load(suite_folder)
    out = webtest_history.suite_results(root, suite["id"], suite["cases"])
    assert [r["id"] for r in out["runs"]] == [second.name, first.name]
    row = out["cases"][0]
    assert row["case"] == "c1" and row["row"] == "r01"
    assert row["cells"][second.name] == {"verdict": "pass", "fixed": True, "changed": False}
    assert row["cells"][first.name] == {"verdict": "fail", "fixed": False, "changed": False}
    assert out["cases"][1]["cells"][second.name]["verdict"] == "fail"
    assert out["cases"][3]["cells"][first.name]["verdict"] == "manual"
