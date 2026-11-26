"""Browsers per run, flaky rows, replay with nobody at the console, template versions, the console's
profile form, and the setup check. No browser: the engine is replaced where a row would run."""

import json
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from console_helpers import InProcessServer, call  # noqa: E402
from make_webtest_run import FakeConsole, build  # noqa: E402

from testign import (  # noqa: E402
    cli, login_recipe, login_scenarios, secret_guard, setup_check, templates, webtest, webtest_export, webtest_live,
    webtest_replay,
)
from testign.console import lifecycle  # noqa: E402
from testign.console import server as srv  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "templates" / "testcase-template-sample.xlsx"


@pytest.fixture
def root(tmp_path):
    return tmp_path / "webtest"


def folder_of(root, run_id):
    return webtest.find_run(root, run_id)


# browsers -------------------------------------------------------------------------------------
def test_browsers_are_checked_and_kept_in_a_fixed_order():
    assert webtest.check_browsers(None) == ["chromium"]
    assert webtest.check_browsers(["webkit", "chromium"]) == ["chromium", "webkit"]
    with pytest.raises(webtest.TargetError, match="unknown browser opera"):
        webtest.check_browsers(["opera"])
    target = webtest.check_run_target({"demo": {"hosts": ["dev.example.test"]}}, {"templates": [{"name": "t"}]},
                                      "https://dev.example.test/", "demo", "t", ["firefox"])
    assert target["browsers"] == ["firefox"]


def test_several_browsers_get_a_result_column_each(tmp_path):
    home = tmp_path / "home"
    templates.register(SAMPLE, "sample", home=home, purpose="webtest")
    entry = templates.resolve("sample", home)
    facts = webtest_export.sheet_facts(entry)
    plan = webtest_export.first_guess(entry, facts, "en", browsers=["chromium", "firefox"])
    fields = [c["field"] for c in plan["columns"]]
    assert "verdict_chromium" in fields and "verdict_firefox" in fields
    header = next(c["header"] for c in plan["columns"] if c["field"] == "verdict_firefox")
    assert header == "Result (Firefox)"
    one = webtest_export.first_guess(entry, facts, "en", browsers=["chromium"])
    assert not any(c["field"].startswith("verdict_") for c in one["columns"])


def test_browser_verdicts_and_the_flaky_mark_in_the_export():
    labels = {"pass": "OK", "fail": "NG", "not-run": "-", "pending": "保留"}
    case = {"row": "r01", "state": "pass", "result": {"verdict": "pass", "flaky": True, "browsers": {
        "chromium": {"verdict": "pass", "flaky": True}, "firefox": {"verdict": "spec-error"},
        "webkit": {"verdict": "pending"}}}}
    assert webtest_export.value_for(case, "verdict_chromium", labels) == "OK"
    assert webtest_export.value_for(case, "verdict_firefox", labels) == "-"
    assert webtest_export.value_for(case, "verdict_webkit", labels) == "保留"
    assert webtest_export.value_for(case, "verdict_msedge", labels) == ""  # not one of the run's browsers
    assert webtest_export.value_for(case, "flaky", labels) == "flaky"
    plain = {"row": "r02", "state": "fail", "result": {"verdict": "fail"}}
    assert webtest_export.value_for(plain, "verdict_chromium", labels) == "NG"
    assert webtest_export.value_for(plain, "verdict_firefox", labels) == ""


# a replayed row --------------------------------------------------------------------------------
def queued_row(folder):
    run = webtest.load(folder)
    case = next(c for c in run["cases"] if c["state"] == "queued")
    return run, case


def fake_engine(monkeypatch, outcomes):
    """run_case answers from ``outcomes[browser]`` in order. The browsers are plain strings here, so a
    browser that could not start is told apart by its message."""
    seen = []
    monkeypatch.setattr(webtest_replay, "_is_missing", lambda b: b.startswith("cannot start"))

    def run_case(browser, **kw):
        seen.append(browser)
        out = dict(outcomes[browser].pop(0))
        shot = kw.get("screenshot")
        if shot is not None:
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
            out["screenshot"] = shot
        return {"step": None, "error": None, "url": "https://dev.example.test/mypage", **out}

    monkeypatch.setattr(webtest_live, "run_case", run_case)
    return seen


