"""The Playwright engine for recording and replaying a suite's spec, and for Login Recipes.

Only this module talks to a Playwright browser, and Playwright is imported lazily: it is needed
only to record or replay (``pip install playwright`` and ``python -m playwright install chromium``).

A step's failure is told apart, so the person reading a run knows whether to fix the spec or file a
defect:

* ``spec_error``       the locator finds nothing, or several elements, or the page does not open: the
                       spec is wrong;
* ``fail``             an ``expect_`` check failed (or an action on a found element failed): the app is
                       wrong;
* ``session_expired``  a page opened on the sign-in page: the saved session no longer signs in;
* ``off_site``         the page tried to open a page outside the run's hosts; the request is aborted.

Every attempt starts in a fresh browser context, signed in from the saved session, so a step list
that passes while recording replays the same way in a run.
"""

from __future__ import annotations

import base64
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from . import login_recipe
from .login_recipe import RecipeError, url_matcher
from .webtest import url_on_hosts

OK, FAIL, SPEC_ERROR, SESSION_EXPIRED, OFF_SITE = "ok", "fail", "spec_error", "session_expired", "off_site"
DEFAULT_TIMEOUT_MS = 8_000
LOGIN_TIMEOUT_MS = 15_000
LOGIN_WAIT_MS = 30_000
MAX_ERROR = 300
MAX_SNAPSHOT = 8_000
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
MAX_REPLY_BYTES = 5_000_000
DROP_HEADERS = ("content-length", "content-encoding", "transfer-encoding")
SETTLE_MS = 3_000
EXPECT_TEXT = ("expect_text", "expect_value")


class SpecProblem(Exception):
    """The spec is wrong, or the page cannot be tried."""


class SessionExpired(Exception):
    """A page opened on the sign-in page."""


class EngineUnavailable(RecipeError):
    """Playwright or Chromium is missing on this machine."""


def first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        raise EngineUnavailable("Playwright is not installed for this Python: "
                                "python -m pip install playwright && python -m playwright install chromium") from None
    return sync_playwright()


BROWSER_NAMES = {"chromium": "Chromium", "msedge": "Microsoft Edge", "firefox": "Firefox", "webkit": "WebKit"}


def launch(p, headed: bool = False, browser: str = "chromium"):
    """Start one browser: ``chromium`` (``TESTIGN_BROWSER_EXECUTABLE`` points at another Chromium build
    when set), ``msedge`` (the installed Microsoft Edge), ``firefox`` or ``webkit`` (Playwright's builds)."""
    kwargs: dict[str, Any] = {"headless": not headed}
    if browser == "chromium":
        exe = os.environ.get("TESTIGN_BROWSER_EXECUTABLE")
        if exe:
            kwargs["executable_path"] = exe
        kind = p.chromium
    elif browser == "msedge":
        kwargs["channel"] = "msedge"
        kind = p.chromium
    elif browser in ("firefox", "webkit"):
        kind = getattr(p, browser)
    else:
        raise EngineUnavailable(f"unknown browser {browser}")
    try:
        return kind.launch(**kwargs)
    except Exception as exc:  # noqa: BLE001 - browser missing, no display for headed ...
        raise EngineUnavailable(f"cannot start {BROWSER_NAMES[browser]}: {first_line(exc)[:200]}") from None


def build_locator(page, loc: dict):
    if "nth" in loc:
        return build_locator(page, {k: v for k, v in loc.items() if k != "nth"}).nth(loc["nth"])
    kw = {"exact": loc["exact"]} if loc.get("exact") is not None else {}
    if "role" in loc:
        if loc.get("name"):
            kw["name"] = loc["name"]
        return page.get_by_role(loc["role"], **kw)
    if "label" in loc:
        return page.get_by_label(loc["label"], **kw)
    if "placeholder" in loc:
        return page.get_by_placeholder(loc["placeholder"], **kw)
    if "text" in loc:
        return page.get_by_text(loc["text"], **kw)
    if "test_id" in loc:
        return page.get_by_test_id(loc["test_id"])
    return page.locator(loc["css"])


def describe(step: dict) -> str:
    loc = step.get("locator") or {}
    target = ", ".join(f"{k}={v}" for k, v in loc.items() if k != "exact")
    value = repr(step["value"]) if step.get("value") is not None else ""
    return " ".join(x for x in (step["action"], target, value) if x)


