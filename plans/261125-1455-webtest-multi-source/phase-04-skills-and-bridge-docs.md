---
phase: 4
title: "Skills and bridge docs"
status: completed
priority: P1
effort: "0.5d"
dependencies: [3]
---

# Phase 4: Skills and bridge docs

<!-- Updated: Validation Session 1 - the Plan job section stays until phase 7 retires webtest-plan; webtest-table gains a --suite target -->

## Goal

The agent knows how to process a `suite-generate` job for Figma and for a Backlog survey report, and
the run job starts from a run made out of a suite.

## Context

- `skills/webtest/SKILL.md`: checks before a job (line 61), Plan job (78), Run job (171), Export job
  (240). `skills/console/SKILL.md:78-82` maps job kinds to skills. `references/console-bridge.md`
  documents web test jobs (124-148) and the review table (96).
- The Figma import writes rows with `webtest-table` (`cli.py:614-628`), which today targets a run
  folder only.

## Tasks & Steps

1. Give `webtest-table` a `--suite <id>` target that writes suite cases (with their
   `source {no, target_node}` block and captures) instead of run rows; the run target stays for the
   legacy flow until phase 7.
2. Add a **Generate job** section that branches on source kind:
   - Figma: today's import steps (`webtest-table --suite`, captures, one design-context call when it
     fits), then triage fields (`class`, `runner`, `scenario`, `screen` path, `mobile_method`) through
     `suite-stage`, then `suite-generated`.
   - Backlog: read the survey report revision named in the job; write at least one case per B* row
     and per R* row with `trace` set to the row id; mark rows that only the app, a batch or the
     database shows as `class=not-web`, `runner=none`; guess `screen` paths from the scout brief;
     never invent behaviour that the report does not state; finish with `suite-generated`.
3. Keep the Run job and Export job sections; note that a run made from a suite is already confirmed
   and has its columns, so the run job does not wait for a review table. Mark the Plan job section as
   the legacy flow; phase 7 removes it with the kind.
4. Update the job table in `skills/console/SKILL.md` and the web test part of
   `references/console-bridge.md` (job parameters, agent routes, the suite's Cases tab as the place
   where cases are reviewed).
5. Update `commands/webtest.md`: `/testign:webtest <figma url>` creates a Figma suite and opens it;
   the description names Backlog suites too.

## Files to Create / Modify

- Modify: `scripts/testign/cli.py` (`webtest-table --suite`), `tests/test_figma_table.py`
- Modify: `skills/webtest/SKILL.md`, `skills/console/SKILL.md`, `references/console-bridge.md`,
  `commands/webtest.md`, `commands/console.md`

## Verification

- `python -m pytest tests/test_figma_table.py`
- `claude plugin validate --strict .`
- Read-through: every command a skill names exists in `cli.py` after phases 1–3
  (`rg -o "testign [a-z-]+" skills | sort -u` against `python -m testign.cli --help`).
