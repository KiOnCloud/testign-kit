---
phase: 3
title: "Console: review table and run screen"
status: done
priority: P1
effort: "1d"
dependencies: [2]
---

# Phase 3: Console: review table and run screen

## Goal

The tester sees and sets the method on mobile rows in the review table, and sees it with a how-to
on the run screen.

## Files

- `scripts/testign/console/ui/views/review-table.mjs`: `FIELDS`, `EDIT_KEYS` (`:13`, `:17`); a
  method select in the row grid next to viewport (`:405-416`), shown only when the final viewport
  is `mobile`; bulk entries `mobile_method:device` / `mobile_method:emulation` (`:363-367`);
  validator (`:171`) refuses agent only for `device`; switching a row to `mobile` sets `device`.
- `scripts/testign/console/ui/views/run.mjs` (`:281`): show the method; for `device` rows a short
  how-to (open the screen URL on a phone, sign in by hand if the scenario needs it); for
  `emulation` rows that fell back to the tester, the DevTools how-to (F12, then Cmd/Ctrl+Shift+M,
  width under 600 px).
- `scripts/testign/console/ui/i18n/{vi,en,ja}.json`: labels, bulk entries, new error
  `rt_err_mobile_device_agent` (replaces the text of `rt_err_mobile_agent`), how-to strings.
- Tests: `scripts/testign/console/ui/tests/review-table.test.mjs`, run screen tests, e2e review
  table spec under `tests/e2e/`.

## Steps

1. Pure functions and validator, with unit tests.
2. Grid select and bulk menu.
3. Run screen display and how-to.
4. i18n in three languages; asset test (`tests/test_console_ui_assets.py`) stays green.

## Validation

UI unit tests, `tests/test_console_ui_assets.py`, the e2e console suite.

## Risk and rollback

An open review-table ask from 0.4.0 has no method on its lines; the UI treats it as `device`.
Revert the commit to roll back.

## As built

- The method select sits in the viewport cell, shown only when the final viewport is `mobile`;
  the bulk menu has `mobile_method:device` / `mobile_method:emulation` and skips pc rows.
- The run screen shows the method and, on `awaiting-tester` mobile rows, `run_howto_device` (open
  the screen on a phone) or `run_howto_emulation` (Chrome device mode, width under 600 px).
- Error key kept as `rt_err_mobile_agent` with new text (see phase 2).
