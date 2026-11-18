"""Shared helpers for the console tests: an in-process server and raw HTTP calls."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from testign.console import lifecycle
from testign.console import server as srv

REPO = Path(__file__).resolve().parent.parent
RUN_PY = REPO / "scripts" / "run.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(port: int, method: str, path: str, *, headers: dict | None = None, body=None,
         host: str | None = None, timeout: float = 5.0):
    """Send one request; returns (status, headers, parsed JSON or raw bytes)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    hdrs = {"Host": host if host is not None else f"127.0.0.1:{port}"}
    payload = None
    if isinstance(body, (dict, list)):
        payload = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    elif isinstance(body, bytes):
        payload = body
    hdrs.update(headers or {})
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for k, v in hdrs.items():
        conn.putheader(k, v)
    if payload is not None and "Content-Length" not in hdrs:
        conn.putheader("Content-Length", str(len(payload)))
    conn.endheaders(payload)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        data = json.loads(raw.decode()) if raw else None
    except (UnicodeDecodeError, ValueError):
        data = raw
    return resp.status, resp.headers, data


class InProcessServer:
    """A ConsoleServer on an ephemeral port in a thread, for request-level tests."""

    def __init__(self, state: srv.ConsoleState) -> None:
        self.state = state
        self.httpd = srv.ConsoleServer(0, state)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)
        self.thread.start()

    def session(self) -> str:
        code = self.state.mint_launch_code()
        status, _, data = call(self.port, "POST", "/api/session", body={"code": code})
        assert status == 200, data
        return data["session"]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def write_config(home: Path, **console) -> None:
    path = home / ".testign-kit" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["output_dir"] = str(home / "out")
    data.setdefault("console", {}).update(console)
    path.write_text(json.dumps(data), encoding="utf-8")


def cli_env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_REMOTE", "SSH_CONNECTION")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_cli(home: Path, *args: str, timeout: float = 60):
    return subprocess.run([sys.executable, str(RUN_PY), *args], capture_output=True, text=True,
                          encoding="utf-8", env=cli_env(home), timeout=timeout)


def serve_in_thread(home: Path, **kwargs) -> tuple[threading.Thread, dict]:
    """Run lifecycle.serve in a thread; returns once server.json proves itself."""
    holder: dict = {}
    ready = threading.Event()

    def on_ready(state):
        holder["state"] = state
        ready.set()

    t = threading.Thread(target=lifecycle.serve, args=(home,), kwargs={"port": 0, "ready": on_ready, **kwargs},
                         daemon=True)
    t.start()
    assert ready.wait(10), "server did not start"
    return t, holder


def kill_server(home: Path) -> None:
    """Teardown: stop whatever server.json names, by proof first, by pid as a last resort."""
    info = lifecycle.read_server_json(home)
    if info is None:
        return
    try:
        lifecycle.stop(home, force=True)
        return
    except lifecycle.ConsoleError:
        pass
    try:
        os.kill(int(info["pid"]), 9 if os.name == "posix" else 15)
    except OSError:
        pass
    time.sleep(0.2)
