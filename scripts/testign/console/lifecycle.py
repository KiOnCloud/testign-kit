"""Start, reuse, find stale, stop and run the per-user console server.

State lives in ``~/.testign-kit/console/`` (mode 0700). ``server.json`` (mode 0600) names the
running server: pid (the server's own, not a launcher's), port, instance, version, started_at,
mode and the agent token. A server proves itself by answering ``/health?nonce=`` with
HMAC-SHA256(agent token, nonce); nothing is reused or stopped without that proof.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .. import __version__, config, fsutil
from . import server as srv

CONSOLE_DIR_NAME = "console"
SERVER_FILE = "server.json"
LOG_FILE = "server.log"
START_WAIT = 5.0
STOP_WAIT = 10.0
RUN_PY = Path(__file__).resolve().parents[2] / "run.py"


class ConsoleError(Exception):
    """A console command cannot go on; the message says what to do."""


# paths and secure writes ----------------------------------------------------------------------
def console_dir(home: Path | None = None) -> Path:
    return config.config_dir(home) / CONSOLE_DIR_NAME


def server_file(home: Path | None = None) -> Path:
    return console_dir(home) / SERVER_FILE


def ensure_state_dirs(home: Path | None = None) -> Path:
    root = console_dir(home)
    for path in (root, root / "jobs", root / "uploads"):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(path, 0o700)
    return root


def write_secure(path: Path, data: bytes | str) -> None:
    """Write ``data`` with mode 0600 to a fresh temporary sibling, then replace ``path``."""
    fsutil.atomic_write_bytes(path, data.encode("utf-8") if isinstance(data, str) else data, mode=0o600)


def read_server_json(home: Path | None = None) -> dict | None:
    try:
        data = json.loads(server_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    needed = ("pid", "port", "instance", "agent_token")
    if not isinstance(data, dict) or any(k not in data for k in needed):
        return None
    return data


def remove_server_json_if(home: Path | None, instance: str) -> bool:
    """Delete ``server.json`` only while it still names ``instance``."""
    current = read_server_json(home)
    if current is None or current.get("instance") != instance:
        return False
    try:
        server_file(home).unlink()
    except OSError:
        return False
    return True


# HTTP to the local server ---------------------------------------------------------------------
class NoAnswer(Exception):
    """Something holds the port but did not answer like a console server."""


def request(port: int, method: str, path: str, *, token: str | None = None, body: Any = None,
            timeout: float = 3.0) -> tuple[int, Any]:
    """One request to 127.0.0.1:port. Raises ConnectionRefusedError or NoAnswer."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    headers = {"Host": f"127.0.0.1:{port}"}
    payload = None
    if token:
        headers[srv.AGENT_HEADER] = token
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
    except ConnectionRefusedError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        if isinstance(exc, ConnectionRefusedError):
            raise
        raise NoAnswer(type(exc).__name__) from None
    finally:
        conn.close()
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        raise NoAnswer("not json") from None
    return resp.status, data


def expected_proof(token: str, nonce: str) -> str:
    return hmac.new(token.encode(), nonce.encode(), hashlib.sha256).hexdigest()


def probe(info: dict, timeout: float = 3.0) -> tuple[str, dict | None]:
    """Return ("ok", health), ("refused", None) or ("foreign", None) for a ``server.json``."""
    nonce = secrets.token_hex(16)
    try:
        status, data = request(int(info["port"]), "GET", f"/health?nonce={nonce}", timeout=timeout)
    except ConnectionRefusedError:
        return "refused", None
    except NoAnswer:
        return "foreign", None
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("proof"), str):
        return "foreign", None
    if not hmac.compare_digest(data["proof"], expected_proof(str(info["agent_token"]), nonce)):
        return "foreign", None
    return "ok", data


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def _port_message(port: int, home: Path | None) -> str:
    return (
        f"port {port} is held by a program that is not this user's testign console. "
        f"Find it with `netstat -ano | findstr :{port}` (Windows) or `lsof -i :{port}` (macOS), "
        f"or choose another port in console.port of {config.config_path(home)}."
    )


def _port_from_config(cfg: dict) -> int:
    console = cfg.get("console") if isinstance(cfg.get("console"), dict) else {}
    port = console.get("port", 4791)
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise ConsoleError("console.port in config.json must be a whole number from 1024 to 65535")
    return port


def _idle_from_config(cfg: dict) -> float:
    console = cfg.get("console") if isinstance(cfg.get("console"), dict) else {}
    minutes = console.get("idle_minutes", 30)
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
        raise ConsoleError("console.idle_minutes in config.json must be a positive number")
    return float(minutes)


