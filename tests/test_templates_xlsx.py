import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from make_report import write_report  # noqa: E402

from testign import report, templates, trace, xlsx  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIPPED_SAMPLE = REPO / "templates" / "testcase-template-sample.xlsx"

CASES = [
    {"item": "Tổng tiền trừ giảm giá", "steps": "1. Mở 注文確定\n2. Bấm 「確定」", "expected": "Tổng = hàng + thuế − giảm", "trace": ["B2"]},
    {"item": "Làm tròn tổng", "steps": "...", "expected": "(chờ Q1)", "trace": ["B3"], "waiting_on": ["Q1"]},
    {"item": "請求書 dùng tổng mới", "steps": "...", "expected": "...", "trace": ["R1", "B2"]},
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def sample(tmp_path):
    return xlsx.build_sample(tmp_path / "src" / "sample.xlsx")


@pytest.fixture
def registered(tmp_path, sample):
    return templates.register(sample, "sample", home=tmp_path)


def english_template(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cases"
    ws.merge_cells("A1:B1")
    ws["A1"] = "Test cases"
    for c, h in enumerate(["Case", "What to check", "How", "Should see", "Comment"], start=1):
        ws.cell(row=3, column=c, value=h)
    wb.save(path)
    return path


def test_shipped_sample_is_committed_and_detectable():
    assert SHIPPED_SAMPLE.exists()
    layout = templates.detect_layout(SHIPPED_SAMPLE)
    assert layout["sheet"] == "テストケース"
    assert layout["header_row"] == 4
    assert layout["columns"] == {"no": "A", "item": "B", "steps": "C", "expected": "D", "evidence": "E", "trace": "H"}


def test_register_copies_into_home_registry(tmp_path, sample, registered):
    stored = Path(registered["path"])
    assert stored.parent == templates.templates_dir(tmp_path)
    assert stored.read_bytes() == sample.read_bytes()
    index = json.loads(templates.index_path(tmp_path).read_text(encoding="utf-8"))
    assert index["default"] == "sample"
    assert index["templates"]["sample"]["columns"]["trace"] == "H"
    assert REPO not in stored.parents


def test_register_refuses_duplicate_name_unless_replace(tmp_path, sample, registered):
    with pytest.raises(templates.TemplateError, match="already registered"):
        templates.register(sample, "sample", home=tmp_path)
    assert templates.register(sample, "sample", replace=True, home=tmp_path)["name"] == "sample"


def test_multiple_templates_and_default(tmp_path, sample, registered):
    eng = english_template(tmp_path / "eng.xlsx")
    templates.register(eng, "khach-B", overrides={"item": "B", "trace": "E"}, home=tmp_path)
    listing = templates.list_templates(tmp_path)
    assert [t["name"] for t in listing["templates"]] == ["sample", "khach-B"]
    assert listing["default"] == "sample"
    templates.set_default("khach-B", home=tmp_path)
    assert templates.resolve(home=tmp_path)["name"] == "khach-B"
    assert templates.resolve("sample", home=tmp_path)["columns"]["trace"] == "H"
    templates.remove("khach-B", home=tmp_path)
    assert templates.resolve(home=tmp_path)["name"] == "sample"


def test_unmapped_template_reports_headers_and_accepts_overrides(tmp_path):
    eng = english_template(tmp_path / "eng.xlsx")
    with pytest.raises(templates.TemplateError) as err:
        templates.register(eng, "eng", home=tmp_path)
    assert "What to check" in str(err.value)
    entry = templates.register(
        eng, "eng", sheet="Cases", header_row=3, overrides={"item": "B", "steps": "C", "expected": "D", "trace": "E"},
        home=tmp_path,
    )
    assert entry["columns"] == {"item": "B", "steps": "C", "expected": "D", "trace": "E"}


def test_preview_shows_layout_without_model_reading_xlsx(tmp_path, registered):
    entry = templates.resolve(home=tmp_path)
    text = templates.preview(Path(entry["path"]), entry["sheet"], entry["header_row"], entry["columns"], title="sample")
    assert "**テストケース** (dùng)" in text
    assert "| trace | H | 備考 |" in text
    assert "4 ◀ header" in text
    assert "A1:H1" in text
    assert "OK,NG,保留,対象外" in text


def test_fill_copy_keeps_template_bytes_and_formatting(tmp_path, registered):
    entry = templates.resolve(home=tmp_path)
    src = Path(entry["path"])
    before = sha(src)
    out = xlsx.fill_copy(src, entry, CASES, tmp_path / "out" / "DEMO-1-testcase.xlsx")
    assert sha(src) == before
    wb = openpyxl.load_workbook(out["path"])
    ws = wb["テストケース"]
    assert [ws.cell(row=r, column=8).value for r in (5, 6, 7)] == ["B2", "B3 (chờ Q1)", "R1, B2"]
    assert [ws.cell(row=r, column=1).value for r in (5, 6, 7)] == [1, 2, 3]
    assert ws.cell(row=7, column=2).border.left.style == "thin"
    assert "A1:H1" in [str(m) for m in ws.merged_cells.ranges]
    assert any("F5:F500" in str(dv.sqref) for dv in ws.data_validations.dataValidation)
    assert wb["表紙"]["B2"].value == "テスト仕様書（サンプル）"


def test_prefilled_number_formulas_do_not_push_cases_down(tmp_path, sample):
    wb = openpyxl.load_workbook(sample)
    ws = wb["テストケース"]
    for r in range(5, 205):
        ws.cell(row=r, column=1, value=f"=ROW()-4")
    prefilled = tmp_path / "prefilled.xlsx"
    wb.save(prefilled)
    entry = templates.register(prefilled, "prefilled", home=tmp_path)
    out = xlsx.fill_copy(Path(entry["path"]), entry, CASES, tmp_path / "out" / "p.xlsx")
    assert out["rows"] == [5, 6, 7]
    filled = openpyxl.load_workbook(out["path"])["テストケース"]
    assert filled["A5"].value == "=ROW()-4"
    assert filled["H5"].value == "B2"


def test_rerun_never_overwrites(tmp_path, registered):
    entry = templates.resolve(home=tmp_path)
    target = tmp_path / "out" / "DEMO-1-testcase.xlsx"
    first = xlsx.fill_copy(Path(entry["path"]), entry, CASES, target)
    first_bytes = Path(first["path"]).read_bytes()
    second = xlsx.fill_copy(Path(entry["path"]), entry, CASES, target)
    assert first["path"] != second["path"]
    assert Path(first["path"]).read_bytes() == first_bytes


def test_add_sheet_to_filled_workbook_keeps_existing_sheets(tmp_path, registered):
    entry = templates.resolve(home=tmp_path)
    first = Path(xlsx.fill_copy(Path(entry["path"]), entry, CASES, tmp_path / "out" / "a.xlsx")["path"])
    wb = openpyxl.load_workbook(first)
    wb["テストケース"]["G5"] = "tester edit"
    wb.save(first)
    before = sha(first)
    res = xlsx.add_sheet(first, entry, CASES[:1], "TC-20260101-0900")
    assert sha(first) == before
    out = openpyxl.load_workbook(res["path"])
    assert out["テストケース"]["G5"].value == "tester edit"
    new = out["TC-20260101-0900"]
    assert new["H5"].value == "B2"
    assert new["H6"].value is None
    assert new["B4"].value == "確認項目"


def test_every_case_needs_a_row_id(tmp_path, registered):
    entry = templates.resolve(home=tmp_path)
    with pytest.raises(templates.TemplateError, match="B\\*/R\\*"):
        xlsx.fill_copy(Path(entry["path"]), entry, [{"item": "x", "trace": ["Q1"]}], tmp_path / "o.xlsx")


def test_trace_gaps_orphans_waiting_and_section7(tmp_path, registered):
    entry = templates.resolve(home=tmp_path)
    out = Path(xlsx.fill_copy(Path(entry["path"]), entry, CASES, tmp_path / "out" / "a.xlsx")["path"])
    wb = openpyxl.load_workbook(out)
    ws = wb["テストケース"]
    ws["B8"], ws["H8"] = "TC tự thêm", "không có ID"
    ws["B9"], ws["H9"] = "TC trỏ dòng không tồn tại", "B9"
    wb.save(out)

    rpt = write_report(tmp_path / "reports", tmp_path, "d" * 40, "b" * 40)
    _, body = report.load(rpt)
    rows = report.behavior_rows(body) + report.regression_rows(body)
    assert [r["id"] for r in rows if r["needs_case"]] == ["B2", "B3", "R1", "R2"]

    cases = xlsx.read_trace(out, entry)
    summary = trace.summarize(rows, cases)
    assert summary["gaps"] == ["R2"]
    assert summary["orphans"] == ["row 8", "row 9"]
    assert summary["waiting"] == [{"case": "2", "questions": ["Q1"]}]

    new_body = report.replace_section(body, 7, trace.section7(summary, out.name, "テストケース"))
    rev = report.write_revision(rpt, new_body)
    assert rev.name == "DEMO-1-survey-r2.md"
    meta, text = report.load(rev)
    assert meta["previous"] == "DEMO-1-survey-r1.md" and meta["revision"] == 2
    sec7 = report.section(text, 7)
    assert "**Gaps** (dòng có lệch/ảnh hưởng nhưng chưa có TC): R2" in sec7
    assert "2 → Q1" in sec7
    assert "## 8. Phụ lục cho dev" in text
    assert report.load(rpt)[1] == body


def run_cli(*args, home):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run.py"), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


def test_cli_first_run_register_fill_trace(tmp_path):
    home = tmp_path / "home"
    proc = run_cli("xlsx-fill", "--report", "x.md", "--cases", "x.json", home=home)
    assert proc.returncode == 2 and "no template registered yet" in proc.stderr

    proc = run_cli("template-register", "--file", str(SHIPPED_SAMPLE), "--name", "mẫu cơ bản", home=home)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["default"] is True

    proc = run_cli("template-preview", home=home)
    assert proc.returncode == 0 and "| trace | H | 備考 |" in proc.stdout

    rpt = write_report(tmp_path / "reports", tmp_path, "d" * 40, "b" * 40)
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(CASES, ensure_ascii=False), encoding="utf-8")
    proc = run_cli("xlsx-fill", "--report", str(rpt), "--cases", str(cases), "--out-dir", str(tmp_path / "out"), home=home)
    assert proc.returncode == 0, proc.stderr
    filled = json.loads(proc.stdout)
    assert Path(filled["path"]).parent == tmp_path / "out" / "DEMO-1"

    proc = run_cli("trace", "--report", str(rpt), "--xlsx", filled["path"], "--write-revision", home=home)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["gaps"] == ["R2"] and result["orphans"] == []
    assert Path(result["revision"]).name == "DEMO-1-survey-r2.md"


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_template_preview_output_is_pinned(tmp_path):
    """template-preview prints exactly what it printed before the console added preview_grid."""
    home = tmp_path / "home"
    assert run_cli("template-register", "--file", str(SHIPPED_SAMPLE), "--name", "mẫu", home=home).returncode == 0
    proc = run_cli("template-preview", home=home)
    assert proc.returncode == 0
    assert proc.stdout == (FIXTURES / "template-preview-golden.md").read_text(encoding="utf-8")
    proc = run_cli("template-preview", "--file", str(SHIPPED_SAMPLE), home=home)
    assert proc.stdout == (FIXTURES / "template-preview-file-golden.md").read_text(encoding="utf-8")