# assertions a reviewer looks at ----------------------------------------------------------------
def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("“", '"').replace("”", '"')).strip().lower()


def sourced_value(step: dict) -> str | None:
    """The text an ``expect_`` step compares with the case's expected result."""
    if step.get("action") in EXPECT_TEXT:
        return step.get("value")
    if step.get("action") == "expect_visible" and "text" in (step.get("locator") or {}):
        return step["locator"]["text"]
    return None


def is_sourced(step: dict, expected: str) -> bool | None:
    value = sourced_value(step)
    if value is None:
        return None
    want = norm(value)
    return bool(want) and want in norm(expected)


# Text that changes with the data or the day: a locator naming a control by it passes today and
# finds nothing next week.
_LIVE_DATA = re.compile(
    r"\d{4}\s*[-/.年]\s*\d{1,2}|\d{1,2}\s*[/月]\s*\d{1,2}|\d{1,2}\s*日|\d{1,2}:\d{2}"
    r"|(?:残り?|あと|在庫|空き)\s*[:：]?\s*\d"
    r"|\d+\s*(?:件|個|名|人|枠|席|点|left\b|remaining\b|available\b|in stock\b|slots?\b|seats?\b|results?\b|items?\b)"
    r"|[(（]\s*\d+\s*[)）]|\d+\s*/\s*\d+", re.IGNORECASE)


def live_data_name(step: dict, expected: str) -> str | None:
    loc = step.get("locator") or {}
    for key in ("name", "label", "placeholder", "text"):
        name = loc.get(key)
        if isinstance(name, str) and any(norm(m.group(0)) not in norm(expected) for m in _LIVE_DATA.finditer(name)):
            return name
    return None


def assertion_warnings(steps: list[dict], expected: str) -> list[dict]:
    """Locators holding live data, checks whose text is not in the expected result, and a case
    where no check compares any text of the expected result."""
    out = []
    for i, step in enumerate(steps, start=1):
        name = live_data_name(step, expected)
        if name is not None:
            out.append({"step": i, "kind": "live_data_locator", "value": name})
    marks = [(i, is_sourced(s, expected)) for i, s in enumerate(steps, start=1) if s.get("action", "").startswith("expect_")]
    for i, ok in marks:
        if ok is False:
            out.append({"step": i, "kind": "unsourced", "value": sourced_value(steps[i - 1])})
    if marks and not any(ok for _, ok in marks):
        out.append({"step": None, "kind": "no_value_check"})
    return out


# steps --------------------------------------------------------------------------------------------
def do_step(page, base_url: str, step: dict) -> None:
    from playwright.sync_api import expect  # noqa: PLC0415

    action = step["action"]
    timeout = step.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    loc = build_locator(page, step["locator"]) if step.get("locator") else None
    value = step.get("value")
    if action == "goto":
        page.goto(urljoin(base_url.rstrip("/") + "/", value.lstrip("/")), timeout=timeout)
    elif action == "fill":
        loc.fill(value, timeout=timeout)
    elif action == "click":
        loc.click(timeout=timeout)
    elif action == "dblclick":
        loc.dblclick(timeout=timeout)
    elif action == "press":
        loc.press(value, timeout=timeout)
    elif action == "select":
        loc.select_option(value, timeout=timeout)
    elif action == "check":
        loc.check(timeout=timeout)
    elif action in ("wait_visible", "expect_visible"):
        expect(loc).to_be_visible(timeout=timeout)
    elif action == "expect_hidden":
        expect(loc).to_be_hidden(timeout=timeout)
    elif action == "expect_text":
        expect(loc).to_contain_text(value, timeout=timeout)
    elif action == "expect_value":
        expect(loc).to_have_value(value, timeout=timeout)
    elif action == "expect_url":
        match = url_matcher(value)
        deadline = time.monotonic() + timeout / 1000
        while not match(page.url):
            if time.monotonic() > deadline:
                raise AssertionError(f"the URL is {page.url}, expected {value}")
            page.wait_for_timeout(100)
    else:
        raise SpecProblem(f"unknown action {action}")


