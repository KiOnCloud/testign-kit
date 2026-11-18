"""Browser smoke test of the console UI (Playwright, Chromium). Runs only with TESTIGN_E2E=1.

Each screen loads against made-up DEMO data in vi, en and ja at 390 and 1440 px with no console
error (CSP violations included) and no horizontal page scroll; switching language changes chrome
but not report text; a reused launch code shows the reopen message.
"""

from __future__ import annotations

import os

import pytest

if os.environ.get("TESTIGN_E2E") != "1":
    pytest.skip("browser tests run only with TESTIGN_E2E=1", allow_module_level=True)

sync_api = pytest.importorskip("playwright.sync_api")

from console_helpers import InProcessServer  # noqa: E402

from testign.console import lifecycle  # noqa: E402
from testign.console import server as srv  # noqa: E402

LANGS = ("vi", "en", "ja")
WIDTHS = (390, 1440)
NAV_TICKETS = {"vi": "Tickets", "en": "Tickets", "ja": "チケット"}


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
    server.close()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def launch_url(console) -> str:
    return f"http://127.0.0.1:{console.port}/#c={console.state.mint_launch_code()}"


def routes(console):
    workbook = console.data["workbook"]
    return [
        ("tickets", "#/tickets"),
        ("report", "#/tickets/DEMO-1"),
        ("report", "#/tickets/DEMO-2"),
        ("report", "#/tickets/DEMO-3"),
        ("trace", "#/tickets/DEMO-1/trace"),
        ("trace", f"#/tickets/DEMO-1/trace?workbook={workbook}&template=english"),
        ("templates", "#/templates"),
        ("cache", "#/cache"),
        ("settings", "#/settings"),
    ]


def open_page(browser, console, lang, width):
    context = browser.new_context(viewport={"width": width, "height": 900}, locale="en-US")
    context.add_init_script(f"localStorage.setItem('testign.uiLang', '{lang}')")
    page = context.new_page()
    problems: list[str] = []
    page.on("console", lambda m: problems.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.goto(launch_url(console))
    page.wait_for_selector("#main[data-ready='tickets']")
    return context, page, problems


def go(page, name, hash_):
    page.evaluate(
        """([h]) => { const m = document.getElementById('main'); if (m) delete m.dataset.ready;
        if (location.hash === h) window.dispatchEvent(new HashChangeEvent('hashchange')); else location.hash = h; }""",
        [hash_],
    )
    page.wait_for_function(
        "([n, h]) => { const m = document.getElementById('main'); return m && m.dataset.ready === n && location.hash === h; }",
        arg=[name, hash_],
    )
    page.wait_for_load_state("networkidle")


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("lang", LANGS)
def test_every_screen_renders_clean(browser, console, lang, width):
    context, page, problems = open_page(browser, console, lang, width)
    try:
        assert page.evaluate("location.hash") == "#/tickets"
        assert page.evaluate("document.documentElement.lang") == lang
        for name, hash_ in routes(console):
            go(page, name, hash_)
            assert page.text_content("[data-nav=tickets] .nav-label") == NAV_TICKETS[lang]
            sw, cw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            assert sw <= cw, f"horizontal scroll on {hash_} at {width}px"
        assert not [p for p in problems if "Content Security Policy" in p or "Refused" in p], problems
        assert not problems, problems
    finally:
        context.close()


def test_language_switch_changes_chrome_not_report_text(browser, console):
    context, page, problems = open_page(browser, console, "vi", 1440)
    try:
        go(page, "report", "#/tickets/DEMO-1")
        cell = 'td[data-cell="B3:2"]'
        label_before = page.text_content("[data-nav=tickets] .nav-label")
        text_before = page.text_content(cell)
        assert "⟨U+202E⟩" in text_before
        page.click("[data-radio=side-lang][data-value=ja]")
        page.wait_for_function("() => document.documentElement.lang === 'ja' && document.getElementById('main').dataset.ready === 'report'")
        assert page.text_content("[data-nav=tickets] .nav-label") != label_before
        assert page.text_content(cell) == text_before
        assert page.evaluate("localStorage.getItem('testign.uiLang')") == "ja"
        assert page.evaluate("Object.keys(localStorage).some(k => k.includes('session'))") is False
        assert not problems, problems
    finally:
        context.close()


def test_palette_and_escape(browser, console):
    context, page, problems = open_page(browser, console, "en", 1440)
    try:
        page.keyboard.press("Control+k")
        page.wait_for_selector(".k-palette")
        page.keyboard.type("DEMO-2")
        page.keyboard.press("Enter")
        page.wait_for_function("() => location.hash === '#/tickets/DEMO-2'")
        go(page, "report", "#/tickets/DEMO-1")
        page.click("tr[data-row=B3]")
        page.wait_for_selector(".k-split__panel")
        page.keyboard.press("Escape")
        page.wait_for_selector(".k-split__panel", state="detached")
        go(page, "tickets", "#/tickets")
        page.focus("[data-search]")
        page.keyboard.press("j")
        assert page.input_value("[data-search]") == "j"
        assert not problems, problems
    finally:
        context.close()


def test_reused_launch_code_shows_reopen_message(browser, console):
    url = launch_url(console)
    first = browser.new_context()
    page = first.new_page()
    page.goto(url)
    page.wait_for_selector("#main[data-ready]")
    first.close()
    second = browser.new_context()
    page = second.new_page()
    page.goto(url)
    page.wait_for_selector("[data-reopen]")
    assert "testign console open" in page.text_content("[data-reopen]")
    second.close()
