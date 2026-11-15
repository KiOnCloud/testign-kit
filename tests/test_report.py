import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from make_report import write_report

from testign import __version__, report

REPO = Path(__file__).resolve().parent.parent
SHA_D, SHA_B = "d" * 40, "b" * 40


def test_fixture_report_is_valid(tmp_path):
    result = report.validate(write_report(tmp_path, tmp_path, SHA_D, SHA_B))
    assert result["ok"], result["errors"]


def test_template_section_order_is_accepted_by_the_parser():
    text = (REPO / "templates" / "survey-report-template.md").read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    for key in report.FRONTMATTER_KEYS:
        assert f"\n{key}:" in front, key
    for n in range(1, 9):
        assert f"## {n}." in text


@pytest.mark.parametrize(
    "old,new,error",
    [
        ("| Hiện màn xác nhận `[code]` |", "| Hiện màn xác nhận |", "B1 has no source label"),
        ("· F4 · intent ·", "· F4 ·", "Q1 heading has no fact/intent label"),
        ("- **Câu hỏi (ja, draft cho BrSE):** 割引は請求書にも適用されますか？\n", "", "no ja draft"),
        ("## 6. Coverage & độ tin cậy", "## 9. Khác", "section 6 is missing"),
        (f"merge_base: {SHA_B}", "merge_base: abc123", "full 40-character SHA"),
    ],
)
def test_validate_catches_contract_breaks(tmp_path, old, new, error):
    path = write_report(tmp_path, tmp_path, SHA_D, SHA_B)
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
    result = report.validate(path)
    assert not result["ok"]
    assert any(error in e for e in result["errors"]), result["errors"]


def test_placeholders_are_warnings(tmp_path):
    result = report.validate(write_report(tmp_path, tmp_path, SHA_D, SHA_B))
    assert any("<n>" in w for w in result["warnings"])


def test_revision_paths_never_reuse_a_number(tmp_path):
    out = tmp_path / "out"
    assert report.new_report_path(out, "DEMO-1") == out / "DEMO-1" / "DEMO-1-survey-r1.md"
    write_report(out / "DEMO-1", tmp_path, SHA_D, SHA_B, revision=1)
    write_report(out / "DEMO-1", tmp_path, SHA_D, SHA_B, revision=3)
    assert report.latest_revision(out / "DEMO-1", "DEMO-1").name == "DEMO-1-survey-r3.md"
    assert report.new_report_path(out, "DEMO-1").name == "DEMO-1-survey-r4.md"


def make_draft(folder, repo):
    path = write_report(folder, repo, SHA_D, SHA_B)
    return path.rename(path.with_name("DEMO-1-survey-draft.md"))


def run_cli(*args, home):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    return subprocess.run([sys.executable, str(REPO / "scripts" / "run.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def test_report_save_numbers_revisions_and_refuses_invalid(tmp_path):
    out, home = tmp_path / "out", tmp_path / "home"
    draft = make_draft(tmp_path / "drafts", tmp_path)

    first = run_cli("report-save", "--draft", str(draft), "--out-dir", str(out), home=home)
    assert first.returncode == 0, first.stderr
    saved = json.loads(first.stdout)
    assert Path(saved["saved"]) == out / "DEMO-1" / "DEMO-1-survey-r1.md"
    assert saved["previous"] is None and not draft.exists()

    draft = make_draft(tmp_path / "drafts", tmp_path)
    second = json.loads(run_cli("report-save", "--draft", str(draft), "--out-dir", str(out), home=home).stdout)
    meta, _ = report.load(Path(second["saved"]))
    assert meta["revision"] == 2 and meta["previous"] == "DEMO-1-survey-r1.md"
    assert meta["plugin_version"] == __version__

    draft = make_draft(tmp_path / "drafts", tmp_path)
    draft.write_text(draft.read_text(encoding="utf-8").replace("`[code]`", ""), encoding="utf-8")
    invalid_text = draft.read_text(encoding="utf-8")
    bad = run_cli("report-save", "--draft", str(draft), "--out-dir", str(out), home=home)
    assert bad.returncode == 1
    assert json.loads(bad.stdout)["saved"] is None
    assert draft.read_text(encoding="utf-8") == invalid_text  # an invalid draft is not modified
    assert not (out / "DEMO-1" / "DEMO-1-survey-r3.md").exists()


def test_report_save_refuses_a_saved_revision_as_draft(tmp_path):
    out, home = tmp_path / "out", tmp_path / "home"
    r1 = write_report(out / "DEMO-1", tmp_path, SHA_D, SHA_B)
    before = r1.read_bytes()
    res = run_cli("report-save", "--draft", str(r1), "--out-dir", str(out), home=home)
    assert res.returncode == 2 and "saved revision" in res.stderr
    assert r1.read_bytes() == before
    assert not (out / "DEMO-1" / "DEMO-1-survey-r2.md").exists()


def test_report_save_refuses_ticket_outside_output_dir(tmp_path):
    draft = make_draft(tmp_path / "drafts", tmp_path)
    draft.write_text(draft.read_text(encoding="utf-8").replace("ticket: DEMO-1", "ticket: ../x"), encoding="utf-8")
    res = run_cli("report-save", "--draft", str(draft), "--out-dir", str(tmp_path / "out"), home=tmp_path / "home")
    assert res.returncode == 2 and "invalid ticket ID" in res.stderr
    assert not (tmp_path / "x").exists()


def test_write_new_never_replaces(tmp_path):
    target = tmp_path / "DEMO-1-survey-r1.md"
    report.write_new(target, "first")
    with pytest.raises(report.ReportError, match="already exists"):
        report.write_new(target, "second")
    assert target.read_text(encoding="utf-8") == "first"


def test_report_path_cli(tmp_path):
    home = tmp_path / "home"
    (home / ".testign-kit").mkdir(parents=True)
    (home / ".testign-kit" / "config.json").write_text(json.dumps({"output_dir": str(tmp_path / "out")}), encoding="utf-8")
    res = json.loads(run_cli("report-path", "--ticket", "DEMO-9", home=home).stdout)
    assert res["latest"] is None
    assert Path(res["next"]) == tmp_path / "out" / "DEMO-9" / "DEMO-9-survey-r1.md"
