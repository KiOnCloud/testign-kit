---
phase: 7
title: "Test run and settings screens"
status: completed
priority: P1
effort: "2.25d"
dependencies: [3, 4, 5, 6]
---

# Phase 7: Test run and settings screens

<!-- Updated: Validation Session 1 - webtest-plan retired here with the run form, with every consumer listed; legacy Figma re-import commands retired; old views deleted at the end; theme and tester name in Preferences -->

## Goal

The Test runs and Settings groups match the mockup (runs list with icon results, the New run dialog,
the run detail restyled, Agent & jobs, the five Settings screens), and the `webtest-plan` flow is
retired with the run form that used it.

## Context

- Existing views to restyle rather than rewrite: `runs.mjs` (195 lines), `run.mjs` (424),
  `run-form.mjs` (131), `jobs.mjs` (309), `job-actions.mjs`, `ask-form.mjs`, `login.mjs` (274;
  projects at 105-150, hosts form 159+), `templates.mjs`, `cache.mjs`, `settings.mjs`.
- `webtest-plan` consumers (each gets a disposition in step 7):
  - UI: `run-form.mjs:2, 121`, `job-actions.mjs:81, 206-207`, `runs.mjs:136`.
  - Python: `jobs.py:45, 629, 876, 890, 1222-1223, 1357, 1368`; `webtest.py:449, 616, 815`;
    `cli.py:757, 775, 883-885`; agent routes `POST /agent/jobs/:id/run` (`attach_run`,
    `jobs.py:1354-1362`) and `GET /agent/jobs/:id/review` (`jobs.py:1365-1368`) and the review-table
    ask gate (`jobs.py:1218-1226`).
  - Docs: `skills/webtest/SKILL.md:4, 42, 78, 166`, `skills/console/SKILL.md:81`,
    `references/console-bridge.md:101-131, 169`.
  - Tests: `tests/test_webtest.py` (13 `add_job` sites), `test_console_jobs.py:123`,
    `test_console_webtest_jobs.py:72, 265, 288`, `test_figma_table.py:156`,
    `fixtures/make_webtest_run.py:133`, `e2e/test_console_webtest_smoke.py:128, 139`,
    `ui/tests/runs.test.mjs:82-84, 147, 160`, `ui/tests/review-table.test.mjs:134`.
- Figma re-import helpers that only serve the run-owned import: `copy_import`, `new_run_from`,
  `find_source`, CLI `webtest-find` (`cli.py:597-601`), `webtest-new --from-run` (`cli.py:759`), and
  run-targeted `webtest-stage`, `webtest-import`, `webtest-triage`, `webtest-plan`
  (`cli.py:605-645`); their tests `tests/test_webtest.py:59-69, 549-651`.

## Tasks & Steps

1. Runs (`runs.mjs`): "needs you" alert summarising parked questions and sign-ins with one Handle
   link; table with run id, suite (with case count), source badge, environment, result icons (pass,
   fail, needs you, queued, each with a count and a tooltip), state badge, tester, when. Legacy runs
   show their Figma source and no suite link.
2. New run dialog (`views/new-run.mjs`, replacing `run-form.mjs`): ready suites only, project,
   environment URL, tester, result template, allowed hosts and needed scenarios shown before
   creating; calls `POST /api/webtest/runs`, then queues `webtest-run`.
3. Run detail (`run.mjs`): header actions (resume, finish, export), progress bar, rows table with
   status icons, the agent question panel (design capture beside current page, answer choices) in a
   sticky side panel, and a way to change the export columns that the run got from `first_guess`.
   Run behaviour stays as today.
4. Agent & jobs (`jobs.mjs`, route `agent`): agent status alert with capability icons (Claude in
   Chrome, Figma MCP, Backlog MCP), jobs table including `suite-generate` with a link to its suite;
   job detail at `agent/:id`.
5. Settings: split `login.mjs` into `projects.mjs` (projects and allowed or sign-in hosts) and
   `scenarios.mjs` (grouped by project, status icon approved, waiting, rejected, approve action);
   restyle `templates.mjs` and `cache.mjs` tables; `settings.mjs` becomes Preferences with the
   mockup's fields (output folder, report language, git branches and ticket pattern, Backlog space
   and decisions prefix, console port and idle time) plus two kept from today and not in the mockup:
   the light/dark theme control and the tester name.
6. i18n keys for every screen in en and ja; tests for result icon mapping, new run dialog
   validation and the projects/scenarios split.
7. Retire `webtest-plan`:
   - remove the kind from `KINDS`, the attach and review agent routes and the review-table ask gate;
     a queued or offered `webtest-plan` job found at startup fails with a `retired-kind` reason
     (active ones already fail with `server-stopped`, `jobs.py:725-737`);
   - remove the CLI commands `webtest-plan`, `webtest-stage`, `webtest-import`, `webtest-triage`,
     `webtest-find`, `webtest-new --from-run`, the run target of `webtest-table`, and `copy_import`,
     `new_run_from`, `find_source`, `apply_plan`, `triage` with their tests; keep `webtest-recover`,
     `webtest-run` and export, which legacy and suite runs both use;
   - remove the Plan job section from `skills/webtest/SKILL.md` and its rows in
     `skills/console/SKILL.md` and `references/console-bridge.md`;
   - update the tests listed in the context, moving fixtures to suites where they built runs through
     a plan job.
8. Delete `tickets.mjs`, `review.mjs`, `review-table.mjs`, `login.mjs`, `run-form.mjs` and their tests
   once `rg` shows no importer.

## Files to Create / Modify

- Create: `ui/views/projects.mjs`, `ui/views/scenarios.mjs`, `ui/views/new-run.mjs`
- Modify: `ui/views/runs.mjs`, `run.mjs`, `jobs.mjs`, `job-actions.mjs`, `templates.mjs`, `cache.mjs`,
  `settings.mjs`, `ui/i18n/en.json`, `ui/i18n/ja.json`, the UI tests above
- Modify: `scripts/testign/console/jobs.py`, `scripts/testign/webtest.py`, `scripts/testign/cli.py`,
  `skills/webtest/SKILL.md`, `skills/console/SKILL.md`, `references/console-bridge.md`, the Python
  tests and fixtures above
- Delete: `ui/views/tickets.mjs`, `review.mjs`, `review-table.mjs`, `login.mjs`, `run-form.mjs` and
  their tests

## Verification

- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`
- `python -m pytest`
- `rg -n "webtest-plan" scripts skills references commands tests` returns only the retired-kind
  reason and its test.
- Browser check against the mockup in en and ja; the version 1 fixture run opens and exports.
