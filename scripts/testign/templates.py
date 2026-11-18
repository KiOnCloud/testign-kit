"""Registry of the tester's Excel test case templates, plus header detection and a text preview.

Registered templates are copied to ``~/.testign-kit/templates/`` with an ``index.json`` that maps a
tester-given name to the file, sheet, header row and column mapping. They are kept outside the
plugin folder on purpose: plugin updates replace that folder, and customer templates must never end
up in the public repository.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, fsutil

ROLES = ["no", "item", "steps", "expected", "evidence", "trace"]
REQUIRED_ROLES = ["item", "trace"]

HEADER_SYNONYMS: dict[str, list[str]] = {
    "no": ["no", "no.", "#", "番号", "項番", "stt", "tcid", "tc-id", "testcaseid", "id"],
    "item": [
        "確認項目", "テスト項目", "確認内容", "テスト内容", "項目", "観点", "description", "testitem",
        "item", "testcase", "mô tả", "nội dung", "hạng mục",
    ],
    "steps": ["手順", "操作手順", "テスト手順", "確認手順", "steps", "step", "procedure", "các bước", "thao tác"],
    "expected": ["期待結果", "期待値", "予想結果", "確認結果期待値", "expected", "expectedresult", "kết quả mong đợi"],
    "evidence": ["エビデンス", "証跡", "evidence", "bằng chứng"],
    "trace": ["備考", "remarks", "remark", "note", "notes", "ghi chú"],
}
HEADER_SCAN_ROWS = 30


class TemplateError(Exception):
    """A template cannot be registered, found or read. The message is meant for the tester."""


class TemplateNameTaken(TemplateError):
    """A template with this name is already registered and ``replace`` was not asked for."""


class TemplateMappingFailed(TemplateError):
    """The columns could not be mapped; ``headers`` holds the header cells that were found."""

    def __init__(self, message: str, headers: dict[str, str], missing: list[str]) -> None:
        super().__init__(message)
        self.headers = headers
        self.missing = missing


class TemplateFileClash(TemplateError):
    """The stored file name of this template already belongs to another template."""


def _openpyxl():
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError as exc:
        raise TemplateError(
            "openpyxl is not installed. Run: <python> -m pip install openpyxl (Python >= 3.10)"
        ) from exc
    return openpyxl


def templates_dir(home: Path | None = None) -> Path:
    return config.config_dir(home) / "templates"


def index_path(home: Path | None = None) -> Path:
    return templates_dir(home) / "index.json"


def load_index(home: Path | None = None) -> dict[str, Any]:
    path = index_path(home)
    if not path.exists():
        return {"default": None, "templates": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TemplateError(f"{path} is not valid JSON: {exc}") from exc
    data.setdefault("default", None)
    data.setdefault("templates", {})
    return data


def _save_index(data: dict[str, Any], home: Path | None = None) -> None:
    path = index_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _norm(value: Any) -> str:
    return re.sub(r"[\s_　]+", "", str(value or "")).lower()


def _role_for(header: Any) -> str | None:
    text = _norm(header)
    if not text:
        return None
    for role, names in HEADER_SYNONYMS.items():
        for name in names:
            n = _norm(name)
            if text == n or (len(n) > 2 and text.startswith(n)):
                return role
    return None


def _col_letter(index: int) -> str:
    return _openpyxl().utils.get_column_letter(index)


def _col_index(letter: str) -> int:
    try:
        return _openpyxl().utils.column_index_from_string(letter.strip().upper())
    except ValueError as exc:
        raise TemplateError(f"'{letter}' is not a column letter") from exc


def _scan_layout(sheets: list[tuple[str, list[tuple]]]) -> dict[str, Any]:
    """Pick sheet, header row and role mapping from the first rows (values only) of each sheet.

    The header row is the first row that has a 備考/Remarks-like header. When no sheet has one, the
    first sheet's row with the most text cells is guessed so the tester can map it.
    """
    for name, rows in sheets:
        for number, values in enumerate(rows, start=1):
            roles: dict[str, str] = {}
            headers: dict[str, str] = {}
            for col, value in enumerate(values, start=1):
                if value is None:
                    continue
                letter = _col_letter(col)
                headers[letter] = str(value)
                role = _role_for(value)
                if role and role not in roles:
                    roles[role] = letter
            if "trace" in roles:
                return {"sheet": name, "header_row": number, "columns": roles, "headers": headers}
    first_name, first_rows = sheets[0]
    best, best_number, best_count = None, None, 1
    for number, values in enumerate(first_rows, start=1):
        count = sum(1 for v in values if isinstance(v, str) and v.strip())
        if count > best_count:
            best, best_number, best_count = values, number, count
    if best is None:
        return {"sheet": first_name, "header_row": None, "columns": {}, "headers": {}}
    headers = {_col_letter(i): str(v) for i, v in enumerate(best, start=1) if v is not None}
    roles = {}
    for letter, text in headers.items():
        role = _role_for(text)
        if role and role not in roles:
            roles[role] = letter
    return {"sheet": first_name, "header_row": best_number, "columns": roles, "headers": headers}


def _sheet_rows(ws, max_rows: int) -> list[tuple]:
    return [tuple(row) for row in ws.iter_rows(min_row=1, max_row=max_rows, values_only=True)]


def detect_layout(path: Path, sheet: str | None = None) -> dict[str, Any]:
    """Find the sheet, header row and role → column letter mapping by header names.

    The header row is the first row (within the first 30) that has a 備考/Remarks-like header. When no
    sheet is given, the first sheet with such a row is used.
    """
    wb = _openpyxl().load_workbook(path)
    names = [sheet] if sheet else wb.sheetnames
    for name in names:
        if name not in wb.sheetnames:
            raise TemplateError(f"sheet '{name}' not found; sheets: {', '.join(wb.sheetnames)}")
    return _scan_layout([(n, _sheet_rows(wb[n], min(wb[n].max_row, HEADER_SCAN_ROWS))) for n in names])


def detect_layout_bounded(path: Path, sheet: str | None = None, max_rows: int = 50) -> dict[str, Any]:
    """Like ``detect_layout`` for an untrusted upload: read-only, at most ``max_rows`` rows per sheet."""
    wb = _openpyxl().load_workbook(path, read_only=True)
    try:
        names = [sheet] if sheet else wb.sheetnames
        for name in names:
            if name not in wb.sheetnames:
                raise TemplateError(f"sheet '{name}' not found; sheets: {', '.join(wb.sheetnames)}")
        scan = min(max_rows, HEADER_SCAN_ROWS)
        layout = _scan_layout([(n, _sheet_rows(wb[n], scan)) for n in names])
        layout["sheets"] = list(wb.sheetnames)
        return layout
    finally:
        wb.close()


def headers_at(path: Path, sheet: str, header_row: int) -> dict[str, str]:
    ws = _openpyxl().load_workbook(path)[sheet]
    return {c.column_letter: str(c.value) for c in ws[header_row] if c.value is not None}


def _slug(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", name, flags=re.UNICODE).strip("-")
    return slug or "template"


def register(
    file: Path,
    name: str,
    sheet: str | None = None,
    header_row: int | None = None,
    overrides: dict[str, str] | None = None,
    make_default: bool = False,
    replace: bool = False,
    home: Path | None = None,
    *,
    source_name: str | None = None,
) -> dict[str, Any]:
    """Copy ``file`` into the registry under ``name`` with its column mapping.

    ``source_name`` is the file name recorded for the template (default: ``file``'s own name); the
    console passes the name the tester uploaded.
    """
    file = Path(file).expanduser()
    if not file.exists():
        raise TemplateError(f"template file not found: {file}")
    if file.suffix.lower() not in (".xlsx", ".xlsm"):
        raise TemplateError("only .xlsx and .xlsm templates are supported")
    data = load_index(home)
    if name in data["templates"] and not replace:
        raise TemplateNameTaken(f"a template named '{name}' is already registered; pass --replace to update it")

    layout = detect_layout(file, sheet)
    if header_row:
        if not layout["sheet"]:
            raise TemplateError("pass --sheet together with --header-row when headers cannot be detected")
        layout["header_row"] = header_row
        layout["headers"] = headers_at(file, layout["sheet"], header_row)
        layout["columns"] = {r: c for c, h in layout["headers"].items() if (r := _role_for(h))}
    columns = dict(layout["columns"])
    for role, letter in (overrides or {}).items():
        if role not in ROLES:
            raise TemplateError(f"unknown role '{role}'; roles: {', '.join(ROLES)}")
        columns[role] = _col_letter(_col_index(letter))
    missing = [r for r in REQUIRED_ROLES if r not in columns]
    if not layout["sheet"] or not layout["header_row"] or missing:
        raise TemplateMappingFailed(
            "could not map the template columns automatically"
            + (f" (missing: {', '.join(missing)})" if missing else "")
            + f". Headers found: {json.dumps(layout['headers'], ensure_ascii=False)}. "
            "Pass --sheet, --header-row and --map role=COLUMN (roles: " + ", ".join(ROLES) + ").",
            headers=dict(layout["headers"]),
            missing=missing,
        )

    folder = templates_dir(home)
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{_slug(name)}{file.suffix.lower()}"
    old = data["templates"].get(name)
    if stored.exists() and (not old or old["file"] != stored.name):
        raise TemplateFileClash(f"{stored} already exists for another template; choose another name")
    # Copy to a temporary sibling and replace in one step, so a replaced template is never half written.
    tmp = fsutil.temp_sibling(stored)
    try:
        shutil.copyfile(file, tmp)
        fsutil.replace_retry(tmp, stored)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    entry = {
        "file": stored.name,
        "source_name": source_name or file.name,
        "sheet": layout["sheet"],
        "header_row": layout["header_row"],
        "columns": {r: columns[r] for r in ROLES if r in columns},
        "registered_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    data["templates"][name] = entry
    if make_default or not data["default"]:
        data["default"] = name
    _save_index(data, home)
    return {"name": name, "default": data["default"] == name, **entry, "path": str(stored)}


def resolve(name: str | None = None, home: Path | None = None) -> dict[str, Any]:
    """Return a registered template (the default when ``name`` is None) with its absolute path."""
    data = load_index(home)
    if not data["templates"]:
        raise TemplateError("no template registered yet; register one with template-register")
    key = name or data["default"]
    if key not in data["templates"]:
        raise TemplateError(f"template '{key}' is not registered; registered: {', '.join(data['templates'])}")
    entry = data["templates"][key]
    path = templates_dir(home) / entry["file"]
    if not path.exists():
        raise TemplateError(f"registered file for '{key}' is missing: {path}")
    return {"name": key, **entry, "path": str(path)}


def list_templates(home: Path | None = None) -> dict[str, Any]:
    data = load_index(home)
    return {
        "default": data["default"],
        "templates": [
            {"name": n, "default": n == data["default"], **e} for n, e in data["templates"].items()
        ],
    }


def set_default(name: str, home: Path | None = None) -> dict[str, Any]:
    data = load_index(home)
    if name not in data["templates"]:
        raise TemplateError(f"template '{name}' is not registered")
    data["default"] = name
    _save_index(data, home)
    return list_templates(home)


def remove(name: str, home: Path | None = None) -> dict[str, Any]:
    data = load_index(home)
    entry = data["templates"].pop(name, None)
    if entry is None:
        raise TemplateError(f"template '{name}' is not registered")
    (templates_dir(home) / entry["file"]).unlink(missing_ok=True)
    if data["default"] == name:
        data["default"] = next(iter(data["templates"]), None)
    _save_index(data, home)
    return list_templates(home)


def _cell_text(value: Any, width: int) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", "").replace("\n", "⏎").replace("|", "\\|")
    return text if len(text) <= width else text[: width - 1] + "…"


def preview(path: Path, sheet: str | None = None, header_row: int | None = None,
            columns: dict[str, str] | None = None, title: str | None = None,
            rows: int = 12, max_cols: int = 12, width: int = 24) -> str:
    """Render a template's layout as Markdown so it can be shown in chat without reading the xlsx."""
    wb = _openpyxl().load_workbook(path)
    if not sheet or not header_row:
        layout = detect_layout(path, sheet)
        sheet = sheet or layout["sheet"] or wb.sheetnames[0]
        header_row = header_row or layout["header_row"]
        columns = columns or layout["columns"]
    ws = wb[sheet]
    last_row = min(ws.max_row, max((header_row or 1) + rows, rows))
    last_col = min(ws.max_column, max_cols)
    letters = [_col_letter(i) for i in range(1, last_col + 1)]

    out = [f"### Template preview: {title or Path(path).name}", ""]
    out.append("**Sheets:** " + ", ".join(f"**{n}** (dùng)" if n == sheet else n for n in wb.sheetnames))
    out.append(f"**Header row:** {header_row or 'không tìm thấy'}")
    if columns:
        out += ["", "| Vai trò | Cột | Header |", "|---|---|---|"]
        heads = {c.column_letter: c.value for c in ws[header_row]} if header_row else {}
        for role in ROLES:
            if role in columns:
                out.append(f"| {role} | {columns[role]} | {_cell_text(heads.get(columns[role]), width)} |")
    out += ["", f"**{sheet}!A1:{letters[-1]}{last_row}**", ""]
    out.append("| # | " + " | ".join(letters) + " |")
    out.append("|---|" + "---|" * len(letters))
    for r in range(1, last_row + 1):
        values = [_cell_text(ws.cell(row=r, column=c).value, width) for c in range(1, last_col + 1)]
        marker = f"{r} ◀ header" if r == header_row else str(r)
        out.append(f"| {marker} | " + " | ".join(values) + " |")
    if ws.max_column > last_col or ws.max_row > last_row:
        out.append(f"\n_(sheet có {ws.max_row} dòng × {ws.max_column} cột; chỉ hiện phần đầu)_")
    merged = [str(m) for m in ws.merged_cells.ranges]
    if merged:
        out.append("\n**Merged:** " + ", ".join(merged[:15]) + (" …" if len(merged) > 15 else ""))
    dvs = [
        f"{dv.sqref} → {dv.formula1}" for dv in ws.data_validations.dataValidation if dv.type == "list"
    ]
    if dvs:
        out.append("**Dropdowns:** " + "; ".join(dvs[:10]))
    return "\n".join(out) + "\n"


def _grid_text(value: Any) -> str:
    return "" if value is None else str(value).replace("\r", "")


def preview_grid(path: Path, sheet: str | None = None, header_row: int | None = None,
                 columns: dict[str, str] | None = None, rows: int = 8, max_cols: int = 12) -> dict[str, Any]:
    """A template's layout as data for the console: header, a few rows, merged ranges, dropdowns.

    Rows run from the header row (row 1 when there is none) for at most ``rows`` rows.
    """
    wb = _openpyxl().load_workbook(path)
    if sheet and sheet not in wb.sheetnames:
        raise TemplateError(f"sheet '{sheet}' not found; sheets: {', '.join(wb.sheetnames)}")
    sheet = sheet or wb.sheetnames[0]
    ws = wb[sheet]
    columns = columns or {}
    last_col = min(ws.max_column, max_cols)
    letters = [_col_letter(i) for i in range(1, last_col + 1)]
    roles_by_letter = {letter: role for role, letter in columns.items()}
    heads = {c.column_letter: c.value for c in ws[header_row]} if header_row else {}
    first = header_row or 1
    last = min(ws.max_row, first + rows - 1)
    grid = [
        {"row": r, "header": r == header_row,
         "cells": [_grid_text(ws.cell(row=r, column=c).value) for c in range(1, last_col + 1)]}
        for r in range(first, last + 1)
    ]
    return {
        "sheet": sheet,
        "sheets": list(wb.sheetnames),
        "header_row": header_row,
        "letters": letters,
        "columns": [
            {"letter": letter, "header": _grid_text(heads.get(letter)), "role": roles_by_letter.get(letter)}
            for letter in letters
        ],
        "rows": grid,
        "size": {"rows": ws.max_row, "cols": ws.max_column},
        "merged": [str(m) for m in ws.merged_cells.ranges][:50],
        "dropdowns": [
            {"range": str(dv.sqref), "formula": dv.formula1}
            for dv in ws.data_validations.dataValidation if dv.type == "list"
        ][:20],
    }
