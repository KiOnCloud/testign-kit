"""Fill a copy of an Excel test case template and read trace IDs back from it.

The template file is only ever read. Output always goes to a new file name; when the tester points at
an already filled workbook, the new cases go into a new sheet ``TC-<stamp>`` of a copy of it.
"""

from __future__ import annotations

import contextlib
import copy
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from .templates import TemplateError, _col_index, _openpyxl

TRACE_ID_RE = re.compile(r"\b([BR]\d+)\b")
QUESTION_ID_RE = re.compile(r"\b(Q\d+)\b")
SAMPLE_SHEET = "テストケース"


@contextlib.contextmanager
def _editable(path: Path) -> Iterator[Any]:
    """Load ``path`` for writing a copy, keeping the macros of an .xlsm.

    openpyxl keeps an .xlsm's macro parts in an in-memory zip it never closes; closing it here keeps
    it from failing later when the garbage collector frees its buffer first.
    """
    wb = _openpyxl().load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm")
    try:
        yield wb
    finally:
        archive = getattr(wb, "vba_archive", None)
        if archive is not None:
            archive.close()


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M")


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.stem}-{n}{path.suffix}")).exists():
        n += 1
    return candidate


def trace_text(case: dict) -> str:
    ids = ", ".join(case["trace"])
    waiting = case.get("waiting_on") or []
    return f"{ids} (chờ {', '.join(waiting)})" if waiting else ids


def validate_cases(cases: list[dict]) -> None:
    if not isinstance(cases, list) or not cases:
        raise TemplateError("cases must be a non-empty JSON list")
    for i, case in enumerate(cases, 1):
        trace = case.get("trace")
        if not isinstance(trace, list) or not any(TRACE_ID_RE.fullmatch(str(t)) for t in trace):
            raise TemplateError(f"case {i} has no B*/R* ID in 'trace'; every case must trace to a report row")
        if not case.get("item"):
            raise TemplateError(f"case {i} has no 'item'")


def _first_free_row(ws, header_row: int, columns: dict[str, str]) -> int:
    """First row below the header after any content already in the mapped columns.

    The No column and formulas are ignored, because templates often prefill numbering formulas far
    below the header.
    """
    idx = [_col_index(c) for role, c in columns.items() if role != "no"]
    last = header_row
    for r in range(header_row + 1, ws.max_row + 1):
        if any(_has_content(ws.cell(row=r, column=c).value) for c in idx):
            last = r
    return last + 1


def _has_content(value: Any) -> bool:
    if value in (None, ""):
        return False
    return not (isinstance(value, str) and value.startswith("="))


def _write_rows(ws, header_row: int, columns: dict[str, str], rows: list[dict[str, Any]],
                literal: bool = False) -> list[int]:
    """Write one sheet row per ``rows`` item: ``columns`` maps a key to a letter, each item a key to a value.

    The style of the first data row is copied to every written row. The ``no`` key keeps a numbering
    formula already in the template, and counts from 1 below the header when an item has no ``no``.
    With ``literal``, text starting with ``=`` is stored as text, never as a formula: it comes from
    outside (a design table, a web page) and Excel would run it on open.
    """
    style_row = header_row + 1
    start = _first_free_row(ws, header_row, columns)
    written = []
    for offset, values in enumerate(rows):
        r = start + offset
        for c in range(1, ws.max_column + 1):
            src, dst = ws.cell(row=style_row, column=c), ws.cell(row=r, column=c)
            if r != style_row and src.has_style:
                dst._style = copy.copy(src._style)
        for key, letter in columns.items():
            cell = ws.cell(row=r, column=_col_index(letter))
            if key == "no" and isinstance(cell.value, str) and cell.value.startswith("="):
                continue  # keep the template's numbering formula
            value = values.get(key) if key != "no" or "no" in values else start - header_row + offset
            if value not in (None, ""):
                cell.value = value
                if literal and isinstance(value, str) and value.startswith("="):
                    cell.data_type = "s"
        written.append(r)
    return written


def _role_values(cases: list[dict]) -> list[dict[str, Any]]:
    out = []
    for case in cases:
        values = {"item": case.get("item"), "steps": case.get("steps"), "expected": case.get("expected"),
                  "evidence": case.get("evidence"), "trace": trace_text(case)}
        if "no" in case:
            values["no"] = case["no"]
        out.append(values)
    return out


