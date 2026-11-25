import json
import os
import stat
import subprocess
import sys
import threading
import time

import pytest

from console_helpers import RUN_PY, call, cli_env, free_port, kill_server, run_cli, serve_in_thread, write_config
from make_report import write_report

from testign import decisions, templates
from testign.console import client, jobs, lifecycle
from testign.console import server as srv

S = "s-1111222233334444"
ROWS_ASK = {"type": "review-rows", "id": "rows-1", "body": "レビューしてください", "rows": [
    {"row": "q1-a", "q": "Q1", "class": "intent", "feature": "注文確定", "page": "QA/Decisions/order",
     "anchors": ["確定"], "decision": "割引は請求書にも適用", "quote": "請求書にも適用します", "quote_lang": "ja",
     "source": "Backlog comment", "decided_by": "BrSE", "date": "2026-11-18"},
    {"row": "q1-b", "q": "Q1", "class": "fact", "feature": "注文確定", "page": "QA/Decisions/order",
     "anchors": [], "decision": "切り捨て", "quote": "", "source": "code", "decided_by": "Dev", "date": "2026-11-18"},
]}
NEW_PAGE = "| Q1 | 割引 |\n"
PREVIEW = {"mode": "api", "added": ["Q1"], "skipped": [], "superseded": [], "index_repaired": [],
           "approval": decisions.approval_hash([("QA/Decisions/order", None, NEW_PAGE)]),
           "pages": [{"name": "QA/Decisions/order", "exists": False, "updated": None, "diff": "--- a\n+++ b",
                      "old_content": "", "new_content": NEW_PAGE}]}


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    write_config(home, port=free_port())
    write_report(home / "out" / "DEMO-1", tmp_path, "d" * 40, "b" * 40, revision=1)
    write_report(home / "out" / "DEMO-1", tmp_path, "d" * 40, "b" * 40, revision=2)
    yield home
    kill_server(home)


@pytest.fixture
def server(home):
    thread, holder = serve_in_thread(home)
    info = lifecycle.read_server_json(home)
    state = holder["state"]
    code = state.mint_launch_code()
    session = call(info["port"], "POST", "/api/session", body={"code": code})[2]["session"]
    yield {"port": info["port"], "browser": {srv.SESSION_HEADER: session}, "state": state, "info": info,
           "thread": thread}
    try:
        lifecycle.stop(home, force=True)
    except lifecycle.ConsoleError:
        pass
    thread.join(5)


def api(server, method, path, body=None):
    return call(server["port"], method, path, headers=server["browser"], body=body)


def queue_close(server):
    status, _, job = api(server, "POST", "/api/jobs",
                         {"kind": "close", "ticket": "DEMO-1", "tester": "Asher", "ui_lang": "ja"})
    assert status == 200, job
    return job["id"]


