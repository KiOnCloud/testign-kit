"""A suite's spec: what may go in, the review gate, and which run rows replay it. No browser."""

import pytest

from make_webtest_run import ready_suite

from testign import webtest_spec, webtest_suite

LABEL = [{"action": "goto", "value": "/mypage"},
         {"action": "expect_text", "locator": {"role": "banner"}, "value": "予約履歴"}]
FOOTER = [{"action": "goto", "value": "/"},
          {"action": "expect_visible", "locator": {"role": "link", "name": "help"}}]


@pytest.fixture
def suite_folder(tmp_path):
    return ready_suite(tmp_path / "webtest")


def suite_of(folder):
    return webtest_suite.load(folder)


def test_only_eligible_cases_with_a_check_and_no_host_or_placeholder(suite_folder):
    suite = suite_of(suite_folder)
    with pytest.raises(webtest_spec.SpecError) as err:
        webtest_spec.save(suite_folder, suite, {
            "c3": {"steps": LABEL},                                            # a choice case
            "c1": {"steps": [{"action": "goto", "value": "/mypage"}]},         # no expect_
            "c2": {"steps": [{"action": "goto", "value": "https://dev.example.test/"},
                             {"action": "fill", "locator": {"label": "User"}, "value": "{{user}}"},
                             {"action": "expect_visible", "locator": {"text": "x"}}]},
            "c9": {"steps": LABEL},
        })
    text = " ".join(err.value.problems)
    assert "c3: only a sure case" in text
    assert "c1: the steps need at least one expect_" in text
    assert "goto takes a path" in text and "no placeholder" in text
    assert "c9: no such case" in text
    assert webtest_spec.load(suite_folder) is None


def test_steps_are_checked_one_by_one():
    problems = []
    webtest_spec.check_step({"action": "click", "locator": {"role": "button", "css": "x"}}, "s", problems)
    webtest_spec.check_step({"action": "goto"}, "s", problems)
    webtest_spec.check_step({"action": "expect_url", "value": "**/done", "timeout_ms": 0}, "s", problems)
    webtest_spec.check_step({"action": "hover", "locator": {"text": "x"}}, "s", problems)
    assert len(problems) == 4


def test_review_needs_a_passing_check_on_the_current_content(suite_folder):
    suite = suite_of(suite_folder)
    spec = webtest_spec.save(suite_folder, suite, {"c1": {"steps": LABEL}, "c2": {"steps": FOOTER}})
    digest = webtest_spec.content_hash(spec)
    with pytest.raises(webtest_spec.SpecError, match="replay the spec first"):
        webtest_spec.review(suite_folder, digest, "fp")
    webtest_spec.store_check(suite_folder, {"c1": {"result": "ok"}, "c2": {"result": "spec_error", "error": "x"}},
                             "check", digest)
    with pytest.raises(webtest_spec.SpecError, match="c2"):
        webtest_spec.review(suite_folder, digest, "fp")
    webtest_spec.store_check(suite_folder, {"c1": {"result": "ok"}, "c2": {"result": "fail"}}, "check", digest)
    with pytest.raises(webtest_spec.SpecError, match="changed since you opened it"):
        webtest_spec.review(suite_folder, "0" * 64, "fp")
    reviewed = webtest_spec.review(suite_folder, digest, "fp")
    assert webtest_spec.is_reviewed(reviewed)
    # Any edit clears the review and needs a new check.
    after = webtest_spec.save(suite_folder, suite, {"c2": {"steps": FOOTER + [{"action": "expect_url", "value": "**/"}]}})
    assert not webtest_spec.is_reviewed(after)
    assert webtest_spec.check_state(after)["status"] == "missing"


def test_first_run_check_keeps_results_of_unchanged_cases(suite_folder):
    suite = suite_of(suite_folder)
    webtest_spec.save(suite_folder, suite, {"c1": {"steps": LABEL}}, check={"c1": {"result": "ok"}})
    spec = webtest_spec.save(suite_folder, suite, {"c2": {"steps": FOOTER}}, check={"c2": {"result": "ok"}})
    assert set(spec["check"]["cases"]) == {"c1", "c2"}
    assert webtest_spec.check_state(spec)["status"] == "passed"


def test_a_row_replays_only_its_unchanged_reviewed_case(suite_folder):
    suite = suite_of(suite_folder)
    spec = webtest_spec.save(suite_folder, suite, {"c1": {"steps": LABEL}}, check={"c1": {"result": "ok"}})
    row = {**suite["cases"][0], "row": "r01"}
    assert webtest_spec.replayable(spec, row, "c1") is None  # not reviewed yet
    spec = webtest_spec.review(suite_folder, webtest_spec.content_hash(spec), "fp")
    assert webtest_spec.replayable(spec, row, "c1")["steps"] == LABEL
    assert webtest_spec.replayable(spec, {**row, "expected": "something else"}, "c1") is None
    assert webtest_spec.replayable(spec, row, "c2") is None
    assert webtest_spec.row_case_id("r03") == "c3" and webtest_spec.row_case_id("r12") == "c12"


def test_view_lists_eligible_cases_with_warnings(suite_folder):
    suite = suite_of(suite_folder)
    steps = [{"action": "goto", "value": "/mypage"},
             {"action": "click", "locator": {"role": "button", "name": "2026/11/28 残 4"}},
             {"action": "expect_text", "locator": {"role": "banner"}, "value": "予約確認"}]
    webtest_spec.save(suite_folder, suite, {"c1": {"steps": steps}})
    view = webtest_spec.view(suite_folder, suite)
    assert view["status"] == "draft" and view["eligible"] == 2 and view["recorded"] == 1
    assert [c["case"] for c in view["cases"]] == ["c1", "c2"]
    kinds = {w["kind"] for w in view["cases"][0]["warnings"]}
    assert {"live_data_locator", "unsourced", "no_value_check"} <= kinds
    removed = webtest_spec.remove_cases(suite_folder, ["c1"])
    assert removed["cases"] == {}
