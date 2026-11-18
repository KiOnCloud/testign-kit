"""Throwaway spike for the console plan: does a detached server survive the Bash call that started it?

Run each step as a SEPARATE Bash call inside Claude Code on the machine under test, from the repo root:

    python plans/261118-1431-testign-console/spike/console_spike.py start
    python plans/261118-1431-testign-console/spike/console_spike.py check      # right after start returned
    (wait about 60 seconds, then)
    python plans/261118-1431-testign-console/spike/console_spike.py check
    python plans/261118-1431-testign-console/spike/console_spike.py git        # watch the screen for console windows
    python plans/261118-1431-testign-console/spike/console_spike.py browser    # a browser tab should open
    python plans/261118-1431-testign-console/spike/console_spike.py stop

Variants for start (Windows only): --no-breakaway, --detached (adds DETACHED_PROCESS, the flag the plan
rejected, to confirm the git-window problem). Every command prints one JSON object. Nothing outside
~/.testign-kit/console-spike/ is written. Standard library only; Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 4799
STATE_DIR = Path.home() / ".testign-kit" / "console-spike"
STATE = STATE_DIR / "state.json"
LOG = STATE_DIR / "serve.log"
IS_WINDOWS = os.name == "nt"


def _emit(data: dict) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def _log(message: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")


def _get(path: str, timeout: float = 3.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except OSError:
        return None


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = not IS_WINDOWS


class _Handler(BaseHTTPRequestHandler):
    started = time.time()
    last_request = time.time()

    def log_message(self, *_args) -> None:  # keep stderr silent
        pass

    def _json(self, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        _Handler.last_request = time.time()
        if self.path == "/health":
            self._json({"pid": os.getpid(), "uptime_s": round(time.time() - _Handler.started, 1)})
        elif self.path.startswith("/git"):
            flags = 0
            if IS_WINDOWS and "noconsole=1" in self.path:
                flags = subprocess.CREATE_NO_WINDOW
            started = time.time()
            out = subprocess.run(["git", "--version"], capture_output=True, text=True, creationflags=flags)
            self._json({"creationflags": flags, "returncode": out.returncode,
                        "stdout": out.stdout.strip(), "ms": round((time.time() - started) * 1000)})
        elif self.path == "/shutdown":
            self._json({"stopping": True})
            _log("shutdown requested")
            os._exit(0)
        else:
            self.send_error(404)


def _serve(idle_minutes: float) -> int:
    server = _Server(("127.0.0.1", PORT), _Handler)
    _log(f"serve pid={os.getpid()} port={PORT}")

    import threading

    def idle_watch() -> None:
        while True:
            time.sleep(5)
            if time.time() - _Handler.last_request > idle_minutes * 60:
                _log("idle exit")
                os._exit(0)

    threading.Thread(target=idle_watch, daemon=True).start()
    server.serve_forever()
    return 0


def _start(args: argparse.Namespace) -> int:
    if _get("/health"):
        return _emit({"error": "a spike server already answers on the port; run stop first"})
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, os.path.abspath(__file__), "serve", "--idle-minutes", str(args.idle_minutes)]
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                    "close_fds": True}
    flags_used: list[str] = []
    if IS_WINDOWS:
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        flags_used = ["CREATE_NO_WINDOW", "CREATE_NEW_PROCESS_GROUP"]
        if args.detached:
            flags |= subprocess.DETACHED_PROCESS
            flags_used.append("DETACHED_PROCESS")
        breakaway_denied = False
        if not args.no_breakaway:
            try:
                proc = subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
                flags_used.append("CREATE_BREAKAWAY_FROM_JOB")
            except OSError as exc:
                breakaway_denied = True
                _log(f"breakaway denied: {exc}")
                proc = subprocess.Popen(cmd, creationflags=flags, **kwargs)
        else:
            proc = subprocess.Popen(cmd, creationflags=flags, **kwargs)
    else:
        breakaway_denied = None
        flags_used = ["start_new_session"]
        proc = subprocess.Popen(cmd, start_new_session=True, **kwargs)

    health = None
    for _ in range(50):
        health = _get("/health", timeout=0.5)
        if health:
            break
        time.sleep(0.1)
    state = {"child_pid": proc.pid, "flags": flags_used, "breakaway_denied": breakaway_denied,
             "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "platform": sys.platform,
             "python": sys.version.split()[0]}
    STATE.write_text(json.dumps(state), encoding="utf-8")
    return _emit({**state, "answering": bool(health),
                  "next": "run `check` in a NEW Bash call now, and again after about 60 seconds"})


def _check(_args: argparse.Namespace) -> int:
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    health = _get("/health")
    return _emit({"alive": bool(health), "health": health, "state": state,
                  "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")})


def _git(_args: argparse.Namespace) -> int:
    plain = _get("/git", timeout=15)
    hidden = _get("/git?noconsole=1", timeout=15)
    return _emit({"git_without_flag": plain, "git_with_CREATE_NO_WINDOW": hidden,
                  "observe": "Did a console window flash for either call? Note which one (or none)."})


def _browser(_args: argparse.Namespace) -> int:
    opened = webbrowser.open(f"http://127.0.0.1:{PORT}/health")
    return _emit({"webbrowser_open_returned": opened,
                  "observe": "Did a browser tab open showing the pid and uptime?"})


def _stop(_args: argparse.Namespace) -> int:
    answered = _get("/shutdown")
    time.sleep(0.5)
    return _emit({"stopped": bool(answered), "still_answering": bool(_get("/health", timeout=0.5))})


def main() -> int:
    parser = argparse.ArgumentParser(prog="console_spike")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--idle-minutes", type=float, default=10)
    start.add_argument("--no-breakaway", action="store_true")
    start.add_argument("--detached", action="store_true")
    start.set_defaults(func=_start)
    serve = sub.add_parser("serve")
    serve.add_argument("--idle-minutes", type=float, default=10)
    serve.set_defaults(func=lambda a: _serve(a.idle_minutes))
    for name, func in (("check", _check), ("git", _git), ("browser", _browser), ("stop", _stop)):
        sub.add_parser(name).set_defaults(func=func)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
