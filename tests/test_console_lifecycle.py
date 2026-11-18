import json
import os
import socket
import stat
import subprocess
import sys
import time

import pytest

from console_helpers import RUN_PY, call, cli_env, free_port, kill_server, run_cli, serve_in_thread, write_config
from testign import __version__, config
from testign.console import lifecycle
from testign.console import server as srv

posix_only = pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only")


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    write_config(home, port=free_port(), idle_minutes=30)
    yield home
    kill_server(home)


def _port(home):
    return json.loads(config.config_path(home).read_text(encoding="utf-8"))["console"]["port"]


def _start(home, *extra):
    result = run_cli(home, "console", "start", "--no-browser", *extra)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result


def test_start_reuse_status_stop(home):
    out, result = _start(home)
    assert out["reused"] is False and out["mode"] == "detached" and out["browser_opened"] is False
    assert out["port"] == _port(home) and out["version"] == out["server_version"] == __version__
    info = lifecycle.read_server_json(home)
    assert info["agent_token"] not in result.stdout + result.stderr
    assert "url" not in out

    # The CLI process has exited; the detached server still answers.
    status, _, health = call(out["port"], "GET", "/health")
    assert status == 200 and health["pid"] == info["pid"]

    again, result2 = _start(home)
    assert again["reused"] is True
    assert lifecycle.read_server_json(home)["pid"] == info["pid"]
    assert info["agent_token"] not in result2.stdout + result2.stderr

    st = json.loads(run_cli(home, "console", "status").stdout)
    assert st == {"running": True, "version": __version__, "port": out["port"], "mode": "detached", "busy": False}

    stopped = run_cli(home, "console", "stop")
    assert stopped.returncode == 0 and json.loads(stopped.stdout)["stopped"] is True
    assert not lifecycle.port_in_use(out["port"])
    assert lifecycle.read_server_json(home) is None
    assert json.loads(run_cli(home, "console", "status").stdout)["running"] is False


def test_stale_server_json_is_replaced(home):
    lifecycle.ensure_state_dirs(home)
    stale = {"pid": 999999, "port": _port(home), "instance": "old", "version": "0.0.1",
             "mode": "detached", "agent_token": "stale"}
    lifecycle.write_secure(lifecycle.server_file(home), json.dumps(stale))
    out, _ = _start(home)
    assert out["reused"] is False
    assert lifecycle.read_server_json(home)["instance"] != "old"


def test_foreign_socket_on_the_port_exits_2_without_touching_server_json(home):
    port = _port(home)
    sock = socket.socket()
    if sys.platform == "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(5)
    try:
        result = run_cli(home, "console", "start", "--no-browser")
        assert result.returncode == 2
        assert str(port) in result.stderr and "console.port" in result.stderr
        assert not lifecycle.server_file(home).exists()

        lifecycle.ensure_state_dirs(home)
        foreign = {"pid": 1, "port": port, "instance": "x", "agent_token": "t"}
        lifecycle.write_secure(lifecycle.server_file(home), json.dumps(foreign))
        before = lifecycle.server_file(home).read_bytes()
        assert run_cli(home, "console", "start", "--no-browser").returncode == 2
        assert lifecycle.server_file(home).read_bytes() == before
    finally:
        sock.close()
        lifecycle.server_file(home).unlink(missing_ok=True)


def test_idle_end(home):
    write_config(home, idle_minutes=0.02)
    out, _ = _start(home)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and lifecycle.port_in_use(out["port"]):
        time.sleep(0.2)
    assert not lifecycle.port_in_use(out["port"])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and lifecycle.server_file(home).exists():
        time.sleep(0.1)
    assert not lifecycle.server_file(home).exists()


def test_no_idle_end_while_busy_and_stop_needs_force(home):
    def busy(state):
        state.busy = lambda: True

    thread, holder = serve_in_thread(home, idle_minutes=0.005, setup=busy)
    port = lifecycle.read_server_json(home)["port"]
    time.sleep(1.5)
    assert lifecycle.port_in_use(port)
    assert lifecycle.status(home)["busy"] is True
    with pytest.raises(lifecycle.ConsoleError, match="--force"):
        lifecycle.stop(home)
    assert lifecycle.stop(home, force=True)["stopped"] is True
    thread.join(5)
    assert not thread.is_alive()


def test_reuse_when_the_running_server_has_another_version(home):
    thread, holder = serve_in_thread(home, version="0.0.1")
    first_pid = lifecycle.read_server_json(home)["pid"]
    out = lifecycle.start(home, browser=False, env={})
    assert out["reused"] is True and out["server_version"] == "0.0.1" and out["version"] == __version__
    assert "console stop" in out["version_note"]
    assert lifecycle.read_server_json(home)["pid"] == first_pid
    lifecycle.stop(home)
    thread.join(5)


def test_cloud_session_is_refused_unless_skipped(home):
    with pytest.raises(lifecycle.ConsoleError, match="cloud"):
        lifecycle.start(home, browser=False, env={"CLAUDE_CODE_REMOTE": "true"})
    assert not lifecycle.server_file(home).exists()


