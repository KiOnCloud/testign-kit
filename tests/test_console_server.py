import socket
import time

import pytest

from console_helpers import InProcessServer, call
from testign.console import lifecycle
from testign.console import server as srv

AGENT = "agent-token-for-tests"


@pytest.fixture
def console(tmp_path):
    ui = tmp_path / "ui"
    (ui / "tests").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    (ui / "app.js").write_text("export {};", encoding="utf-8")
    (ui / "tests" / "spec.js").write_text("// not served", encoding="utf-8")
    state = srv.ConsoleState(version="9.9.9", agent_token=AGENT, ui_dir=ui, log_path=tmp_path / "server.log")
    srv.install_base_routes(state)
    state.router.add("GET", "/api/ping", "browser", lambda r: {"pong": True})
    state.router.add("GET", "/api/items/:name", "browser", lambda r: {"name": r.params["name"]})
    state.router.add("POST", "/api/echo", "browser", lambda r: {"body": r.body})
    state.router.add("POST", "/api/upload", "browser", lambda r: {"n": len(r.body)}, body="binary", max_body=16)
    state.router.add("GET", "/agent/ping", "agent", lambda r: {"agent": True})
    server = InProcessServer(state)
    yield server
    server.close()


def _session_headers(server):
    return {srv.SESSION_HEADER: server.session()}


def test_health_proves_the_agent_token(console):
    status, headers, data = call(console.port, "GET", "/health?nonce=abc123")
    assert status == 200
    assert data["proof"] == lifecycle.expected_proof(AGENT, "abc123")
    assert data["version"] == "9.9.9" and data["busy"] is False
    assert "token" not in str(data).lower()


@pytest.mark.parametrize("path", ["/health", "/api/ping", "/nope"])
def test_security_headers_on_every_answer(console, path):
    status, headers, _ = call(console.port, "GET", path)
    assert status in (200, 403, 404)
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers.get("Access-Control-Allow-Origin") is None


def test_api_answers_are_not_cached(console):
    status, headers, _ = call(console.port, "GET", "/api/ping", headers=_session_headers(console))
    assert status == 200 and headers["Cache-Control"] == "no-store"


def test_browser_routes_need_a_browser_session(console):
    assert call(console.port, "GET", "/api/ping")[0] == 403
    assert call(console.port, "GET", "/api/ping", headers={srv.SESSION_HEADER: "wrong"})[0] == 403
    status, _, data = call(console.port, "GET", "/api/ping", headers=_session_headers(console))
    assert status == 200 and data == {"pong": True}


def test_agent_token_is_refused_on_browser_routes(console):
    assert call(console.port, "GET", "/api/ping", headers={srv.SESSION_HEADER: AGENT})[0] == 403
    assert call(console.port, "GET", "/api/ping", headers={srv.AGENT_HEADER: AGENT})[0] == 403


def test_browser_session_is_refused_on_agent_routes(console):
    session = console.session()
    assert call(console.port, "GET", "/agent/ping", headers={srv.SESSION_HEADER: session})[0] == 403
    assert call(console.port, "GET", "/agent/ping", headers={srv.AGENT_HEADER: session})[0] == 403
    assert call(console.port, "GET", "/agent/ping", headers={srv.AGENT_HEADER: AGENT})[0] == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:4791", "127.0.0.1.evil.example", "", "[::1]:80"])
def test_foreign_host_is_refused(console, host):
    status, _, data = call(console.port, "GET", "/health", host=host)
    assert status == 403 and data["error"]["code"] == "forbidden"


def test_host_with_another_port_is_accepted(console):
    headers = _session_headers(console)
    assert call(console.port, "GET", "/api/ping", headers=headers, host="localhost:9999")[0] == 200
    assert call(console.port, "GET", "/api/ping", headers=headers, host="127.0.0.1")[0] == 200


def test_origin_must_match_host(console):
    headers = _session_headers(console)
    host = f"127.0.0.1:{console.port}"
    assert call(console.port, "GET", "/api/ping", headers={**headers, "Origin": f"http://{host}"})[0] == 200
    for origin in ("http://evil.example", "null", f"https://{host}", "http://localhost:1"):
        assert call(console.port, "GET", "/api/ping", headers={**headers, "Origin": origin})[0] == 403


@pytest.mark.parametrize("site,expected", [("same-origin", 200), ("none", 200), ("same-site", 403), ("cross-site", 403)])
def test_fetch_metadata(console, site, expected):
    headers = {**_session_headers(console), "Sec-Fetch-Site": site}
    assert call(console.port, "GET", "/api/ping", headers=headers)[0] == expected


def test_options_is_refused(console):
    assert call(console.port, "OPTIONS", "/api/ping")[0] == 403


def test_wrong_method_for_a_known_route(console):
    status, _, data = call(console.port, "DELETE", "/api/ping", headers=_session_headers(console))
    assert status == 405


