import json
import os
import stat
import time
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from console_helpers import InProcessServer, call  # noqa: E402
from make_webtest_run import FakeConsole, build  # noqa: E402

from testign import login_scenarios, webtest  # noqa: E402
from testign.console import lifecycle, templates_api, webtest_api  # noqa: E402
from testign.console import server as srv  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
AGENT = "s-agentagentagent1"


def make_state(home: Path) -> srv.ConsoleState:
    state = srv.ConsoleState(version="t", agent_token="agent", home=home)
    srv.install_base_routes(state)
    lifecycle.install_routes(state)
    return state


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    login_scenarios.save_project(home, "demo", ["dev.example.test"])
    return home


@pytest.fixture
def run_id(home):
    return build(home / "Downloads" / "webtest", FakeConsole())


@pytest.fixture
def console(home, run_id):
    server = InProcessServer(make_state(home))
    server.headers = {srv.SESSION_HEADER: server.session()}
    yield server
    server.close()


def browser(console, method, path, body=None, headers=None):
    return call(console.port, method, path, headers={**console.headers, **(headers or {})}, body=body)


def agent(console, method, path, body=None):
    return call(console.port, method, path, headers={srv.AGENT_HEADER: "agent"}, body=body, timeout=15)


class JobReader:
    """The job view the run commands read, through this test's console."""

    def __init__(self, console):
        self.console = console

    def job(self, job, session):
        status, _, data = agent(self.console, "GET", f"/agent/jobs/{job}/info?session={session}")
        if status != 200:
            raise ValueError(data)
        return data


def folder_of(home, run_id):
    return webtest.find_run(home / "Downloads" / "webtest", run_id)


def queue_run_job(console, run_id):
    status, _, job = browser(console, "POST", "/api/jobs",
                             {"kind": "webtest-run", "ui_lang": "en", "run": run_id, "tester": "T"})
    assert status == 200, job
    assert agent(console, "POST", "/agent/wait", {"session": AGENT, "timeout": 0})[2]["job"]["id"] == job["id"]
    assert agent(console, "POST", f"/agent/jobs/{job['id']}/claim", {"session": AGENT})[0] == 200
    return job["id"]


def park_r02(console, home, run_id, job):
    folder = folder_of(home, run_id)
    got = webtest.next_row(folder, JobReader(console), job, AGENT)
    assert got["row"] == "r02"  # the only row that needs no sign-in
    webtest.park(folder, "r02", {"body": "Which footer?"})
    return folder


# read routes -----------------------------------------------------------------------------------------
def test_runs_listing_and_detail(console, home, run_id):
    (home / "Downloads" / "webtest" / "W20261119-0900-broken").mkdir()
    (home / "Downloads" / "webtest" / "W20261119-0900-broken" / "run.json").write_text("{", encoding="utf-8")
    status, _, data = browser(console, "GET", "/api/webtest/runs")
    assert status == 200
    by_id = {r["id"]: r for r in data["runs"]}
    assert by_id["W20261119-0900-broken"] == {"id": "W20261119-0900-broken", "readable": False}
    assert by_id[run_id]["counts"]["queued"] == 4 and by_id[run_id]["confirmed"] is True
    status, _, run = browser(console, "GET", f"/api/webtest/runs/{run_id}")
    assert status == 200 and run["hosts"] == ["dev.example.test"] and len(run["cases"]) == 8
    assert run["waiting_on_tester"] == 1 and run["jobs"] == []


@pytest.mark.parametrize("name", ["..", "%2e%2e", "a%2Fb", "a%5Cb", "NUL", "W20261119-1000-x%2F..", "nope"])
def test_bad_run_names_get_404(console, name):
    assert browser(console, "GET", f"/api/webtest/runs/{name}")[0] == 404
    assert browser(console, "POST", f"/api/webtest/runs/{name}/finish", {})[0] == 404


def test_evidence_and_captures_are_resolved_by_listing(console, home, run_id):
    folder = folder_of(home, run_id)
    (folder / "evidence" / "r02-a1-1.png").write_bytes(PNG)
    (folder / "source" / "r01.png").write_bytes(PNG)
    (folder / "source" / "r01.json").write_text("{}", encoding="utf-8")
    status, headers, data = browser(console, "GET", f"/api/webtest/runs/{run_id}/evidence/r02-a1-1.png")
    assert status == 200 and data == PNG and headers["Content-Type"] == "image/png"
    assert browser(console, "GET", f"/api/webtest/runs/{run_id}/captures/r01.png")[0] == 200
    for name in ("r01.json", "..%2Frun.json", "%2e%2e", "r02-a1-1.png%00", "NUL"):
        assert browser(console, "GET", f"/api/webtest/runs/{run_id}/captures/{name}")[0] == 404, name