def try_step(page, base_url: str, step: dict, expected: str, login_url: str | None, state: dict) -> None:
    """Run one step; SpecProblem when the locator matches nothing or several elements (unless the
    locator is the expected text itself: then nothing found is the app's fail)."""
    loc_spec = step.get("locator")
    if loc_spec and step["action"] != "expect_hidden":
        loc = build_locator(page, {k: v for k, v in loc_spec.items() if k != "nth"})
        try:
            loc.first.wait_for(state="attached", timeout=step.get("timeout_ms", DEFAULT_TIMEOUT_MS))
        except Exception as exc:  # noqa: BLE001 - Playwright timeout
            _check_session(page, login_url)
            if state.get("off_site"):
                raise SpecProblem(f"the page tried to open {state['off_site']}, outside the run's hosts") from exc
            if step["action"].startswith("expect_") and is_sourced(step, expected) and "text" in loc_spec:
                raise AssertionError(f"the expected text {loc_spec['text']!r} is not on the page") from exc
            raise SpecProblem(f"no element matches {describe(step)}") from exc
        count = loc.count()
        if "nth" in loc_spec:
            if count <= loc_spec["nth"]:
                raise SpecProblem(f"{count} elements match {describe(step)}; there is no element at nth={loc_spec['nth']}")
        elif count > 1:
            raise SpecProblem(f"{count} elements match {describe(step)}; make the locator unique")
    if step["action"] == "goto":
        try:
            do_step(page, base_url, step)
        except Exception as exc:  # noqa: BLE001 - wrong URL, the app is down, or an aborted off-site jump
            if state.get("off_site"):
                raise SpecProblem(f"the page tried to open {state['off_site']}, outside the run's hosts") from exc
            raise SpecProblem(f"cannot open {step['value']}: {first_line(exc)}") from exc
        _check_session(page, login_url)
        return
    do_step(page, base_url, step)


def _check_session(page, login_url: str | None) -> None:
    if login_url and login_recipe.same_page(page.url, login_url):
        raise SessionExpired("the page opened on the sign-in page: the saved session no longer signs in")


def _guard_hosts(context, hosts: list[str], state: dict) -> None:
    """Abort every page navigation outside the run's hosts (other requests, such as a CDN's
    scripts, still load)."""
    def route(r):
        req = r.request
        if req.is_navigation_request() and req.url.startswith(("http://", "https://")) and not url_on_hosts(req.url, hosts):
            state["off_site"] = req.url[:200]
            r.abort()
            return
        if state.get("answers") is not None:
            _answer(r, state)
            return
        r.continue_()
    context.route("**/*", route)


def changes_data(method: str) -> bool:
    return (method or "GET").upper() not in SAFE_METHODS


def _trying(state: dict) -> bool:
    return state.get("capture_from") is not None and state["step"] >= state["capture_from"]


def _answer(r, state: dict) -> None:
    """A recorded step's data-changing request gets the reply kept when it first passed."""
    req = r.request
    if changes_data(req.method) and not _trying(state):
        for n, kept in enumerate(state["queue"]):
            if kept["method"] == req.method and kept["url"] == req.url and not kept.get("too_big"):
                state["queue"].pop(n)
                r.fulfill(status=kept["status"], headers=kept.get("headers") or {},
                          body=base64.b64decode(kept["body"]) if kept.get("body") else b"")
                return
        state["resent"].append({"step": state["step"], "method": req.method, "url": req.url})
    r.continue_()


def _keep_replies(context, state: dict) -> None:
    def started(req):
        if _trying(state) and changes_data(req.method):
            state["inflight"].add(req)

    def finished(req):
        state["inflight"].discard(req)

    def reply(res):
        req = res.request
        if not _trying(state) or not changes_data(req.method):
            return
        entry = {"step": state["step"], "method": req.method, "url": req.url, "status": res.status,
                 "headers": {k: v for k, v in res.headers.items() if k.lower() not in DROP_HEADERS}, "body": None}
        if not 300 <= res.status < 400:
            try:
                body = res.body()
            except Exception:  # noqa: BLE001 - the page went on before the body could be read
                body = b""
            if len(body) > MAX_REPLY_BYTES:
                entry["too_big"] = True
            else:
                entry["body"] = base64.b64encode(body).decode("ascii")
        state["sent"].append(entry)

    context.on("request", started)
    context.on("requestfinished", finished)
    context.on("requestfailed", finished)
    context.on("response", reply)


def _settle(page, done) -> None:
    waited = 0
    while not done() and waited < SETTLE_MS:
        page.wait_for_timeout(50)
        waited += 50


