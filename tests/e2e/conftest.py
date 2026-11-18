"""Made-up DEMO data for the console's browser tests: reports, a stale ticket, an unreadable one,
two templates (one with other headers), a filled workbook and a scout cache entry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from make_report import write_report
from make_repo import make_repo

from testign import cache, gitscope, templates, xlsx

REPO = Path(__file__).resolve().parents[2]
SHIPPED_SAMPLE = REPO / "templates" / "testcase-template-sample.xlsx"
CASES = [
    {"item": "Tổng tiền trừ giảm giá", "steps": "...", "expected": "...", "trace": ["B2"]},
    {"item": "Làm tròn", "steps": "...", "expected": "...", "trace": ["B3"], "waiting_on": ["Q1"]},
    {"item": "請求書", "steps": "...", "expected": "...", "trace": ["R1"]},
    {"item": "Nhấp đúp không tạo đơn trùng", "steps": "...", "expected": "...", "trace": ["B9"]},
]
BIDI_CELL = "Làm tròn xuống ‮gnoud‬"


def english_template(path: Path) -> Path:
    import openpyxl  # noqa: PLC0415 - only needed when the data is built

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "テストケース"
    for c, h in enumerate(["No", "Test item", "Steps", "Expected", "Remarks"], start=1):
        ws.cell(row=4, column=c, value=h)
    wb.save(path)
    return path


def build_demo_home(home: Path, scratch: Path) -> dict:
    """Fill ``home`` (a fake user home) with console data; returns names the tests use."""
    out = home / "Downloads"
    out.mkdir(parents=True, exist_ok=True)
    repo = make_repo(scratch / "repo")
    head = gitscope.resolve_ref(str(repo.path), "develop")
    base = gitscope.merge_base(str(repo.path), "master", "develop")

    write_report(out / "DEMO-1", repo.path, head, base, revision=1)
    latest = write_report(out / "DEMO-1", repo.path, head, base, revision=2)
    text = latest.read_text(encoding="utf-8").replace("Làm tròn xuống", BIDI_CELL, 1)
    latest.write_text(text, encoding="utf-8", newline="\n")

    # DEMO-2 was surveyed before develop moved past a file its report cites.
    write_report(out / "DEMO-2", repo.path, repo.commits["D1"], base, lang="ja", ticket="DEMO-2")

    write_report(out / "DEMO-3", repo.path, head, base, lang="en", ticket="DEMO-3")
    (out / "DEMO-3" / "DEMO-3-survey-r2.md").write_bytes(b"\xff\xfe not a report")

    entry = templates.register(SHIPPED_SAMPLE, "mẫu", home=home)
    workbook = "DEMO-1-tc.xlsx"
    xlsx.fill_copy(Path(entry["path"]), entry, CASES, out / "DEMO-1" / workbook)
    templates.register(english_template(scratch / "english.xlsx"), "english", home=home)

    folder = cache.entry_dir("a" * 40, "order-confirm", home)
    folder.mkdir(parents=True)
    brief = "## 1. Brief\n| B1 | x | `src/a.cs@abcd1234` |\n"
    (folder / cache.BRIEF).write_bytes(brief.encode("utf-8"))
    manifest = {
        "feature": "order-confirm", "root_commit": "a" * 40, "merge_base": "b" * 40, "anchors": ["確定", "合計"],
        "files": {"src/a.cs": "abcd1234"}, "rows": {"B1": ["src/a.cs"], "B2": ["src/a.cs"], "B3": ["src/a.cs"]},
        "unread": ["sp_calc_tax"], "plugin_version": "0.2.0", "scout_model": "sonnet",
        "brief_sha256": hashlib.sha256(brief.encode()).hexdigest(),
        "reviewed_by": {"name": "Tester A", "date": "2026-11-17"}, "created_at": "2026-11-17T10:00:00+07:00",
    }
    (folder / cache.MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    cache.entry_dir("a" * 40, "broken", home).mkdir(parents=True)
    return {"workbook": workbook, "bidi_cell": BIDI_CELL}


@pytest.fixture(scope="module")
def demo_home(tmp_path_factory) -> tuple[Path, dict]:
    root = tmp_path_factory.mktemp("console-e2e")
    home = root / "home"
    home.mkdir()
    return home, build_demo_home(home, root)
