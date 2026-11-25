import socket
import time
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from console_helpers import InProcessServer, call  # noqa: E402
from make_report import write_report  # noqa: E402
from make_webtest_run import BASE_URL, HOSTS  # noqa: E402

from testign import login_scenarios, templates, webtest, webtest_suite, xlsx  # noqa: E402
from testign.console import lifecycle  # noqa: E402
from testign.console import server as srv  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIPPED_SAMPLE = REPO / "templates" / "testcase-template-sample.xlsx"
AGENT_S = "s-agentagentagent1"
FIGMA = "https://www.figma.com/design/AbCdEfGhIjKlMn/USUPP?node-id=6647-118148"


def make_state(home: Path) -> srv.ConsoleState:
    state = srv.ConsoleState(version="t", agent_token="agent", home=home)
    srv.install_base_routes(state)
    lifecycle.install_routes(state)
    return state


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    login_scenarios.save_project(home, "demo", HOSTS)
    templates.register(SHIPPED_SAMPLE, "sample", home=home, purpose="webtest")
    write_report(home / "Downloads" / "DEMO-1", tmp_path, "a" * 40, "b" * 40, revision=2)
    return home


@pytest.fixture
def console(home):
    server = InProcessServer(make_state(home))
    token = server.session()
    created = server.state.session_created(token)
    while time.time() <= created:
        time.sleep(0.001)
    server.headers = {srv.SESSION_HEADER: token}
    yield server
    server.close()


def browser(console, method, path, body=None, headers=None):
    return call(console.port, method, path, headers={**console.headers, **(headers or {})}, body=body)


def agent(console, method, path, body=None):
    return call(console.port, method, path, headers={srv.AGENT_HEADER: "agent"}, body=body, timeout=15)


def case(**extra):
    return {"content": "Label shows 確定", "class": "sure", "runner": "agent", "scenario": "none", "screen": "/",
            **extra}


def new_manual(console, name="Smoke"):
    status, _, data = browser(console, "POST", "/api/webtest/suites", {"kind": "manual", "name": name,
                                                                       "project": "demo"})
    assert status == 200, data
    return data["suite"]


def claim(console, job_id):
    bridge = console.state.bridge
    bridge.jobs[job_id]["created_ts"] = time.time() + 1.0
    assert bridge.wait(AGENT_S, 0)["job"]["id"] == job_id
    bridge.claim(job_id, AGENT_S)


def test_routes_need_a_session(console):
    status, _, _ = call(console.port, "GET", "/api/webtest/suites")
    assert status in (401, 403)
    status, _, _ = call(console.port, "POST", "/agent/suites/S20261125-1000-x/stage", body={})
    assert status in (401, 403)


def test_sources_list_drives_the_wizard(console):
    status, _, data = browser(console, "GET", "/api/webtest/sources")
    assert status == 200 and [s["kind"] for s in data["sources"]] == ["figma", "backlog", "excel", "manual"]


def test_manual_suite_edit_confirm_and_run(console, home):
    sid = new_manual(console)
    status, _, data = browser(console, "POST", f"/api/webtest/suites/{sid}/cases", case())
    assert status == 200 and data["case"]["case"] == "c1"
    status, _, data = browser(console, "PUT", f"/api/webtest/suites/{sid}/cases/c1", {"viewport": "mobile"})
    assert status == 400 and data["error"]["code"] == "case-rules"
    assert data["error"]["details"]["errors"] == {"runner": webtest_suite.DEVICE_IS_THE_TESTERS}
    status, _, data = browser(console, "POST", "/api/webtest/runs", {"suite": sid, "base_url": BASE_URL,
                                                                     "project": "demo", "tester": "Kien"})
    assert status == 409 and "not ready" in data["error"]["message"]
    status, _, data = browser(console, "POST", f"/api/webtest/suites/{sid}/confirm", {"by": "Kien"})
    assert status == 200 and data["state"] == "ready"
    status, _, run = browser(console, "POST", "/api/webtest/runs", {"suite": sid, "base_url": BASE_URL,
                                                                    "project": "demo", "tester": "Kien"})
    assert status == 200 and run["suite"]["id"] == sid and "folder" not in run
    status, _, view = browser(console, "GET", f"/api/webtest/suites/{sid}")
    assert view["runs"][0]["id"] == run["run"] and view["runs"][0]["open"]
    status, _, data = browser(console, "DELETE", f"/api/webtest/suites/{sid}")
    assert status == 409 and "still open" in data["error"]["message"]
    status, _, listing = browser(console, "GET", "/api/webtest/runs")
    assert listing["runs"][0]["suite"]["id"] == sid
    status, _, data = browser(console, "GET", "/api/webtest/suites")
    assert data["suites"][0]["runs"] == 1


