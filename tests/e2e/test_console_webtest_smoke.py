"""Browser test of the web test suite and run screens (Playwright, Chromium). Runs only with TESTIGN_E2E=1.

A project and its hosts are saved on the Projects & hosts screen, a manual suite is made in the new
suite wizard, given one case and confirmed, and a run is started from it with the New run dialog.
On the Run screen of runs made from the ready Figma suite of the fixture, with the agent side played
in-process on the server's bridge, the tester signs in from the sign-in card, queues an export, and
answers a parked row.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime

import pytest

if os.environ.get("TESTIGN_E2E") != "1":
    pytest.skip("browser tests run only with TESTIGN_E2E=1", allow_module_level=True)

sync_api = pytest.importorskip("playwright.sync_api")

from console_helpers import InProcessServer  # noqa: E402
from make_webtest_run import FakeConsole, build  # noqa: E402

from testign import login_scenarios, webtest  # noqa: E402
from testign.console import lifecycle, suite_api, webtest_api  # noqa: E402
from testign.console import server as srv  # noqa: E402

AGENT = "s-e2ewebagent00001"
HOST = "dev.example.test"
BASE_URL = f"https://{HOST}/"
TESTER = "Tester A"
MEMBER = {"name": "member", "label": "Member", "login_url": f"https://{HOST}/login",
          "signout_url": f"https://{HOST}/logout", "steps": ["Open the login page", "Sign in as a member"],
          "signed_in_check": {"url": f"https://{HOST}/mypage", "text": "My Page"},
          "account_hint": "any member account on dev"}


def make_state(home):
    state = srv.ConsoleState(version="e2e", agent_token="agent", home=home)
    srv.install_base_routes(state)
    lifecycle.install_routes(state)
    return state


@pytest.fixture(scope="module")
def console(demo_home):
    home, data = demo_home
    server = InProcessServer(make_state(home))
    server.data = data
    yield server
    server.state.bridge.shutdown()
    server.close()


@pytest.fixture(scope="module")
def runs_root(console):
    return console.state.home / "Downloads" / "webtest"


@pytest.fixture(scope="module")
def figma_run(console, runs_root):
    """The fixture's eight-row run, made from its ready Figma suite (built once: the suite id is fixed)."""
    login_scenarios.save_project(console.state.home, "demo", [HOST])
    return build(runs_root, FakeConsole(), when=datetime(2026, 11, 19, 12, 0))


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, console):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
    context.add_init_script(f"localStorage.setItem('testign.uiLang', 'en'); localStorage.setItem('testign.testerName', '{TESTER}')")
    pg = context.new_page()
    pg.problems = []
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: pg.problems.append(f"{m.type}: {m.text}")
          if m.type in ("error", "warning") and "status of 409" not in m.text else None)
    pg.goto(f"http://127.0.0.1:{console.port}/#c={console.state.mint_launch_code()}")
    pg.wait_for_selector("#main[data-ready='suites']")
    yield pg
    context.close()


def go(page, name, hash_):
    page.evaluate(
        """([h]) => { const m = document.getElementById('main'); if (m) delete m.dataset.ready;
        if (location.hash === h) window.dispatchEvent(new HashChangeEvent('hashchange')); else location.hash = h; }""",
        [hash_],
    )
    page.wait_for_function("([n]) => document.getElementById('main') && document.getElementById('main').dataset.ready === n", arg=[name])


def wait_ready(page, name):
    page.wait_for_function("([n]) => document.getElementById('main') && document.getElementById('main').dataset.ready === n", arg=[name])


class BridgeReader:
    """The job view the run commands read, straight from the in-process bridge (what /agent/jobs/:id/info returns)."""

    def __init__(self, bridge):
        self.bridge = bridge

    def job(self, job, session):
        return self.bridge.info(job, session)


def agent_take(bridge, session=AGENT):
    got = bridge.wait(session, 0)
    assert got["job"], "no job offered"
    assert bridge.claim(got["job"]["id"], session) == {"ok": True}
    return got["job"]["id"]


