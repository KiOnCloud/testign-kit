import io
import json
import os
import shutil
import socket
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest

openpyxl = pytest.importorskip("openpyxl")

from console_helpers import InProcessServer, call  # noqa: E402

from testign import templates  # noqa: E402
from testign.console import lifecycle, templates_api  # noqa: E402
from testign.console import server as srv  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIPPED_SAMPLE = REPO / "templates" / "testcase-template-sample.xlsx"
JA_NAME = "結合テスト仕様書_v3.xlsx"


@pytest.fixture
def console(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    state = srv.ConsoleState(version="t", agent_token="agent", home=home)
    srv.install_base_routes(state)
    lifecycle.install_routes(state)
    server = InProcessServer(state)
    server.home = home
    server.headers = {srv.SESSION_HEADER: server.session()}
    yield server
    server.close()


def upload(console, data: bytes, name: str | None = JA_NAME, raw_header: str | None = None):
    headers = {**console.headers, "Content-Type": "application/octet-stream"}
    if raw_header is not None:
        headers["X-Filename"] = raw_header
    elif name is not None:
        headers["X-Filename"] = "UTF-8''" + quote(name, safe="")
    return call(console.port, "POST", "/api/templates/uploads", headers=headers, body=data)


def post(console, path, body):
    return call(console.port, "POST", path, headers=console.headers, body=body)


def no_headers_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cases"
    for c, h in enumerate(["Case", "What to check", "How", "Should see", "Comment"], start=1):
        ws.cell(row=3, column=c, value=h)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _entry_without_time(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k != "registered_at"}


def test_upload_detects_layout_and_previews(console):
    status, _, data = upload(console, SHIPPED_SAMPLE.read_bytes())
    assert status == 200, data
    assert data["name"] == JA_NAME and data["sheets"] == ["表紙", "テストケース"]
    assert data["layout"]["sheet"] == "テストケース" and data["layout"]["header_row"] == 4
    assert data["layout"]["columns"]["trace"] == "H"
    grid = data["preview"]
    assert grid["rows"][0]["header"] is True and grid["rows"][0]["cells"][7] == "備考"
    assert len(grid["rows"]) <= 8
    assert {"letter": "H", "header": "備考", "role": "trace"} in grid["columns"]
    # An upload is read read-only and bounded, so merged ranges and dropdowns wait for registration.
    assert grid["complete"] is False and grid["dropdowns"] == []
    stored = templates_api.uploads_dir(console.home) / data["upload"] / JA_NAME
    assert stored.exists()


def test_console_and_cli_registration_give_the_same_index_entry(console, tmp_path):
    status, _, up = upload(console, SHIPPED_SAMPLE.read_bytes())
    status, _, reg = post(console, "/api/templates", {"upload": up["upload"], "name": "結合テスト"})
    assert status == 200, reg
    assert not (templates_api.uploads_dir(console.home) / up["upload"]).exists()

    other = tmp_path / "cli-home"
    src = tmp_path / "src" / JA_NAME
    src.parent.mkdir()
    shutil.copyfile(SHIPPED_SAMPLE, src)
    templates.register(src, "結合テスト", home=other)

    api_index = json.loads(templates.index_path(console.home).read_text(encoding="utf-8"))
    cli_index = json.loads(templates.index_path(other).read_text(encoding="utf-8"))
    assert api_index["default"] == cli_index["default"] == "結合テスト"
    assert _entry_without_time(api_index["templates"]["結合テスト"]) == _entry_without_time(
        cli_index["templates"]["結合テスト"])
    assert api_index["templates"]["結合テスト"]["source_name"] == JA_NAME
    assert (templates.templates_dir(console.home) / api_index["templates"]["結合テスト"]["file"]).read_bytes() == \
        SHIPPED_SAMPLE.read_bytes()


def test_list_preview_default_and_remove(console):
    for name in ("a", "b"):
        up = upload(console, SHIPPED_SAMPLE.read_bytes())[2]
        assert post(console, "/api/templates", {"upload": up["upload"], "name": name})[0] == 200
    status, _, listing = call(console.port, "GET", "/api/templates", headers=console.headers)
    assert listing["default"] == "a" and [t["name"] for t in listing["templates"]] == ["a", "b"]
    assert all("path" not in t for t in listing["templates"])

    status, _, grid = call(console.port, "GET", "/api/templates/b/preview", headers=console.headers)
    assert status == 200 and grid["sheet"] == "テストケース" and grid["header_row"] == 4
    assert grid["complete"] is True and grid["dropdowns"][0]["range"].startswith("F5")
    assert grid["merged"] == ["A1:H1"]

    status, _, listing = post(console, "/api/templates/b/default", {})
    assert status == 200 and listing["default"] == "b"
    status, _, listing = call(console.port, "DELETE", "/api/templates/b", headers=console.headers)
    assert status == 200 and listing["default"] == "a"
    for method, path in (("POST", "/api/templates/b/default"), ("DELETE", "/api/templates/b"),
                         ("GET", "/api/templates/b/preview")):
        body = {} if method == "POST" else None
        assert call(console.port, method, path, headers=console.headers, body=body)[0] == 404


def test_registration_errors_map_to_status_codes(console):
    up = upload(console, SHIPPED_SAMPLE.read_bytes())[2]
    assert post(console, "/api/templates", {"upload": up["upload"], "name": "a"})[0] == 200
    up = upload(console, SHIPPED_SAMPLE.read_bytes())[2]
    status, _, data = post(console, "/api/templates", {"upload": up["upload"], "name": "a"})
    assert status == 409 and data["error"]["code"] == "name-taken"
    assert post(console, "/api/templates", {"upload": up["upload"], "name": "a", "replace": True})[0] == 200

    status, _, up = upload(console, no_headers_workbook(), name="cases.xlsx")
    assert status == 200
    status, _, data = post(console, "/api/templates", {"upload": up["upload"], "name": "en"})
    assert status == 400 and data["error"]["code"] == "mapping-failed"
    assert data["error"]["details"]["headers"]["E"] == "Comment"
    status, _, data = post(console, "/api/templates", {"upload": up["upload"], "name": "en", "sheet": "Cases",
                                                       "header_row": 3, "map": {"item": "B", "trace": "E"}})
    assert status == 200, data
    assert data["template"]["columns"]["trace"] == "E"

    assert post(console, "/api/templates", {"upload": "nope", "name": "x"})[0] == 404
    assert post(console, "/api/templates", {"upload": up["upload"], "name": ""})[0] in (400, 404)


def test_file_clash_is_409(console, tmp_path):
    templates.register(SHIPPED_SAMPLE, "a-b", home=console.home)
    up = upload(console, SHIPPED_SAMPLE.read_bytes())[2]
    status, _, data = post(console, "/api/templates", {"upload": up["upload"], "name": "a b"})
    assert status == 409 and data["error"]["code"] == "file-clash"


@pytest.mark.parametrize("header", [
    None, "sample.xlsx", "UTF-8''..", "UTF-8''a%2Fb.xlsx", "UTF-8''a%5Cb.xlsx", "UTF-8''CON.xlsx",
    "UTF-8''lpt1.xlsm", "UTF-8''notes.txt", "UTF-8''%FF%FE.xlsx", "UTF-8''",
])
def test_bad_file_names_are_refused(console, header):
    status, _, data = upload(console, SHIPPED_SAMPLE.read_bytes(), name=None, raw_header=header)
    assert status == 400, header


def test_non_zip_and_wrong_content_type_are_refused(console):
    assert upload(console, b"not a zip at all", name="x.xlsx")[0] == 400
    headers = {**console.headers, "Content-Type": "application/json", "X-Filename": "UTF-8''x.xlsx"}
    assert call(console.port, "POST", "/api/templates/uploads", headers=headers, body=b"{}")[0] == 415


def test_upload_over_ten_megabytes_is_413(console):
    with socket.create_connection(("127.0.0.1", console.port), timeout=5) as sock:
        sock.sendall((
            "POST /api/templates/uploads HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{console.port}\r\n"
            f"{srv.SESSION_HEADER}: {console.headers[srv.SESSION_HEADER]}\r\n"
            "Content-Type: application/octet-stream\r\n"
            "X-Filename: UTF-8''big.xlsx\r\n"
            f"Content-Length: {10 * 1024 * 1024 + 1}\r\n\r\n"
        ).encode())
        assert sock.recv(4096).startswith(b"HTTP/1.1 413")


def _bomb(size: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/worksheets/sheet1.xml", b"\0" * size)
    return buf.getvalue()


def test_zip_bombs_are_refused_before_openpyxl_opens_them(console, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("openpyxl must not open this file")

    monkeypatch.setattr(templates, "detect_layout_bounded", boom)
    status, _, data = upload(console, _bomb(20 * 1024 * 1024), name="bomb.xlsx")
    assert status == 400 and data["error"]["code"] == "zip-ratio"

    monkeypatch.setattr(templates_api, "UNZIPPED_CAP", 1000)
    monkeypatch.setattr(templates_api, "RATIO_CAP", 10**9)
    status, _, data = upload(console, _bomb(5000), name="bomb.xlsx")
    assert status == 400 and data["error"]["code"] == "too-large-unzipped"
    assert not any(templates_api.uploads_dir(console.home).iterdir())


def test_old_uploads_are_swept(console):
    root = templates_api.uploads_dir(console.home)
    old = root / "old"
    old.mkdir()
    (old / "x.xlsx").write_bytes(b"x")
    fresh = root / "fresh"
    fresh.mkdir()
    past = time.time() - 2 * 3600
    os.utime(old, (past, past))
    assert templates_api.sweep(console.home) == 1
    assert not old.exists() and fresh.exists()


def test_concurrent_set_default_leaves_a_valid_index(console):
    for name in ("a", "b"):
        templates.register(SHIPPED_SAMPLE, name, home=console.home)
    results = []

    def flip(name):
        for _ in range(5):
            results.append(post(console, f"/api/templates/{name}/default", {})[0])

    threads = [threading.Thread(target=flip, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(results) == {200}
    index = json.loads(templates.index_path(console.home).read_text(encoding="utf-8"))
    assert index["default"] in ("a", "b") and set(index["templates"]) == {"a", "b"}
    assert [p.name for p in templates.templates_dir(console.home).iterdir() if p.name.endswith(".tmp")] == []


def test_upload_preview_for_another_header_row(console):
    up = upload(console, no_headers_workbook(), name="cases.xlsx")[2]
    status, _, data = post(console, f"/api/templates/uploads/{up['upload']}/preview", {"sheet": "Cases", "header_row": 3})
    assert status == 200 and data["layout"]["header_row"] == 3
    assert data["preview"]["rows"][0]["cells"][:2] == ["Case", "What to check"]
    assert post(console, f"/api/templates/uploads/{up['upload']}/preview", {"sheet": "Nope"})[0] == 400
    assert post(console, "/api/templates/uploads/zzz/preview", {})[0] == 404


def _padded_bomb(sheet_size: int, padding: int) -> bytes:
    """One huge, very compressible sheet hidden behind stored random padding."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>", compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("xl/worksheets/sheet1.xml", b"<c>0</c>" * (sheet_size // 8), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("xl/media/pad.bin", os.urandom(padding), compress_type=zipfile.ZIP_STORED)
    return buf.getvalue()


def test_padding_does_not_hide_one_huge_sheet(console, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("openpyxl must not open this file")

    monkeypatch.setattr(templates, "detect_layout_bounded", boom)
    status, _, data = upload(console, _padded_bomb(8 * 1024 * 1024, 2 * 1024 * 1024), name="padded.xlsx")
    assert status == 400 and data["error"]["code"] == "zip-ratio"
    monkeypatch.setattr(templates_api, "ENTRY_CAP", 1024 * 1024)
    status, _, data = upload(console, _padded_bomb(4 * 1024 * 1024, 2 * 1024 * 1024), name="padded.xlsx")
    assert status == 400 and data["error"]["code"] == "too-large-unzipped"


def test_registration_from_the_console_reads_only_the_first_rows(console, monkeypatch):
    def full_load(*_a, **_k):
        raise AssertionError("registration of an upload must not fully load it")

    up = upload(console, SHIPPED_SAMPLE.read_bytes())[2]
    monkeypatch.setattr(templates, "detect_layout", full_load)
    status, _, data = post(console, "/api/templates", {"upload": up["upload"], "name": "a", "sheet": "テストケース",
                                                       "header_row": 4})
    assert status == 200, data
    assert data["template"]["columns"]["trace"] == "H"