def run_case(browser, *, base_url: str, hosts: list[str], steps: list[dict], expected: str = "",
             storage: str | None = None, login_url: str | None = None, snapshot: bool = False,
             secrets: list[str] | None = None, answers: list | None = None, capture_from: int | None = None,
             screenshot: Path | None = None) -> dict:
    """Replay ``steps`` in a fresh context. Returns {"result", "step", "error", "url"} plus
    ``snapshot``, ``sent`` (replies of the steps from ``capture_from`` on), ``resent`` and
    ``screenshot`` (the page at the end, or where it failed, when a path was given)."""
    context = browser.new_context(storage_state=storage) if storage else browser.new_context()
    state: dict = {"step": 0, "queue": list(answers or []), "sent": [], "resent": [], "inflight": set(),
                   "capture_from": capture_from,
                   "answers": list(answers or []) if (answers is not None or capture_from is not None) else None}
    _guard_hosts(context, hosts, state)
    if capture_from is not None:
        _keep_replies(context, state)
    page = context.new_page()
    out: dict = {"result": OK, "step": None, "error": None}
    scrub = secrets or []
    try:
        for i, step in enumerate(steps, start=1):
            if capture_from is not None and i == capture_from:
                _settle(page, lambda: not state["queue"])
                state["queue"] = []
            state["step"] = i
            try:
                try_step(page, base_url, step, expected, login_url, state)
            except SessionExpired as exc:
                out = {"result": SESSION_EXPIRED, "step": i, "error": f"step {i}: {exc}"}
                break
            except SpecProblem as exc:
                kind = OFF_SITE if state.get("off_site") else SPEC_ERROR
                out = {"result": kind, "step": i, "error": login_recipe.redact(f"step {i}: {exc}", scrub)[:MAX_ERROR]}
                break
            except Exception as exc:  # noqa: BLE001 - any other failure is the app's answer
                out = {"result": FAIL, "step": i,
                       "error": login_recipe.redact(f"step {i} ({describe(step)}): {first_line(exc)}", scrub)[:MAX_ERROR]}
                break
        if capture_from is not None:
            _settle(page, lambda: not state["inflight"])
        out["url"] = page.url
        if screenshot is not None:
            try:
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot), full_page=True)
                out["screenshot"] = screenshot
            except Exception:  # noqa: BLE001 - a missing screenshot does not change the result
                out["screenshot"] = None
        if snapshot:
            out["snapshot"] = page_snapshot(page, scrub)
    finally:
        context.close()
    if capture_from is not None:
        out["sent"] = state["sent"]
    if state["resent"]:
        out["resent"] = state["resent"]
    return out


_TEST_IDS_JS = """() => [...document.querySelectorAll('[data-testid]')].slice(0, 80)
  .map(e => ({test_id: e.getAttribute('data-testid'), text: (e.innerText || e.value || '').trim().slice(0, 60)}))"""


def page_snapshot(page, secrets: list[str]) -> dict:
    """What the agent sees: the accessibility tree and the elements with a test id, with profile
    values replaced."""
    try:
        tree = page.locator("body").aria_snapshot(timeout=5_000)
    except Exception as exc:  # noqa: BLE001
        tree = f"(no snapshot: {first_line(exc)})"
    try:
        test_ids = page.evaluate(_TEST_IDS_JS)
    except Exception:  # noqa: BLE001
        test_ids = []
    try:
        title = page.title()
    except Exception:  # noqa: BLE001
        title = ""

    def scrub(text: str) -> str:
        for secret in sorted((s for s in secrets if s), key=len, reverse=True):
            text = text.replace(secret, "[redacted]")
        return text

    tree = scrub(tree)
    if len(tree) > MAX_SNAPSHOT:
        tree = tree[:MAX_SNAPSHOT] + "\n... (cut)"
    return {"title": scrub(title), "tree": tree,
            "test_ids": [{"test_id": scrub(t.get("test_id") or ""), "text": scrub(t.get("text") or "")} for t in test_ids]}


