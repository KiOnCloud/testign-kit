from pathlib import Path

import pytest

from console_helpers import InProcessServer, call  # noqa: E402

from testign import login_scenarios  # noqa: E402
from testign.console import lifecycle  # noqa: E402
from testign.console import server as srv  # noqa: E402

DRAFT = {"name": "member", "label": "Member", "login_url": "https://dev.example.test/login",
         "steps": ["Open the login page", "Sign in as a member"], "account_hint": "a member account"}


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    return home


@pytest.fixture
def console(home: Path):
    state = srv.ConsoleState(version="t", agent_token="agent", home=home)
    srv.install_base_routes(state)
    lifecycle.install_routes(state)
    server = InProcessServer(state)
    server.headers = {srv.SESSION_HEADER: server.session()}
    yield server
    server.close()


def req(console, method, path, body=None):
    return call(console.port, method, path, headers=console.headers, body=body)


def test_projects_are_created_and_edited_in_the_console(console, home):
    assert req(console, "GET", "/api/webtest/projects")[2] == {"projects": []}
    status, _, data = req(console, "PUT", "/api/webtest/projects/demo",
                          {"hosts": ["dev.example.test"], "signin_hosts": ["auth.example.test"]})
    assert status == 200 and data["hosts"] == ["dev.example.test"]
    assert req(console, "PUT", "/api/webtest/projects/demo", {"hosts": []})[0] == 400
    assert req(console, "PUT", "/api/webtest/projects/demo", {"hosts": ["https://x.test/"]})[0] == 400
    listed = req(console, "GET", "/api/webtest/projects")[2]["projects"]
    assert listed == [{"name": "demo", "hosts": ["dev.example.test"], "signin_hosts": ["auth.example.test"],
                       "scenarios": 0, "approved": 0}]


def test_approve_reject_and_remove(console, home):
    login_scenarios.save_project(home, "demo", ["dev.example.test"])
    login_scenarios.save_draft(home, "demo", DRAFT)
    scenarios = req(console, "GET", "/api/webtest/login/demo")[2]["scenarios"]
    assert scenarios[0]["approved"] is False and scenarios[0]["steps"] == DRAFT["steps"]
    digest = scenarios[0]["hash"]
    login_scenarios.save_draft(home, "demo", {**DRAFT, "label": "Member (redrafted)"})
    status, _, data = req(console, "POST", "/api/webtest/login/demo/member/approve", {"hash": digest})
    assert status == 409 and data["error"]["code"] == "scenario-changed"
    fresh = req(console, "GET", "/api/webtest/login/demo")[2]["scenarios"][0]["hash"]
    assert req(console, "POST", "/api/webtest/login/demo/member/approve", {"hash": fresh})[2]["approved"] is True
    assert req(console, "POST", "/api/webtest/login/demo/member/reject", {"note": ""})[0] == 400
    rejected = req(console, "POST", "/api/webtest/login/demo/member/reject", {"note": "wrong login page"})[2]
    assert rejected["approved"] is False and rejected["rejection"]["note"] == "wrong login page"
    assert req(console, "DELETE", "/api/webtest/login/demo/member")[0] == 200
    assert req(console, "GET", "/api/webtest/login/demo")[2]["scenarios"] == []


@pytest.mark.parametrize("name", ["..", "%2e%2e", "a%2Fb", "a%5Cb", "NUL", "CON", "nope"])
def test_bad_names_get_404(console, home, name):
    login_scenarios.save_project(home, "demo", ["dev.example.test"])
    login_scenarios.save_draft(home, "demo", DRAFT)
    assert req(console, "GET", f"/api/webtest/login/{name}")[0] == 404
    assert req(console, "POST", f"/api/webtest/login/demo/{name}/approve", {"hash": "x"})[0] == 404
    assert req(console, "DELETE", f"/api/webtest/login/demo/{name}")[0] == 404
    assert req(console, "DELETE", f"/api/webtest/login/{name}/member")[0] == 404


def test_login_routes_need_a_browser_session(console, home):
    login_scenarios.save_project(home, "demo", ["dev.example.test"])
    assert call(console.port, "GET", "/api/webtest/projects")[0] in (401, 403)
    assert call(console.port, "PUT", "/api/webtest/projects/demo", headers={srv.AGENT_HEADER: "agent"},
                body={"hosts": ["evil.test"]})[0] in (401, 403)
    assert login_scenarios.get_project(home, "demo")["hosts"] == ["dev.example.test"]
