import pytest

from testign import config, decisions

RX = config.DEFAULT_TICKET_ID_REGEX

PAGE = """# Decisions log — DEMO

> Managed by testign `/testign:close`. Ghi chú tay ở đây được giữ nguyên.

## DEMO-12 · 注文確定画面の確認ダイアログ

### D-DEMO-12-001 · Q1
- Date: 2026-11-14
- Question: 「確定」ボタン押下時に確認ダイアログを表示するか
- Decision: Hiển thị dialog xác nhận.
- Quote:
  > 確認ダイアログを表示してください。
  > キャンセル時は画面をそのままにしてください。
- Source: https://demo.backlog.com/view/DEMO-12#comment-1001
- Decided by: BrSE (Tanaka)
- Approved by: Asher
- Report: DEMO-12-survey-r1.md
- Status: active

Ghi chú tay không đúng format.

## Ghi chú khác
Không thuộc ticket nào.
"""


def row(**over):
    base = {
        "ticket": "DEMO-12",
        "q": "Q2",
        "date": "2026-11-15",
        "question": "割引は請求書にも適用されますか？",
        "decision": "Có, 請求書 cũng trừ giảm giá.",
        "quote": "はい、請求書にも適用してください。",
        "source": "https://demo.backlog.com/view/DEMO-12#comment-1010",
        "decided_by": "Customer",
        "approved_by": "Asher",
        "report": "DEMO-12-survey-r2.md",
    }
    return {**base, **over}


def test_parse_entries_quote_and_unparsed():
    parsed = decisions.parse(PAGE, RX)
    section = parsed["tickets"]["DEMO-12"]
    assert section["title"] == "注文確定画面の確認ダイアログ"
    (entry,) = section["entries"]
    assert entry["id"] == "D-DEMO-12-001" and entry["q"] == "Q1" and entry["active"]
    assert entry["fields"]["Quote"] == "確認ダイアログを表示してください。\nキャンセル時は画面をそのままにしてください。"
    assert entry["fields"]["Decided by"] == "BrSE (Tanaka)"
    assert [u["text"] for u in parsed["unparsed"]] == ["Ghi chú tay không đúng format."]


def test_append_keeps_existing_bytes_and_jp_text():
    new, result = decisions.append(PAGE, [row()], RX)
    assert result == {"added": ["D-DEMO-12-002"], "skipped": [], "superseded": []}
    assert new.startswith(PAGE.split("Ghi chú tay không đúng format.")[0])
    assert "## Ghi chú khác\nKhông thuộc ticket nào.\n" in new
    removed = [line for line in PAGE.splitlines() if line not in new.splitlines()]
    assert removed == []
    entry = decisions.parse(new, RX)["tickets"]["DEMO-12"]["entries"][1]
    assert entry["fields"]["Quote"] == "はい、請求書にも適用してください。"
    assert new.index("D-DEMO-12-002") < new.index("## Ghi chú khác")


def test_duplicate_is_skipped():
    once, _ = decisions.append(PAGE, [row()], RX)
    twice, result = decisions.append(once, [row()], RX)
    assert twice == once
    assert result["added"] == [] and len(result["skipped"]) == 1


def test_same_question_new_source_supersedes():
    first, _ = decisions.append(PAGE, [row(q="Q1", source="https://demo.backlog.com/view/DEMO-12#comment-2000")], RX)
    entries = decisions.parse(first, RX)["tickets"]["DEMO-12"]["entries"]
    assert entries[0]["fields"]["Status"] == "superseded by D-DEMO-12-002"
    assert not entries[0]["active"] and entries[1]["active"]
    from collections import Counter

    removed = Counter(PAGE.splitlines()) - Counter(first.splitlines())
    assert removed == Counter()  # the old Status line is replaced, and the new entry adds an active one
    old_entry = first[: first.index("### D-DEMO-12-002")]
    assert old_entry.count("- Status: superseded by D-DEMO-12-002") == 1
    assert "- Status: active" not in old_entry


def test_new_ticket_gets_its_own_section_with_title():
    new, result = decisions.append(PAGE, [row(ticket="DEMO-15", q="Q1", report="DEMO-15-survey-r1.md")], RX,
                                   {"DEMO-15": "ポイント利用"})
    assert result["added"] == ["D-DEMO-15-001"]
    assert "\n## DEMO-15 · ポイント利用\n\n### D-DEMO-15-001 · Q1\n" in new
    assert new.startswith(PAGE)


def test_crlf_page_keeps_crlf():
    crlf = PAGE.replace("\n", "\r\n")
    new, _ = decisions.append(crlf, [row()], RX)
    assert "\r\n" in new and "\n" not in new.replace("\r\n", "")
    assert new.startswith(crlf.split("Ghi chú tay")[0])


def test_empty_page():
    new, result = decisions.append("", [row()], RX, {"DEMO-12": "注文確定"})
    assert new.startswith("# Decisions — page\n\n## DEMO-12 · 注文確定\n\n### D-DEMO-12-001 · Q2\n")
    assert result["added"] == ["D-DEMO-12-001"]


@pytest.mark.parametrize("bad", [{"q": "3"}, {"ticket": "nope"}, {"quote": ""}, {"source": " "}])
def test_invalid_rows_are_refused(bad):
    with pytest.raises(decisions.DecisionsError):
        decisions.append(PAGE, [row(**bad)], RX)


def test_backlog_notation_is_refused():
    decisions.check_text_format("markdown")
    with pytest.raises(decisions.DecisionsError, match="Backlog notation"):
        decisions.check_text_format("backlog")