# answers and results ------------------------------------------------------------------------------------
def test_answer_is_stored_server_side_and_handed_to_the_agent_once(console, home, run_id):
    job = queue_run_job(console, run_id)
    park_r02(console, home, run_id, job)
    assert webtest_api.needs_input(console.state) == 2  # the parked question and r08 awaiting the tester
    status, _, data = browser(console, "POST", f"/api/webtest/runs/{run_id}/answers/r02-a1", {"action": "delegate"})
    assert status == 400 and data["error"]["code"] == "preconditions-required"
    status, _, data = browser(console, "POST", f"/api/webtest/runs/{run_id}/answers/r02-a1",
                              {"action": "delegate", "preconditions": "the footer of the top page"})
    assert status == 200, data
    assert browser(console, "POST", f"/api/webtest/runs/{run_id}/answers/r09-a1", {"action": "skip"})[0] == 409
    assert webtest_api.needs_input(console.state) == 1
    pending = agent(console, "POST", f"/agent/webtest/runs/{run_id}/pending", {"session": AGENT, "job": job})[2]
    assert pending["answers"]["r02-a1"]["preconditions"] == "the footer of the top page"
    assert pending["finish"] is False
    folder = folder_of(home, run_id)
    run = webtest.load(folder)
    applied, ignored = webtest.apply_pending(folder, run, pending, Path("/nonexistent"))
    assert applied == ["r02-a1"] and not ignored
    webtest.save(folder, run)
    assert agent(console, "POST", f"/agent/webtest/runs/{run_id}/applied",
                 {"session": AGENT, "job": job, "ids": applied})[0] == 200
    again = agent(console, "POST", f"/agent/webtest/runs/{run_id}/pending", {"session": AGENT, "job": job})[2]
    assert again["answers"] == {}
    assert webtest.case_of(webtest.load(folder), "r02")["state"] == "queued"


def test_result_for_a_row_parked_then_run_by_the_tester_reaches_the_agent(console, home, run_id):
    job = queue_run_job(console, run_id)
    folder = park_r02(console, home, run_id, job)
    assert browser(console, "POST", f"/api/webtest/runs/{run_id}/answers/r02-a1", {"action": "self-run"})[0] == 200
    pending = agent(console, "POST", f"/agent/webtest/runs/{run_id}/pending", {"session": AGENT, "job": job})[2]
    run = webtest.load(folder)
    applied, _ = webtest.apply_pending(folder, run, pending, home / "no-images")
    webtest.save(folder, run)
    agent(console, "POST", f"/agent/webtest/runs/{run_id}/applied", {"session": AGENT, "job": job, "ids": applied})
    assert webtest.case_of(webtest.load(folder), "r02")["state"] == "awaiting-tester"
    status, _, data = browser(console, "POST", f"/api/webtest/runs/{run_id}/rows/r02/result", {"verdict": "pass"})
    assert status == 200 and data["result"] != "r02-a1", data
    pending = agent(console, "POST", f"/agent/webtest/runs/{run_id}/pending", {"session": AGENT, "job": job})[2]
    assert list(pending["results"]) == [data["result"]]
    run = webtest.load(folder)
    applied, ignored = webtest.apply_pending(folder, run, pending, home / "no-images")
    assert applied == [data["result"]] and not ignored
    assert webtest.case_of(run, "r02")["state"] == "self-run"


def test_an_answer_to_an_earlier_park_is_not_applied_to_a_later_one(console, home, run_id):
    job = queue_run_job(console, run_id)
    folder = park_r02(console, home, run_id, job)
    browser(console, "POST", f"/api/webtest/runs/{run_id}/answers/r02-a1", {"action": "skip"})
    run = webtest.load(folder)  # the agent re-ran the row and parked it again before applying
    case = webtest.case_of(run, "r02")
    webtest.move(case, "queued", question=None)
    webtest.save(folder, run)
    webtest.next_row(folder, JobReader(console), job, AGENT)
    webtest.park(folder, "r02", {"body": "Which footer, again?"})
    pending = agent(console, "POST", f"/agent/webtest/runs/{run_id}/pending", {"session": AGENT, "job": job})[2]
    run = webtest.load(folder)
    applied, ignored = webtest.apply_pending(folder, run, pending, Path("/nonexistent"))
    assert applied == [] and ignored == ["r02-a1"]
    assert webtest.case_of(run, "r02")["question"]["id"] == "r02-a2"