def test_run_refused_off_the_projects_hosts(console):
    sid = new_manual(console)
    browser(console, "POST", f"/api/webtest/suites/{sid}/cases", case())
    browser(console, "POST", f"/api/webtest/suites/{sid}/confirm", {})
    status, _, data = browser(console, "POST", "/api/webtest/runs", {"suite": sid, "base_url": "https://evil.test/",
                                                                     "project": "demo", "tester": "Kien"})
    assert status == 400 and data["error"]["code"] == "off-host"


def test_bulk_duplicate_rename_delete(console):
    sid = new_manual(console)
    for _ in range(2):
        browser(console, "POST", f"/api/webtest/suites/{sid}/cases", case(runner="tester"))
    status, _, data = browser(console, "POST", f"/api/webtest/suites/{sid}/cases/bulk",
                              {"cases": ["c1", "c2"], "fields": {"runner": "agent"}})
    assert status == 200 and data["changed"] == ["c1", "c2"]
    status, _, data = browser(console, "POST", f"/api/webtest/suites/{sid}/cases/bulk",
                              {"cases": ["c2"], "delete": True})
    assert data["deleted"] == ["c2"]
    status, _, data = browser(console, "PATCH", f"/api/webtest/suites/{sid}", {"name": "Renamed"})
    assert status == 200 and data["name"] == "Renamed"
    status, _, copy = browser(console, "POST", f"/api/webtest/suites/{sid}/duplicate", {})
    assert status == 200 and copy["cases"] == 1
    status, _, data = browser(console, "DELETE", f"/api/webtest/suites/{copy['id']}")
    assert status == 200 and data["removed"]
    status, _, _ = browser(console, "GET", "/api/webtest/suites/S20990101-0000-nope")
    assert status == 404


def test_backlog_suite_is_generated_by_its_claimed_job_only(console):
    status, _, made = browser(console, "POST", "/api/webtest/suites",
                              {"kind": "backlog", "name": "DEMO-1", "ticket": "DEMO-1", "ui_lang": "ja"})
    assert status == 200 and made["state"] == "generating" and made["job"]["kind"] == "suite-generate"
    sid, job_id = made["suite"], made["job"]["id"]
    assert made["job"]["suite"] == sid
    status, _, data = browser(console, "POST", f"/api/webtest/suites/{sid}/cases", case())
    assert status == 409 and "still writing" in data["error"]["message"]
    stage = {"job": job_id, "session": AGENT_S, "cases": [case(trace=["B1"]), case(trace=["R1"])]}
    status, _, data = agent(console, "POST", f"/agent/suites/{sid}/stage", stage)
    assert status == 409  # not claimed yet
    claim(console, job_id)
    status, _, data = agent(console, "POST", f"/agent/suites/{sid}/stage", stage)
    assert status == 200 and data["staged"] == ["c1", "c2"]
    other = new_manual(console, "Other")
    status, _, _ = agent(console, "POST", f"/agent/suites/{other}/stage", stage)
    assert status == 409
    status, _, data = agent(console, "POST", f"/agent/suites/{sid}/generated", {"job": job_id, "session": AGENT_S})
    assert status == 200 and data["state"] == "review"
    status, _, view = browser(console, "GET", f"/api/webtest/suites/{sid}")
    assert view["coverage"]["uncovered"] == ["B2", "B3", "R2"] and view["generate"]["id"] == job_id


def test_a_cancelled_generate_job_hands_the_suite_to_the_tester(console):
    status, _, made = browser(console, "POST", "/api/webtest/suites",
                              {"kind": "figma", "name": "Figma", "figma_url": FIGMA})
    assert status == 200
    browser(console, "POST", f"/api/jobs/{made['job']['id']}/cancel", {})
    status, _, view = browser(console, "GET", f"/api/webtest/suites/{made['suite']}")
    assert view["state"] == "review"


def test_backlog_suite_needs_a_report(console):
    status, _, data = browser(console, "POST", "/api/webtest/suites", {"kind": "backlog", "name": "x",
                                                                       "ticket": "DEMO-404"})
    assert status == 400 and data["error"]["code"] == "no-report"
    status, _, data = browser(console, "GET", "/api/webtest/suites")
    assert data["suites"] == []


def test_excel_suite_from_an_upload(console, home, tmp_path):
    templates.register(xlsx.build_sample(tmp_path / "src" / "tc.xlsx"), "tc", home=home)
    entry = templates.resolve("tc", home)
    filled = xlsx.fill_copy(Path(entry["path"]), entry, [{"item": "Label", "steps": "", "expected": "ok",
                                                          "trace": ["B1"]}], tmp_path / "filled.xlsx")
    data = Path(filled["path"]).read_bytes()
    status, _, up = browser(console, "POST", "/api/webtest/suites/uploads", data,
                            headers={"X-Filename": "UTF-8''v118%20cases.xlsx",
                                     "Content-Type": "application/octet-stream"})
    assert status == 200 and up["name"] == "v118 cases.xlsx"
    status, _, made = browser(console, "POST", "/api/webtest/suites", {"kind": "excel", "name": "v118",
                                                                       "upload": up["upload"], "template": "tc"})
    assert status == 200 and made["cases"] == 1 and made["job"] is None
    status, _, out = browser(console, "POST", f"/api/webtest/suites/{made['suite']}/export", {"template": "tc"})
    assert status == 200 and out["rows"] == 1 and out["name"].endswith("-testcases.xlsx")


