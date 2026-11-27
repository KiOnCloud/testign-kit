"""Record once, replay with Playwright, sign in with a Login Recipe: real Chromium on a local made-up
site. Runs only with TESTIGN_E2E=1 and Playwright installed (TESTIGN_BROWSER_EXECUTABLE may point at
a Chromium build)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

if os.environ.get("TESTIGN_E2E") != "1":
    pytest.skip("browser tests run only with TESTIGN_E2E=1", allow_module_level=True)
pytest.importorskip("playwright.sync_api")

from demo_site import PASSWORD, USER, DemoSite  # noqa: E402
from make_webtest_run import ready_suite  # noqa: E402

from testign import (  # noqa: E402
    login_recipe, login_scenarios, templates, webtest, webtest_export, webtest_live, webtest_record, webtest_replay,
    webtest_spec, webtest_suite,
)

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "templates" / "testcase-template-sample.xlsx"
HOSTS = ["localhost"]
CASES = [
    {"content": "予約確認 → 予約履歴 on the header link", "kind": "label", "class": "sure", "runner": "agent",
     "scenario": "member", "screen": "/mypage", "steps": "1. Open My Page", "expected": "The header link reads 予約履歴"},
    {"content": "A help link is added to the footer", "kind": "element", "class": "sure", "runner": "agent",
     "scenario": "none", "screen": "/", "steps": "1. Open the top page", "expected": "The footer has a Help link"},
    {"content": "Subscribe shows a confirmation", "kind": "behaviour", "class": "sure", "runner": "agent",
     "scenario": "member", "screen": "/mypage", "steps": "1. Press Subscribe", "expected": "Subscribed is shown"},
    {"content": "Totals are written by the nightly batch", "kind": "data-rule", "class": "not-web"},
]


@pytest.fixture(scope="module")
def site():
    s = DemoSite()
    yield s
    s.close()


def browsers_path() -> str:
    """Playwright's browser folder under the real home: the tests point HOME at a temporary folder, and
    on macOS and Linux Playwright looks for its browsers under HOME."""
    home = Path.home()
    if sys.platform == "darwin":
        return str(home / "Library" / "Caches" / "ms-playwright")
    if os.name == "nt":
        return str(Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "ms-playwright")
    return str(Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache") / "ms-playwright")


@pytest.fixture
def env(tmp_path, monkeypatch, site):
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", browsers_path())
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".testign-kit").mkdir()
    (tmp_path / ".testign-kit" / "config.json").write_text(
        json.dumps({"output_dir": str(tmp_path / "out"), "lang": "en"}), encoding="utf-8")
    templates.register(SAMPLE, "sample", home=tmp_path, purpose="webtest")
    login_scenarios.save_project(tmp_path, "demo", HOSTS)
    login_scenarios.save_draft(tmp_path, "demo", {"name": "member", "label": "Member",
                                                 "login_url": f"{site.base_url}login", "steps": ["Sign in"]})
    recipe = login_recipe.save(tmp_path, "demo", "member", {"profile": "member01", "login_url": f"{site.base_url}login", "steps": [
        {"action": "goto", "value": f"{site.base_url}login"},
        {"action": "fill", "locator": {"label": "User"}, "value": "{{username}}"},
        {"action": "fill", "locator": {"label": "Password"}, "value": "{{password}}"},
        {"action": "click", "locator": {"role": "button", "name": "Sign in"}},
        {"action": "wait_url", "value": "**/mypage"},
    ]})
    login_recipe.set_profile(tmp_path, "demo", "member01", {"username": USER, "password": PASSWORD})
    tested = webtest_live.test_recipe(tmp_path, "demo", "member", HOSTS)
    assert tested["ok"], tested
    login_recipe.approve(tmp_path, "demo", "member", recipe["fingerprint"], "fp-tester")
    site.label, site.footer_link, site.submits = "予約履歴", True, 0
    root = tmp_path / "out" / "webtest"
    return {"home": tmp_path, "root": root, "suite": ready_suite(root, cases=CASES)}


def new_run(env, site, minute, browsers=None):
    target = webtest.check_run_target({"demo": {"hosts": HOSTS}}, templates.list_templates(), site.base_url, "demo",
                                      browsers=browsers)
    suite = webtest_suite.load(env["suite"])
    made = webtest.new_run_from_suite(env["root"], suite, env["suite"], name=f"round {minute}", target=target,
                                      tester="Kien", columns_for=lambda run: webtest_export.suite_plan(run),
                                      when=datetime(2026, 11, 26, 10, minute))
    return webtest.find_run(env["root"], made["run"])


def states(folder):
    return {c["row"]: (c["state"], c.get("not_run_reason")) for c in webtest.load(folder)["cases"]}


def ok(detail):
    assert detail["result"] == "ok", detail
    return detail


def record_all(folder, home):
    started = webtest_record.start(folder, home)
    assert [r["row"] for r in started["rows"]] == ["r01", "r02", "r03"]
    opened = webtest_record.open_row(folder, "r01", home=home)
    assert "予約履歴" in opened["snapshot"]["tree"] and PASSWORD not in json.dumps(opened)
    ok(webtest_record.step(folder, "r01", {"action": "goto", "value": "/mypage"}, home))
    missing = webtest_record.step(folder, "r01", {"action": "expect_visible", "locator": {"role": "link", "name": "Nope"}}, home)
    assert missing["result"] == "spec_error"
    ok(webtest_record.step(folder, "r01", {"action": "expect_text", "locator": {"role": "banner"}, "value": "予約履歴"}, home))
    webtest_record.done(folder, "r01")
    ok(webtest_record.step(folder, "r02", {"action": "goto", "value": "/"}, home))
    ok(webtest_record.step(folder, "r02", {"action": "expect_visible", "locator": {"role": "link", "name": "Help"}}, home))
    webtest_record.done(folder, "r02")
    ok(webtest_record.step(folder, "r03", {"action": "goto", "value": "/mypage"}, home))
    sent = ok(webtest_record.step(folder, "r03", {"action": "click", "locator": {"role": "button", "name": "Subscribe"}}, home))
    assert sent["this_step_sent"][0]["method"] == "POST"
    ok(webtest_record.step(folder, "r03", {"action": "expect_text", "locator": {"css": "body"}, "value": "Subscribed"}, home))
    webtest_record.done(folder, "r03")
    return webtest_record.finish(folder, None, home)


def test_record_review_and_replay(env, site):
    home = env["home"]
    first = new_run(env, site, 1)
    finished = record_all(first, home)
    # The recorded submit reached the app once: later replays while recording, and the replay that
    # wrote the run's result, got the kept reply.
    assert site.submits == 1
    assert states(first)["r01"] == ("pass", None) and states(first)["r02"] == ("pass", None)
    run = webtest.load(first)
    assert all(c["result"]["by"] == "record" and c["evidence"] for c in run["cases"] if c["row"] in ("r01", "r02"))
    assert finished["spec"] == "draft"

    suite = webtest_suite.load(env["suite"])
    view = webtest_spec.view(env["suite"], suite)
    assert view["check"]["status"] == "passed" and view["recorded"] == 3
    webtest_spec.review(env["suite"], view["hash"], "fp-tester")

    second = new_run(env, site, 2)
    plan = webtest_replay.plan(second)
    assert [r["row"] for r in plan["rows"]] == ["r01", "r02", "r03"]
    result = webtest_replay.replay(second, None, home)
    assert {r["row"]: r["state"] for r in result["results"]} == {"r01": "pass", "r02": "pass", "r03": "pass"}
    assert webtest.load(second)["cases"][0]["result"]["by"] == "replay"

    # The app changes the label: the replay fails the row (a defect), not the spec.
    site.label = "予約確認"
    site.footer_link = False
    third = new_run(env, site, 3)
    webtest_replay.replay(third, None, home)
    assert states(third)["r01"][0] == "fail"
    assert states(third)["r02"] == ("not-run", "spec-error")  # the locator finds nothing: fix the spec


def test_a_broken_sign_in_leaves_rows_not_run(env, site):
    home = env["home"]
    folder = new_run(env, site, 4)
    record_all(folder, home)
    view = webtest_spec.view(env["suite"], webtest_suite.load(env["suite"]))
    webtest_spec.review(env["suite"], view["hash"], "fp-tester")
    login_recipe.set_profile(home, "demo", "member01", {"username": USER, "password": "wrong"})
    second = new_run(env, site, 5)
    webtest_replay.replay(second, None, home)
    assert states(second)["r01"] == ("not-run", "session-expired")
    assert states(second)["r02"] == ("pass", None)  # public page, no sign-in
    assert "wrong" not in json.dumps(webtest.load(second))


def test_each_browser_gets_its_verdict_and_a_missing_one_is_pending(env, site):
    home = env["home"]
    record_all(new_run(env, site, 6), home)
    view = webtest_spec.view(env["suite"], webtest_suite.load(env["suite"]))
    webtest_spec.review(env["suite"], view["hash"], "fp-tester")
    # WebKit is never installed for these tests, so it stays Pending while Chromium decides the row.
    folder = new_run(env, site, 7, browsers=["chromium", "webkit"])
    result = webtest_replay.replay(folder, None, home)
    assert result["browsers"] == ["chromium", "webkit"]
    r02 = webtest.case_of(webtest.load(folder), "r02")
    assert r02["state"] == "pass"
    assert r02["result"]["browsers"]["chromium"]["verdict"] == "pass"
    assert r02["result"]["browsers"]["webkit"]["verdict"] == "pending"


def test_engine_tells_failures_apart(env, site):
    home = env["home"]
    session = webtest_live.session_for(home, "demo", "member", HOSTS, fresh=True)
    with webtest_live.playwright() as p:
        browser = webtest_live.launch(p)
        try:
            run = lambda steps, storage=session["storage"]: webtest_live.run_case(  # noqa: E731
                browser, base_url=site.base_url, hosts=HOSTS, steps=steps, storage=storage,
                login_url=session["login_url"], secrets=session["secrets"])
            assert run([{"action": "goto", "value": "/mypage"},
                        {"action": "expect_text", "locator": {"role": "banner"}, "value": "予約履歴"}])["result"] == "ok"
            assert run([{"action": "goto", "value": "/mypage"},
                        {"action": "expect_text", "locator": {"role": "banner"}, "value": "Other"}])["result"] == "fail"
            assert run([{"action": "goto", "value": "/mypage"},
                        {"action": "click", "locator": {"role": "button", "name": "Missing"}}])["result"] == "spec_error"
            expired = run([{"action": "goto", "value": "/mypage"},
                           {"action": "expect_visible", "locator": {"text": "My Page"}}], storage=None)
            assert expired["result"] == "session_expired"
            away = run([{"action": "goto", "value": "/away"},
                        {"action": "click", "locator": {"role": "link", "name": "Partner"}},
                        {"action": "expect_visible", "locator": {"text": "Partner site"}}])
            assert away["result"] == "off_site" and "other.invalid" in away["error"]
        finally:
            browser.close()


def test_state_checks_and_click_blocked(env, site):
    with webtest_live.playwright() as p:
        browser = webtest_live.launch(p)
        try:
            run = lambda steps: webtest_live.run_case(browser, base_url=site.base_url, hosts=HOSTS,  # noqa: E731
                                                      steps=[{"action": "goto", "value": "/cart"}, *steps])
            save = {"role": "button", "name": "Save"}
            update = {"role": "button", "name": "Update"}
            assert run([{"action": "expect_disabled", "locator": save},
                        {"action": "click_blocked", "locator": save, "value": "Cart updated"},
                        {"action": "expect_readonly", "locator": {"label": "Code"}},
                        {"action": "expect_editable", "locator": {"label": "Quantity"}},
                        {"action": "expect_checked", "locator": {"label": "Agree"}}])["result"] == "ok"
            assert site.cart_posts == 0
            assert run([{"action": "expect_enabled", "locator": save, "timeout_ms": 1000}])["result"] == "fail"
            assert run([{"action": "expect_unchecked", "locator": {"label": "Agree"}, "timeout_ms": 1000}])["result"] == "fail"
            # A plain click on the natively disabled button fails on the app's state, and says so.
            clicked = run([{"action": "click", "locator": save, "timeout_ms": 1000}])
            assert clicked["result"] == "fail" and clicked.get("disabled") is True
            # [Update] is only marked disabled: pressing it anyway still submits.
            leaked = run([{"action": "click_blocked", "locator": update}])
            assert leaked["result"] == "fail" and "aria-disabled" in leaked["error"] and "POST /cart" in leaked["error"]
            assert site.cart_posts == 1
        finally:
            browser.close()
