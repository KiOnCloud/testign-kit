"""Browser test of the Jobs and Close review screens (Playwright, Chromium). Runs only with TESTIGN_E2E=1.

The agent side is played in-process on the server's bridge: a close job queued from the ja UI with
an empty tester name (prompted), one row edited, a diff with a new page and a superseded entry
confirmed, the manual pages pasted, a survey waiting with no agent, a silent agent released, and
the triggers disabled on an older revision.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

if os.environ.get("TESTIGN_E2E") != "1":
    pytest.skip("browser tests run only with TESTIGN_E2E=1", allow_module_level=True)

sync_api = pytest.importorskip("playwright.sync_api")

from console_helpers import InProcessServer  # noqa: E402

from testign import decisions  # noqa: E402

from testign.console import client, lifecycle  # noqa: E402
from testign.console import server as srv  # noqa: E402

AGENT = "s-e2eagent00000001"
ROWS_ASK = {"type": "review-rows", "id": "rows-1", "body": "レビューしてください", "rows": [
    {"row": "q1-a", "q": "Q1", "class": "decided", "feature": "注文確定", "page": "QA/Decisions/order",
     "anchors": ["確定"], "decision": "割引は請求書にも適用", "quote": "請求書にも適用します", "quote_lang": "ja",
     "source": "#comment-1009", "decided_by": "BrSE", "date": "2026-11-18"},
    {"row": "q1-b", "q": "Q1", "class": "fact", "feature": "注文確定", "page": "QA/Decisions/order",
     "anchors": [], "decision": "切り捨て", "quote": "", "source": "code", "decided_by": "Dev", "date": "2026-11-18"},
]}
NEW_PAGE = "## DEMO-1\n| Q1 | 割引 |\n"
PREVIEW = {"mode": "api", "added": ["D-DEMO-1-002"], "skipped": [], "superseded": ["D-DEMO-1-001"], "index_repaired": [],
           "approval": decisions.approval_hash([("QA/Decisions/order", None, NEW_PAGE)]),
           "pages": [{"name": "QA/Decisions/order", "exists": False, "updated": None, "old_content": "", "new_content": NEW_PAGE}]}
MANUAL = {"mode": "manual", "added": [], "pages": [{"page": "order", "name": "QA/Decisions/order", "exists": True,
                                                   "diff": "x", "new_content": "## DEMO-1\n| Q1 | 割引 |"}]}


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
    server.offset = [0.0]
    server.state.bridge.clock = lambda: time.monotonic() + server.offset[0]
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
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ja-JP")
    context.add_init_script("if (!localStorage.getItem('testign.uiLang')) localStorage.setItem('testign.uiLang', 'ja')")
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


def job_id(page) -> str:
    page.wait_for_function("location.hash.startsWith('#/jobs/')")
    return page.evaluate("location.hash").split("/")[2]


def agent_take(bridge, session=AGENT):
    got = bridge.wait(session, 0)
    assert got["job"], "no job offered"
    assert bridge.claim(got["job"]["id"], session) == {"ok": True}
    return got["job"]["id"]


def ask_async(bridge, jid, ask, out, key, session=AGENT):
    t = threading.Thread(target=lambda: out.setdefault(key, bridge.ask(jid, session, ask, 30)), daemon=True)
    t.start()
    return t


def test_survey_waits_with_no_agent(page, console):
    bridge = console.state.bridge
    assert bridge.attached is None
    page.wait_for_function("document.getElementById('agent-status').textContent.includes('/testign:console')")
    page.click("[data-trigger=survey]")
    page.fill("#survey-ticket", "DEMO-1")
    page.fill("#survey-repo", str(next((console.state.home.parent / "repo").iterdir())))
    page.click(".k-dialog__footer .k-btn--primary")
    jid = job_id(page)
    page.wait_for_selector(".k-split__panel")
    assert bridge.get(jid)["state"] == "queued" and bridge.get(jid)["ui_lang"] == "ja"
    assert "/testign:console" in page.text_content(".k-banner--warning")
    assert page.locator("#view .k-spinner").count() == 0
    page.click(".k-split__panel-head .k-btn--ghost")
    for _ in range(50):
        if bridge.get(jid)["state"] == "cancelled":
            break
        time.sleep(0.1)
    assert bridge.get(jid)["state"] == "cancelled"
    assert not page.problems, page.problems


def test_close_round_with_prompt_edit_and_diff(page, console):
    bridge = console.state.bridge
    out: dict = {}
    page.evaluate("localStorage.removeItem('testign.testerName')")
    go(page, "report", "#/tickets/DEMO-1")
    page.click("[data-trigger=close]")
    page.wait_for_selector("#tester-prompt")
    page.fill("#tester-prompt", "テスター A")
    page.click(".k-dialog__footer .k-btn--primary")
    jid = job_id(page)
    assert bridge.get(jid)["params"] == {"tester": "テスター A"} and bridge.get(jid)["ui_lang"] == "ja"

    assert agent_take(bridge) == jid
    t = ask_async(bridge, jid, ROWS_ASK, out, "rows")
    page.wait_for_function("document.title.startsWith('(1)')")
    page.click("[data-open-review]")
    page.wait_for_selector(".review-table")
    send = ".review-footer .k-btn--primary"
    assert page.is_disabled(send)
    assert page.get_attribute("tr[data-review-row='q1-a'] .quote", "lang") == "ja"
    page.click("[data-row='q1-a'][data-action='write']")
    page.click("[data-row='q1-b'][data-action='edit']")
    assert page.is_disabled(send)
    page.fill("#edit-decision-q1-b", "切り捨て (請求書も同じ)")
    assert page.is_enabled(send)
    page.click(send)
    t.join(10)
    assert out["rows"]["answers"]["rows"] == {
        "q1-a": {"action": "write"}, "q1-b": {"action": "edit", "decision": "切り捨て (請求書も同じ)"}}

    t = ask_async(bridge, jid, client.ask_from_preview(PREVIEW), out, "diff")
    page.click("[data-open-review]")
    page.wait_for_selector(".diff-box")
    assert "新規ページ" in page.text_content(".diff-head")
    assert "D-DEMO-1-001" in page.text_content(".summary-strip")
    page.click(".review-footer .k-btn--primary")
    t.join(10)
    assert out["diff"]["answers"] == {"confirm": True}
    assert bridge.get(jid)["confirmed_approval"] == PREVIEW["approval"]
    bridge.done(jid, AGENT, "done", "2 行を書き込みました")
    page.wait_for_function("document.querySelector('.agent-text') && document.querySelector('.agent-text').textContent.includes('2 行')")
    assert not page.problems, page.problems


def test_manual_mode_shows_pages_to_paste(page, console):
    bridge = console.state.bridge
    out: dict = {}
    jid = bridge.create({"kind": "close", "ticket": "DEMO-1", "tester": "テスター A", "ui_lang": "ja"})["id"]
    assert agent_take(bridge) == jid
    t = ask_async(bridge, jid, client.ask_from_preview(MANUAL), out, "paste")
    page.wait_for_function("document.title.startsWith('(1)')")
    late = page.context.browser.new_context()
    other = late.new_page()
    other.goto(f"http://127.0.0.1:{console.port}/#c={console.state.mint_launch_code()}")
    other.wait_for_selector("#main[data-ready='tickets']")
    go(other, "review", f"#/jobs/{jid}/review")
    other.click(".review-footer .k-btn--primary")
    other.wait_for_selector(".k-toast--danger")
    assert other.locator("[data-reopen]").count() == 0
    assert bridge.get(jid)["state"] == "needs-input"
    late.close()
    page.wait_for_selector("[data-session-notice].k-banner--warning [data-notice-release]")
    go(page, "review", f"#/jobs/{jid}/review")
    page.wait_for_selector(".page-content")
    assert page.text_content(".page-content") == "## DEMO-1\n| Q1 | 割引 |"
    assert page.locator("[data-copy-page]").count() == 1
    page.click(".review-footer .k-btn--primary")
    t.join(10)
    assert out["paste"]["answers"] == {"done": True}
    bridge.done(jid, AGENT, "done", "貼り付け済み")
    assert not page.problems, page.problems


def test_silent_agent_can_be_released(page, console):
    bridge = console.state.bridge
    jid = bridge.create({"kind": "close", "ticket": "DEMO-1", "tester": "テスター A", "ui_lang": "ja"})["id"]
    assert agent_take(bridge) == jid
    console.offset[0] += 16 * 60
    go(page, "jobs", f"#/jobs/{jid}")
    page.wait_for_selector(".k-split__panel-head .k-btn--danger")
    page.click(".k-split__panel-head .k-btn--secondary")
    page.wait_for_function("document.getElementById('agent-status').textContent.includes('/testign:console')")
    assert bridge.get(jid)["state"] == "failed" and bridge.get(jid)["reason"] == "session-lost"
    page.wait_for_selector(".k-banner--danger")
    assert not page.problems, page.problems


def test_triggers_disabled_on_an_older_revision(page, console):
    go(page, "report", "#/tickets/DEMO-1?rev=DEMO-1-survey-r1.md")
    assert page.is_disabled("[data-trigger=close]") and page.is_disabled("[data-trigger=write]")
    assert page.locator("[data-older-note]").count() == 1
    go(page, "report", "#/tickets/DEMO-1")
    assert page.is_enabled("[data-trigger=close]")
    assert not page.problems, page.problems