def wait_for_state(server, job_id, state, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job = api(server, "GET", f"/api/jobs/{job_id}")[2]
        if job["state"] == state:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job did not reach {state}: {job['state']}")


def test_full_close_round_through_the_bridge(server, home):
    job_id = queue_close(server)
    got = client.wait(S, 5, home=home)
    assert got["session"] == S and got["job"]["id"] == job_id and got["job"]["state"] == "offered"
    assert got["job"]["ui_lang"] == "ja" and got["job"]["base_revision"] == "DEMO-1-survey-r2.md"
    assert client.claim(job_id, S, home=home) == {"ok": True}
    assert client.progress(job_id, S, "レポートを読んでいます", home=home) == {"ok": True}

    result = {}
    agent = threading.Thread(target=lambda: result.setdefault("rows", client.ask(job_id, S, ROWS_ASK, 10, home=home)))
    agent.start()
    job = wait_for_state(server, job_id, "needs-input")
    assert job["ask"]["type"] == "review-rows" and [r["row"] for r in job["ask"]["rows"]] == ["q1-a", "q1-b"]
    assert "answer" not in job["ask"]
    answer = {"ask_id": "rows-1", "answer": {"rows": {
        "q1-a": {"action": "edit", "decision": "割引は請求書と領収書に適用", "anchors": ["確定", "領収書"]},
        "q1-b": {"action": "write"}}}}
    assert call(server["port"], "POST", f"/api/jobs/{job_id}/answer", body=answer,
                headers={srv.AGENT_HEADER: server["info"]["agent_token"]})[0] == 403
    assert api(server, "POST", f"/api/jobs/{job_id}/answer", answer)[0] == 200
    agent.join(10)
    assert result["rows"]["answers"]["rows"]["q1-a"]["decision"] == "割引は請求書と領収書に適用"
    assert api(server, "POST", f"/api/jobs/{job_id}/answer", answer)[0] == 409

    agent = threading.Thread(target=lambda: result.setdefault(
        "diff", client.ask(job_id, S, client.ask_from_preview(PREVIEW), 10, home=home)))
    agent.start()
    job = wait_for_state(server, job_id, "needs-input")
    assert job["ask"]["type"] == "confirm-diff" and job["ask"]["preview"]["pages"][0]["exists"] is False
    assert client.approval(job_id, S, home=home) == {"approval": None}
    assert api(server, "POST", f"/api/jobs/{job_id}/answer",
               {"ask_id": job["ask"]["id"], "answer": {"confirm": True}})[0] == 200
    agent.join(10)
    assert result["diff"]["answers"] == {"confirm": True}
    assert client.approval(job_id, S, home=home) == {"approval": PREVIEW["approval"]}

    assert client.done(job_id, S, "done", "2 行を書きました", home=home) == {"ok": True}
    job = api(server, "GET", f"/api/jobs/{job_id}")[2]
    assert job["state"] == "done" and job["summary"] == "2 行を書きました"
    assert [a["type"] for a in job["asked"]] == ["review-rows", "confirm-diff"]
    assert job["progress"][0]["message"] == "レポートを読んでいます"
    assert job["confirmed_approval"] == PREVIEW["approval"]
    listing = api(server, "GET", "/api/jobs")[2]["jobs"]
    assert listing[0]["id"] == job_id


def test_paste_pages_from_a_manual_preview(server, home):
    job_id = queue_close(server)
    client.wait(S, 5, home=home)
    client.claim(job_id, S, home=home)
    manual = {"mode": "manual", "added": [], "pages": [{"page": "order", "name": "QA/Decisions/order",
                                                       "exists": True, "diff": "x", "new_content": "| Q1 |"}]}
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", client.ask(job_id, S, client.ask_from_preview(manual), 10,
                                                                       home=home)))
    t.start()
    job = wait_for_state(server, job_id, "needs-input")
    assert job["ask"]["type"] == "paste-pages" and job["ask"]["pages"][0]["new_content"] == "| Q1 |"
    api(server, "POST", f"/api/jobs/{job_id}/answer", {"ask_id": job["ask"]["id"], "answer": {"done": True}})
    t.join(10)
    assert out["a"]["answers"] == {"done": True}


