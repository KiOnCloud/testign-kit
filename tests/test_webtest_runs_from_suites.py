import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from make_webtest_run import BASE_URL, HOSTS, ready_suite  # noqa: E402

from testign import cli, login_scenarios, templates, webtest, webtest_export, webtest_suite  # noqa: E402
from testign.webtest import WebtestError  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIPPED_SAMPLE = REPO / "templates" / "testcase-template-sample.xlsx"
V1 = Path(__file__).resolve().parent / "fixtures" / "webtest-run-v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 16
WHEN = datetime(2026, 11, 25, 11, 0)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".testign-kit").mkdir()
    (tmp_path / ".testign-kit" / "config.json").write_text(
        json.dumps({"output_dir": str(tmp_path / "out"), "lang": "en"}), encoding="utf-8")
    templates.register(SHIPPED_SAMPLE, "sample", home=tmp_path, purpose="webtest")
    login_scenarios.save_project(tmp_path, "demo", HOSTS)
    return tmp_path


@pytest.fixture
def root(home):
    return home / "out" / "webtest"


def make_run(root, suite_folder, **extra):
    target = webtest.check_run_target({"demo": {"hosts": HOSTS}}, templates.list_templates(), BASE_URL, "demo")
    suite = webtest_suite.load(suite_folder)
    return webtest.new_run_from_suite(root, suite, suite_folder, name=extra.get("name"), target=target,
                                      tester="Kien", columns_for=lambda run: webtest_export.suite_plan(run),
                                      when=extra.get("when", WHEN))


def test_a_run_from_a_suite_is_confirmed_with_its_own_copy(root):
    suite_folder = ready_suite(root, kind="backlog")
    (suite_folder / "source" / "c1.png").write_bytes(PNG)
    suite = webtest_suite.load(suite_folder)
    suite["cases"][0]["capture"] = "source/c1.png"
    webtest_suite.save(suite_folder, suite)
    webtest_suite.confirm(suite_folder, "Kien")
    made = make_run(root, suite_folder)
    folder = webtest.find_run(root, made["run"])
    run = webtest.load(folder)
    assert run["version"] == 2 and run["suite"]["id"] == suite_folder.name and run["ticket"] == "DEMO-1"
    assert run["confirmed"]["by"] == "Kien" and run["confirmed"]["job"] is None
    assert run["digest"] == webtest.cases_digest(run)
    states = {c["row"]: c["state"] for c in run["cases"]}
    assert states == {"r01": "queued", "r02": "queued", "r03": "awaiting-tester", "r04": "manual"}
    first = run["cases"][0]
    assert first["source"] == {"kind": "backlog", "trace": "B4,R1"}
    assert first["screen"]["url"] == "https://dev.example.test/mypage"
    assert first["capture"] == "source/r01.png" and (folder / "source" / "r01.png").read_bytes() == PNG
    fields = [c["field"] for c in run["columns"]["columns"]]
    assert "trace" in fields and "content" in fields and "verdict" in fields
    assert next(c for c in run["columns"]["columns"] if c["field"] == "trace")["header"] == "Trace"
    # editing the suite afterwards leaves the run unchanged
    webtest_suite.update_case(suite_folder, "c1", {"content": "changed"})
    assert webtest.load(folder)["cases"][0]["content"] == "予約確認 → 予約履歴 on the header link"


def test_a_run_exports_without_a_review_step_with_a_trace_column(root):
    made = make_run(root, ready_suite(root, kind="backlog"))
    folder = webtest.find_run(root, made["run"])
    webtest.close(folder, lambda _job: False)
    out = webtest_export.export(folder, webtest.load(folder))
    run = webtest.load(folder)
    trace_letter = next(c["letter"] for c in run["columns"]["columns"] if c["field"] == "trace")
    ws = openpyxl.load_workbook(out["workbook"])[templates.resolve("sample")["sheet"]]
    header_row = run["columns"]["header_row"]
    column = [ws[f"{trace_letter}{r}"].value for r in range(header_row, header_row + 5)]
    assert column == ["Trace", "B4,R1", "B2", "B5", "R2"]
    report = Path(out["report"]).read_text(encoding="utf-8")
    assert f"- Test suite: Header update (`{run['suite']['id']}`)" in report
    assert "- Source: DEMO-1-survey-r2.md" in report