def test_tester_result_with_an_image_survives_a_restart_and_the_upload_sweep(console, home, run_id):
    assert browser(console, "PUT", f"/api/webtest/runs/{run_id}/images", b"GIF89a....",
                   {"Content-Type": "application/octet-stream"})[0] == 415
    status, _, data = browser(console, "PUT", f"/api/webtest/runs/{run_id}/images", PNG,
                              {"Content-Type": "application/octet-stream"})
    assert status == 200, data
    image = data["image"]
    assert browser(console, "POST", f"/api/webtest/runs/{run_id}/rows/r08/result",
                   {"verdict": "pass", "image": "0" * 16})[0] == 400
    assert browser(console, "POST", f"/api/webtest/runs/{run_id}/rows/r01/result", {"verdict": "pass"})[0] == 409
    status, _, data = browser(console, "POST", f"/api/webtest/runs/{run_id}/rows/r08/result",
                              {"verdict": "fail", "actual": "the menu still reads 料金", "image": image})
    assert status == 200 and data["result"] == "r08-r0"
    images = webtest_api.server_dir(home, run_id) / "images"
    old = time.time() - 2 * 3600
    for p in images.iterdir():
        os.utime(p, (old, old))
    templates_api.sweep(home)
    console.close()
    restarted = InProcessServer(make_state(home))
    try:
        restarted.headers = {srv.SESSION_HEADER: restarted.session()}
        run = browser(restarted, "GET", f"/api/webtest/runs/{run_id}")[2]
        r08 = next(c for c in run["cases"] if c["row"] == "r08")
        assert r08["tester_result"]["image"] == image and run["waiting_on_tester"] == 0
        folder = folder_of(home, run_id)
        loaded = webtest.load(folder)
        pending = webtest_api._pending(restarted.state, run_id)
        applied, _ = webtest.apply_pending(folder, loaded, pending, images)
        assert applied == ["r08-r0"]
        case = webtest.case_of(loaded, "r08")
        assert case["state"] == "self-run" and case["result"]["evidence"][0].startswith("evidence/r08-a0-1.")
    finally:
        restarted.close()


def test_a_tab_newer_than_the_run_job_cannot_act(console, home, run_id):
    job = queue_run_job(console, run_id)
    park_r02(console, home, run_id, job)
    newer = {srv.SESSION_HEADER: console.session()}
    for method, path, body in (
            ("POST", f"/api/webtest/runs/{run_id}/answers/r02-a1", {"action": "skip"}),
            ("POST", f"/api/webtest/runs/{run_id}/rows/r08/result", {"verdict": "pass"}),
            ("POST", f"/api/webtest/runs/{run_id}/finish", {})):
        status, _, data = call(console.port, method, path, headers=newer, body=body)
        assert status == 403 and data["error"]["code"] == "session-too-new", path
    status, _, data = call(console.port, "PUT", f"/api/webtest/runs/{run_id}/images", body=PNG,
                           headers={**newer, "Content-Type": "application/octet-stream"})
    assert status == 403
    assert browser(console, "POST", f"/api/webtest/runs/{run_id}/answers/r02-a1", {"action": "skip"})[0] == 200


def test_done_needs_finish_while_rows_are_open_and_finish_ends_the_sign_in_question(console, home, run_id):
    job = queue_run_job(console, run_id)
    status, _, data = agent(console, "POST", f"/agent/jobs/{job}/done", {"session": AGENT, "result": "done"})
    assert status == 409 and data["error"]["code"] == "open-rows"
    login_scenarios.save_draft(home, "demo", {"name": "member", "steps": ["Sign in"]})
    digest = login_scenarios.get_scenario(home, "demo", "member")["hash"]
    assert browser(console, "POST", "/api/webtest/login/demo/member/approve", {"hash": digest})[0] == 200
    ask = {"type": "sign-in", "id": "signin-member-1", "scenario": "member"}
    assert agent(console, "POST", f"/agent/jobs/{job}/ask", {"session": AGENT, "ask": ask, "timeout": 0})[0] == 200
    status, _, data = browser(console, "POST", f"/api/webtest/runs/{run_id}/finish", {})
    assert status == 200 and data["sign_in_ended"] is True
    answered = agent(console, "POST", f"/agent/jobs/{job}/ask", {"session": AGENT, "ask": ask, "timeout": 0})[2]
    assert answered == {"answers": {"choice": "finish"}}
    pending = agent(console, "POST", f"/agent/webtest/runs/{run_id}/pending", {"session": AGENT, "job": job})[2]
    assert pending["finish"] is True
    assert agent(console, "POST", f"/agent/jobs/{job}/done", {"session": AGENT, "result": "done"})[0] == 200