def test_ssh_session_starts_and_explains_forwarding(home):
    thread, _ = serve_in_thread(home)
    opened = []
    out = lifecycle.start(home, env={"SSH_CONNECTION": "1 2 3 4"}, opener=opened.append)
    assert out["browser_opened"] is False and not opened and "url" not in out
    assert "console open --print" in out["notes"][0]
    lifecycle.stop(home)
    thread.join(5)


def test_open_hands_a_single_use_code_to_the_browser(home):
    thread, _ = serve_in_thread(home)
    port = lifecycle.read_server_json(home)["port"]
    urls = []
    out = lifecycle.open_console(home, opener=lambda url: urls.append(url) or True)
    assert out == {"browser_opened": True}
    code = urls[0].split("#c=")[1]
    assert urls[0].startswith(f"http://127.0.0.1:{port}/#c=")
    assert call(port, "POST", "/api/session", body={"code": code})[0] == 200
    assert call(port, "POST", "/api/session", body={"code": code})[0] == 403

    out = lifecycle.open_console(home, opener=lambda url: False)
    assert out["browser_opened"] is False and out["single_use"] is True and "#c=" in out["url"]
    printed = lifecycle.open_console(home, print_only=True)
    assert printed["single_use"] is True and "#c=" in printed["url"]
    lifecycle.stop(home)
    thread.join(5)


def test_spawn_flags(monkeypatch, home):
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append((cmd, kwargs))

    monkeypatch.setattr(lifecycle.subprocess, "Popen", FakePopen)
    lifecycle._spawn(4791, "abc", home)
    cmd, kwargs = calls[0]
    assert "--instance" in cmd and not any("token" in part.lower() for part in cmd)
    assert kwargs["stdout"] is subprocess.DEVNULL and kwargs["stderr"] is subprocess.DEVNULL
    if sys.platform == "win32":
        flags = kwargs["creationflags"]
        assert flags & subprocess.CREATE_NO_WINDOW and flags & subprocess.CREATE_NEW_PROCESS_GROUP
        assert flags & subprocess.CREATE_BREAKAWAY_FROM_JOB
        assert not flags & subprocess.DETACHED_PROCESS
    else:
        assert kwargs["start_new_session"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="job object breakaway is Windows only")
def test_spawn_retries_without_breakaway(monkeypatch, home):
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append(kwargs["creationflags"])
            if kwargs["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB:
                raise PermissionError("access denied")

    monkeypatch.setattr(lifecycle.subprocess, "Popen", FakePopen)
    lifecycle._spawn(4791, "abc", home)
    assert len(calls) == 2 and not calls[1] & subprocess.CREATE_BREAKAWAY_FROM_JOB


def test_foreground_serve_keeps_stderr_silent(home):
    port = _port(home)
    proc = subprocess.Popen(
        [sys.executable, str(RUN_PY), "console", "serve", "--foreground"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=cli_env(home),
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and lifecycle.read_server_json(home) is None:
            time.sleep(0.1)
        info = lifecycle.read_server_json(home)
        if info is None:
            proc.kill()
            out, err = proc.communicate(timeout=10)
            raise AssertionError(f"server did not start; exit={proc.returncode} stderr={err.decode(errors='replace')}")
        assert info["mode"] == "foreground" and info["port"] == port
        call(port, "GET", "/health?nonce=1")
        call(port, "GET", "/api/anything")
        call(port, "GET", "/nope", host="evil.example")
        call(port, "POST", "/api/session", body=b"{bad", headers={"Content-Type": "application/json"})
        call(port, "OPTIONS", "/health")
        assert lifecycle.status(home)["mode"] == "foreground"
        lifecycle.stop(home)
        out, err = proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert err == b"" and out == b""


@posix_only
def test_state_folder_and_server_json_modes(home):
    thread, _ = serve_in_thread(home)
    root = lifecycle.console_dir(home)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "jobs").stat().st_mode) == 0o700
    assert stat.S_IMODE(lifecycle.server_file(home).stat().st_mode) == 0o600
    lifecycle.stop(home)
    thread.join(5)


def test_write_secure_replaces_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "x.json"
    lifecycle.write_secure(target, "one")
    lifecycle.write_secure(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_server_reads_config_without_creating_it(tmp_path):
    home = tmp_path / "fresh"
    home.mkdir()
    thread, _ = serve_in_thread(home)
    assert not config.config_path(home).exists()
    lifecycle.stop(home)
    thread.join(5)
    assert not config.config_path(home).exists()


def test_second_serve_on_a_busy_port_leaves_the_live_servers_jobs_alone(home):
    thread, holder = serve_in_thread(home)
    info = lifecycle.read_server_json(home)
    folder = lifecycle.console_dir(home) / "jobs"
    record = {"id": "j20261119-000000-aaaa", "kind": "close", "ticket": "DEMO-1", "state": "queued", "ask": None,
              "asked": [], "created_at": "2026-11-19T00:00:00+07:00", "finished_at": None, "reason": None}
    lifecycle.write_secure(folder / f"{record['id']}.json", json.dumps(record))
    assert lifecycle.serve(home, port=info["port"]) == 2
    on_disk = json.loads((folder / f"{record['id']}.json").read_text(encoding="utf-8"))
    assert on_disk["state"] == "queued"
    assert lifecycle.read_server_json(home)["instance"] == info["instance"]
    lifecycle.stop(home, force=True)
    thread.join(5)
