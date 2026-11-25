---
phase: 2
title: "Runs from suites"
status: completed
priority: P1
effort: "1.25d"
dependencies: [1]
---

# Phase 2: Runs from suites

<!-- Updated: Validation Session 1 - columns from first_guess, captures copied through the import checks, confirmed/digest shape, trace stored as text, export adds a trace field instead of renaming target_node, VERSION accepts 1 and 2, stored version-1 fixture, ui_lang edit dropped -->

## Goal

A run is created from a confirmed suite as a frozen copy, runs with the existing state machine, and
exports with the suite name and each case's trace; runs written before this plan still load.

## Context

- A run today is born in a `webtest-plan` job (`new_run`, `webtest.py:447`), imports and triages its
  own rows, then becomes `confirmed` through the review table (`apply_plan`, `webtest.py:809`), which
  writes `confirmed {at, by, job}`, `digest` and `columns` (`webtest.py:864-868`). Initial row states
  come from `_initial_state` (`webtest.py:788`).
- Export refuses a run with no `columns` (`webtest_export.py:464-466`); `first_guess` proposes them
  (`webtest_export.py:115`) and `check_columns` requires content and verdict and rejects unknown
  fields (`webtest_export.py:160-197`).
- `check_run` compares `version` by strict equality on every load (`webtest.py:334`); `check_case`
  needs `capture` to be `source/<row>.png` inside the run (`webtest.py:329-331`).
- The run job checks only `confirmed` (`console/jobs.py:611`); `plan_job` is read only by
  `new_run_from` (`webtest.py:623`).

## Design

- `new_run_from_suite(root, suite, *, name, base_url, project, hosts, template, tester)`:
  - refuses a suite that is not `ready`;
  - copies each suite case into a run case: `row` = `r` + case number; `source` = the suite case's
    source block plus `kind` and `trace` written as text (`"B4,R1"`), because `_check_source` takes
    text or numbers only; `screen.url` = `base_url` joined with the suite path;
  - copies each capture to `source/r<n>.png|jpg` through the same link, type and size checks that
    `check_import_source` uses (`webtest.py:523-528`);
  - sets `columns` from `first_guess` with `default_labels`, passed through `check_columns`; the
    tester can change them later from the run page;
  - sets `confirmed = {at, by: tester, job: null}` and `digest = cases_digest(cases)`;
  - puts rows in their `_initial_state`.
- `run.json` gains `suite: {id, name, suite_digest}`. `VERSION = 2`; `check_run` accepts versions 1
  and 2 explicitly. A version 1 run has no `suite` and keeps its Figma `source`; every reader treats a
  missing `suite` as a legacy run.
- Export (`webtest_export.py`): add a new `trace` field (header from the registry's `trace_label`)
  and add it to suite runs' columns explicitly, since it is not in `PROPOSED_NEW`
  (`webtest_export.py:31`). Keep `target_node` unchanged, because legacy runs store it in their
  `columns`. The cover sheet and the Markdown report name the suite.
- The UI language default is handled in phase 5; `new_run` is not used for suite runs, so its
  `ui_lang` default is left alone here.

## Files to Create / Modify

- Modify: `scripts/testign/webtest.py` (`VERSION`, `check_run`, `check_case`, `new_run_from_suite`)
- Modify: `scripts/testign/webtest_export.py` (`trace` field, suite on cover and report)
- Modify: `scripts/testign/cli.py` (`webtest-new --suite <id>`)
- Create: `tests/fixtures/webtest-run-v1/run.json` (a stored version 1 run with captures and
  columns, copied from a run made by today's code before the change)
- Modify: `tests/test_webtest*.py`, `tests/fixtures/make_webtest_run.py`

## Tasks & Steps

1. Store the version 1 fixture first, generated with today's `make_webtest_run.py`.
2. Bump `VERSION` and make the checks accept versions 1 and 2.
3. Write `new_run_from_suite` and its CLI flag; move the host checks of `_check_webtest_plan`
   (`console/jobs.py:573`) into a shared helper both callers use.
4. Add the `trace` export field and the suite on the cover; legacy golden output stays identical.
5. Tests: a run from a suite has the suite's cases in `_initial_state`, copied captures and valid
   columns, and exports without a review step; editing the suite after does not change the run; the
   version 1 fixture loads, shows and exports as before; a Backlog run's export has a `Trace` column
   with `B4`, `R1`.

## Verification

- `python -m pytest tests -k webtest`
