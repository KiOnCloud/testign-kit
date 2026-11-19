"""Browser test of the web test run screens (Playwright, Chromium). Runs only with TESTIGN_E2E=1.

The agent side is played in-process on the server's bridge: a project and its hosts saved on the
Login screen, a plan job queued from the new-run form, the review table confirmed after one row is
delegated with its preconditions, and a parked row answered on the Run screen.
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
from testign.console import lifecycle, webtest_api  # noqa: E402
from testign.console import server as srv  # noqa: E402

AGENT = "s-e2ewebagent00001"
FIGMA = "https://www.figma.com/design/AbCdEfGhIjKl/Shop?node-id=12-34"
HOST = "dev.example.test"


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
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, console):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
    context.add_init_script("localStorage.setItem('testign.uiLang', 'en'); localStorage.setItem('testign.testerName', 'Tester A')")
    pg = context.new_page()
    pg.problems = []
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: pg.problems.append(f"{m.type}: {m.text}")
          if m.type in ("error", "warning") and "status of 409" not in m.text else None)
    pg.goto(f"http://127.0.0.1:{console.port}/#c={console.state.mint_launch_code()}")
    pg.wait_for_selector("#main[data-ready='tickets']")
    yield pg
    context.close()


def go(page, name, hash_):
    page.evaluate(
        """([h]) => { const m = document.getElementById('main'); if (m) delete m.dataset.ready;
        if (location.hash === h) window.dispatchEvent(new HashChangeEvent('hashchange')); else location.hash = h; }""",
        [hash_],
    )
    page.wait_for_function("([n]) => document.getElementById('main') && document.getElementById('main').dataset.ready === n", arg=[name])


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


def test_project_hosts_and_new_run_form(page, console):
    home = console.state.home
    go(page, "login", "#/login")
    page.fill("#login-project-name", "demo")
    page.fill("#login-hosts", f"{HOST.upper()}\n")
    page.click("[data-save-hosts]")
    page.wait_for_selector("[data-project='demo'].is-selected")
    assert login_scenarios.get_project(home, "demo")["hosts"] == [HOST]

    go(page, "runs", "#/runs")
    page.fill("#runform-figma_url", FIGMA)
    page.select_option("#runform-project", "demo")
    page.fill("#runform-base_url", f"https://{HOST}/")
    page.fill("#runform-name", "Header update")
    page.click(".run-form .k-btn--primary")
    page.wait_for_function("() => location.hash.startsWith('#/jobs/')")
    jid = page.evaluate("location.hash").split("/")[2]
    job = console.state.bridge.get(jid)
    assert job["kind"] == "webtest-plan" and job["params"]["project"] == "demo"
    assert job["params"]["source"]["node"] == "12:34" and job["params"]["hosts"] == [HOST]
    console.state.bridge.cancel(jid)
    assert not page.problems, page.problems


def test_review_table_needs_preconditions_for_a_delegated_row(page, console):
    home = console.state.home
    bridge = console.state.bridge
    login_scenarios.save_project(home, "demo", [HOST])
    run_id = build(home / "Downloads" / "webtest", FakeConsole(), confirm=False, when=datetime(2026, 11, 19, 11, 0))
    jid = bridge.create({"kind": "webtest-plan", "ui_lang": "en", "name": "Header update", "figma_url": FIGMA,
                         "base_url": f"https://{HOST}/", "project": "demo"})["id"]
    assert agent_take(bridge) == jid
    bridge.attach_run(jid, AGENT, run_id)
    ask = {"type": "review-table", "id": f"review-{run_id}", "run": run_id, "template": "mẫu",
           "headers": {"A": "No", "B": "確認内容", "F": "結果"}, "last_column": "H",
           "columns": [{"field": "content", "letter": "B"}, {"field": "verdict", "letter": "F"}],
           "verdict_labels": {"pass": "OK", "fail": "NG"},
           "samples": [{"row": "r01", "class": "sure", "cells": {"B": "Label reads 予約履歴"}}],
           "lines": [{"row": "r01", "content": "label", "class": "sure", "runner": "agent", "scenario": "none",
                      "viewport": "pc", "screen": "/mypage", "confidence": "high"},
                     {"row": "r05", "content": "rule", "class": "choice", "runner": "tester", "scenario": "none",
                      "viewport": "pc", "screen": "/reservations", "confidence": "low"}],
           "digest": "d1"}
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("r", bridge.ask(jid, AGENT, ask, 30)), daemon=True)
    t.start()
    wait_for(lambda: bridge.get(jid)["state"] == "needs-input")

    go(page, "reviewTable", f"#/jobs/{jid}/review-table")
    page.wait_for_selector("[data-rt-row='r05']")
    confirm = "[data-confirm-table]"
    assert page.is_enabled(confirm)
    page.select_option("#rt-runner-r05", "agent")
    assert page.is_disabled(confirm)
    page.fill("tr[data-rt-row='r05'] textarea", "booking #1042, Confirmed")
    page.press("tr[data-rt-row='r05'] textarea", "Tab")
    assert page.is_enabled(confirm)
    page.click(confirm)
    t.join(10)
    answer = out["r"]["answers"]
    assert answer["confirm"] is True
    assert answer["rows"] == {"r05": {"runner": "agent", "preconditions": "booking #1042, Confirmed"}}
    page.wait_for_function("([r]) => location.hash === '#/runs/' + r", arg=[run_id])
    bridge.done(jid, AGENT, "done", "plan saved")
    assert not page.problems, page.problems


def test_run_screen_answers_a_parked_row(page, console):
    home = console.state.home
    bridge = console.state.bridge
    login_scenarios.save_project(home, "demo", [HOST])
    run_id = build(home / "Downloads" / "webtest", FakeConsole(), when=datetime(2026, 11, 19, 12, 0))
    jid = bridge.create({"kind": "webtest-run", "ui_lang": "en", "run": run_id, "tester": "Tester A"})["id"]
    assert agent_take(bridge) == jid
    folder = webtest.find_run(home / "Downloads" / "webtest", run_id)
    assert webtest.next_row(folder, jid, AGENT)["row"] == "r02"
    webtest.park(folder, "r02", {"body": "Which footer?"})

    go(page, "run", f"#/runs/{run_id}")
    page.click("tr[data-row='r02']")
    page.wait_for_selector("#park-r02-0")
    page.check("#park-r02-0")
    page.click(".ask-form .k-btn--primary")
    page.wait_for_selector(".ask-form .k-field__error")
    page.fill("#park-r02-pre", "the footer of the member page")
    page.click(".ask-form .k-btn--primary")
    answers = wait_for(lambda: webtest_api.read_answers(home, run_id)["answers"])
    (entry,) = answers.values()
    assert entry["action"] == "delegate" and entry["preconditions"] == "the footer of the member page"
    assert not page.problems, page.problems
