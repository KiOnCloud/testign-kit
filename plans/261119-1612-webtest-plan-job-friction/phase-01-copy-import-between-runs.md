---
phase: 1
title: "Copy an import between runs"
status: completed
priority: P1
effort: "0.75d"
dependencies: []
---

# Phase 1: Copy an import between runs

<!-- Updated: Red Team Session 1 - validate before attaching, idempotent copy, carry the triage draft, report missing captures, fix facts -->

## Goal

A plan job that reuses or resumes an earlier import gets it, and an unconfirmed earlier triage
draft, with one command, and a mistake in that command never strands the job.

## Context

- A job has one run (`new_run`, `scripts/testign/webtest.py:441-483`, saves and calls
  `server.attach_run` at :481-482; a second run is refused at :444-445 and `jobs.py:1302-1303`).
  A completed import takes no more rows (`stage`, :512).
- Skill step 2 (`skills/webtest/SKILL.md:86-89`) has the agent stage each earlier row by hand.
- `find_source` (:486-497) is covered for complete and partial runs
  (`tests/test_webtest.py:59`, `:69`) but reports no capture count; the USUPP source has a
  complete run without captures (`-2213`) next to a complete one with them (`-2215`).
- The triage draft lives in `run.json` cases, written by `webtest-triage` after import
  (`triage()`, :573-591); `import_staged` resets those fields (:560-563).
- An unknown run id raises `no such run: <id>` (`find_run`, :190-196); `unknown-run` is only a
  console job-parameter code (`jobs.py:602`).

## Files to Create / Modify

- Modify: `scripts/testign/webtest.py` (`check_import_source`, `copy_import`; `find_source` gains
  `captures`)
- Modify: `scripts/testign/cli.py` (`webtest-new --from-run <run>`, handler `_cmd_webtest_new` at
  :587; parser at :736)
- Modify: `skills/webtest/SKILL.md` steps 1 and 2
- Modify: `tests/test_webtest.py`

## Tasks & Steps

- [x] `check_import_source(earlier_folder, job_source)`: load the earlier run; refuse when its
      `source` (file, node) differs from the job's params, when the folder is a symlink or
      junction, or when any staged row's JSON fails `check_staged`, names another row than its
      file, or its capture is unreadable or over 20 MB (check the size with `stat()` before
      reading). Runs before anything is created.
- [x] `_cmd_webtest_new --from-run`: `find_run` the earlier run, run `check_import_source`, and
      only then `new_run` and `copy_import`.
- [x] `copy_import(folder, earlier)`: stage every earlier row with its `_staged_capture` through
      `stage()` (identical rows are skipped by `stage`, so a repeat after a crash is safe; drop
      the "already has staged rows" refusal). Copy `source/page-index.json` when present. When
      the earlier import is complete and its plan is unconfirmed, also `import_staged` and
      re-apply the earlier cases' triage fields through `triage()`, so steps 4–7 need not be
      redone. Return `{run, staged, captures, missing_captures: [rows], page_index, triaged}`.
- [x] `find_source` adds `captures` (rows with a capture) to each run it reports.
- [x] Skill: step 1 prefers a complete run whose `captures` equals `staged`; step 2 becomes
      `webtest-new --job <j> --session <s> --from-run <earlier>`; a non-empty `missing_captures`
      is reported in a progress line and those rows get their captures before `webtest-import`
      (or the run is read again).
- [x] Tests: complete run → identical cases and triage after the copy; partial run → staged rows
      copied and the import resumes; source mismatch, symlinked folder, unreadable capture and
      mismatched row name refused **before** a run exists (the job can still `webtest-new`);
      repeat after an interrupted copy succeeds; capture-less earlier run reports
      `missing_captures`; `find_source` reports `captures` and skips an unreadable run.

## Verification

- `python -m pytest tests/test_webtest.py -q`
- Manual: `webtest-new --from-run W20261119-2215-usuppu-6647-118139` on a fresh plan job gives 45
  rows, 45 captures and the triage draft; `--from-run W20261119-2213-…` reports 45 missing
  captures.

## Risks

- Re-applying triage from an earlier run trusts that run's draft: it is still shown to the tester
  in the review table before anything is confirmed.
