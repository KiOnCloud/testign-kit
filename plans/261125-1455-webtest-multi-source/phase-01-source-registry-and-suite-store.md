---
phase: 1
title: "Source registry and suite store"
status: completed
priority: P1
effort: "1.75d"
dependencies: []
---

# Phase 1: Source registry and suite store

<!-- Updated: Validation Session 1 - Excel row reader is new code; suite case keeps a source block and mobile_method; confirm enforces the run rules; caps and link guards named; digest naming; frontmatter line range -->

## Goal

A suite (a case list with its source, kept apart from runs) can be created, read, edited, confirmed
and deleted from the CLI, and each source kind is one entry in a registry.

## Context

- Today the case list lives only inside a run (`run.json` `cases[]`, `webtest.py:447-490`), validated
  strictly by `check_case` / `CASE_KEYS` (`webtest.py:80, 306`). A run's source is a Figma table only
  (`figma_source`, `console/jobs.py:550`). `workbook` in `SOURCE_KINDS` (`webtest.py:89`) is never
  created and is replaced here by `excel`.
- Source identity is `_source_ref` = (kind, file, node) (`webtest.py:518`); sort order is
  `_source_key` from `source.no` (`webtest.py:392`). `_check_source` accepts only text or number
  values, at most 500 characters (`webtest.py:214-227`).
- Run rules a suite must satisfy before a run can be made from it: `check_triage`, `agent_may_run`
  and the `mobile_method` default (`webtest.py:294-303`), agent plus `device` is refused
  (`webtest.py:322-323`), a delegated `choice` row is refused (`webtest.py:818-820`).

## Design

**Registry** (`scripts/testign/webtest_sources.py`). One dict entry per kind; every caller (suite
store, export, console API, wizard list) reads the registry instead of naming kinds.

| Field | Meaning |
|---|---|
| `mode` | `extract` (one source row gives one case: figma, excel), `generate` (agent writes N cases per source row: backlog), `none` (manual) |
| `check(payload)` | validate the wizard input and return the stored `source` dict |
| `ref(source)` | identity tuple, replacing `_source_ref` for this kind |
| `rows(source)` | source rows a case can trace to (figma: table rows; backlog: B*/R* rows from the report; excel: sheet rows; manual: none) |
| `trace_label` | export column header key: `Figma node`, `Trace`, `Row`, none |
| `needs_agent` | true for figma and backlog |

Kinds: `figma` (file, node, url), `backlog` (ticket, report revision path, `develop_head`,
`merge_base` read from the report frontmatter, `FRONTMATTER_KEYS` at `report.py:14-25`), `excel`
(file name, template, sheet), `manual` (nothing). A Backlog source refuses a ticket with no survey
report.

**Suite store** (`scripts/testign/webtest_suite.py`). Folder
`<output_dir>/webtest/suites/<suite-id>/` with `suite.json` and `source/` (captures, the copied
Excel file). Suite id `S\d{8}-\d{4}-<slug>`; `list_runs` already ignores it because it matches only
`RUN_ID_RE` (`webtest.py:41, 178-190`).

`suite.json`: `version`, `id`, `name`, `project`, `case_lang`, `created_at`, `updated_at`,
`source`, `state` (`generating` | `review` | `ready`), `generate_job`, `confirmed_at`,
`suite_digest`, `cases[]`. A suite case keeps only design fields: `case` id (`c\d{1,4}`), `trace`
(list of source row ids, the shape `trace.py` uses: `["B4"]`, `["R1"]`; empty for manual),
`source` (per-case source block: `{no, target_node}` for Figma as `figma_table.py:429` writes it,
`{no}` for Excel, absent for Backlog and manual), `content`, `preconditions`, `steps`, `expected`,
`screen` (path only, for example `/office/edit`; the host comes from the run), `viewport`,
`mobile_method`, `kind`, `class`, `reason`, `runner`, `scenario`, `creator` (`agent` | `tester`),
`capture`. Run-time fields (state, attempt, result, evidence, questions) stay in runs only.