def test_killed_client_during_wait_then_a_new_wait_gets_the_job(server, home):
    proc = subprocess.Popen([sys.executable, str(RUN_PY), "console", "wait", "--session", S, "--timeout", "30"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=cli_env(home))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not api(server, "GET", "/api/state")[2]["agent"]["waiting"]:
        time.sleep(0.05)
    proc.kill()
    proc.wait(10)
    job_id = queue_close(server)
    time.sleep(0.3)
    got = client.wait(S, 5, home=home)
    assert got["job"]["id"] == job_id


def test_offer_not_claimed_returns_to_the_queue(server, home, monkeypatch):
    monkeypatch.setattr(jobs, "OFFER_TIMEOUT", 0.5)
    job_id = queue_close(server)
    assert client.wait(S, 5, home=home)["job"]["id"] == job_id
    wait_for_state(server, job_id, "queued", seconds=5)


def test_close_queued_on_r2_fails_when_r3_exists_at_claim(server, home, tmp_path):
    job_id = queue_close(server)
    client.wait(S, 5, home=home)
    write_report(home / "out" / "DEMO-1", tmp_path, "d" * 40, "b" * 40, revision=3)
    assert client.claim(job_id, S, home=home) == {"ok": False, "reason": "revision-moved"}
    job = api(server, "GET", f"/api/jobs/{job_id}")[2]
    assert job["state"] == "failed" and job["reason"] == "revision-moved"


def test_wiki_update_with_job_refuses_an_unconfirmed_approval(server, home, tmp_path):
    job_id = queue_close(server)
    client.wait(S, 5, home=home)
    client.claim(job_id, S, home=home)
    rows = tmp_path / "rows.json"
    rows.write_text("[]", encoding="utf-8")
    result = run_cli(home, "wiki-update", "--rows", str(rows), "--approval", "e" * 64, "--job", job_id,
                     "--session", S)
    assert result.returncode == 2 and "not confirmed" in result.stderr
    result = run_cli(home, "wiki-update", "--rows", str(rows), "--approval", "e" * 64, "--job", job_id)
    assert result.returncode == 2 and "go together" in result.stderr


def test_agent_cli_commands_and_error_codes(server, home):
    result = run_cli(home, "console", "wait", "--session", S, "--timeout", "0")
    assert result.returncode == 0 and json.loads(result.stdout) == {"session": S, "job": None}
    result = run_cli(home, "console", "wait", "--session", "s-9999888877776666", "--timeout", "0")
    assert result.returncode == 2 and json.loads(result.stderr)["error"]["code"] == "session-refused"
    result = run_cli(home, "console", "claim", "j-nope", "--session", S)
    assert result.returncode == 2 and json.loads(result.stderr)["error"]["code"] == "not-found"
    result = run_cli(home, "console", "wait", "--session", "x", "--timeout", "0")
    assert json.loads(result.stderr)["error"]["code"] == "bad-request"


def test_agent_cli_without_a_server(tmp_path):
    home = tmp_path / "nobody"
    home.mkdir()
    result = run_cli(home, "console", "wait", "--session", S, "--timeout", "0")
    assert result.returncode == 2 and json.loads(result.stderr)["error"]["code"] == "no-server"


def test_restart_fails_open_and_queued_jobs(home):
    # Records left by a server that died (no shutdown hook ran): one running, one queued.
    folder = lifecycle.ensure_state_dirs(home) / "jobs"
    for job_id, state in (("j20261118-100000-aaaa", "running"), ("j20261118-100001-bbbb", "queued")):
        record = {"id": job_id, "kind": "close", "ticket": "DEMO-1", "state": state, "ask": None, "asked": [],
                  "created_at": "2026-11-18T10:00:00+07:00", "finished_at": None, "reason": None}
        lifecycle.write_secure(folder / f"{job_id}.json", json.dumps(record))
    thread, holder = serve_in_thread(home)
    bridge = holder["state"].bridge
    for job_id in ("j20261118-100000-aaaa", "j20261118-100001-bbbb"):
        assert bridge.jobs[job_id]["state"] == "failed" and bridge.jobs[job_id]["reason"] == "server-stopped"
        on_disk = json.loads((folder / f"{job_id}.json").read_text(encoding="utf-8"))
        assert on_disk["reason"] == "server-stopped"
    assert lifecycle.status(home)["busy"] is False

    job = bridge.create({"kind": "close", "ticket": "DEMO-1", "tester": "A", "ui_lang": "en"})
    assert lifecycle.stop(home, force=True)["stopped"] is True
    thread.join(5)
    on_disk = json.loads((folder / f"{job['id']}.json").read_text(encoding="utf-8"))
    assert on_disk["state"] == "failed" and on_disk["reason"] == "server-stopped"


def test_release_and_mark_failed_from_the_console(server, home, monkeypatch):
    job_id = queue_close(server)
    client.wait(S, 5, home=home)
    client.claim(job_id, S, home=home)
    assert api(server, "POST", f"/api/jobs/{job_id}/fail", {})[0] == 409
    state = api(server, "GET", "/api/state")[2]
    assert state["agent"]["attached"] is True and state["open"]["id"] == job_id and state["open"]["silent"] is False
    assert api(server, "POST", "/api/agent/release", {})[2] == {"released": True}
    job = api(server, "GET", f"/api/jobs/{job_id}")[2]
    assert job["reason"] == "session-lost"

    second = queue_close(server)
    assert api(server, "POST", f"/api/jobs/{second}/cancel", {})[0] == 200
    assert api(server, "GET", f"/api/jobs/{second}")[2]["state"] == "cancelled"


def test_survey_repo_must_be_a_git_clone(server, home, demo_repo, tmp_path):
    wt = tmp_path / "wt"
    demo_repo.git("worktree", "add", "-q", str(wt), "develop")
    body = {"kind": "survey", "ticket": "DEMO-7", "ui_lang": "en"}
    assert api(server, "POST", "/api/jobs", {**body, "repo": str(wt)})[0] == 200
    plain = tmp_path / "plain"
    plain.mkdir()
    status, _, data = api(server, "POST", "/api/jobs", {**body, "repo": str(plain)})
    assert status == 400


def test_testcase_checks_against_templates_and_rows(server, home):
    body = {"kind": "testcase", "ticket": "DEMO-1", "ui_lang": "en"}
    assert api(server, "POST", "/api/jobs", {**body, "mode": "write"})[2]["error"]["code"] == "template-required"
    from pathlib import Path
    sample = Path(__file__).resolve().parent.parent / "templates" / "testcase-template-sample.xlsx"
    templates.register(sample, "a", home=home)
    assert api(server, "POST", "/api/jobs", {**body, "mode": "write", "template": "zz"})[0] == 400
    assert api(server, "POST", "/api/jobs", {**body, "mode": "trace", "template": "a"})[0] == 400
    status, _, data = api(server, "POST", "/api/jobs", {**body, "mode": "write", "focus": ["R9"]})
    assert status == 400 and data["error"]["code"] == "unknown-row"
    assert api(server, "POST", "/api/jobs", {**body, "mode": "write", "focus": ["R2"]})[0] == 200


def test_busy_server_does_not_end_idle_and_needs_force(server, home):
    queue_close(server)
    assert lifecycle.status(home)["busy"] is True
    with pytest.raises(lifecycle.ConsoleError):
        lifecycle.stop(home)


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only")
def test_job_files_are_private(server, home):
    job_id = queue_close(server)
    path = lifecycle.console_dir(home) / "jobs" / f"{job_id}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_start_prints_a_new_session_each_time(home):
    first = json.loads(run_cli(home, "console", "start", "--no-browser").stdout)
    second = json.loads(run_cli(home, "console", "start", "--no-browser").stdout)
    assert first["session"] != second["session"] and second["reused"] is True
    assert first["session"].startswith("s-")


def test_a_browser_session_opened_during_the_job_cannot_answer(server, home):
    job_id = queue_close(server)
    client.wait(S, 5, home=home)
    client.claim(job_id, S, home=home)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", client.ask(job_id, S, ROWS_ASK, 5, home=home)),
                         daemon=True)
    t.start()
    job = wait_for_state(server, job_id, "needs-input")
    code = server["state"].mint_launch_code()
    new_tab = call(server["port"], "POST", "/api/session", body={"code": code})[2]["session"]
    answer = {"ask_id": job["ask"]["id"], "answer": {"rows": {"q1-a": {"action": "skip"}, "q1-b": {"action": "skip"}}}}
    status, _, data = call(server["port"], "POST", f"/api/jobs/{job_id}/answer", body=answer,
                           headers={srv.SESSION_HEADER: new_tab})
    assert status == 403 and data["error"]["code"] == "session-too-new"
    assert api(server, "POST", f"/api/jobs/{job_id}/answer", answer)[0] == 200
    t.join(10)
