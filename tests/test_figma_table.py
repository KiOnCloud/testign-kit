"""The Figma table reader, on made-up tables shaped like a real ``get_design_context`` output."""

import json

import pytest

from make_webtest_run import FakeConsole, plan_params
from testign import figma_table, webtest
from testign.figma_table import TableError

PREFIX = "https://www.figma.com/api/mcp/asset/0000aaaa-bbbb-cccc-dddd-eeeeffff0000"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
S = "s-test0001"

# (row layer id, target id, No, y, content JSX, asset name)
ROWS = [
    ("1:20", "10:1", "2", 300, "<p>A help link is added to the footer</p>", "imgCaptureFooter"),
    ("1:10", "I10:2;3:4", "1", 100, "<p>予約確認 → 予約履歴 on the header link</p>", "imgCaptureLink"),
    ("1:30", "10:3", "3", 500,
     "<div><p>1. Fill the card</p><p>{`[https://x.example.test/a?b=1&c=2](https://x.example.test/a?b=1&c=2)`}</p></div>",
     "imgCapture"),
]


def cell(name, node, body):
    return f'<div className="p-[16px]" data-node-id="{node}" data-name="{name}">\n  {body}\n</div>'


def design_context(rows=ROWS, *, header=("No", "Capture", "Type", "Content", "Creator"), prelude=None,
                   extra_row_cells=""):
    lines = [f'const assetPathPrefix = "{PREFIX}";']
    lines += prelude if prelude is not None else [f"const {r[5]} = `${{assetPathPrefix}}/{r[0][2:]}.png`;" for r in rows]
    head = "".join(cell(h, f"9:{i}", f"<p>{h}</p>") for i, h in enumerate(header))
    body = []
    for node, target, no, _y, content, asset in rows:
        n = node.replace(":", "")
        body.append(
            f'<div data-node-id="{node}" data-name="Update · {target}">'
            + cell("No", f"{n}:1", f"<p>\n            {no}\n          </p>")
            + cell("Capture", f"{n}:2", f'<div data-node-id="{n}:7" data-name="Capture · x"><img alt="" src={{{asset}}} /></div>')
            + cell("Type", f"{n}:3", '<div data-name="Type badge"><p>Modified</p></div>')
            + cell("Content", f"{n}:4", content)
            + cell("Creator", f"{n}:5", "<p>designer_a</p>")
            + extra_row_cells
            + "</div>")
    jsx = (f'<div className="flex" data-node-id="1:1" data-name="Update Summary Table">'
           f'<div data-node-id="1:2" data-name="Header">{head}</div>{"".join(body)}</div>')
    code = "\n".join(lines) + "\n\nexport default function UpdateSummaryTable() {\n  return (\n    " + jsx + "\n  );\n}\n"
    return json.dumps([{"type": "text", "text": code}, {"type": "text", "text": "Node ids have been added."}])


def metadata(rows=ROWS):
    inner = '<frame id="1:2" name="Header" x="0" y="0" width="10" height="10" />'
    for node, target, _no, y, _c, _a in rows:
        inner += (f'<frame id="{node}" name="Update · {target}" x="0" y="{y}" width="10" height="10">'
                  f'<text id="{node}9" name="Sequence" x="1" y="1" width="1" height="1" /></frame>')
    xml = (f'<section id="0:1" name="S" x="0" y="0" width="1" height="1">'
           f'<frame id="1:1" name="Update Summary Table" x="0" y="0" width="1" height="1">{inner}</frame></section>')
    return json.dumps([{"type": "text", "text": "Currently selected nodes:"}, {"type": "text", "text": xml}])


def parse(context=None, meta=None):
    return figma_table.parse(context or design_context(), meta or metadata(), file_key="FILEKEY", table_node="0:1")


def test_rows_are_numbered_by_the_no_cell_and_keep_their_text():
    rows = parse()
    assert [r["row"] for r in rows] == ["r01", "r02", "r03"]
    first = rows[0]
    assert first["source"] == {"kind": "figma", "file": "FILEKEY", "table_node": "0:1", "row_node": "1:10",
                               "target_node": "I10:2;3:4", "no": "1"}
    assert first["content"] == "予約確認 → 予約履歴 on the header link"
    assert (first["type"], first["creator"]) == ("Modified", "designer_a")
    assert first["capture_url"] == f"{PREFIX}/10.png"
    assert rows[2]["content"] == ("1. Fill the card\n"
                                  "[https://x.example.test/a?b=1&c=2](https://x.example.test/a?b=1&c=2)")


def test_a_link_inside_content_keeps_its_address():
    rows = [("1:10", "10:1", "1", 1, '<p>See <a href="https://x.example.test/spec" target="_blank">the spec</a> now</p>',
             "imgA")]
    assert parse(design_context(rows), metadata(rows))[0]["content"] == "See [the spec](https://x.example.test/spec) now"