Rules:
- Any edit while `ready` moves the suite back to `review`.
- Each case save runs the per-case run rules (`check_triage`, `agent_may_run`, the mobile rules, the
  delegated-choice rule) and returns field errors, so `confirm` only re-checks the whole list and
  requires every case to have content, a class and, for `class=sure` with `runner=agent`, a screen.
- `suite_digest` reuses the `cases_digest` idea (`webtest.py:422`) over suite cases; the name differs
  from a run's `digest` on purpose.
- Coverage for `generate` sources lists every row of `rows(source)` that no case traces to, plus
  cases whose trace names no row. It reuses the covered-set logic of `trace.py:10-26` but not
  `trace.gaps` itself, which filters on `needs_case` (true for every R* row but only some B* rows,
  `report.py:174`); the plan's acceptance needs every B* and R* row.

Caps and file safety: Excel upload at most `UPLOAD_CAP` 10 MB (`templates_api.py:24`) and
`FULL_LOAD_CAP` 5 MB unzipped (`templates.py:416`); captures at most `IMAGE_CAP` 20 MB
(`webtest.py:76`); case text at most `TEXT_CAP` 4000 (`webtest.py:75`); source values 500. The Excel
file name is reduced to a safe slug before it is written, and every file read from a suite folder
goes through the `_is_link` guard (`webtest.py:508-515`), which matters on Windows too.

## Files to Create / Modify

- Create: `scripts/testign/webtest_sources.py`, `scripts/testign/webtest_suite.py`
- Create: `tests/test_webtest_sources.py`, `tests/test_webtest_suite.py`
- Modify: `scripts/testign/webtest.py` (`SOURCE_KINDS`, `_check_source`, `_source_ref`, `_source_key`
  read the registry; `workbook` removed; the per-case rule helpers become importable)
- Modify: `scripts/testign/cli.py` (commands below)

## Tasks & Steps

1. Write the registry with the four kinds; move Figma checks out of `console/jobs.py:550` into the
   `figma` entry and import them back from there.
2. Write the Backlog entry on top of `report.behavior_rows` / `regression_rows`
   (`report.py:153-177`); store the report path and revision, never a copy of the report.
3. Write the Excel entry: a new case-row reader built on `templates.detect_layout` (`templates.py:178`)
   and `templates.resolve` (`templates.py:315`); no such reader exists today (`xlsx.read_trace`,
   `xlsx.py:243`, reads trace only). No new dependency.
4. Write the suite store: `new_suite`, `load`, `save` (atomic write like runs), `list_suites`,
   `add_case`, `update_case`, `delete_cases`, `bulk_update` (class, runner, scenario), `confirm`,
   `duplicate`, `rename`, `remove`, `coverage`, `stage_generated` (agent writes cases while
   `generating`, then `finish_generate` moves to `review`).
5. Add CLI commands, JSON in and out like the `webtest-*` commands (`cli.py:553-651`):
   `suite-new`, `suite-show`, `suite-list`, `suite-case-add|update|delete`, `suite-stage`,
   `suite-generated`. (`suite-confirm` was dropped after review on 2026-11-25: only the tester
   confirms a suite, in the console; the case commands apply the agent's rules.)
6. Tests: each kind's `check` / `ref` / `rows`; a Backlog source from a fixture report with B1–B3 and
   R1; the review/ready state rule; per-case rule errors (agent plus device, delegated choice);
   confirm refusals; coverage gaps; an oversized and a linked Excel file are refused; a fake fifth
   kind registered in a test appears in the registry list with no other change (extension check).

## Extension trace

A fifth source (for example a Google Sheet) adds one registry entry, one wizard step-2 form
(phase 6), its i18n keys and a skill section if it needs the agent. The suite schema, run snapshot,
export and API stay unchanged; step 6's fake-kind test proves the registry side.

## Verification

- `python -m pytest tests/test_webtest_sources.py tests/test_webtest_suite.py`
- `python -m pytest` (existing webtest tests still pass with `workbook` gone)
