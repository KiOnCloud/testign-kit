---
phase: 5
title: "Jobs and Close review screens"
status: pending
priority: P1
effort: "3d"
dependencies: [3, 4]
---

# Phase 5: Jobs and Close review screens

## Goal

The Jobs screen, the agent question form, the Close review (row approval, then diff
confirmation, or pages to paste in manual mode), and the job triggers on the Tickets, Report
and Trace screens, in vi, en and ja.

## Context

- Mockup screens Jobs and Close review: https://claude.ai/artifact/FbwXMaek4XshNT2nPdpkTB
- API, states and ask schema: phase 4.

## Requirements

- [ ] The console polls `/api/state` every 1.5 seconds while the tab is visible and stops while hidden; views refresh from the change counter, not on every poll.
- [ ] Every job sent from the console carries the current `ui_lang`; survey also carries `report_lang` (default: config `lang`); close carries `tester` from Settings, and Close QA asks for the name first when it is empty.
- [ ] Job triggers act on the latest revision only; while an older revision is shown, they are disabled with a note. <!-- Red team 2026-11-18: revision pinning -->
- [ ] With no agent attached, the sidebar and Jobs screen say "No agent attached: run /testign:console in Claude Code"; queued jobs wait; nothing shows a spinner without a reason.
- [ ] A job silent for 15 minutes shows as silent with "Mark failed" and "Release agent"; a failed job shows its reason (`revision-moved` explains that the report changed and offers "Queue again on the latest revision") and "Queue again".
- [ ] `needs-input` jobs: sidebar badge with the count, document title prefixed with the count, and the question shown in the Jobs detail panel.
- [ ] `questions` asks render as radio or checkbox groups with an optional "Other" text (multi-line where the ask allows it).
- [ ] `review-rows` opens the Close review screen: one row per `row` id with Q (when present), class, decision, quote, source, feature, page and anchors; actions Write, Skip, Edit; Edit opens fields for decision, anchors and page. The primary button stays disabled until every row has a choice. <!-- Red team 2026-11-18: close gates -->
- [ ] `confirm-diff` shows each page's unified diff from the preview as given (a "new page" badge when `exists` is false), and the `added`, `skipped`, `superseded` and `index_repaired` lists; Write confirms, Back declines.
- [ ] `paste-pages` shows each page's `new_content` with a copy button and the page name, and states that testign wrote nothing; "Done" answers it.
- [ ] Agent text, quotes and diff lines are shown with `textContent` through the bidi-visible helper; quotes keep `lang="ja"` when the ask marks them so.
- [ ] New browser sessions reported by `/api/state` are shown as a notice in every open tab.
- [ ] The accent budget of Kestrel holds: one primary button per view.

## Triggers

| Where | Button | Job |
|---|---|---|
| Tickets | Survey ticket (`C`) | `survey` via a form: ticket, repo path (last value remembered in `localStorage`), refs, fetch, feature, report language |
| Tickets banner | Survey again | opens the same form prefilled from the report frontmatter; `repo` is taken from `localStorage` when the frontmatter value is not an existing path; `fetch` is never prefilled; the tester confirms before it is queued <!-- Red team 2026-11-18: survey parameters from frontmatter --> |
| Report | Close QA | `close` on the latest revision |
| Report | Write test cases | `testcase`, `mode: write`, template picker when more than one is registered |
| Trace | Write §7 to r{n+1} | `testcase`, `mode: trace`, the shown workbook and the selected template |
| Trace gap card | Add a case for R3 | `testcase`, `mode: write`, `workbook`, the selected template, `focus: ["R3"]` |
| Jobs | Cancel (queued), Mark failed (silent), Release agent (silent), Queue again (failed) | the matching console route |

## Files to Create / Modify

- Create: `scripts/testign/console/ui/store.mjs` (state polling, change counter, subscriptions)
- Create: `scripts/testign/console/ui/views/jobs.mjs`, `review.mjs`, `ask-form.mjs`, `survey-form.mjs`, `paste-pages.mjs`
- Modify: `scripts/testign/console/ui/views/shell.mjs` (agent status, badge, title count, session notices), `tickets.mjs`, `report.mjs`, `trace.mjs`, `settings.mjs` (triggers, tester name prompt)
- Modify: `scripts/testign/console/ui/router.mjs` (`#/jobs`, `#/jobs/:id`, `#/jobs/:id/review`)
- Modify: `scripts/testign/console/ui/i18n/vi.json`, `en.json`, `ja.json`
- Create: `scripts/testign/console/ui/tests/store.test.mjs`, `ask-form.test.mjs`
- Modify: `tests/e2e/test_console_smoke.py` (job flows)

## Tasks & Steps

1. Store with visibility-aware polling and the change counter.
2. Jobs screen: open and history tabs, rows with Kestrel status glyphs (queued and offered hollow, running and needs-input partial, done filled, failed hollow with a cross in the danger colour), detail panel with progress steps.
3. Ask form for `questions`; Close review screen for `review-rows`, `confirm-diff` and `paste-pages`.
4. Survey form with field checks mirroring phase 4 (the server stays authoritative), including the prefilled "Survey again" path.
5. Triggers on Tickets, Report and Trace; tester name prompt.
6. Strings in all three dictionaries; tests.

## Verification

- `node --test scripts/testign/console/ui/tests/` — store applies a state only when the counter changes; ask form builds the answer shape of each ask type, including edit answers, and refuses an incomplete `review-rows` answer.
- `TESTIGN_E2E=1 python -m pytest tests/e2e -v` — with a fake agent: queue a close job in the ja UI with an empty tester name (prompted), edit one row, confirm a diff with a new page and a superseded entry, see the job done; run the manual mode and see `paste-pages`; queue a survey with no agent and see the "No agent attached" state; release a silent agent; see triggers disabled on an older revision.

## Success Criteria

Acceptance criteria 7 and 8 pass against a fake agent; every trigger of the mockup that belongs to stage 2 queues the right kind with the right parameters.

## Risk Assessment

- Polling every 1.5 seconds wakes the laptop. Signal: none expected; polling stops while the tab is hidden. Response: lengthen the interval if testers report it.

## Security Considerations

- The repo path and tester name are stored in `localStorage` of the console's own origin; they are values the tester typed, not secrets.