def fill_copy(template: Path, layout: dict, cases: list[dict], out_path: Path) -> dict[str, Any]:
    """Load ``template`` (never saved), write ``cases`` into its mapped sheet and save to a new file."""
    validate_cases(cases)
    template = Path(template)
    with _editable(template) as wb:
        if layout["sheet"] not in wb.sheetnames:
            raise TemplateError(f"sheet '{layout['sheet']}' not found in {template.name}")
        rows = _write_rows(wb[layout["sheet"]], layout["header_row"], layout["columns"], _role_values(cases))
        out = _unique(Path(out_path).with_suffix(template.suffix.lower()))
        out.parent.mkdir(parents=True, exist_ok=True)
        wb.save(out)
    return {"path": str(out), "sheet": layout["sheet"], "rows": rows}


def fill_placeholders(wb, values: dict[str, str]) -> int:
    """Replace every cell whose whole value is one of ``values``' keys, on every sheet; returns the count.

    The new value is stored as text (never a formula), and an empty value clears the cell. A cell
    holding anything else, such as a customer template's own text around a placeholder, is untouched.
    """
    count = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.strip() in values:
                    text = values[cell.value.strip()]
                    cell.value = text or None
                    if text:
                        cell.data_type = "s"
                    count += 1
    return count


def fill_columns(template: Path, sheet: str, header_row: int, columns: dict[str, str], rows: list[dict[str, Any]],
                 out_path: Path, new_headers: dict[str, str] | None = None, *,
                 placeholders: dict[str, str] | None = None, links: list[str | None] | None = None,
                 link_key: str | None = None) -> dict[str, Any]:
    """Like ``fill_copy`` with the values per column given by the caller.

    ``new_headers`` (letter → text) adds header cells to the copy, styled like the last header cell
    that already holds text. ``placeholders`` replaces whole-cell placeholders on every sheet
    (``fill_placeholders``). ``links`` gives, per row, a relative file target set as the hyperlink of
    that row's ``link_key`` cell, whose value stays as written. The template file is only read.
    """
    template = Path(template)
    with _editable(template) as wb:
        if sheet not in wb.sheetnames:
            raise TemplateError(f"sheet '{sheet}' not found in {template.name}")
        ws = wb[sheet]
        if new_headers:
            filled = [c for c in ws[header_row] if c.value not in (None, "")]
            style = filled[-1]._style if filled else None
            for letter, text in new_headers.items():
                cell = ws.cell(row=header_row, column=_col_index(letter))
                cell.value = text
                if style is not None:
                    cell._style = copy.copy(style)
        if placeholders:
            fill_placeholders(wb, placeholders)
        written = _write_rows(ws, header_row, columns, rows, literal=True)
        if links and link_key in columns:
            for r, target in zip(written, links):
                if target:
                    ws.cell(row=r, column=_col_index(columns[link_key])).hyperlink = target
        out = _unique(Path(out_path).with_suffix(template.suffix.lower()))
        out.parent.mkdir(parents=True, exist_ok=True)
        wb.save(out)
    return {"path": str(out), "sheet": sheet, "rows": written}


def append_table_sheet(workbook: Path, sheet_name: str, rows: list[list[Any]]) -> str:
    """Add a plain sheet of ``rows`` to a workbook this plugin just wrote (an export, never the
    template). Text starting with ``=`` stays text. Returns the sheet name used."""
    workbook = Path(workbook)
    with _editable(workbook) as wb:
        name, n = sheet_name, 2
        while name in wb.sheetnames:
            name, n = f"{sheet_name}-{n}", n + 1
        ws = wb.create_sheet(name)
        for r, values in enumerate(rows, start=1):
            for c, value in enumerate(values, start=1):
                if value in (None, ""):
                    continue
                cell = ws.cell(row=r, column=c, value=value)
                if isinstance(value, str) and value.startswith("="):
                    cell.data_type = "s"
        for letter, width in zip("ABCDEFG", (12, 32, 40, 14, 12, 16, 48)):
            ws.column_dimensions[letter].width = width
        wb.save(workbook)
    return name