def test_upload_over_the_cap_is_refused(console):
    with socket.create_connection(("127.0.0.1", console.port), timeout=5) as sock:
        sock.sendall((
            "POST /api/webtest/suites/uploads HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{console.port}\r\n"
            f"{srv.SESSION_HEADER}: {console.headers[srv.SESSION_HEADER]}\r\n"
            "Content-Type: application/octet-stream\r\n"
            "X-Filename: UTF-8''big.xlsx\r\n"
            f"Content-Length: {10 * 1024 * 1024 + 1}\r\n\r\n"
        ).encode())
        assert sock.recv(4096).startswith(b"HTTP/1.1 413")
    status, _, data = browser(console, "POST", "/api/webtest/suites/uploads", b"not a zip",
                              headers={"X-Filename": "UTF-8''x.xlsx", "Content-Type": "application/octet-stream"})
    assert status == 400


def test_suite_capture_route(console, home):
    sid = new_manual(console)
    browser(console, "POST", f"/api/webtest/suites/{sid}/cases", case())
    folder = webtest_suite.find_suite(webtest.runs_root({"output_dir": str(home / "Downloads")}), sid)
    (folder / "source" / "c1.png").write_bytes(b"\x89PNG\r\n\x1a\n0000")
    status, headers, data = browser(console, "GET", f"/api/webtest/suites/{sid}/captures/c1.png")
    assert status == 200 and headers["Content-Type"] == "image/png"
    status, _, _ = browser(console, "GET", f"/api/webtest/suites/{sid}/captures/..%2Fsuite.json")
    assert status == 404


def test_agent_queues_suite_generate_but_not_other_kinds(console):
    status, _, made = browser(console, "POST", "/api/webtest/suites", {"kind": "figma", "name": "F",
                                                                       "figma_url": FIGMA})
    console.state.bridge.cancel(made["job"]["id"])
    status, _, data = agent(console, "POST", "/agent/jobs", {"kind": "survey", "ticket": "DEMO-1", "ui_lang": "en"})
    assert status == 400 and "suite-generate and webtest-run" in data["error"]["message"]
    status, _, data = agent(console, "POST", "/agent/jobs", {"kind": "webtest-plan", "ui_lang": "en"})
    assert status == 400


def test_ticket_list_has_freshness_questions_and_suites(console):
    browser(console, "POST", "/api/webtest/suites", {"kind": "backlog", "name": "DEMO-1", "ticket": "DEMO-1"})
    status, _, data = browser(console, "GET", "/api/tickets")
    ticket = next(t for t in data["tickets"] if t["id"] == "DEMO-1")
    assert ticket["freshness"]["status"] == "unknown"  # the made-up report names no usable repo
    assert ticket["freshness"]["reason"] in ("repo-not-found", "busy")
    assert ticket["open_questions"] == 1
    assert ticket["suites"][0]["name"] == "DEMO-1" and ticket["suites"][0]["revision"] == 2


def test_run_columns_are_edited_on_the_run_page_while_no_job_works_on_it(console):
    sid = new_manual(console)
    browser(console, "POST", f"/api/webtest/suites/{sid}/cases", case())
    browser(console, "POST", f"/api/webtest/suites/{sid}/confirm", {})
    _, _, run = browser(console, "POST", "/api/webtest/runs", {"suite": sid, "base_url": BASE_URL, "project": "demo",
                                                               "tester": "Kien"})
    status, _, view = browser(console, "GET", f"/api/webtest/runs/{run['run']}/columns")
    assert status == 200 and view["templates"] == ["sample"] and "trace" in view["fields"]
    plan = view["plan"]
    kept = [c for c in plan["columns"] if c["field"] != "trace"]
    status, _, data = browser(console, "PUT", f"/api/webtest/runs/{run['run']}/columns",
                              {"columns": kept, "verdict_labels": plan["verdict_labels"]})
    assert status == 200 and not any(c["field"] == "trace" for c in data["plan"]["columns"])
    status, _, data = browser(console, "PUT", f"/api/webtest/runs/{run['run']}/columns", {"columns": []})
    assert status == 400 and data["error"]["code"] == "bad-columns"
    console.state.bridge.create({"kind": "webtest-run", "ui_lang": "en", "run": run["run"], "tester": "Kien",
                                 "mode": "run"})
    status, _, data = browser(console, "PUT", f"/api/webtest/runs/{run['run']}/columns",
                              {"columns": plan["columns"], "verdict_labels": plan["verdict_labels"]})
    assert status == 409 and data["error"]["code"] == "run-busy"