# spawning -------------------------------------------------------------------------------------
def _spawn(port: int, instance: str, home: Path | None) -> subprocess.Popen:
    """Start ``console serve`` detached, stdio discarded, outliving the calling command."""
    cmd = [sys.executable, str(RUN_PY), "console", "serve", "--port", str(port), "--instance", instance]
    if home is not None:
        cmd += ["--home", str(home)]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": str(ensure_state_dirs(home)),
    }
    if sys.platform == "win32":
        # CREATE_NO_WINDOW gives the server a hidden console that git and other console
        # programs inherit, so none of them opens a window. DETACHED_PROCESS would not.
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
        except OSError:
            return subprocess.Popen(cmd, creationflags=flags, **kwargs)
    return subprocess.Popen(cmd, start_new_session=True, **kwargs)


def _find_or_spawn(home: Path | None, port: int) -> tuple[dict, dict, bool]:
    info = read_server_json(home)
    if info is not None:
        kind, health = probe(info)
        if kind == "ok":
            return info, health or {}, True
        if kind == "refused":
            remove_server_json_if(home, str(info["instance"]))
        else:
            raise ConsoleError(_port_message(int(info["port"]), home))
    if port_in_use(port):
        raise ConsoleError(_port_message(port, home))
    instance = secrets.token_hex(8)
    proc = _spawn(port, instance, home)
    deadline = time.monotonic() + START_WAIT
    while time.monotonic() < deadline:
        info = read_server_json(home)
        if info is not None:
            kind, health = probe(info)
            if kind == "ok":
                return info, health or {}, info.get("instance") != instance
        if proc.poll() is not None and info is None:
            break
        time.sleep(0.1)
    if port_in_use(port):
        raise ConsoleError(_port_message(port, home))
    raise ConsoleError(f"the console server did not start on port {port}; see {console_dir(home) / LOG_FILE}")


# commands -------------------------------------------------------------------------------------
def new_session_id() -> str:
    """A fresh agent session id; every ``console start`` hands out a new one."""
    return "s-" + secrets.token_hex(8)


def _launch_url(info: dict) -> str:
    status, data = request(int(info["port"]), "POST", "/agent/launch-code", token=str(info["agent_token"]), body={})
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("code"), str):
        raise ConsoleError("the console server refused to make a launch code")
    return f"http://127.0.0.1:{info['port']}/#c={data['code']}"


def _open_in_browser(info: dict, opener: Callable[[str], bool]) -> dict:
    url = _launch_url(info)
    try:
        opened = bool(opener(url))
    except Exception:  # noqa: BLE001 - any browser failure falls back to printing the URL
        opened = False
    if opened:
        return {"browser_opened": True}
    return {"browser_opened": False, "url": url, "single_use": True,
            "message": "No browser could be opened. Open this URL once; it works a single time."}


def start(home: Path | None = None, *, browser: bool = True, skip_cloud_check: bool = False,
          env: dict | None = None, opener: Callable[[str], bool] = webbrowser.open) -> dict:
    env = os.environ if env is None else env
    if str(env.get("CLAUDE_CODE_REMOTE", "")).lower() == "true" and not skip_cloud_check:
        raise ConsoleError(
            "this is a cloud session; the console runs on the tester's own machine, where the browser "
            "can reach 127.0.0.1. Run it from Claude Code on your machine, or pass --skip-cloud-check."
        )
    cfg = config.load(home, create=False)
    port = _port_from_config(cfg)
    info, health, reused = _find_or_spawn(home, port)
    out: dict[str, Any] = {
        "session": new_session_id(),
        "reused": reused,
        "version": __version__,
        "server_version": health.get("version", info.get("version")),
        "port": int(info["port"]),
        "mode": info.get("mode", "detached"),
    }
    if reused and out["server_version"] != __version__:
        out["version_note"] = (
            f"the running server is version {out['server_version']}, this plugin is {__version__}; "
            "`console stop` then `console start` replaces it when no job is open"
        )
    if env.get("SSH_CONNECTION"):
        out["browser_opened"] = False
        out["notes"] = [
            f"this is an SSH session: forward port {out['port']} to your machine "
            f"(ssh -L {out['port']}:127.0.0.1:{out['port']}), then run `console open --print` "
            "for a single-use URL"
        ]
    elif browser:
        out.update(_open_in_browser(info, opener))
    else:
        out["browser_opened"] = False
    return out


def _proven(home: Path | None) -> tuple[dict, dict]:
    info = read_server_json(home)
    if info is None:
        raise ConsoleError("the console is not running; start it with `console start`")
    kind, health = probe(info)
    if kind == "refused":
        remove_server_json_if(home, str(info["instance"]))
        raise ConsoleError("the console is not running; start it with `console start`")
    if kind != "ok":
        raise ConsoleError(_port_message(int(info["port"]), home))
    return info, health or {}


