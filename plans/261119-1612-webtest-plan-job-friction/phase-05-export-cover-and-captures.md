---
phase: 5
title: "Export cover and captures"
status: completed
priority: P2
effort: "0.5d"
dependencies: []
---

# Phase 5: Export cover and captures

<!-- Updated: Validation Session 1 - captures are relative links; no Pillow -->
<!-- Updated: Red Team Session 1 - link on the No cell at export (works for confirmed runs, no column plan change), path from the row id, tester stored on the run, formula guard -->

## Goal

The exported workbook leaves no template placeholder behind and lets a reader open each row's
capture.

## Context

- `export` (`scripts/testign/webtest_export.py:432-452`) writes case cells only
  (`xlsx.fill_columns`, values only, `xlsx.py:90-118`, `:146-170`); nothing touches the cover. The
  sample template carries `<project>`, `<TICKET-ID>`, `<tester>`, `<YYYY-MM-DD>` on `表紙` and
  `<TICKET-ID>` in `テストケース!B2` (`xlsx.py:254`, `:270`). `run["ticket"]` exists
  (`webtest.py:465`).
- `run.json` has no tester (`webtest.py:455-480`); it is a `webtest-run` job parameter
  (`jobs.py:604-610`), pruned with old jobs; `webtest-export` may run without a job
  (`cli.py:700-706`).
- The column plan is frozen at confirmation (`webtest.py:661-663`) and checked against fixed
  field lists in Python and the UI (`webtest_export.py:21-24`, `review-table.mjs:13`); a new
  column would miss every confirmed run.
- `case["capture"]` is not validated by `check_case` (`webtest.py:303-324`); the report escapes
  only `|` and newlines (`webtest_export.py:374-375`).

## Files to Create / Modify

- Modify: `scripts/testign/webtest_export.py`
- Modify: `scripts/testign/xlsx.py` (hyperlink on a written cell; placeholder fill as strings)
- Modify: `scripts/testign/webtest.py` (`tester` on the run, set in `recover()`; `capture`
  validated in `check_case`)
- Modify: `tests/test_webtest_export.py`, `tests/test_webtest.py`

## Tasks & Steps

- [x] Run tester: `recover()` stores `view.params.tester` as `run["tester"]` (last value wins); a
      run without it loads as before.
- [x] Placeholders: replace cells whose whole value is a sample placeholder: `<project>` → run
      project, `<TICKET-ID>` → run ticket or empty, `<tester>` → `run["tester"]` or empty,
      `<YYYY-MM-DD>` → export date. Written as strings (`data_type "s"`) with leading `= + - @`
      neutralized; a customer template's own text is never touched.
- [x] Captures: at export, set a relative hyperlink on the row's `No` cell to the file found by
      `_staged_capture(folder, row)` (never from `case["capture"]` text), value unchanged; no new
      column, so confirmed 0.5.0 runs get links too. The Markdown report adds a capture link built
      the same way. `check_case` validates `capture` against `^source/r\d{1,4}\.(png|jpg)$`.
- [x] Tests: placeholders with and without ticket/tester; a template without placeholders is
      unchanged outside case cells; a placeholder value starting with `=` stays text; the link
      targets the staged file and resolves relative to the workbook; a UNC or traversal
      `capture` in `run.json` fails `check_case`; runs without captures export as before.

## Verification

- `python -m pytest tests/test_webtest_export.py tests/test_webtest.py -q`
- Manual: re-export a copy of `W20261119-2215-usuppu-6647-118139` and open it in Excel on
  Windows: no `<...>` on `表紙`, clicking `No` opens the PNG.

## Risks

- Relative links break when the workbook is moved without its run folder (accepted; embedding was
  declined to keep `openpyxl` the only dependency). The report says so.
- Export of a 0.5.0 run now adds links on `No` cells: values and columns stay the same.
