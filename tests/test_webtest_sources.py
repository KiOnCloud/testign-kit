import os
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from make_report import write_report  # noqa: E402

from testign import templates, webtest, webtest_sources, xlsx  # noqa: E402
from testign.webtest_sources import Env, SourceError  # noqa: E402

FIGMA = "https://www.figma.com/design/AbCdEfGhIjKlMn/USUPP?node-id=6647-118148&m=dev"
SHA_A, SHA_B = "a" * 40, "b" * 40


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path / "out", tmp_path)


@pytest.fixture
def survey(env, tmp_path):
    return write_report(env.output_dir / "DEMO-1", tmp_path, SHA_A, SHA_B, revision=2)


@pytest.fixture
def template(tmp_path):
    return templates.register(xlsx.build_sample(tmp_path / "src" / "sample.xlsx"), "sample", home=tmp_path)


def test_the_four_kinds_are_registered():
    assert webtest_sources.kinds() == ("figma", "backlog", "excel", "manual")
    modes = {s["kind"]: (s["mode"], s["needs_agent"]) for s in webtest_sources.listing()}
    assert modes == {"figma": ("extract", True), "backlog": ("generate", True), "excel": ("extract", False),
                     "manual": ("none", False)}


def test_figma_source_and_ref(env):
    source = webtest_sources.check("figma", {"figma_url": FIGMA}, env)
    assert source == {"kind": "figma", "url": FIGMA, "file": "AbCdEfGhIjKlMn", "node": "6647:118148"}
    assert webtest_sources.ref(source) == ("figma", "AbCdEfGhIjKlMn", "6647:118148")
    assert webtest_sources.get("figma").trace_value({"no": "3", "target_node": "1:2"}) == "1:2"
    with pytest.raises(SourceError, match="node-id"):
        webtest_sources.check("figma", {"figma_url": "https://www.figma.com/design/AbCdEfGhIjKlMn/x?a=1"}, env)


def test_backlog_source_reads_the_report_frontmatter(env, survey):
    source = webtest_sources.check("backlog", {"ticket": "DEMO-1"}, env)
    assert source == {"kind": "backlog", "ticket": "DEMO-1", "report": "DEMO-1-survey-r2.md", "revision": 2,
                      "develop_head": SHA_A, "merge_base": SHA_B}
    rows = webtest_sources.get("backlog").rows(source, env, None)
    assert [r["id"] for r in rows] == ["B1", "B2", "B3", "R1", "R2"]
    assert webtest_sources.ref(source) == ("backlog", "DEMO-1", "DEMO-1-survey-r2.md")


def test_backlog_source_needs_a_survey_report(env, survey):
    with pytest.raises(SourceError, match="no survey report") as err:
        webtest_sources.check("backlog", {"ticket": "DEMO-9"}, env)
    assert err.value.code == "no-report"
    with pytest.raises(SourceError, match="r7.md of DEMO-1 cannot be read"):
        webtest_sources.check("backlog", {"ticket": "DEMO-1", "revision": 7}, env)
    with pytest.raises(SourceError, match="ticket_id_regex"):
        webtest_sources.check("backlog", {"ticket": "../DEMO-1"}, env)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_backlog_report_that_is_a_link_is_refused(env, survey, tmp_path):
    other = tmp_path / "elsewhere.md"
    other.write_text(survey.read_text(encoding="utf-8"), encoding="utf-8")
    link = survey.parent / "DEMO-1-survey-r3.md"
    link.symlink_to(other)
    with pytest.raises(SourceError, match="cannot be read"):
        webtest_sources.check("backlog", {"ticket": "DEMO-1"}, env)


