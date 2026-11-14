"""Decisions split across feature pages, a common page and a project index."""

import pytest

from testign import config, decisions

RX = config.DEFAULT_TICKET_ID_REGEX

ORDER_PAGE = """# Decisions — DEMO / order-confirm

## DEMO-12 · 注文確定

### D-DEMO-12-001 · Q1
- Date: 2026-11-14
- Question: 「確定」ボタン押下時に確認ダイアログを表示するか
- Decision: Hiển thị dialog xác nhận.
- Quote:
  > 確認ダイアログを表示してください。
- Source: https://demo.backlog.com/view/DEMO-12#comment-1001
- Decided by: BrSE (Tanaka)
- Approved by: Asher
- Report: DEMO-12-survey-r1.md
- Status: active
"""

COMMON_PAGE = """# Decisions — DEMO / common

## DEMO-12 · 注文確定

### D-DEMO-12-002 · Q2
- Date: 2026-11-14
- Question: 税率は設定から取得するか
- Decision: Lấy từ config TaxRate.
- Quote:
  > 設定値を使ってください。
- Source: https://demo.backlog.com/view/DEMO-12#comment-1002
- Decided by: Customer
- Approved by: Asher
- Report: DEMO-12-survey-r1.md
- Status: active
"""

INDEX = """# Decisions index — DEMO

> Managed by testign `/testign:close`. One row per decision; keep the columns.

| ID | Page | Ticket | Q | Anchors | Date | Status |
|---|---|---|---|---|---|---|
| D-DEMO-12-001 | order-confirm | DEMO-12 | Q1 | 注文確定; 「確定」 | 2026-11-14 | active |
| D-DEMO-12-002 | common | DEMO-12 | Q2 | CalcTotal; TaxRate | 2026-11-14 | active |
| D-DEMO-30-001 | invoice | DEMO-30 | Q1 | 請求書; 「確定」 | 2026-11-10 | active |
"""


def row(**over):
    base = {
        "ticket": "DEMO-12", "q": "Q3", "feature": "order-confirm", "anchors": ["注文確定", "ポイント利用"],
        "date": "2026-11-15", "question": "割引は請求書にも適用されますか？", "decision": "Có.",
        "quote": "はい。", "source": "https://demo.backlog.com/view/DEMO-12#comment-1010",
        "decided_by": "Customer", "approved_by": "Asher", "report": "DEMO-12-survey-r2.md",
    }
    return {**base, **over}


def test_lookup_finds_decisions_filed_under_other_features():
    found = decisions.lookup(INDEX, ["「確定」ボタン"], ticket="DEMO-99", feature="order-confirm")
    assert [m["id"] for m in found["matched"]] == ["D-DEMO-12-001", "D-DEMO-30-001"]
    assert found["pages"] == ["order-confirm", "invoice", "common"]


def test_lookup_by_ticket_and_always_common():
    found = decisions.lookup(INDEX, ["no-such-anchor"], ticket="DEMO-12")
    assert [m["id"] for m in found["matched"]] == ["D-DEMO-12-001", "D-DEMO-12-002"]
    assert found["pages"] == ["order-confirm", "common"]
    assert decisions.lookup("", ["x"], feature="point")["pages"] == ["common", "point"]


def test_first_decision_creates_page_and_index():
    pages, index, result = decisions.apply_changes({"point": ""}, "", [row(feature="point", ticket_title="ポイント")], RX,
                                                   project="DEMO")
    assert result["added"] == ["D-DEMO-12-001"]
    assert pages["point"].startswith("# Decisions — DEMO / point\n\n## DEMO-12 · ポイント\n\n### D-DEMO-12-001 · Q3\n")
    assert index.startswith("# Decisions index — DEMO\n")
    assert "| D-DEMO-12-001 | point | DEMO-12 | Q3 | 注文確定; ポイント利用 | 2026-11-15 | active |\n" in index
    assert decisions.parse_index(index)[0]["anchors"] == ["注文確定", "ポイント利用"]


def test_ids_are_global_per_ticket_across_pages():
    pages, index, result = decisions.apply_changes(
        {"order-confirm": ORDER_PAGE, "common": COMMON_PAGE}, INDEX, [row()], RX)
    assert result["added"] == ["D-DEMO-12-003"]
    assert list(pages) == ["order-confirm"]
    assert pages["order-confirm"].startswith(ORDER_PAGE)
    assert index.startswith(INDEX)
    assert index.endswith("| D-DEMO-12-003 | order-confirm | DEMO-12 | Q3 | 注文確定; ポイント利用 | 2026-11-15 | active |\n")


def test_supersede_across_pages_updates_old_page_and_index():
    new_q1 = row(q="Q1", feature="common", source="https://demo.backlog.com/view/DEMO-12#comment-2000",
                 anchors=["「確定」"])
    needed = decisions.pages_needed([new_q1], INDEX)
    assert needed == ["common", "order-confirm"]
    pages, index, result = decisions.apply_changes(
        {"order-confirm": ORDER_PAGE, "common": COMMON_PAGE}, INDEX, [new_q1], RX)
    assert result["superseded"] == ["D-DEMO-12-001"] and result["added"] == ["D-DEMO-12-003"]
    assert sorted(pages) == ["common", "order-confirm"]
    assert pages["order-confirm"] == ORDER_PAGE.replace("- Status: active", "- Status: superseded by D-DEMO-12-003")
    assert "| D-DEMO-12-001 | order-confirm | DEMO-12 | Q1 | 注文確定; 「確定」 | 2026-11-14 | superseded by D-DEMO-12-003 |" in index
    untouched = [l for l in INDEX.splitlines() if "D-DEMO-12-001" not in l]
    assert all(l in index.splitlines() for l in untouched)


def test_duplicate_is_skipped_and_missing_index_row_is_repaired():
    index_without_001 = "\n".join(l for l in INDEX.splitlines() if "D-DEMO-12-001" not in l) + "\n"
    again = row(q="Q1", source="https://demo.backlog.com/view/DEMO-12#comment-1001", anchors=["「確定」"])
    pages, index, result = decisions.apply_changes(
        {"order-confirm": ORDER_PAGE}, index_without_001, [again], RX)
    assert pages == {} and result["added"] == []
    assert result["skipped"][0]["id"] == "D-DEMO-12-001"
    assert result["index_repaired"] == ["D-DEMO-12-001"]
    assert "| D-DEMO-12-001 | order-confirm | DEMO-12 | Q1 | 「確定」 |" in index


def test_needed_pages_must_be_loaded():
    with pytest.raises(decisions.DecisionsError, match="pages not loaded: order-confirm"):
        decisions.apply_changes({"common": COMMON_PAGE}, INDEX, [row(q="Q1", feature="common")], RX)


@pytest.mark.parametrize("bad", [{"anchors": []}, {"anchors": "x"}, {"feature": ""}, {"feature": "index"}])
def test_rows_need_anchors_and_a_valid_feature(bad):
    with pytest.raises(decisions.DecisionsError):
        decisions.apply_changes({"order-confirm": ORDER_PAGE}, INDEX, [row(**bad)], RX)


def test_index_pipes_in_anchors_are_escaped():
    pages, index, _ = decisions.apply_changes({"order-confirm": ORDER_PAGE}, INDEX, [row(anchors=["A|B"])], RX)
    assert "A\\|B" in index
    assert decisions.parse_index(index)[-1]["anchors"] == ["A|B"]