def open_console(home: Path | None = None, *, print_only: bool = False,
                 opener: Callable[[str], bool] = webbrowser.open) -> dict:
    info, _health = _proven(home)
    if print_only:
        return {"url": _launch_url(info), "single_use": True}
    return _open_in_browser(info, opener)


def status(home: Path | None = None) -> dict:
    info = read_server_json(home)
    if info is None:
        port = _port_from_config(config.load(home, create=False))
        return {"running": False, "version": None, "port": port, "mode": None, "busy": False}
    kind, health = probe(info)
    if kind != "ok":
        if kind == "refused":
            remove_server_json_if(home, str(info["instance"]))
        return {"running": False, "version": None, "port": int(info["port"]), "mode": None, "busy": False,
                **({"error": "port held by another program"} if kind == "foreign" else {})}
    health = health or {}
    return {"running": True, "version": health.get("version"), "port": int(info["port"]),
            "mode": info.get("mode"), "busy": bool(health.get("busy"))}


def _wait_port_closed(port: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not port_in_use(port):
            return True
        time.sleep(0.1)
    return not port_in_use(port)


def stop(home: Path | None = None, *, force: bool = False) -> dict:
    info = read_server_json(home)
    if info is None:
        return {"stopped": False, "running": False}
    kind, health = probe(info)
    if kind == "refused":
        remove_server_json_if(home, str(info["instance"]))
        return {"stopped": False, "running": False}
    if kind != "ok":
        raise ConsoleError(_port_message(int(info["port"]), home))
    health = health or {}
    if health.get("busy") and not force:
        raise ConsoleError("jobs are open in the console; finish them, or stop with --force (they fail as server-stopped)")
    port = int(info["port"])
    try:
        status_code, _ = request(port, "POST", "/agent/shutdown", token=str(info["agent_token"]),
                                 body={"force": force})
    except (ConnectionRefusedError, NoAnswer):
        status_code = 0
    if status_code == 409:
        raise ConsoleError("jobs are open in the console; stop with --force")
    if not _wait_port_closed(port, STOP_WAIT):
        pid = health.get("pid")
        if isinstance(pid, int) and pid == info.get("pid"):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        if not _wait_port_closed(port, STOP_WAIT):
            raise ConsoleError(f"the console server on port {port} did not stop")
    remove_server_json_if(home, str(info["instance"]))
    return {"stopped": True, "running": False}


# the server process ---------------------------------------------------------------------------
def install_routes(state: srv.ConsoleState) -> None:
    """Every route group beyond the base routes: read API, template management and the job bridge."""
    from . import jobs, readapi, templates_api  # noqa: PLC0415 - they import this module

    readapi.install(state)
    templates_api.install(state)
    jobs.install(state)


def serve(home: Path | None = None, *, port: int | None = None, instance: str | None = None,
          mode: str = "detached", version: str = __version__, idle_minutes: float | None = None,
          ready: Callable[[srv.ConsoleState], None] | None = None,
          setup: Callable[[srv.ConsoleState], None] | None = None) -> int:
    """Run the server until shutdown or idle end. Writes ``server.json`` only after the bind."""
    cfg = config.load(home, create=False)
    port = _port_from_config(cfg) if port is None else port
    idle_seconds = (idle_minutes if idle_minutes is not None else _idle_from_config(cfg)) * 60
    root = ensure_state_dirs(home)
    instance = instance or secrets.token_hex(8)
    state = srv.ConsoleState(version=version, agent_token="", home=home, log_path=root / LOG_FILE)
    srv.install_base_routes(state)
    install_routes(state)
    if setup is not None:
        setup(state)
    try:
        httpd = srv.ConsoleServer(port, state)
    except OSError:
        state.log.write("-", "bind", 0, "0ms", "port-busy")
        return 2
    state.agent_token = secrets.token_urlsafe(32)
    bound_port = httpd.server_address[1]
    info = {
        "pid": os.getpid(),
        "port": bound_port,
        "instance": instance,
        "version": version,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "agent_token": state.agent_token,
    }
    write_secure(server_file(home), json.dumps(info, indent=2) + "\n")
    state.log.write("-", "start", 0, "0ms", mode)

    stop_idle = threading.Event()

    def idle_watch() -> None:
        interval = max(0.2, min(60.0, idle_seconds / 4))
        while not stop_idle.wait(interval):
            if state.idle_for() >= idle_seconds and state.held_calls == 0 and not state.is_busy():
                state.log.write("-", "idle", 0, "0ms", "idle-end")
                srv.shutdown_server(state)
                return

    threading.Thread(target=idle_watch, daemon=True).start()
    if ready is not None:
        ready(state)
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        stop_idle.set()
        for hook in list(state.shutdown_hooks):
            try:
                hook()
            except Exception:  # noqa: BLE001
                pass
        httpd.server_close()
        remove_server_json_if(home, instance)
        state.log.write("-", "stop", 0, "0ms", "-")
    return 0
