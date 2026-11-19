---
phase: 4
title: "Review table rules without silent drops"
status: completed
priority: P2
effort: "0.5d"
dependencies: [3]
---

# Phase 4: Review table rules without silent drops

<!-- Updated: Red Team Session 1 - send normalized edits from the UI, refuse only explicit edits, triage rule, missing consumers, upgrade risk -->

## Goal

The review table never accepts a value that confirmation then throws away, and never refuses a
value the tester did not set and cannot clear.

## Context

- USUPP answer: `runner: agent` on r11, r14–r18 (`not-web`) and `mobile_method: emulation` on r19
  (`pc`) were accepted (`_review_answer`, `scripts/testign/console/jobs.py:297-354`) and dropped
  (`mobile_method()` at :345; `_initial_state` forces `runner: none`, `webtest.py:594-598`).
- Cause of the leak: the UI sends raw `edit` keys (`review-table.mjs:174-195`), while `finalLine`
  normalizes only for display (:127-129); `setEdit` drops edits equal to the agent's line
  (:117-125).
- The final line is `{**line, **clean}` (jobs.py:342); agent lines carry `mobile_method: device`
  on phone rows (`webtest_export.py:311`) and an edit cannot send `null` (jobs.py:324-329). So a
  rule on the final line would refuse a legitimate mobile→pc switch or a sure→not-web change.
- `triage()` has no class/runner rule (`webtest.py:573-591`).

## Files to Create / Modify

- Modify: `scripts/testign/console/ui/views/review-table.mjs` (answer from normalized lines)
- Modify: `scripts/testign/console/ui/views/job-actions.mjs` (`ERROR_KEYS`)
- Modify: `scripts/testign/console/jobs.py` (`_review_answer`)
- Modify: `scripts/testign/webtest.py` (`apply_plan`, `triage`)
- Modify: `scripts/testign/console/ui/i18n/{en,vi,ja}.json`
- Modify: `references/console-bridge.md` (errors table, :178)
- Modify: tests `tests/test_console_webtest_jobs.py` (`test_review_answer_rules`),
  `tests/test_webtest.py`, `scripts/testign/console/ui/tests/review-table.test.mjs`

## Tasks & Steps

- [x] UI: build the answer from `finalLine` values: when the final class is `not-web`, send
      `runner: "none"`; when the final viewport is `pc`, send no `mobile_method`. The runner select
      of a not-web row is disabled showing "none"; changing the class back re-enables it.
- [x] Server `_review_answer` and `apply_plan`: normalize the agent-line values (as today) and
      refuse only an explicit edit: `runner` other than `none` with a final `not-web` class
      (`not-web-runner`), `mobile_method` with a final `pc` viewport (`pc-method`).
- [x] `triage()`: refuse `runner` other than `none` on a `not-web` draft, so the agent's line never
      carries it.
- [x] Map both codes in `job-actions.mjs` with vi/en/ja messages; add them to the bridge errors
      table.
- [x] Tests at all layers: sure→not-web and back; mobile→pc with an inherited `device`; explicit
      bad edits refused; a hand-built answer refused by `apply_plan`; a UI unit test that the r19
      sequence sends no method.

## Verification

- `python -m pytest tests/test_console_webtest_jobs.py tests/test_webtest.py -q`
- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`
- e2e `tests/e2e/test_console_webtest_smoke.py`

## Risks

- A 0.5.0 console server still running after the plugin is updated serves the old UI, which can
  send values the 0.5.1 `apply_plan` refuses (open jobs fail on restart, so only a running server
  matters). Phase 6's update steps restart the console before new jobs.
