"""HTTP side of the console: request checks, credentials, routes, static files and a scrubbed log.

Every request passes one check chain before its body is read:
method for the route, ``Host`` name, ``Origin``, ``Sec-Fetch-Site``, credential for the route
group, ``Content-Type`` and body size. Route groups:

- ``public``: static files, ``/health``, ``/api/session``; no credential.
- ``browser``: ``/api/*``; a browser session token in ``X-Testign-Session``.
- ``agent``: ``/agent/*``; the agent token from ``server.json`` in ``X-Testign-Token``.

The agent token is never accepted on ``/api/*`` and a browser session never on ``/agent/*``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

JSON_BODY_CAP = 1024 * 1024
LAUNCH_CODE_TTL = 600.0
LOG_CAP = 1024 * 1024

SESSION_HEADER = "X-Testign-Session"
AGENT_HEADER = "X-Testign-Token"

UI_DIR = Path(__file__).resolve().parent / "ui"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".txt": "text/plain; charset=utf-8",
}

KNOWN_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")


class ApiError(Exception):
    """An error answered as ``{error: {code, message}}``. Messages never hold customer text."""

    def __init__(self, status: int, code: str, message: str = "", details: dict | None = None) -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code
        self.details = details


@dataclass
class Request:
    method: str
    path: str
    params: dict[str, str]
    query: dict[str, list[str]]
    headers: Any
    body: Any
    session: str | None
    state: "ConsoleState"
    handler: "BaseHTTPRequestHandler"

    def arg(self, name: str, default: str | None = None) -> str | None:
        values = self.query.get(name)
        return values[0] if values else default


@dataclass
class Response:
    status: int = 200
    data: Any = None
    raw: bytes | None = None
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    after: Callable[[], None] | None = None


Handler = Callable[[Request], Any]


@dataclass
class Route:
    method: str
    pattern: str
    group: str
    handler: Handler
    body: str | None = None  # None, "json" or "binary"
    max_body: int = JSON_BODY_CAP
    regex: re.Pattern = field(init=False)

    def __post_init__(self) -> None:
        parts = []
        for segment in self.pattern.strip("/").split("/"):
            if segment.startswith(":"):
                parts.append(f"(?P<{segment[1:]}>[^/]+)")
            else:
                parts.append(re.escape(segment))
        self.regex = re.compile("^/" + "/".join(parts) + "$")


class Router:
    def __init__(self) -> None:
        self.routes: list[Route] = []

    def add(self, method: str, pattern: str, group: str, handler: Handler, *, body: str | None = None,
            max_body: int = JSON_BODY_CAP) -> None:
        if group not in ("public", "browser", "agent"):
            raise ValueError(f"unknown route group {group}")
        if body is None and method in ("POST", "PUT", "PATCH"):
            body = "json"
        self.routes.append(Route(method, pattern, group, handler, body, max_body))

    def match(self, method: str, path: str) -> tuple[Route | None, dict[str, str], bool]:
        """Return (route, params, path_known). ``path_known`` is true when another method matches."""
        known = False
        for route in self.routes:
            m = route.regex.match(path)
            if not m:
                continue
            known = True
            if route.method == method or (method == "HEAD" and route.method == "GET"):
                return route, {k: unquote(v) for k, v in m.groupdict().items()}, True
        return None, {}, known


def build_static_manifest(root: Path = UI_DIR) -> dict[str, tuple[Path, str]]:
    """Map URL paths to UI files, built once at start; anything else is 404."""
    manifest: dict[str, tuple[Path, str]] = {}
    if not root.is_dir():
        return manifest
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts[0] == "tests" or any(p.startswith(".") for p in rel.parts):
            continue
        ctype = CONTENT_TYPES.get(path.suffix.lower())
        if not ctype:
            continue
        manifest["/" + rel.as_posix()] = (path, ctype)
    if "/index.html" in manifest:
        manifest["/"] = manifest["/index.html"]
    return manifest


class ScrubbedLog:
    """``server.log``: method, route pattern, status, duration and an error code; nothing else."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, *fields: Any) -> None:
        if self.path is None:
            return
        line = time.strftime("%Y-%m-%dT%H:%M:%S") + " " + " ".join(str(f) for f in fields) + "\n"
        with self._lock:
            try:
                if self.path.exists() and self.path.stat().st_size > LOG_CAP:
                    os.replace(self.path, self.path.with_suffix(".log.1"))
                fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass


