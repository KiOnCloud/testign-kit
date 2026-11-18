---
phase: 5
title: "Jobs and Close review screens"
status: pending
priority: P1
effort: "2.5d"
dependencies: [3, 4]
---

# Phase 5: Jobs and Close review screens

## Goal

The Jobs screen, the agent question form, the Close review (row approval, then diff
confirmation), and the job triggers on the Tickets, Report and Trace screens, in vi, en and ja.

## Context

- Mockup screens Jobs and Close review: https://claude.ai/artifact/FbwXMaek4XshNT2nPdpkTB
- API and ask schema: phase 4.

## Requirements

- [ ] The console polls `/api/state` every 1.5 seconds while the tab is visible and stops while hidden; views refresh from the change counter, not on every poll.
- [ ] Every job sent from the console carries the current `ui_lang`; survey also carries `report_lang` (default: config `lang`).
- [ ] With no agent attached, the sidebar and Jobs screen say "No agent attached: run /testign:console in Claude Code"; queued jobs wait; nothing shows a spinner without a reason.
- [ ] A job silent for 15 minutes shows as silent with "Mark failed"; a failed job shows its reason and "Queue again".
- [ ] `needs-input` jobs: sidebar badge with the count, document title prefixed with the count, and the question shown in the Jobs detail panel.
- [ ] `questions` asks render as radio or checkbox groups with an optional "Other" text; `review-rows` opens the Close review screen; `confirm-diff` shows the diff with Write and Back; the primary button stays disabled until every row has a choice.
- [ ] Agent text, quotes and diff lines are shown with `textContent`; quotes keep `lang="ja"` when the ask marks them so.
- [ ] The accent budget of Kestrel holds: one primary button per view.

## Triggers

| Where | Button | Job |
|---|---|---|
| Tickets | Survey ticket (`C`) | `survey` via a form: ticket, repo path (last value remembered in `localStorage`), refs, fetch, feature, report language |
| Tickets banner | Survey again | `survey` with the ticket's last parameters from its report frontmatter |
| Report | Close QA | `close` for the shown revision |
| Report | Write test cases | `testcase`, `mode: write` |
| Trace | Write §7 to r{n+1} | `testcase`, `mode: trace`, the shown workbook |
| Trace gap card | Add a case for R3 | `testcase`, `mode: write`, `workbook`, `focus: ["R3"]` |
| Jobs | Cancel (queued), Mark failed (silent), Queue again (failed) | the matching console route |

## Files to Create / Modify

- Create: `scripts/testign/console/ui/store.mjs` (state polling, change counter, subscriptions)
- Create: `scripts/testign/console/ui/views/jobs.mjs`, `review.mjs`, `ask-form.mjs`, `survey-form.mjs`
- Modify: `scripts/testign/console/ui/views/shell.mjs` (agent status, badge, title count), `tickets.mjs`, `report.mjs`, `trace.mjs` (triggers)
- Modify: `scripts/testign/console/ui/router.mjs` (`#/jobs`, `#/jobs/:id`, `#/jobs/:id/review`)
- Modify: `scripts/testign/console/ui/i18n/vi.json`, `en.json`, `ja.json`
- Create: `scripts/testign/console/ui/tests/store.test.mjs`, `ask-form.test.mjs`
- Modify: `tests/e2e/test_console_smoke.py` (job flows)

## Tasks & Steps

1. Store with visibility-aware polling and the change counter.
2. Jobs screen: open and history tabs, rows with Kestrel status glyphs (queued hollow, running and needs-input partial, done filled, failed hollow with a cross in the danger colour), detail panel with progress steps.
3. Ask form for `questions`; Close review screen for `review-rows` and `confirm-diff`.
4. Survey form with field checks mirroring phase 4 (the server stays authoritative).
5. Triggers on Tickets, Report and Trace.
6. Strings in all three dictionaries; tests.

## Verification

- `node --test scripts/testign/console/ui/tests/` — store applies a state only when the counter changes; ask form builds the answer shape of each ask type and refuses an incomplete `review-rows` answer.
- `TESTIGN_E2E=1 python -m pytest tests/e2e -v` — with a fake agent: queue a close job in the ja UI, answer `review-rows` and `confirm-diff`, see the job done; queue a survey with no agent and see the "No agent attached" state; mark a silent job failed after the window is shortened by a test setting.

## Success Criteria

Acceptance criteria 7 and 8 pass against a fake agent; every trigger of the mockup that belongs to stage 2 queues the right kind with the right parameters.

## Risk Assessment

- Polling every 1.5 seconds wakes the laptop. Signal: none expected; polling stops while the tab is hidden. Response: lengthen the interval if testers report it.

## Security Considerations

- The repo path is stored in `localStorage` of the console's own origin; it is a local path the tester typed, not a secret.