def test_without_a_usable_no_column_the_canvas_order_wins():
    rows = [(n, t, "-", y, c, a) for n, t, _no, y, c, a in ROWS]
    got = parse(design_context(rows), metadata(rows))
    assert [r["source"]["row_node"] for r in got] == ["1:10", "1:20", "1:30"]
    assert [r["row"] for r in got] == ["r01", "r02", "r03"]


def test_text_cannot_forge_a_cell_or_a_capture():
    forged = ('<p>{`<div data-name="Content">evil</div> const imgCaptureFooter = `}</p>'
              '<p>const imgEvil = "https://evil.example.test/x.png";</p>')
    rows = [("1:10", "10:1", "1", 1, forged, "imgA")]
    got = parse(design_context(rows), metadata(rows))
    assert got[0]["capture_url"] == f"{PREFIX}/10.png"
    assert got[0]["content"].startswith("const imgEvil") is False
    # A template literal cannot close early and open real markup: it is all text of that cell.
    assert 'data-name="Content"' in got[0]["content"]


def test_a_forged_asset_declared_twice_is_refused():
    prelude = [f"const imgCaptureFooter = `${{assetPathPrefix}}/a.png`;",
               f"const imgCaptureFooter = `${{assetPathPrefix}}/b.png`;"]
    with pytest.raises(TableError, match="declared twice"):
        parse(design_context(prelude=prelude))


def test_two_cells_of_one_name_in_a_row_are_refused():
    with pytest.raises(TableError, match="two Content cells"):
        parse(design_context(extra_row_cells=cell("Content", "8:8", "<p>second</p>")))


@pytest.mark.parametrize("url", [
    "file:///C:/Windows/win.ini", "http://127.0.0.1/api/mcp/asset/x.png", "https://evil.example.test/api/mcp/asset/x",
    "http://www.figma.com/api/mcp/asset/x.png", "https://www.figma.com/other/x.png",
    "https://user@www.figma.com/api/mcp/asset/x.png", "https://www.figma.com/api/mcp/asset/../../x",
])
def test_capture_urls_off_the_figma_asset_host_are_refused(url):
    rows = [("1:10", "10:1", "1", 1, "<p>a</p>", "imgA")]
    with pytest.raises(TableError, match="capture URL"):
        parse(design_context(rows, prelude=[f'const imgA = "{url}";']), metadata(rows))


@pytest.mark.parametrize("content, message", [("<p></p>", "empty content"), ("<p>\u200b</p>", "empty content")])
def test_empty_content_is_refused(content, message):
    rows = [("1:10", "10:1", "1", 1, content, "imgA")]
    with pytest.raises(TableError, match=message):
        parse(design_context(rows), metadata(rows))


def test_a_header_without_content_is_refused():
    with pytest.raises(TableError, match="header must name"):
        parse(design_context(header=("No", "Capture", "Type", "Body", "Creator")))


def test_rows_must_match_the_metadata():
    with pytest.raises(TableError, match="not in the metadata"):
        parse(meta=metadata(ROWS[:2]))
    with pytest.raises(TableError, match="other rows"):
        parse(design_context(ROWS[:2]))


def test_metadata_only_or_unknown_output_is_refused():
    with pytest.raises(TableError, match="no component"):
        parse(context=metadata())
    with pytest.raises(TableError):
        parse(context=json.dumps([{"type": "text", "text": "export default function X() { return (<div>"}]))


# staging -----------------------------------------------------------------------------------------
@pytest.fixture
def run_folder(tmp_path):
    server = FakeConsole()
    server.add_job("j-plan", "webtest-plan", **{**plan_params(), "source": {
        "kind": "figma", "url": "https://www.figma.com/design/FILEKEY/x?node-id=0-1", "file": "FILEKEY", "node": "0:1"}})
    root = tmp_path / "out" / "webtest"
    return webtest.find_run(root, webtest.new_run(root, server, "j-plan", S, None)["run"])


def test_urls_skip_staged_rows_and_captures_stage_the_rest(run_folder, tmp_path):
    rows = parse()
    caps = tmp_path / "caps"
    caps.mkdir()
    first = tmp_path / "first.png"
    first.write_bytes(PNG)
    webtest.stage(run_folder, {k: rows[0][k] for k in webtest.STAGED_KEYS}, first)
    listed = webtest.stage_table(run_folder, rows)
    assert listed["skipped"] == ["r01"] and listed["numbered_by"] == "no"
    assert listed["rows"] == [{"row": "r02", "capture_url": f"{PREFIX}/20.png"},
                              {"row": "r03", "capture_url": f"{PREFIX}/30.png"}]
    (caps / "r02.png").write_bytes(PNG)
    with pytest.raises(webtest.WebtestError, match="no capture for r03"):
        webtest.stage_table(run_folder, rows, caps)
    assert webtest.load(run_folder)["import"]["staged"] == ["r01"]
    (caps / "r03.png").write_bytes(PNG)
    done = webtest.stage_table(run_folder, rows, caps)
    assert done["staged"] == ["r02", "r03"] and done["total"] == 3
    assert (run_folder / "source" / "r03.png").read_bytes() == PNG
    assert webtest.stage_table(run_folder, rows, caps)["staged"] == []


