---
phase: 6
title: "Test case design screens"
status: completed
priority: P1
effort: "2d"
dependencies: [3, 5]
---

# Phase 6: Test case design screens

<!-- Updated: Validation Session 1 - complete old-to-new hash table with job detail and the default route; legacy review links map through job.run; shared helpers extracted here and old views deleted only at the end of phase 7 -->

## Goal

The new navigation exists, and the Test case design group works end to end: Test suites list, new
suite wizard, suite detail with case editing, and Ticket survey with icon freshness.

## Context

- Routes: `router.mjs:5` `SCREENS` = tickets, jobs, runs, login, templates, cache, settings, plus
  report, trace, `jobs/:id`, `jobs/:id/review`, `jobs/:id/review-table` (`router.mjs:47-48`), run;
  views mapped in `main.mjs:26`; nav built in `shell.mjs:76-93` as "work" and "setup";
  `router.test.mjs:8` expects `#/` to mean tickets.
- Hash builders outside the router: `api.mjs:72` turns `#c=<code>` into `#/tickets` (the launch link
  `http://127.0.0.1:<port>/#c=<code>` comes from `lifecycle.py:239`); palette entries
  `main.mjs:112-116`; links in `survey-form.mjs:122`, `job-actions.mjs:131`, `jobs.mjs:80, 260, 270`,
  `runs.mjs:177`, `review.mjs:69-209`, `review-table.mjs:229, 250, 256, 461, 480`,
  `trace.mjs:27-28, 55, 95`, `report.mjs:120-173`, `run.mjs:67, 144`, `run-form.mjs:71, 80, 87, 126`,
  `login.mjs:145, 180`. No `#/` strings exist in Python, skills, commands or references.
- Shared helpers living in views that will be deleted: `hostOf` (`run-form.mjs`, imported by
  `review-table.mjs:10`, `login.mjs:9`, `runs.mjs:7`), `signInCard` (`login.mjs`, imported by
  `run.mjs:11`, `jobs.mjs:10`), `mobileMethod` (`review-table.mjs`, imported by `run.mjs:13`, used at
  `run.mjs:276`).
- The mockup's screens `suites`, `wizard`, `suite`, `survey` are the reference for layout, labels
  (en and ja dictionaries in the mockup script) and behaviour.

## Tasks & Steps

1. Extract shared helpers before any view is replaced: `hostOf` to `ui/hosts.mjs`, `signInCard` to
   `ui/views/sign-in-card.mjs`, `mobileMethod` to `ui/views/mobile-method.mjs`; update their importers
   and `login.test.mjs:4`, `runs.test.mjs:5`, `review-table.test.mjs:7`.
2. Router with this redirect table (old links keep working):

   | Old hash | New hash |
   |---|---|
   | `#/` and `#c=<code>` after sign-in (`api.mjs:72`) | `#/suites` |
   | `#/tickets` | `#/survey` |
   | `#/tickets/:ticket`, `#/tickets/:ticket/trace` | `#/survey/:ticket`, `#/survey/:ticket/trace` |
   | `#/jobs`, `#/jobs/:id` | `#/agent`, `#/agent/:id` (job detail kept) |
   | `#/jobs/:id/review`, `#/jobs/:id/review-table` | `#/runs/<job.run>` from `GET /api/jobs/:id`; when the job has no run, `#/agent/:id` read only |
   | `#/login` | `#/scenarios` |

   New screens: `suites`, `suites/new`, `suites/:id`, `survey`, `runs`, `runs/:id`, `agent`,
   `agent/:id`, `projects`, `scenarios`, `templates`, `cache`, `settings`. Update every hash builder
   listed above and the palette entries to the new hashes.
3. Shell: three groups (Test case design, Test runs, Settings), each collapsible with its open state
   kept under a new `testign.navGroups` key (read and written in try/catch like `prefs.mjs`), counts
   on rows, agent status in the top bar.
4. Test suites list (`views/suites.mjs`): search, filter chips (all, needs you, generating, ready),
   table with name, source badge and ref, cases, state, runs, project, updated, row menu (rename,
   duplicate, delete).
5. Wizard (`views/suite-new.mjs`): steps Source → Input → Details → Review. Step 1 lists
   `/api/webtest/sources`; step 2 forms come from a `SOURCE_FORMS` map keyed by kind (Figma link;
   Backlog ticket select showing only tickets with a report, its freshness icon and a link to Ticket
   survey; Excel file plus template; Manual note). The last button reads "Queue generation job" when
   the kind needs the agent, otherwise "Create suite".
6. Suite detail (`views/suite.mjs`): header with source, project, state, Export Excel, New run
   (disabled until ready); a warning banner with Confirm suite while in review; tabs Cases, Source
   & coverage, Runs. Cases tab: searchable table with checkboxes, a sticky side panel form for the
   selected case (content, preconditions, steps, expected, screen path, trace, class, runner,
   scenario, viewport, mobile method; delete, duplicate, save, with per-field rule errors from the
   API) and bulk actions for the selection. While `generating`, show progress from the job and keep
   the table read only.
7. Ticket survey (`views/survey.mjs`, replacing `views/tickets.mjs`): table of ticket, report
   revision, freshness icon (`same` → check "Report hashes match develop"; `moved_no_impact` → check
   "develop moved, no surveyed file changed"; `stale` → warning "develop changed since this report:
   survey again"; `unknown` → clock for `busy`, otherwise a neutral icon with the reason as its tip),
   open questions icon, suites made from it, one action per row (create suite, answer questions,
   survey again). The new-survey form (`survey-form.mjs`) and the report and trace views stay, moved
   under `survey/`.
8. i18n: add every new key to `en.json` and `ja.json` from the mockup dictionaries.
9. Tests: the redirect table (including `#/` and `#c=`), nav grouping, wizard step flow per kind,
   case form save, rule errors and bulk edit against a fake API, survey icon mapping for all four
   states, tooltip text present as `aria-label`.

`tickets.mjs`, `review.mjs`, `review-table.mjs` and their tests are deleted at the end of phase 7,
once no view imports them.

## Files to Create / Modify

- Create: `ui/hosts.mjs`, `ui/views/sign-in-card.mjs`, `ui/views/mobile-method.mjs`,
  `ui/views/suites.mjs`, `ui/views/suite-new.mjs`, `ui/views/suite.mjs`, `ui/views/survey.mjs`,
  `ui/tests/suites.test.mjs`, `ui/tests/suite.test.mjs`
- Modify: `ui/router.mjs`, `ui/main.mjs`, `ui/api.mjs`, `ui/views/shell.mjs`, every view in the hash
  builder list, `ui/i18n/en.json`, `ui/i18n/ja.json`, `ui/tests/router.test.mjs`,
  `ui/tests/login.test.mjs`, `ui/tests/runs.test.mjs`, `ui/tests/review-table.test.mjs`

## Verification

- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`
- `python -m pytest tests/test_console_ui_assets.py` (no inline style, every `t('key')` exists)
- `rg -n "#/tickets|#/jobs|#/login" scripts/testign/console/ui --glob '!tests/**'` returns only the
  redirect table.
- Browser check against the mockup in en and ja at 1440 px and 1024 px widths.