def test_wrong_content_type_gets_415(console):
    headers = {**_session_headers(console), "Content-Type": "text/plain"}
    status, _, data = call(console.port, "POST", "/api/echo", headers=headers, body=b'{"a":1}')
    assert status == 415 and data["error"]["code"] == "unsupported-media-type"
    headers = {**_session_headers(console), "Content-Type": "application/json"}
    assert call(console.port, "POST", "/api/upload", headers=headers, body=b"{}")[0] == 415


def test_json_body_round_trip_and_bad_json(console):
    headers = _session_headers(console)
    status, _, data = call(console.port, "POST", "/api/echo", headers=headers, body={"a": "ノート"})
    assert status == 200 and data == {"body": {"a": "ノート"}}
    status, _, data = call(console.port, "POST", "/api/echo",
                           headers={**headers, "Content-Type": "application/json"}, body=b"{nope")
    assert status == 400 and data["error"]["code"] == "bad-request"


def test_body_over_the_cap_gets_413_before_it_is_read(console):
    session = console.session()
    with socket.create_connection(("127.0.0.1", console.port), timeout=5) as sock:
        head = (
            "POST /api/echo HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{console.port}\r\n"
            f"{srv.SESSION_HEADER}: {session}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {50 * 1024 * 1024}\r\n\r\n"
        )
        sock.sendall(head.encode())
        started = time.monotonic()
        reply = sock.recv(4096).decode("latin-1")
        assert reply.startswith("HTTP/1.1 413")
        assert time.monotonic() - started < 3
    headers = {**_session_headers(console), "Content-Type": "application/octet-stream"}
    assert call(console.port, "POST", "/api/upload", headers=headers, body=b"x" * 17)[0] == 413
    assert call(console.port, "POST", "/api/upload", headers=headers, body=b"x" * 16)[0] == 200


def test_get_route_with_a_body_is_refused(console):
    headers = {**_session_headers(console), "Content-Type": "application/json"}
    assert call(console.port, "GET", "/api/ping", headers=headers, body=b"{}")[0] == 400


def test_launch_code_works_once(console):
    code = console.state.mint_launch_code()
    status, _, data = call(console.port, "POST", "/api/session", body={"code": code})
    assert status == 200 and data["session"]
    assert call(console.port, "POST", "/api/session", body={"code": code})[0] == 403
    assert call(console.port, "POST", "/api/session", body={"code": "made-up"})[0] == 403
    assert call(console.port, "POST", "/api/session", body={})[0] == 403


def test_launch_code_expires_after_ten_minutes(console, monkeypatch):
    assert srv.LAUNCH_CODE_TTL == 600
    monkeypatch.setattr(srv, "LAUNCH_CODE_TTL", 0.0)
    code = console.state.mint_launch_code()
    assert call(console.port, "POST", "/api/session", body={"code": code})[0] == 403


def test_launch_codes_come_from_the_agent_route_only(console):
    assert call(console.port, "POST", "/agent/launch-code", body={})[0] == 403
    status, _, data = call(console.port, "POST", "/agent/launch-code", headers={srv.AGENT_HEADER: AGENT}, body={})
    assert status == 200
    assert call(console.port, "POST", "/api/session", body={"code": data["code"]})[0] == 200
    assert len(console.state.session_times()) == 1


def test_static_files_come_from_the_manifest_only(console):
    status, headers, raw = call(console.port, "GET", "/")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert headers["Cache-Control"] == "no-store"
    status, headers, _ = call(console.port, "GET", "/app.js")
    assert status == 200 and headers["Content-Type"].startswith("text/javascript")
    for path in ("/tests/spec.js", "/../server.py", "/%2e%2e/server.py", "/server.py", "/index.html/x"):
        assert call(console.port, "GET", path)[0] == 404


def test_named_segments_are_decoded_not_joined(console):
    headers = _session_headers(console)
    status, _, data = call(console.port, "GET", "/api/items/%E7%B5%90%E5%90%88", headers=headers)
    assert status == 200 and data == {"name": "結合"}
    assert call(console.port, "GET", "/api/items/a/b", headers=headers)[0] == 404


def test_log_holds_no_token_code_or_query(console, tmp_path):
    session = console.session()
    call(console.port, "GET", "/api/ping?secret=customer-text", headers={srv.SESSION_HEADER: session})
    call(console.port, "GET", "/api/items/DEMO-1", headers={srv.SESSION_HEADER: session})
    call(console.port, "GET", "/nope?x=1")
    log = (tmp_path / "server.log").read_text(encoding="utf-8")
    assert "/api/ping" in log and "/api/items/:name" in log
    for secret in (AGENT, session, "customer-text", "DEMO-1", "secret="):
        assert secret not in log
