"""The AskUserQuestion hook sends a question to the console while the session works on a job."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from console_helpers import call, free_port, kill_server, serve_in_thread, write_config
from make_report import write_report

from testign.console import client, lifecycle
from testign.console import server as srv

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "ask_to_console.py"
_spec = importlib.util.spec_from_file_location("ask_to_console", HOOK)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

S = "s-1111222233334444"
CLAUDE = "0b6f8c1e-1111-2222-3333-444455556666"
QUESTIONS = [{"question": "Which environment?", "header": "Env", "multiSelect": False,
              "options": [{"label": "Staging", "description": "stg"}, {"label": "Dev", "description": "dev"}]}]


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    write_config(home, port=free_port())
    write_report(home / "out" / "DEMO-1", tmp_path, "d" * 40, "b" * 40, revision=1)
    yield home
    kill_server(home)


@pytest.fixture
def server(home):
    thread, holder = serve_in_thread(home)
    info = lifecycle.read_server_json(home)
    state = holder["state"]
    session = call(info["port"], "POST", "/api/session", body={"code": state.mint_launch_code()})[2]["session"]
    yield {"port": info["port"], "browser": {srv.SESSION_HEADER: session}}
    try:
        lifecycle.stop(home, force=True)
    except lifecycle.ConsoleError:
        pass
    thread.join(5)


def claimed_job(server, home, claude=CLAUDE):
    status, _, job = call(server["port"], "POST", "/api/jobs", headers=server["browser"],
                          body={"kind": "close", "ticket": "DEMO-1", "tester": "Asher", "ui_lang": "ja"})
    assert status == 200, job
    assert client.wait(S, 5, home=home)["job"]["id"] == job["id"]
    assert client.claim(job["id"], S, home=home, claude_session=claude) == {"ok": True}
    return job["id"]


def payload(session=CLAUDE, questions=QUESTIONS):
    return {"session_id": session, "tool_name": "AskUserQuestion", "tool_input": {"questions": questions}}


def test_no_console_lets_the_question_through(home):
    assert hook.decide(payload(), home=home) is None


def test_no_claimed_job_lets_the_question_through(server, home):
    assert hook.decide(payload(), home=home) is None
    assert client.claimed(CLAUDE, home=home) == {"job": None}


def test_question_of_the_working_session_goes_to_the_console(server, home):
    job = claimed_job(server, home)
    assert client.claimed(CLAUDE, home=home) == {"job": job, "session": S, "kind": "close", "ui_lang": "ja"}
    out = hook.decide(payload(), home=home)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    reason = out["permissionDecisionReason"]
    assert f"console ask {job} --session {S} --question" in reason and "(ja)" in reason
    path = Path(reason.split('--question "')[1].split('"')[0])
    ask = json.loads(path.read_text(encoding="utf-8"))
    assert ask["type"] == "questions" and ask["questions"][0]["options"][1]["label"] == "Dev"
    # The written ask is one the console accepts.
    from testign.console import jobs  # noqa: PLC0415
    assert jobs.validate_ask(ask)["questions"][0]["question"] == "Which environment?"


def test_another_claude_session_is_not_redirected(server, home):
    claimed_job(server, home)
    assert hook.decide(payload(session="99999999-aaaa-bbbb-cccc-dddddddddddd"), home=home) is None


def test_claim_reads_the_claude_session_from_the_environment(server, home, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", CLAUDE)
    job = claimed_job(server, home, claude=None)
    assert client.claimed(CLAUDE, home=home)["job"] == job
    assert client.claude_session_id({}) is None


def test_hook_process_fails_open(tmp_path):
    # Windows Python needs SYSTEMROOT to start at all; nothing else of the caller's environment is kept.
    env = {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "PATH": "",
           **{k: os.environ[k] for k in ("SYSTEMROOT",) if k in os.environ}}
    result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload()), text=True,
                            capture_output=True, env=env)
    assert result.returncode == 0 and result.stdout == ""
    result = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True, capture_output=True, env=env)
    assert result.returncode == 0
