"""Template management for the console: uploads, registration under one lock, grid previews.

An upload is checked before openpyxl opens it: extension, zip signature and the zip's totals
(uncompressed size and compression ratio). It is stored as ``uploads/<id>/<original base name>``,
read for its layout (first rows only), and deleted after registration or after an hour.
"""

from __future__ import annotations

import io
import secrets
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .. import templates
from . import lifecycle
from .server import ApiError, ConsoleState, Request

UPLOAD_CAP = 10 * 1024 * 1024
UNZIPPED_CAP = 200 * 1024 * 1024
ENTRY_CAP = 20 * 1024 * 1024
RATIO_CAP = 100
RATIO_FLOOR = 64 * 1024  # entries smaller than this may compress better (empty styles, shared strings)
UPLOAD_TTL = 3600.0
SWEEP_EVERY = 3600.0
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

# Every template change from the server runs under this lock.
LOCK = threading.Lock()


def uploads_dir(home: Path | None) -> Path:
    return lifecycle.console_dir(home) / "uploads"


def decode_filename(header: str | None) -> str:
    """Decode ``X-Filename: UTF-8''<percent-encoded>`` (RFC 5987) to a safe base name."""
    if not header or not header.lower().startswith("utf-8''"):
        raise ApiError(400, "bad-filename", "X-Filename must be UTF-8''<percent-encoded name>")
    try:
        name = unquote(header[7:], encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ApiError(400, "bad-filename", "file name is not UTF-8") from None
    if (
        not name
        or len(name) > 200
        or "/" in name
        or "\\" in name
        or name in (".", "..")
        or any(ord(c) < 32 or c in '<>:"|?*' for c in name)
        or name.endswith((" ", "."))
    ):
        raise ApiError(400, "bad-filename", "file name is not allowed")
    stem = name.split(".")[0].upper()
    if stem in RESERVED:
        raise ApiError(400, "bad-filename", "file name is a reserved device name")
    if Path(name).suffix.lower() not in (".xlsx", ".xlsm"):
        raise ApiError(400, "bad-extension", "only .xlsx and .xlsm templates are supported")
    return name


def check_zip(data: bytes) -> None:
    """Refuse anything that is not a zip, or that expands past the size or ratio caps."""
    if not data.startswith(b"PK\x03\x04"):
        raise ApiError(400, "not-a-workbook", "the file is not an Excel workbook")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise ApiError(400, "not-a-workbook", "the file is not an Excel workbook") from None
    unzipped = sum(i.file_size for i in infos)
    if unzipped > UNZIPPED_CAP or any(i.file_size > ENTRY_CAP for i in infos):
        raise ApiError(400, "too-large-unzipped", "the workbook expands past the size limit")
    for info in infos:
        # Checked per entry: padding the zip with stored data must not hide one huge sheet.
        if info.file_size > RATIO_FLOOR and info.file_size > RATIO_CAP * max(info.compress_size, 1):
            raise ApiError(400, "zip-ratio", "the workbook compresses suspiciously well")
    if not any(i.filename == "[Content_Types].xml" for i in infos):
        raise ApiError(400, "not-a-workbook", "the file is not an Excel workbook")


def sweep(home: Path | None, now: float | None = None) -> int:
    """Delete upload folders older than an hour; returns how many were removed."""
    root = uploads_dir(home)
    now = time.time() if now is None else now
    removed = 0
    try:
        folders = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return 0
    for folder in folders:
        try:
            if now - folder.stat().st_mtime > UPLOAD_TTL:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _upload_file(home: Path | None, upload_id: Any) -> Path:
    """The single file of an upload, found by listing the uploads folder."""
    if not isinstance(upload_id, str):
        raise ApiError(400, "bad-request", "upload id required")
    folders = {p.name: p for p in uploads_dir(home).iterdir() if p.is_dir()} if uploads_dir(home).is_dir() else {}
    folder = folders.get(upload_id)
    if folder is None:
        raise ApiError(404, "not-found", "no such upload (it may have expired)")
    files = [p for p in folder.iterdir() if p.is_file()]
    if len(files) != 1:
        raise ApiError(404, "not-found", "no such upload")
    return files[0]


def _template_names(home: Path | None) -> set[str]:
    return {t["name"] for t in templates.list_templates(home)["templates"]}


def _layout_view(layout: dict) -> dict:
    return {k: layout.get(k) for k in ("sheet", "header_row", "columns", "headers")}


def upload(home: Path | None, filename_header: str | None, data: bytes) -> dict:
    name = decode_filename(filename_header)
    check_zip(data)
    upload_id = secrets.token_hex(8)
    folder = uploads_dir(home) / upload_id
    folder.mkdir(mode=0o700, parents=True)
    path = folder / name
    lifecycle.write_secure(path, data)
    try:
        layout = templates.detect_layout_bounded(path)
        grid = templates.preview_grid(path, layout["sheet"], layout["header_row"], layout["columns"], full=False)
    except Exception:  # noqa: BLE001 - openpyxl raises many types for broken files
        shutil.rmtree(folder, ignore_errors=True)
        raise ApiError(400, "not-a-workbook", "the workbook cannot be read") from None
    return {
        "upload": upload_id,
        "name": name,
        "sheets": layout.get("sheets", []),
        "layout": _layout_view(layout),
        "preview": grid,
    }


def upload_preview(home: Path | None, upload_id: str, sheet: str | None, header_row: int | None) -> dict:
    """Layout and grid for another sheet or header row of an upload, before registering it."""
    path = _upload_file(home, upload_id)
    try:
        layout = templates.detect_layout_bounded(path, sheet)
        if header_row:
            layout["header_row"] = header_row
            grid = templates.preview_grid(path, layout["sheet"], header_row, None, full=False)
            layout["headers"] = {c["letter"]: c["header"] for c in grid["columns"] if c["header"]}
            layout["columns"] = {}
            for letter, text in layout["headers"].items():
                role = templates._role_for(text)
                if role and role not in layout["columns"]:
                    layout["columns"][role] = letter
        grid = templates.preview_grid(path, layout["sheet"], layout["header_row"], layout["columns"], full=False)
    except templates.TemplateError:
        raise ApiError(400, "template-error", "that sheet is not in the workbook") from None
    return {"upload": upload_id, "name": path.name, "sheets": layout.get("sheets", []),
            "layout": _layout_view(layout), "preview": grid}


def register(home: Path | None, body: dict) -> dict:
    path = _upload_file(home, body.get("upload"))
    name = body.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ApiError(400, "bad-request", "a template name of 1 to 100 characters is required")
    sheet = body.get("sheet")
    header_row = body.get("header_row")
    mapping = body.get("map") or {}
    if sheet is not None and not isinstance(sheet, str):
        raise ApiError(400, "bad-request", "sheet must be text")
    if header_row is not None and (not isinstance(header_row, int) or isinstance(header_row, bool) or header_row < 1):
        raise ApiError(400, "bad-request", "header_row must be a positive number")
    if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
        raise ApiError(400, "bad-request", "map must be an object of role to column letter")
    purpose = body.get("purpose") or "testcase"
    if purpose not in templates.PURPOSES:
        raise ApiError(400, "bad-request", "purpose must be testcase or webtest")
    with LOCK:
        try:
            entry = templates.register(
                path, name.strip(), sheet=sheet, header_row=header_row, overrides=mapping,
                make_default=bool(body.get("make_default")), replace=bool(body.get("replace")),
                home=home, source_name=path.name, bounded=True, purpose=purpose,
            )
        except templates.TemplateNameTaken:
            raise ApiError(409, "name-taken", "a template with this name is already registered") from None
        except templates.TemplateFileClash:
            raise ApiError(409, "file-clash", "another template already uses this name's file") from None
        except templates.TemplateMappingFailed as exc:
            raise ApiError(400, "mapping-failed", "the columns could not be mapped",
                           details={"headers": exc.headers, "missing": exc.missing}) from None
        except templates.TemplateError:
            raise ApiError(400, "template-error", "the template cannot be registered") from None
    shutil.rmtree(path.parent, ignore_errors=True)
    entry.pop("path", None)
    return {"template": entry, **templates.list_templates(home)}


def install(state: ConsoleState) -> None:
    home = state.home
    lifecycle.ensure_state_dirs(home)
    sweep(home)

    stopped = threading.Event()
    state.shutdown_hooks.append(stopped.set)

    def sweeper() -> None:
        while not stopped.wait(SWEEP_EVERY):
            sweep(home)

    threading.Thread(target=sweeper, daemon=True).start()

    def known(req: Request) -> str:
        name = req.params["name"]
        if name not in _template_names(home):
            raise ApiError(404, "not-found", "no such template")
        return name

    def get_list(req: Request) -> dict:
        listing = templates.list_templates(home)
        for t in listing["templates"]:
            t.pop("path", None)
        return listing

    def get_preview(req: Request) -> dict:
        name = known(req)
        try:
            entry = templates.resolve(name, home)
            return templates.preview_grid(Path(entry["path"]), entry["sheet"], entry["header_row"], entry["columns"])
        except templates.TemplateError:
            raise ApiError(404, "not-found", "the stored template file is missing") from None

    def post_upload(req: Request) -> dict:
        return upload(home, req.headers.get("X-Filename"), req.body)

    def post_upload_preview(req: Request) -> dict:
        body = req.body if isinstance(req.body, dict) else {}
        header_row = body.get("header_row")
        if header_row is not None and (not isinstance(header_row, int) or isinstance(header_row, bool) or header_row < 1):
            raise ApiError(400, "bad-request", "header_row must be a positive number")
        sheet = body.get("sheet")
        if sheet is not None and not isinstance(sheet, str):
            raise ApiError(400, "bad-request", "sheet must be text")
        return upload_preview(home, req.params["upload"], sheet, header_row)

    def post_register(req: Request) -> dict:
        return register(home, req.body if isinstance(req.body, dict) else {})

    def post_default(req: Request) -> dict:
        name = known(req)
        with LOCK:
            return templates.set_default(name, home)

    def delete(req: Request) -> dict:
        name = known(req)
        with LOCK:
            return templates.remove(name, home)

    r = state.router
    r.add("GET", "/api/templates", "browser", get_list)
    r.add("GET", "/api/templates/:name/preview", "browser", get_preview)
    r.add("POST", "/api/templates/uploads", "browser", post_upload, body="binary", max_body=UPLOAD_CAP)
    r.add("POST", "/api/templates/uploads/:upload/preview", "browser", post_upload_preview)
    r.add("POST", "/api/templates", "browser", post_register)
    r.add("POST", "/api/templates/:name/default", "browser", post_default)
    r.add("DELETE", "/api/templates/:name", "browser", delete)