# sign-in ------------------------------------------------------------------------------------------
def sign_in(browser, recipe: dict, values: dict[str, str], hosts: list[str]) -> dict:
    """Run a recipe's steps with the profile's values. Returns {"ok", "error", "failed_step",
    "state"}; ``error`` never holds a value."""
    context = browser.new_context()
    guard: dict = {"step": 0, "answers": None}
    _guard_hosts(context, hosts, guard)
    page = context.new_page()
    page.set_default_timeout(LOGIN_TIMEOUT_MS)
    out: dict = {"ok": False, "error": None, "failed_step": None, "state": None}
    try:
        for i, step in enumerate(recipe["steps"], start=1):
            try:
                _login_step(page, step, values)
            except Exception as exc:  # noqa: BLE001 - Playwright raises its own Error / TimeoutError
                where = f" (the page tried to open {guard['off_site']}, outside the project's hosts)" if guard.get("off_site") else ""
                out["failed_step"] = i
                out["error"] = login_recipe.redact(f"step {i} ({step['action']}): {type(exc).__name__}: {exc}{where}", values)
                return out
        state = context.storage_state()
        if not state.get("cookies") and not any(o.get("localStorage") for o in state.get("origins") or []):
            out["failed_step"] = len(recipe["steps"])
            out["error"] = ("every step passed but the site saved no session (no cookie, no localStorage): the last "
                            "check passed before the sign-in finished; wait for something only a signed-in page shows")
            return out
        out.update({"ok": True, "state": state})
        return out
    finally:
        context.close()


def _login_step(page, step: dict, values: dict[str, str]) -> None:
    action = step["action"]
    timeout = step.get("timeout_ms")
    if action == "goto":
        page.goto(step["value"], wait_until="domcontentloaded", timeout=timeout or 30_000)
        return
    if action == "wait_url":
        page.wait_for_url(url_matcher(step["value"]), timeout=timeout or LOGIN_WAIT_MS)
        return
    loc = build_locator(page, step["locator"])
    if action == "wait_visible":
        loc.first.wait_for(state="visible", timeout=timeout or LOGIN_WAIT_MS)
    elif action == "fill":
        key = login_recipe.placeholder_key(step["value"])
        if key not in values:
            raise RecipeError(f"the profile has no value for {{{{{key}}}}}")
        loc.fill(values[key], timeout=timeout or LOGIN_TIMEOUT_MS)
    elif action == "click":
        loc.click(timeout=timeout or LOGIN_TIMEOUT_MS)
    elif action == "press":
        loc.press(step["value"], timeout=timeout or LOGIN_TIMEOUT_MS)


def test_recipe(home: Path | None, project: str, scenario: str, hosts: list[str]) -> dict:
    """Sign in with the recipe and the profile, save the session, keep the outcome for the console."""
    recipe = login_recipe.load(home, project, scenario)
    if recipe is None:
        raise RecipeError(f"scenario {scenario} has no recipe yet")
    values = login_recipe.profile_values(home, project, recipe.get("profile"))
    fp = login_recipe.fingerprint(recipe)
    with playwright() as p:
        browser = launch(p)
        try:
            result = sign_in(browser, recipe, values, hosts)
        finally:
            browser.close()
    if result["ok"]:
        login_recipe.save_session(home, project, scenario, result["state"])
    login_recipe.store_test(home, project, scenario, fp, result)
    return {k: result[k] for k in ("ok", "error", "failed_step")}


def session_for(home: Path | None, project: str, scenario: str | None, hosts: list[str], *, fresh: bool) -> dict:
    """The storage state a case of ``scenario`` opens with: {"storage", "login_url", "secrets"}.
    ``fresh`` signs in again; otherwise a saved session is reused. Raises RecipeError when the
    scenario has no usable recipe or the sign-in fails."""
    if not scenario or scenario == "none":
        return {"storage": None, "login_url": None, "secrets": []}
    view = login_recipe.view(home, project, scenario)
    if not view["usable"]:
        raise RecipeError(f"scenario {scenario} has no usable recipe (it needs a profile, a passing test and the tester's approval)")
    recipe = login_recipe.load(home, project, scenario)
    values = login_recipe.profile_values(home, project, recipe.get("profile"))
    path = login_recipe.session_path(home, project, scenario)
    if fresh or path is None or not path.is_file():
        with playwright() as p:
            browser = launch(p)
            try:
                result = sign_in(browser, recipe, values, hosts)
            finally:
                browser.close()
        if not result["ok"]:
            raise RecipeError(f"signing in as {scenario} failed: {result['error']}")
        path = login_recipe.save_session(home, project, scenario, result["state"])
    return {"storage": str(path), "login_url": recipe["login_url"], "secrets": list(values.values())}