def test_excel_source_reads_rows_through_the_template(env, template, tmp_path):
    entry = templates.resolve("sample", tmp_path)
    filled = xlsx.fill_copy(Path(entry["path"]), entry, [
        {"item": "Label shows 確定", "steps": "1. open", "expected": "shown", "trace": ["B2"]},
        {"item": "Total", "steps": "", "expected": "sum", "trace": ["R1"]},
    ], tmp_path / "filled.xlsx")
    source = webtest_sources.check("excel", {"file_name": "My Cases v1.xlsx", "template": "sample"}, env)
    assert source == {"kind": "excel", "file": "My-Cases-v1.xlsx", "template": "sample"}
    rows = webtest_sources.read_case_rows(Path(filled["path"]), entry)
    assert [(r["content"], r["trace"]) for r in rows] == [("Label shows 確定", ["B2"]), ("Total", ["R1"])]
    assert rows[0]["no"] == "1"


def test_excel_source_refuses_bad_names_and_templates(env, template):
    with pytest.raises(SourceError, match="xlsx"):
        webtest_sources.check("excel", {"file_name": "cases.csv", "template": "sample"}, env)
    with pytest.raises(SourceError, match="not registered"):
        webtest_sources.check("excel", {"file_name": "cases.xlsx", "template": "nope"}, env)
    assert webtest_sources.safe_file_name("..\\..\\evil name.XLSX") == "evil-name.xlsx"


def test_oversized_and_non_workbook_files_are_refused(tmp_path, monkeypatch):
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"not a zip")
    with pytest.raises(SourceError, match="not an Excel workbook"):
        webtest_sources.check_workbook_file(junk)
    big = xlsx.build_sample(tmp_path / "big.xlsx")
    monkeypatch.setattr(webtest_sources, "UPLOAD_CAP", 10)
    with pytest.raises(SourceError, match="10 MB"):
        webtest_sources.check_workbook_file(big)


def test_a_zip_that_is_not_a_workbook_and_a_chart_sheet_are_refused(template, tmp_path):
    import zipfile  # noqa: PLC0415

    import openpyxl  # noqa: PLC0415
    import openpyxl.chart  # noqa: PLC0415

    entry = templates.resolve("sample", tmp_path)
    fake = tmp_path / "fake.xlsx"
    with zipfile.ZipFile(fake, "w") as z:
        z.writestr("hello.txt", "not a workbook " * 20)
    with pytest.raises(SourceError) as exc:
        webtest_sources.read_case_rows(fake, entry)
    assert exc.value.code == "bad-file"
    charted = tmp_path / "charted.xlsx"
    wb = openpyxl.load_workbook(entry["path"])
    chart = openpyxl.chart.BarChart()
    chart.add_data(openpyxl.chart.Reference(wb.active, min_col=1, min_row=1, max_row=3))
    wb.create_chartsheet("Chart").add_chart(chart)
    wb.save(charted)
    with pytest.raises(SourceError) as exc:
        webtest_sources.read_case_rows(charted, entry, sheet="Chart")
    assert exc.value.code == "bad-sheet"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_linked_workbook_is_refused(tmp_path):
    real = xlsx.build_sample(tmp_path / "real.xlsx")
    link = tmp_path / "link.xlsx"
    link.symlink_to(real)
    with pytest.raises(SourceError, match="cannot be read"):
        webtest_sources.check_workbook_file(link)


def test_manual_source_needs_nothing(env):
    assert webtest_sources.check("manual", {}, env) == {"kind": "manual"}
    assert webtest_sources.get("manual").trace_label is None


def test_unknown_kind_is_refused(env):
    with pytest.raises(SourceError, match="one of figma, backlog, excel, manual"):
        webtest_sources.check("sheets", {}, env)


def test_a_fifth_kind_needs_only_a_registry_entry(env, monkeypatch):
    monkeypatch.setattr(webtest_sources, "REGISTRY", dict(webtest_sources.REGISTRY))
    webtest_sources.register(webtest_sources.Source(
        "sheet", "extract", True, "Row", lambda p, _e: {"kind": "sheet", "doc": p["doc"]},
        lambda s: ("sheet", s["doc"])))
    assert "sheet" in [s["kind"] for s in webtest_sources.listing()]
    assert webtest_sources.check("sheet", {"doc": "abc"}, env) == {"kind": "sheet", "doc": "abc"}
    # a run case may now carry the new kind without any change to the run module
    assert webtest._check_source({"kind": "sheet", "no": 1}, "r01") == {"kind": "sheet", "no": "1"}