SESSION = {"storage": None, "login_url": None, "secrets": []}
BODY = {"steps": [{"action": "goto", "value": "/"}]}


def test_a_row_that_passes_on_the_second_try_is_flaky(root, monkeypatch):
    folder = folder_of(root, build(root, FakeConsole()))
    run, case = queued_row(folder)
    chromium = "chromium-browser"
    fake_engine(monkeypatch, {chromium: [{"result": "fail", "error": "step 1: timeout"}, {"result": "ok"}]})
    out = webtest_replay._replay_row(folder, run, case["row"], case, BODY, SESSION, {"chromium": chromium}, None)
    assert out["state"] == "pass"
    stored = webtest.case_of(webtest.load(folder), case["row"])
    assert stored["result"]["flaky"] is True and stored["result"]["by"] == "replay"
    assert "browsers" not in stored["result"]  # one browser: the row's own verdict is enough
    assert len(stored["evidence"]) == 1


def test_several_browsers_fail_when_one_fails_and_a_missing_one_is_pending(root, monkeypatch):
    folder = folder_of(root, build(root, FakeConsole()))
    run, case = queued_row(folder)
    fake_engine(monkeypatch, {"c": [{"result": "ok"}],
                              "f": [{"result": "fail", "error": "step 2: text differs"},
                                    {"result": "fail", "error": "step 2: text differs"}]})
    launched = {"chromium": "c", "firefox": "f", "webkit": "cannot start WebKit: not installed"}
    out = webtest_replay._replay_row(folder, run, case["row"], case, BODY, SESSION, launched, None)
    assert out["state"] == "fail"
    result = webtest.case_of(webtest.load(folder), case["row"])["result"]
    assert result["browsers"]["chromium"]["verdict"] == "pass"
    assert result["browsers"]["firefox"]["verdict"] == "fail"
    assert result["browsers"]["webkit"]["verdict"] == "pending"
    assert "firefox: step 2: text differs" in result["actual"]
    assert {e.get("browser") for e in webtest.case_of(webtest.load(folder), case["row"])["evidence"]} == {"chromium", "firefox"}


def test_a_replay_with_nobody_at_the_console_waits_for_a_running_job(root, monkeypatch):
    run_id = build(root, FakeConsole())
    folder = folder_of(root, run_id)
    run = webtest.load(folder)
    row = next(c for c in run["cases"] if c["state"] == "queued")
    row["state"], row["owner_job"] = "running", "j1"
    webtest.save(folder, run)
    with pytest.raises(webtest.WebtestError, match="running in a console job"):
        webtest_replay.replay(folder, None)


# template versions ------------------------------------------------------------------------------
def test_registering_again_keeps_the_earlier_version_for_pinned_runs(tmp_path):
    home = tmp_path / "home"
    first = templates.register(SAMPLE, "web", home=home, purpose="webtest")
    assert first["version"] == 1
    second = templates.register(SAMPLE, "web", home=home, purpose="webtest", replace=True)
    assert second["version"] == 2 and [v["version"] for v in second["versions"]] == [1]
    old = templates.resolve("web", home, 1)
    assert old["version"] == 1 and old["current_version"] == 2 and Path(old["path"]).exists()
    assert templates.resolve("web", home)["version"] == 2
    with pytest.raises(templates.TemplateError, match="no version 7"):
        templates.resolve("web", home, 7)
    kept = Path(old["path"])
    templates.remove("web", home)
    assert not kept.exists()