def active_ids(page, ticket="DEMO-12"):
    return [e["id"] for e in decisions.parse(page, RX)["tickets"][ticket]["entries"] if e["active"]]


def test_same_question_twice_in_one_batch_leaves_one_active():
    s1 = "https://demo.backlog.com/view/DEMO-12#comment-1"
    s2 = "https://demo.backlog.com/view/DEMO-12#comment-2"
    new, result = decisions.append("", [row(q="Q1", source=s1), row(q="Q1", source=s2)], RX)
    assert active_ids(new) == ["D-DEMO-12-002"]
    assert result["superseded"] == ["D-DEMO-12-001"]

    new, result = decisions.append(PAGE, [row(q="Q1", source=s1), row(q="Q1", source=s2)], RX)
    assert active_ids(new) == ["D-DEMO-12-003"]
    assert result["superseded"] == ["D-DEMO-12-001", "D-DEMO-12-002"]


def test_unicode_line_separators_and_mixed_eols_survive():
    page = "# T\r\nline\u2028more\n## DEMO-12 · x\n\n" + PAGE.split("## DEMO-12 · 注文確定画面の確認ダイアログ\n\n", 1)[1]
    new, _ = decisions.append(page, [row()], RX)
    assert new.startswith("# T\r\nline\u2028more\n## DEMO-12 · x\n")
    assert new.count("\r\n") == 1


def test_no_trailing_newline_is_kept():
    page = PAGE.rstrip("\n").split("\n\nGhi chú tay")[0]
    new, _ = decisions.append(page, [row()], RX)
    assert new.startswith(page + "\n")
    assert not new.endswith("\n")


@pytest.mark.parametrize(
    "broken",
    ["### D-DEMO-12-001 · Q1 (edited)", "## DEMO-99 · x\n\n### D-DEMO-12-005 · Q4"],
)
def test_broken_entry_headings_stop_the_append(broken):
    page = PAGE.replace("### D-DEMO-12-001 · Q1", broken)
    with pytest.raises(decisions.DecisionsError, match="do not follow the format"):
        decisions.append(page, [row()], RX)


def test_line_breaks_in_single_line_fields_are_refused():
    for bad in ({"decision": "a\nb"}, {"decision": "x\n- Status: superseded by X"}, {"source": "s\r\nt"}):
        with pytest.raises(decisions.DecisionsError, match="line breaks"):
            decisions.append(PAGE, [row(**bad)], RX)
    multi_quote, _ = decisions.append(PAGE, [row(quote="一行目\n二行目")], RX)
    assert "  > 一行目\n  > 二行目\n" in multi_quote


def test_entry_without_status_line_is_refused():
    page = PAGE.replace("- Status: active\n", "")
    with pytest.raises(decisions.DecisionsError, match="no '- Status:' line"):
        decisions.append(page, [row(q="Q1", source="https://demo.backlog.com/view/DEMO-12#comment-9")], RX)


def test_ticket_regex_with_groups_and_anchors():
    rx = r"^(DEMO|ABC)-\d+$"
    parsed = decisions.parse(PAGE, rx)
    assert parsed["tickets"]["DEMO-12"]["title"] == "注文確定画面の確認ダイアログ"
    new, result = decisions.append(PAGE, [row()], rx)
    assert result["added"] == ["D-DEMO-12-002"] and new.count("## DEMO-12") == 1


def test_inserted_block_is_separated_from_next_heading():
    page = PAGE.replace("Ghi chú tay không đúng format.\n\n", "")
    page = page.replace("- Status: active\n\n## Ghi chú khác", "- Status: active\n## Ghi chú khác")
    new, _ = decisions.append(page, [row()], RX)
    assert "- Status: active\n\n## Ghi chú khác" in new


def test_quote_check_statuses():
    from testign import decisions as d  # noqa: PLC0415

    rows = [{"ticket": "DEMO-1", "q": "Q1", "quote": "請求書にも\n適用します。", "source": "https://demo.backlog.com/view/DEMO-1#comment-7"},
            {"ticket": "DEMO-1", "q": "Q2", "quote": "全然違う", "source": "https://demo.backlog.com/view/DEMO-1#comment-7"},
            {"ticket": "DEMO-1", "q": "Q3", "quote": "x", "source": "https://other.backlog.com/view/DEMO-1#comment-7"},
            {"ticket": "DEMO-1", "q": "Q4", "quote": "x", "source": "meeting note 2026-11-20"},
            {"ticket": "DEMO-1", "q": "Q5", "quote": "x", "source": "https://demo.backlog.com/view/DEMO-1#comment-8"}]
    calls = []

    def read(key, cid):
        calls.append((key, cid))
        return "はい。請求書にも適用します。以上" if cid == "7" else None

    out = d.check_quotes(rows, "demo.backlog.com", read)
    assert [o["status"] for o in out] == ["verified", "mismatch", "unchecked", "unchecked", "missing"]
    assert calls == [("DEMO-1", "7"), ("DEMO-1", "8")]  # one read per comment
    assert d.quote_in("ＡＢＣ　です", "abc ABC です")  # width and spacing do not count
    assert not d.quote_in("", "anything")
    import pytest  # noqa: PLC0415
    with pytest.raises(d.DecisionsError, match="Q2: the quote is not in the linked comment; DEMO-1 Q5"):
        d.refuse_bad_quotes(out)
    d.refuse_bad_quotes([o for o in out if o["status"] in ("verified", "unchecked")])