class ConsoleState:
    """Credentials, launch codes, browser sessions, activity and extension points of one server."""

    def __init__(self, *, version: str, agent_token: str, home: Path | None = None,
                 log_path: Path | None = None, ui_dir: Path = UI_DIR) -> None:
        self.version = version
        self.agent_token = agent_token
        self.home = home
        self.pid = os.getpid()
        self.started_at = time.time()
        self.router = Router()
        self.static = build_static_manifest(ui_dir)
        self.log = ScrubbedLog(log_path)
        self.lock = threading.Lock()
        self._codes: dict[str, float] = {}
        self._sessions: dict[str, float] = {}
        self.last_activity = time.monotonic()
        self.held_calls = 0
        self.busy: Callable[[], bool] = lambda: False
        self.shutdown_hooks: list[Callable[[], None]] = []
        self.server: ThreadingHTTPServer | None = None

    # credentials -------------------------------------------------------------------------
    def mint_launch_code(self) -> str:
        code = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self.lock:
            self._codes = {c: exp for c, exp in self._codes.items() if exp > now}
            self._codes[code] = now + LAUNCH_CODE_TTL
        return code

    def exchange_code(self, code: str) -> str | None:
        """Burn a launch code and return a new browser session token, or None."""
        now = time.monotonic()
        with self.lock:
            match = None
            for known in list(self._codes):
                if hmac.compare_digest(known.encode(), code.encode()):
                    match = known
            if match is None:
                return None
            expiry = self._codes.pop(match)
            if expiry <= now:
                return None
            token = secrets.token_urlsafe(32)
            self._sessions[token] = time.time()
            return token

    def session_ok(self, token: str | None) -> bool:
        if not token:
            return False
        ok = False
        with self.lock:
            for known in self._sessions:
                if hmac.compare_digest(known.encode(), token.encode()):
                    ok = True
        return ok

    def agent_ok(self, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(self.agent_token.encode(), token.encode())

    def session_times(self) -> list[float]:
        """Creation times of the browser sessions, so open tabs can announce a new one."""
        with self.lock:
            return sorted(self._sessions.values())

    def proof(self, nonce: str) -> str:
        return hmac.new(self.agent_token.encode(), nonce.encode(), hashlib.sha256).hexdigest()

    # activity ----------------------------------------------------------------------------
    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def hold(self, delta: int) -> None:
        with self.lock:
            self.held_calls += delta
        self.touch()

    def idle_for(self) -> float:
        return time.monotonic() - self.last_activity

    def is_busy(self) -> bool:
        try:
            return bool(self.busy())
        except Exception:  # noqa: BLE001 - a broken check must keep the server up
            return True


def _host_name(host: str) -> str | None:
    host = host.strip().lower()
    if not host:
        return None
    if host.startswith("["):
        return None
    name, _, port = host.partition(":")
    if port and not port.isdigit():
        return None
    return name


def _error_body(code: str, message: str, details: dict | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "testign-console"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    @property
    def state(self) -> ConsoleState:
        return self.server.state  # type: ignore[attr-defined]

    # logging: nothing reaches stderr ------------------------------------------------------
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def log_error(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        return

    # dispatch ----------------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._dispatch("OPTIONS")

    def _dispatch(self, method: str) -> None:
        started = time.monotonic()
        label = "-"
        status = 500
        code = "-"
        try:
            route, label, response = self._handle(method)
            status = response.status
            if status >= 400 and isinstance(response.data, dict) and "error" in response.data:
                code = response.data["error"]["code"]
            self._send(response, head=method == "HEAD")
            if response.after:
                response.after()
        except ApiError as exc:
            status, code = exc.status, exc.code
            # The body may be unread; never reuse this connection.
            self.close_connection = True
            self._send(Response(exc.status, _error_body(exc.code, exc.message, exc.details)), head=method == "HEAD")
        except (ConnectionError, socket.timeout):
            status, code = 499, "client-gone"
            self.close_connection = True
        except Exception as exc:  # noqa: BLE001 - answer 500 and log only the class name
            status, code = 500, "internal:" + type(exc).__name__
            try:
                self._send(Response(500, _error_body("internal", "internal error")), head=method == "HEAD")
            except OSError:
                self.close_connection = True
        finally:
            ms = int((time.monotonic() - started) * 1000)
            self.state.log.write(method, label, status, f"{ms}ms", code)

    def _handle(self, method: str) -> tuple[Route | None, str, Response]:
        state = self.state
        split = urlsplit(self.path)
        path = split.path or "/"
        static = state.static.get(path) if method in ("GET", "HEAD") else None
        route, params, known = state.router.match(method, path)
        label = route.pattern if route else ("static" if static else "-")

        # 1. method for the route
        if method == "OPTIONS" or method not in KNOWN_METHODS:
            raise ApiError(403, "forbidden", "method not allowed")
        if route is None and static is None and (known or path in state.static):
            raise ApiError(405, "method-not-allowed", "method not allowed for this route")

        # 2. Host, 3. Origin, 4. Sec-Fetch-Site
        host = self.headers.get("Host", "")
        if _host_name(host) not in ("127.0.0.1", "localhost"):
            raise ApiError(403, "forbidden", "host not allowed")
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{host.strip()}":
            raise ApiError(403, "forbidden", "origin not allowed")
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if fetch_site is not None and fetch_site not in ("same-origin", "none"):
            raise ApiError(403, "forbidden", "cross-site request")

        if route is None and static is None:
            raise ApiError(404, "not-found", "no such route")
        if route is None:
            return None, label, self._static(path, static)

        # 5. credential for the route group
        session = None
        if route.group == "browser":
            session = self.headers.get(SESSION_HEADER)
            if not state.session_ok(session):
                raise ApiError(403, "forbidden", "browser session required")
        elif route.group == "agent":
            if not state.agent_ok(self.headers.get(AGENT_HEADER)):
                raise ApiError(403, "forbidden", "agent token required")

        # 6. Content-Type, 7. body size
        body: Any = None
        length_header = self.headers.get("Content-Length")
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(400, "bad-request", "chunked bodies are not accepted")
        try:
            length = int(length_header) if length_header else 0
        except ValueError:
            raise ApiError(400, "bad-request", "bad Content-Length") from None
        if length < 0:
            raise ApiError(400, "bad-request", "bad Content-Length")
        if route.body is None:
            if length:
                raise ApiError(400, "bad-request", "this route takes no body")
        else:
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            wanted = "application/json" if route.body == "json" else "application/octet-stream"
            if ctype != wanted:
                raise ApiError(415, "unsupported-media-type", f"Content-Type must be {wanted}")
            if length > route.max_body:
                self.close_connection = True
                raise ApiError(413, "too-large", "request body too large")
            raw = self.rfile.read(length) if length else b""
            if route.body == "json":
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise ApiError(400, "bad-request", "body is not valid JSON") from None
            else:
                body = raw

        if route.group != "public":
            state.touch()
        request = Request(method, path, params, parse_qs(split.query), self.headers, body, session, state, self)
        result = route.handler(request)
        response = result if isinstance(result, Response) else Response(200, result)
        response.headers.setdefault("Cache-Control", "no-store")
        return route, label, response

    def _static(self, path: str, entry: tuple[Path, str]) -> Response:
        self.state.touch()
        file, ctype = entry
        try:
            raw = file.read_bytes()
        except OSError:
            raise ApiError(404, "not-found", "no such file") from None
        headers = {"Cache-Control": "no-store"} if file.name == "index.html" else {"Cache-Control": "no-cache"}
        return Response(200, raw=raw, content_type=ctype, headers=headers)

    def _send(self, response: Response, head: bool = False) -> None:
        if response.raw is not None:
            payload = response.raw
            ctype = response.content_type
        else:
            payload = json.dumps(response.data, ensure_ascii=False).encode("utf-8")
            ctype = "application/json; charset=utf-8"
            response.headers.setdefault("Cache-Control", "no-store")
        self.send_response_only(response.status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        for name, value in response.headers.items():
            self.send_header(name, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if not head:
            self.wfile.write(payload)


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    if sys.platform == "win32":
        allow_reuse_address = False

    def __init__(self, port: int, state: ConsoleState) -> None:
        self.state = state
        state.server = self
        super().__init__(("127.0.0.1", port), ConsoleHandler)

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[1]
        self.state.log.write("-", "-", 500, "0ms", "internal:" + type(exc).__name__ if exc else "internal")


# routes every server has --------------------------------------------------------------------
def _health(req: Request) -> dict:
    nonce = req.arg("nonce")
    state = req.state
    return {
        "version": state.version,
        "pid": state.pid,
        "busy": state.is_busy(),
        "proof": state.proof(nonce) if nonce else None,
    }


def _session(req: Request) -> dict:
    body = req.body if isinstance(req.body, dict) else {}
    code = body.get("code")
    if not isinstance(code, str) or not code or len(code) > 200:
        raise ApiError(403, "forbidden", "launch code required")
    token = req.state.exchange_code(code)
    if token is None:
        raise ApiError(403, "forbidden", "launch code used, expired or unknown")
    return {"session": token, "version": req.state.version}


def _launch_code(req: Request) -> dict:
    return {"code": req.state.mint_launch_code()}


def _shutdown(req: Request) -> Response:
    body = req.body if isinstance(req.body, dict) else {}
    state = req.state
    if state.is_busy() and not body.get("force"):
        raise ApiError(409, "conflict", "jobs are open; use --force")

    def stop() -> None:
        threading.Thread(target=shutdown_server, args=(state,), daemon=True).start()

    return Response(200, {"ok": True}, after=stop)


def shutdown_server(state: ConsoleState) -> None:
    for hook in list(state.shutdown_hooks):
        try:
            hook()
        except Exception:  # noqa: BLE001
            pass
    if state.server is not None:
        state.server.shutdown()


def install_base_routes(state: ConsoleState) -> None:
    r = state.router
    r.add("GET", "/health", "public", _health)
    r.add("POST", "/api/session", "public", _session)
    r.add("POST", "/agent/launch-code", "agent", _launch_code)
    r.add("POST", "/agent/shutdown", "agent", _shutdown)