def add_sheet(workbook: Path, layout: dict, cases: list[dict], sheet_name: str) -> dict[str, Any]:
    """Copy the filled ``workbook`` to a new file and add a sheet with ``cases``.

    The new sheet starts as a copy of the mapped sheet with its data rows cleared, so it keeps the
    template's header, widths and formatting. Existing sheets are not changed.
    """
    validate_cases(cases)
    workbook = Path(workbook)
    with _editable(workbook) as wb:
        if layout["sheet"] not in wb.sheetnames:
            raise TemplateError(f"sheet '{layout['sheet']}' not found in {workbook.name}")
        name, n = sheet_name, 2
        while name in wb.sheetnames:
            name, n = f"{sheet_name}-{n}", n + 1
        ws = wb.copy_worksheet(wb[layout["sheet"]])
        ws.title = name
        idx = [_col_index(c) for c in layout["columns"].values()]
        for r in range(layout["header_row"] + 1, ws.max_row + 1):
            for c in idx:
                ws.cell(row=r, column=c).value = None
        rows = _write_rows(ws, layout["header_row"], layout["columns"], _role_values(cases))
        out = _unique(workbook.with_name(f"{workbook.stem}-{name}{workbook.suffix}"))
        wb.save(out)
    return {"path": str(out), "sheet": name, "rows": rows}


def pick_sheet(path: Path, layout: dict, sheet: str | None = None) -> str:
    """The sheet to trace: the given one, else the newest ``TC-*`` sheet, else the mapped sheet."""
    wb = _openpyxl().load_workbook(path, read_only=True)
    try:
        names = list(wb.sheetnames)
    finally:
        wb.close()
    if sheet:
        if sheet not in names:
            raise TemplateError(f"sheet '{sheet}' not found; sheets: {', '.join(names)}")
        return sheet
    tc = sorted(n for n in names if n.startswith("TC-"))
    return tc[-1] if tc else layout["sheet"]


def read_trace(path: Path, layout: dict, sheet: str | None = None) -> list[dict]:
    """Test case rows of a filled workbook with the B*/R* and Q IDs found in the trace column."""
    name = pick_sheet(path, layout, sheet)
    wb = _openpyxl().load_workbook(path, data_only=True)
    if name not in wb.sheetnames:
        raise TemplateError(f"sheet '{name}' not found in {Path(path).name}; sheets: {', '.join(wb.sheetnames)}")
    ws = wb[name]
    cols = {role: _col_index(letter) for role, letter in layout["columns"].items()}
    cases = []
    for r in range(layout["header_row"] + 1, ws.max_row + 1):
        item = ws.cell(row=r, column=cols["item"]).value
        note = ws.cell(row=r, column=cols["trace"]).value
        if item in (None, "") and note in (None, ""):
            continue
        no = ws.cell(row=r, column=cols["no"]).value if "no" in cols else None
        note = "" if note is None else str(note)
        cases.append(
            {
                "row": r,
                "id": str(no) if no not in (None, "") else f"row {r}",
                "item": "" if item is None else str(item),
                "trace": list(dict.fromkeys(TRACE_ID_RE.findall(note))),
                "questions": list(dict.fromkeys(QUESTION_ID_RE.findall(note))),
            }
        )
    return cases


def build_sample(path: Path) -> Path:
    """Write the basic made-up template shipped with the plugin (cover sheet + case sheet)."""
    opx = _openpyxl()
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: PLC0415
    from openpyxl.worksheet.datavalidation import DataValidation  # noqa: PLC0415

    wb = opx.Workbook()
    cover = wb.active
    cover.title = "表紙"
    cover["B2"] = "テスト仕様書（サンプル）"
    cover["B2"].font = Font(size=16, bold=True)
    for i, (label, value) in enumerate(
        [("プロジェクト", "<project>"), ("チケット", "<TICKET-ID>"), ("作成者", "<tester>"), ("作成日", "<YYYY-MM-DD>")],
        start=4,
    ):
        cover.cell(row=i, column=2, value=label).font = Font(bold=True)
        cover.cell(row=i, column=3, value=value)
    cover.column_dimensions["B"].width = 16
    cover.column_dimensions["C"].width = 32

    ws = wb.create_sheet(SAMPLE_SHEET)
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DDEBF7")
    ws.merge_cells("A1:H1")
    ws["A1"] = "テストケース一覧"
    ws["A1"].font = Font(size=14, bold=True)
    ws["A2"] = "チケット:"
    ws["B2"] = "<TICKET-ID>"
    headers = ["No", "確認項目", "手順", "期待結果", "エビデンス", "結果", "実施日", "備考"]
    widths = [6, 36, 44, 40, 18, 8, 12, 24]
    for c, (title, width) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=4, column=c, value=title)
        cell.font = Font(bold=True)
        cell.fill = head_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[cell.column_letter].width = width
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=5, column=c)
        cell.border = border
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    dv = DataValidation(type="list", formula1='"OK,NG,保留,対象外"', allow_blank=True)
    dv.add("F5:F500")
    ws.add_data_validation(dv)
    ws.freeze_panes = "A5"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
