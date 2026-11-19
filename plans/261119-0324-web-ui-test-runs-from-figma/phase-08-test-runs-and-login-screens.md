---
phase: 8
title: "Test runs and login screens"
status: pending
priority: P1
effort: "4.5d"
dependencies: [4, 5, 6]
---

# Phase 8: Test runs and login screens

## Goal

Two console screens, Test runs and Login scenarios, plus the review table, so the tester starts a
run, confirms the plan, follows each row, answers parked questions, enters results for rows they
run themselves and signs in, in vi, en and ja.

## Context

- The UI is plain ES modules with no build step, one module per view under `console/ui/views/`, the view map in `ui/main.mjs:22`, routes in `router.mjs`, strings in `i18n/{vi,en,ja}.json`. The key parity check is `tests/test_console_ui_assets.py:32-41`.
- Blocking `questions` asks render inline on the Jobs screen (`ui/views/jobs.mjs:220`); the review types listed in `ui/views/jobs.mjs:16` and `ui/views/review.mjs:13` open the review screen. A new ask type shows nothing until it is added to one of those paths.
- "Queue again" builds its request by kind in `ui/views/job-actions.mjs:162-175`; reason labels are looked up by key at `ui/views/jobs.mjs:211`.
- The Templates screen holds the registry's roles in `ui/views/templates.mjs:11-12`, `305-355`.
- CSP: no inline `style`, no inline script, no `innerHTML` with data (console plan, constraints).
- The console plan's mockup was approved before its UI phase. The same gate applies here.

<!-- Updated: Red Team Session 1 - render path for the review table; requeue and reason labels; purpose on the Templates screen; approval instead of a step editor; run-scoped answers; test Chrome and runner controls -->

## Screens

| Screen | Route | Shows | Actions |
|---|---|---|---|
| Test runs | `#/runs` | Runs with name, source, counts by state, last activity | "New run" form (Figma URL, base URL, name, project, template, ticket) → queues `webtest-plan` |
| Run | `#/runs/<run>` | Header with project, hosts and counts; row list with state, class, runner, scenario, screen; row detail with capture beside evidence, expected, actual | "Run" → queues `webtest-run`; answer a parked row; enter a result with an image for a row awaiting the tester (with or without an open job); "Finish with open rows"; "Export" when no job is open; open the workbook and report paths |
| Review table | `#/jobs/<job>/review-table` | Run hosts (read-only); column plan with three sample rows as a grid; verdict labels; one line per case with editable screen, class, runner, scenario, viewport, preconditions; bulk edit for selected rows | Add, remove and reorder columns; confirm or reject |
| Login scenarios | `#/login` | Projects with hosts and sign-in hosts; scenarios with label, steps, approval state, `filled`; the test Chrome's state | Create a project and edit its hosts; approve or reject a draft (with a note); credentials form; remove a scenario; "Start test Chrome"; "Sign in" with runner progress, "Continue" on a manual step and "Stop"; the manual checklist |

- The nav gains two items; `sectionOf` maps `runs/<run>` to Test runs and the review table to Jobs.
- A waiting `review-table` ask shows an "Open review table" button on the Jobs screen and the Run screen.
- A job queued from the chat is labelled so until the tester opens it.
- The credentials form posts once and clears its fields; a filled scenario shows field names and "filled", never values, and offers "Replace".
- A parked row shows its question in the row detail with the three fixed choices; `delegate` requires the preconditions field.
- Steps are shown read-only. There is no step editor (user, 2026-11-19).
- While a run job is open, the row list refreshes from `/api/state` changes, as the Jobs screen does. A notice appears when the job's last progress line is older than two minutes: the agent may be waiting for a browser permission in the terminal.
- The Templates screen shows each template's purpose and takes it on registration.

## Files to Create / Modify

- Create: `scripts/testign/console/ui/views/runs.mjs`, `run.mjs`, `run-form.mjs`, `review-table.mjs`, `login.mjs`
- Modify: `scripts/testign/console/ui/main.mjs` (view map), `router.mjs`, `views/shell.mjs`, `api.mjs`, `store.mjs`, `app.css`
- Modify: `scripts/testign/console/ui/views/jobs.mjs` (the review-table button, the two kinds, the `queued from the chat` label, the stale-progress notice)
- Modify: `scripts/testign/console/ui/views/job-actions.mjs` ("Queue again" for the two kinds)
- Modify: `scripts/testign/console/ui/views/templates.mjs` (purpose)
- Modify: `scripts/testign/console/ui/i18n/vi.json`, `en.json`, `ja.json` (screens, kinds, the `not-confirmed` reason, row states, purposes)
- Create: `scripts/testign/console/ui/tests/review-table.test.mjs`, `runs.test.mjs`, `login.test.mjs`
- Create: `tests/e2e/test_console_webtest_smoke.py`
- Create: `plans/261119-0324-web-ui-test-runs-from-figma/mockup/` (the approved artboards)

## Tasks & Steps

1. Draw the four screens as artboards in the console's design file and get them approved before any view code.
2. Add routes, the view map, nav items and API calls; write the Test runs list and the new-run form.
3. Write the review table: column plan grid with add, remove, reorder; verdict labels; case lines with single and bulk edit; the answer object of phase 4.
4. Write the Run screen: row list, row detail, parked answers, tester results with image upload, finish, export.
5. Write the Login screen: projects and hosts, scenario approval, credentials form, test Chrome control, runner progress and the manual checklist.
6. Update the Jobs screen, "Queue again" and the Templates screen.
7. Add every string in vi, en and ja.
8. Write the unit tests and the e2e smoke.

## Todo

- [ ] Mockup approved
- [ ] Routes, view map, nav, API calls
- [ ] Test runs list and new-run form
- [ ] Review table with its own route and the Jobs screen button
- [ ] Run screen with parked answers, tester results and export
- [ ] Login screen: hosts, approval, credentials, test Chrome, sign-in
- [ ] Jobs screen, "Queue again", Templates purpose
- [ ] i18n in three languages
- [ ] Unit tests and e2e smoke

## Verification

- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`
- `python -m pytest tests/test_console_ui_assets.py -v` (key parity across vi, en and ja)
- `TESTIGN_E2E=1 python -m pytest tests/e2e/test_console_webtest_smoke.py -v` (macOS e2e job, as today)
- Tests cover: the review table refuses to confirm while a delegated `choice` row has no preconditions; removing a column removes it from the answer and from the sample grid; the credentials form holds no value after submit and the page's DOM has none; a parked row's answer reaches the run; a tester result with an image is stored with no job open; "Queue again" on a failed `webtest-run` job queues the same run; the `not-confirmed` reason has a label in three languages; a run with 45 rows renders and scrolls without layout shift.
- e2e: with a fake agent (as `tests/e2e/test_console_jobs_smoke.py` does) a plan job shows the "Open review table" button and the table, a run job shows rows changing state, a parked row is answered, and finish ends the run.

## Risks

- The review table is the densest screen in the console. Keep one line per case with the editable cells inline and the long text in the row detail; the mockup approval is where this is settled.
- Evidence images are large. The row detail loads an image only when the row is opened.