def test_a_suite_in_review_cannot_be_run(root):
    folder = ready_suite(root)
    webtest_suite.update_case(folder, "c1", {"content": "edited"})
    with pytest.raises(WebtestError, match="not ready"):
        make_run(root, folder)
    assert webtest.list_runs(root) == {}


def test_run_target_checks_hosts_and_template():
    projects = {"demo": {"hosts": HOSTS}}
    listing = {"default": "sample", "templates": [{"name": "sample"}]}
    assert webtest.check_run_target(projects, listing, BASE_URL, "demo")["hosts"] == HOSTS
    for args, code in (((BASE_URL, "nope"), "unknown-project"), (("https://evil.test/", "demo"), "off-host"),
                       (("ftp://dev.example.test", "demo"), "bad-base-url"),
                       ((BASE_URL, "demo", "other"), "unknown-template")):
        with pytest.raises(webtest.TargetError) as err:
            webtest.check_run_target(projects, listing, *args)
        assert err.value.code == code


def test_cli_creates_a_run_from_a_suite(root, home):
    folder = ready_suite(root, kind="figma", cases=[
        {"content": "row", "class": "sure", "runner": "agent", "scenario": "none", "screen": "/",
         "source": {"no": "3", "target_node": "I10:1"}}])
    made = cli.new_run_from_suite(folder.name, name="Smoke", base_url=BASE_URL, project="demo", template=None,
                                  tester="Kien", home=home)
    run = webtest.load(webtest.find_run(root, made["run"]))
    assert run["name"] == "Smoke" and run["cases"][0]["source"] == {"no": "3", "target_node": "I10:1",
                                                                     "kind": "figma"}
    assert next(c for c in run["columns"]["columns"] if c["field"] == "trace")["header"] == "Figma node"
    assert webtest_export.value_for(run["cases"][0], "trace", {}) == "I10:1"


def test_a_version_1_run_loads_shows_and_exports(root):
    target = root / "W20261119-1000-header-update"
    shutil.copytree(V1, target)
    (target / "evidence").mkdir(exist_ok=True)
    run = webtest.load(target)
    assert run["version"] == 1 and "suite" not in run
    status = webtest.status(target)
    assert status["confirmed"] and len(status["rows"]) == 8
    webtest.close(target, lambda _job: False)
    out = webtest_export.export(target, webtest.load(target))
    ws = openpyxl.load_workbook(out["workbook"])[templates.resolve("sample")["sheet"]]
    assert ws["D5"].value == "I10:1;2:3"  # the target_node column a version 1 run stored
    assert "Test suite" not in Path(out["report"]).read_text(encoding="utf-8")


def test_a_long_suite_name_gives_a_run_name_within_the_run_cap(root):
    suite_folder = ready_suite(root, kind="backlog")
    suite = webtest_suite.load(suite_folder)
    suite["name"] = "x" * 120
    webtest_suite.save(suite_folder, suite)
    webtest_suite.confirm(suite_folder, "Kien")
    run = webtest.load(webtest.find_run(root, make_run(root, suite_folder)["run"]))
    assert run["name"] == "x" * 80


def test_the_command_line_cannot_confirm_a_suite_and_its_case_edits_follow_the_agents_rules(root, tmp_path, capsys):
    folder = ready_suite(root)
    with pytest.raises(SystemExit):
        cli.main(["suite-confirm", "--suite", folder.name, "--by", "Kien"])
    capsys.readouterr()
    choice = tmp_path / "choice.json"
    choice.write_text(json.dumps({"content": "Cancel a booking", "class": "choice", "runner": "agent",
                                  "preconditions": "a test booking", "screen": {"url": "/bookings"},
                                  "scenario": "none"}), encoding="utf-8")
    assert cli.main(["suite-case-add", "--suite", folder.name, "--file", str(choice)]) == 2
    assert "tester" in capsys.readouterr().err
    assert webtest_suite.load(folder)["state"] == "ready"
    label = tmp_path / "label.json"
    label.write_text(json.dumps({"content": "Header reads 予約履歴"}), encoding="utf-8")
    assert cli.main(["suite-case-update", "--suite", folder.name, "--case", "c1", "--file", str(label)]) == 0
    assert webtest_suite.load(folder)["state"] == "review"