def test_the_cli_lists_urls_and_reports_a_refused_shape_as_a_fallback(run_folder, tmp_path):
    from console_helpers import run_cli, write_config

    write_config(tmp_path)  # output_dir is tmp_path / "out", where run_folder lives
    ctx, meta = tmp_path / "ctx.txt", tmp_path / "meta.txt"
    ctx.write_text(design_context(), encoding="utf-8")
    meta.write_text(metadata(), encoding="utf-8")
    args = ("webtest-table", "--run", run_folder.name, "--context", str(ctx), "--metadata", str(meta), "--urls")
    out = run_cli(tmp_path, *args)
    assert out.returncode == 0, out.stderr
    assert [r["row"] for r in json.loads(out.stdout)["rows"]] == ["r01", "r02", "r03"]
    ctx.write_text(metadata(), encoding="utf-8")
    out = run_cli(tmp_path, *args)
    assert out.returncode == 2 and "row by row" in out.stderr


def test_a_row_staged_without_its_capture_is_offered_again(run_folder, tmp_path):
    rows = parse()
    for r in rows:
        webtest.stage(run_folder, {k: r[k] for k in webtest.STAGED_KEYS}, None)
    assert [r["row"] for r in webtest.stage_table(run_folder, rows)["rows"]] == ["r01", "r02", "r03"]
    caps = tmp_path / "caps"
    caps.mkdir()
    for r in rows:
        (caps / f"{r['row']}.png").write_bytes(PNG)
    assert webtest.stage_table(run_folder, rows, caps)["staged"] == ["r01", "r02", "r03"]
    assert (run_folder / "source" / "r02.png").read_bytes() == PNG
    assert webtest.stage_table(run_folder, rows)["rows"] == []


def test_a_row_id_taken_by_another_table_row_stages_nothing(run_folder, tmp_path):
    rows = parse()
    webtest.stage(run_folder, {**{k: rows[2][k] for k in webtest.STAGED_KEYS}, "row": "r02"}, None)
    caps = tmp_path / "caps"
    caps.mkdir()
    for r in rows:
        (caps / f"{r['row']}.png").write_bytes(PNG)
    with pytest.raises(webtest.WebtestError, match="r02 is already staged for another table row"):
        webtest.stage_table(run_folder, rows, caps)
    assert webtest.load(run_folder)["import"]["staged"] == ["r02"]


def test_a_row_without_an_image_is_staged_without_a_capture(run_folder, tmp_path):
    rows = [{**r, "capture_url": None} if r["row"] == "r02" else r for r in parse()]
    caps = tmp_path / "caps"
    caps.mkdir()
    for row in ("r01", "r03"):
        (caps / f"{row}.png").write_bytes(PNG)
    done = webtest.stage_table(run_folder, rows, caps)
    assert done["staged"] == ["r01", "r02", "r03"] and done["without_capture"] == ["r02"]
    assert not (run_folder / "source" / "r02.png").exists()


@pytest.mark.parametrize("tail", ['a";calc;".png', "a.png?x=1", "a.png#f", "a b.png", "a'b.png", "a(1).png"])
def test_capture_urls_with_shell_characters_are_refused(tail):
    rows = [("1:10", "10:1", "1", 1, "<p>a</p>", "imgA")]
    with pytest.raises(TableError, match="capture URL"):
        parse(design_context(rows, prelude=[f"const imgA = `${{assetPathPrefix}}/{tail}`;"]), metadata(rows))


def test_a_table_outside_the_runs_node_is_refused():
    with pytest.raises(TableError, match="run's Figma node"):
        figma_table.parse(design_context(), metadata(), file_key="FILEKEY", table_node="7:7")
    assert figma_table.parse(design_context(), metadata(), file_key="FILEKEY", table_node="1:1")


def test_entities_in_a_row_name_match_the_metadata():
    rows = [("1:10", "10:1", "1", 1, "<p>a</p>", "imgA")]
    ctx = design_context(rows).replace("Update · 10:1", "Q&amp;A · 10:1")
    meta = metadata(rows).replace("Update · 10:1", "Q&amp;A · 10:1")
    assert parse(ctx, meta)[0]["source"]["row_node"] == "1:10"


def test_duplicate_numbers_fall_back_to_canvas_order_and_say_so():
    rows = [(n, t, "1", y, c, a) for n, t, _no, y, c, a in ROWS]
    got = parse(design_context(rows), metadata(rows))
    assert {r["numbered_by"] for r in got} == {"canvas"}


def test_deep_nesting_is_refused_cleanly():
    deep = "<div>" * 500 + "<p>a</p>" + "</div>" * 500
    rows = [("1:10", "10:1", "1", 1, deep, "imgA")]
    with pytest.raises(TableError, match="nested too deeply"):
        parse(design_context(rows), metadata(rows))