def test_finish_from_an_earlier_job_does_not_count_for_the_next(console, home, run_id):
    job = queue_run_job(console, run_id)
    browser(console, "POST", f"/api/webtest/runs/{run_id}/finish", {})
    agent(console, "POST", f"/agent/jobs/{job}/done", {"session": AGENT, "result": "done"})
    time.sleep(0.01)
    job = queue_run_job(console, run_id)
    assert webtest_api.finished(console.state, run_id) is False
    status, _, _ = agent(console, "POST", f"/agent/jobs/{job}/done", {"session": AGENT, "result": "done"})
    assert status == 409


def test_pending_is_held_until_an_answer_arrives(console, home, run_id):
    import threading  # noqa: PLC0415

    job = queue_run_job(console, run_id)
    park_r02(console, home, run_id, job)
    timer = threading.Timer(0.5, lambda: browser(console, "POST", f"/api/webtest/runs/{run_id}/answers/r02-a1",
                                                 {"action": "self-run"}))
    timer.start()
    started = time.monotonic()
    pending = agent(console, "POST", f"/agent/webtest/runs/{run_id}/pending",
                    {"session": AGENT, "job": job, "wait": 10})[2]
    assert pending["answers"]["r02-a1"]["action"] == "self-run" and time.monotonic() - started < 5
    timer.join()


def test_pending_belongs_to_the_open_job_of_the_run(console, home, run_id):
    job = queue_run_job(console, run_id)
    assert agent(console, "POST", f"/agent/webtest/runs/{run_id}/pending",
                 {"session": "s-someoneelse0001", "job": job})[0] == 409
    assert agent(console, "POST", f"/agent/webtest/runs/{run_id}/pending", {"session": AGENT, "job": "j-x"})[0] == 404
    assert browser(console, "POST", f"/agent/webtest/runs/{run_id}/pending", {"session": AGENT, "job": job})[0] in (
        401, 403)


def test_agent_routes_for_the_run_commands(console, home, run_id):
    status, _, job = agent(console, "POST", "/agent/jobs",
                           {"kind": "webtest-run", "ui_lang": "en", "run": run_id, "tester": "T"})
    assert status == 200 and job["queued_by"] == "agent"
    assert agent(console, "POST", "/agent/jobs", {"kind": "close", "ui_lang": "en", "ticket": "X-1",
                                                  "tester": "T"})[0] == 400
    assert agent(console, "GET", f"/agent/jobs/{job['id']}/open")[2] == {"open": False}
    agent(console, "POST", "/agent/wait", {"session": AGENT, "timeout": 0})
    agent(console, "POST", f"/agent/jobs/{job['id']}/claim", {"session": AGENT})
    assert agent(console, "GET", f"/agent/jobs/{job['id']}/open")[2] == {"open": True}
    info = agent(console, "GET", f"/agent/jobs/{job['id']}/info?session={AGENT}")[2]
    assert info["kind"] == "webtest-run" and info["params"]["run"] == run_id
    assert agent(console, "GET", f"/agent/jobs/{job['id']}/signed-in?session={AGENT}")[2] == {"signed_in": None}
    assert agent(console, "GET", f"/agent/jobs/{job['id']}/review?session={AGENT}")[2] == {"review": None}
    listed = browser(console, "GET", f"/api/jobs/{job['id']}")[2]
    assert listed["opened"] is True


@pytest.mark.skipif(os.name != "posix", reason="mode bits apply on POSIX only")
def test_server_store_is_owner_only(console, home, run_id):
    browser(console, "POST", f"/api/webtest/runs/{run_id}/rows/r08/result", {"verdict": "pass"})
    root = home / ".testign-kit" / "webtest"
    for folder in (root, root / "runs", root / "runs" / run_id, root / "runs" / run_id / "images"):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700, folder
    answers = root / "runs" / run_id / "answers.json"
    assert stat.S_IMODE(answers.stat().st_mode) == 0o600
    assert json.loads(answers.read_text(encoding="utf-8"))["results"]["r08-r0"]["verdict"] == "pass"
