---
phase: 5
title: "Export, docs and verification"
status: done
priority: P2
effort: "1d"
dependencies: [2, 3, 4]
---

# Phase 5: Export, docs and verification

## Goal

The workbook and report say how each mobile row was checked, the docs describe the method, and
the whole suite passes.

## Files

- `scripts/testign/webtest_export.py`: `CASE_FIELDS` (`:21`), header labels in en/ja/vi
  (`:39-49`), the report rows (`:279`): a method column ("Real device" / "Emulation (agent)" /
  "Emulation (tester)"); the report's mobile section lists rows per method.
- `references/console-bridge.md`: review-table answer shape gains `mobile_method`; error table
  gains `mobile-device-agent`.
- `README.md` web test section and `references/rules.md` §11 if they mention phone-width rows.
- Tests: `tests/test_webtest_export.py`.

## Steps

1. Export column and report section, with tests.
2. Docs.
3. Full verification: `python -m pytest`, UI unit tests, e2e console tests.
4. Compare the result with the plan's acceptance criteria and record any gap.

## Validation

Every acceptance criterion checked off with the command or observation that shows it.

## Rollback

Revert the commit; older exports are unaffected.

## As built

- Export: a "Phone check" column (en / ja スマホ確認方法 / vi Cách kiểm tra mobile) with
  "Real device", "Emulation (agent, 390 px frame)", "Tester (real phone or device mode)" or
  "Emulation (planned)"; proposed in the column plan when the run has phone rows; the report's
  "All rows" table has the same column. No separate per-method section.
- Docs: `references/console-bridge.md`, `skills/webtest/{SKILL,triage-rules,worker-brief}.md`,
  `agents/webtest-worker.md`, `README.md`.
- Verification 2026-11-19 after the review fixes: `pytest` 524 passed, 5 skipped; UI `node --test tests/*.test.mjs`
  91/91; e2e with `TESTIGN_E2E=1` 16 passed, 1 failed:
  `test_run_screen_answers_a_parked_row` calls `webtest.next_row(folder, jid, AGENT)`, a
  signature older than 0.4.0's `next_row(folder, server, job, session)`; it already fails at HEAD
  and this change does not touch it.