def wait_for(fn, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("timed out")


def queued_run_job(bridge, run_id):
    """The id of the queued webtest-run job of ``run_id``, or None."""
    return next((j["id"] for j in bridge.list_jobs()
                 if j["kind"] == "webtest-run" and j["run"] == run_id and j["state"] == "queued"), None)


def test_project_suite_and_run_from_the_ui(page, console, runs_root):
    home = console.state.home
    bridge = console.state.bridge

    go(page, "projects", "#/projects")
    page.click("[data-new-project]")
    page.fill("#project-name", "demo")
    page.fill("#project-hosts", f"{HOST.upper()}\n")
    page.click("[data-save-project]")
    page.wait_for_selector("tr[data-project='demo']")
    assert login_scenarios.get_project(home, "demo")["hosts"] == [HOST]

    go(page, "suiteNew", "#/suites/new")
    page.click("[data-src=manual]")
    page.click("[data-wiz=next]")
    page.wait_for_selector("#wiz-note")
    page.click("[data-wiz=next]")
    page.fill("#wiz-name", "Smoke")
    page.select_option("#wiz-project", "demo")
    page.click("[data-wiz=next]")
    page.click("[data-wiz=done]")
    page.wait_for_function("() => location.hash.startsWith('#/suites/S')")
    suite_id = page.evaluate("location.hash").split("/")[2]
    wait_ready(page, "suite")

    page.click("[data-add-case]")
    page.wait_for_selector("[data-case-form='new']")
    page.fill("#case-content", "The header link reads 予約履歴")
    page.select_option("#case-class", "sure")
    page.select_option("#case-runner", "tester")
    page.click("[data-case-save]")
    page.wait_for_selector("tr[data-case='c1']")
    page.click("[data-suite-action=confirm]")
    page.wait_for_selector("[data-suite-action=new-run]:not([disabled])")

    page.click("[data-suite-action=new-run]")
    page.wait_for_selector("[data-new-run]")
    assert page.input_value("#nr-suite") == suite_id
    assert page.input_value("#nr-project") == "demo"
    assert page.input_value("#nr-tester") == TESTER
    page.fill("#nr-base_url", BASE_URL)
    page.click("[data-new-run-submit]")
    page.wait_for_function("() => location.hash.startsWith('#/runs/')")
    run_id = page.evaluate("location.hash").split("/")[2]
    wait_ready(page, "run")

    run = webtest.load(webtest.find_run(runs_root, run_id))
    assert run["suite"]["id"] == suite_id and run["hosts"] == [HOST] and run["tester"] == TESTER
    jid = wait_for(lambda: queued_run_job(bridge, run_id))
    assert bridge.get(jid)["params"]["mode"] == "run"
    bridge.cancel(jid)
    assert not page.problems, page.problems


def test_run_screen_sign_in_card_and_export(page, console, runs_root, figma_run):
    home = console.state.home
    bridge = console.state.bridge
    suite_id = webtest.load(webtest.find_run(runs_root, figma_run))["suite"]["id"]
    run_id = suite_api.create_run(console.state, {"suite": suite_id, "name": "Sign-in check", "base_url": BASE_URL,
                                                  "project": "demo", "tester": TESTER}, None)["run"]
    draft = login_scenarios.save_draft(home, "demo", MEMBER)
    login_scenarios.approve(home, "demo", "member", draft["hash"], TESTER)

    jid = bridge.create({"kind": "webtest-run", "ui_lang": "en", "run": run_id, "tester": TESTER})["id"]
    assert agent_take(bridge) == jid
    out: dict = {}
    ask = {"type": "sign-in", "id": "signin-member", "scenario": "member"}
    t = threading.Thread(target=lambda: out.setdefault("s", bridge.ask(jid, AGENT, ask, 30)), daemon=True)
    t.start()
    wait_for(lambda: bridge.get(jid)["state"] == "needs-input")

    go(page, "run", f"#/runs/{run_id}")
    card = "[data-sign-in-card='signin-member']"
    page.wait_for_selector(card)
    assert HOST in page.text_content(card)
    page.click(f"{card} [data-sign-in=signed-in]")
    t.join(10)
    assert out["s"]["answers"]["choice"] == "signed-in"
    page.wait_for_selector(card, state="detached")

    # With no job working on the run, its actions come back: queue an export.
    bridge.done(jid, AGENT, "failed", "stopped for the export check")
    page.click("[data-run-action=export]")
    export = wait_for(lambda: queued_run_job(bridge, run_id))
    assert bridge.get(export)["params"]["mode"] == "export" and bridge.get(export)["params"]["tester"] == TESTER
    bridge.cancel(export)
    assert not page.problems, page.problems


def test_run_screen_answers_a_parked_row(page, console, runs_root, figma_run):
    home = console.state.home
    bridge = console.state.bridge
    jid = bridge.create({"kind": "webtest-run", "ui_lang": "en", "run": figma_run, "tester": TESTER})["id"]
    assert agent_take(bridge) == jid
    folder = webtest.find_run(runs_root, figma_run)
    assert webtest.next_row(folder, BridgeReader(bridge), jid, AGENT)["row"] == "r02"
    webtest.park(folder, "r02", {"body": "Which footer?"})

    go(page, "run", f"#/runs/{figma_run}")
    page.click("tr[data-row='r02']")
    # Kestrel radios hide the native input behind a drawn dot: wait for it in the DOM, check it by its label.
    page.wait_for_selector("#park-r02-0", state="attached")
    page.check("label[for='park-r02-0']")
    page.click(".ask-form .k-btn--primary")
    page.wait_for_selector(".ask-form .k-field__error")
    page.fill("#park-r02-pre", "the footer of the member page")
    page.click(".ask-form .k-btn--primary")
    answers = wait_for(lambda: webtest_api.read_answers(home, figma_run)["answers"])
    (entry,) = answers.values()
    assert entry["action"] == "delegate" and entry["preconditions"] == "the footer of the member page"
    assert not page.problems, page.problems


def test_checks_tab_shows_the_test_depth_and_skips_a_check(page, console, runs_root):
    from testign import webtest_sources, webtest_suite  # noqa: PLC0415

    env = webtest_sources.Env(runs_root.parent, console.state.home)
    made = webtest_suite.new_suite(runs_root, name="Cart edit", kind="manual", payload={}, env=env, depth="standard")
    folder = webtest_suite.find_suite(runs_root, made["id"])
    suite = webtest_suite.load(folder)
    btn, qty, note = "Cart edit/Cart lines/[Update]", "Cart edit/Cart lines/[Quantity]", "Cart edit/Cart lines/[Note]"
    suite["controls"] = [
        {"about": btn, "type": "button", "action": True, "needs": [qty, note], "goes_to": "Checkout"},
        {"about": qty, "type": "textbox", "required": True, "format": "integer", "range": {"min": 1, "max": 99}},
        {"about": note, "type": "textbox", "length": {"max": 20}},
    ]
    tagged = [("action.normal", btn, "[Update] saves the cart"), ("action.navigate", btn, "[Update] opens Checkout"),
              ("state.empty", btn, "[Update] is disabled while every input is empty"),
              ("display.initial", qty, "[Quantity] shows 1 first"), ("display.initial", note, "[Note] is empty first")]
    suite["cases"] = [{"case": f"c{n}", **webtest_suite.check_case({"content": text, "class": "sure", "runner": "tester",
                                                                     "rule": rule, "about": about})}
                      for n, (rule, about, text) in enumerate(tagged, start=1)]
    webtest_suite.save(folder, suite)
    go(page, "suite", f"#/suites/{made['id']}?tab=checks")
    page.wait_for_selector("[data-check]")
    assert page.locator("tr[data-check]").count() > 10
    assert page.locator("[data-checks-action='extend']").count() == 0  # a manual suite has no agent job
    page.locator("tr[data-check='state.invalid|Cart edit/Cart lines/[Update]'] [data-checks-action='skip']").click()
    page.fill("#skip-reason", "Quantity has a spinner that refuses letters")
    page.locator("[data-checks-action='skip-save']").click()
    page.wait_for_selector("tr[data-check='state.invalid|Cart edit/Cart lines/[Update]'] [data-checks-action='unskip']")
    shots = os.environ.get("TESTIGN_SHOTS")
    if shots:
        page.evaluate("document.querySelectorAll('*').forEach(e => { if (e.scrollTop) e.scrollTop = 0; })")
        page.set_viewport_size({"width": 1440, "height": 1500})
        page.screenshot(path=f"{shots}/checks-tab.png")
        page.locator("#suite-depth").select_option("thorough")
        page.locator("[data-checks-action='depth']").click()
        page.wait_for_selector("[data-depth='thorough']")
        page.evaluate("document.querySelectorAll('*').forEach(e => { if (e.scrollTop) e.scrollTop = 0; })")
        page.screenshot(path=f"{shots}/checks-tab-thorough.png")
    assert not page.problems, page.problems