def test_editing_a_runs_columns_keeps_its_template_version(tmp_path):
    home = tmp_path / "home"
    templates.register(SAMPLE, "web", home=home, purpose="webtest")
    run = {"template": "web", "report_lang": "en", "cases": [], "source": {"kind": "manual"}, "browsers": ["chromium"]}
    plan = webtest_export.suite_plan(run, templates.resolve("web", home))
    assert plan["template_version"] == 1
    templates.register(SAMPLE, "web", home=home, purpose="webtest", replace=True)
    run["columns"] = plan
    edited = webtest_export.confirmed_plan(run, {"template": "web", "verdict_labels": plan["verdict_labels"],
                                                 "columns": plan["columns"]}, home)
    assert edited["template_version"] == 1


# the console's profile form ---------------------------------------------------------------------
@pytest.fixture
def console(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    login_scenarios.save_project(home, "demo", ["dev.example.test"])
    state = srv.ConsoleState(version="t", agent_token="agent", home=home)
    srv.install_base_routes(state)
    lifecycle.install_routes(state)
    server = InProcessServer(state)
    server.headers = {srv.SESSION_HEADER: server.session()}
    yield server
    server.close()


def test_the_profile_form_is_write_only_and_staging_only(console):
    home = console.state.home
    path = "/api/webtest/profiles/demo/member01"
    status, _, data = call(console.port, "PUT", path, headers=console.headers,
                           body={"values": {"password": "typed-in-1"}})
    assert status == 400 and "staging" in data["error"]["message"]
    status, _, data = call(console.port, "PUT", path, headers=console.headers,
                           body={"staging_test_account": True, "values": {"username": "u1", "password": "typed-in-1"}})
    assert status == 200 and data == {"project": "demo", "profile": "member01", "keys": ["password", "username"]}
    assert login_recipe.profile_values(home, "demo", "member01")["password"] == "typed-in-1"
    listing = call(console.port, "GET", "/api/webtest/login/demo", headers=console.headers)[2]
    assert "typed-in-1" not in json.dumps(listing)
    status, _, _ = call(console.port, "PUT", path, body={"staging_test_account": True, "values": {"a": "b"}})
    assert status in (401, 403)  # a call without the tab's session is refused
    assert call(console.port, "DELETE", path, headers=console.headers)[0] == 200
    assert login_recipe.list_profiles(home, "demo") == []


def test_the_secret_guard_blocks_the_profile_route(tmp_path):
    payload = {"tool_name": "Bash",
               "tool_input": {"command": "curl -X PUT http://127.0.0.1:4791/api/webtest/profiles/demo/p -d '{}'"}}
    assert secret_guard.evaluate(payload, tmp_path) is not None


# setup ------------------------------------------------------------------------------------------
def test_setup_lists_what_is_missing_and_installs_only_with_install(monkeypatch):
    monkeypatch.setattr(setup_check, "_has", lambda m: m == "openpyxl")
    ran = []
    monkeypatch.setattr(setup_check, "_run", lambda cmd: ran.append(cmd) or {"command": " ".join(cmd), "ok": True})
    out = setup_check.check(webtest=True)
    assert not out["ok"] and ran == []
    assert any("pip install" in t and "playwright" in t for t in out["todo"])
    out = setup_check.check(webtest=True, install=True)
    assert any("playwright" in c for cmd in ran for c in cmd)


def test_setup_command_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(setup_check, "check", lambda **kw: {"ok": False, "checks": [], "installed": [], "todo": ["x"]})
    assert cli.main(["setup"]) == 1
    assert json.loads(capsys.readouterr().out)["todo"] == ["x"]


def test_replay_new_needs_a_reviewed_spec(tmp_path, monkeypatch, capsys):
    from make_webtest_run import ready_suite  # noqa: PLC0415

    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    (home / ".testign-kit").mkdir()
    (home / ".testign-kit" / "config.json").write_text(json.dumps({"output_dir": str(home / "out")}), encoding="utf-8")
    suite = ready_suite(home / "out" / "webtest")
    rc = cli.main(["webtest-replay-new", "--suite", suite.name, "--base-url", "https://dev.example.test/",
                   "--project", "demo", "--tester", "nightly"])
    assert rc == 2 and "not reviewed" in capsys.readouterr().err
