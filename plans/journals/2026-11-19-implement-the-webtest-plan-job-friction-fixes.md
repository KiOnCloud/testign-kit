---
title: Implement the webtest plan job friction fixes
date: 2026-11-19
summary: Six USUPP-round fixes implemented and tested; e2e browser suite and live rerun remain
---

# Implement the webtest plan job friction fixes

## What happened

Implemented `plans/261119-1612-webtest-plan-job-friction`: `webtest-new --from-run`, the one-call
Figma table reader (`figma_table.py`, `webtest-table --urls/--captures`), claim-time `no-older-tab`
with `can_answer`/`can_act` notices in the console, review-table rules that refuse only explicit
edits confirmation would drop, cover placeholders and `No`-cell capture links in the export, and
version 0.5.1 with README update steps. 601 Python tests and 95 UI tests pass.

Checked on copies of the real USUPP runs: the parser gives the same 45 rows as run `-2215` (the
only first-run difference was a creator cell ending in a zero-width space, now trimmed);
`--from-run` copies 45 rows and captures; the re-export leaves no placeholder and all 45 links
resolve.

## Decision

- A code review found that the documented auto re-queue could loop forever when the console has no
  tab at all (after a restart), and each failed job pushes real job history out of the 50 kept.
  The user's auto re-queue decision stays, bounded: re-queue once, and `console queue` refuses
  `queued_after` with `no-tab` when there is no tab.
- Capture URLs are limited to plain path characters because the skill passes them to `curl` in a
  quoted shell argument.
- In this environment the Bash tool turned `\t`, `\n` and `\\` inside heredocs into real
  characters, which broke a Python string literal and a test parameter. Edits containing
  backslashes go through Write/Edit or a script file written with Write.

## Next steps

- Run the browser e2e suite (`TESTIGN_E2E=1`, needs Playwright and Chromium) on the tester's machine
  or in CI.
- Re-run the USUPP flow live with the console: one-call table read, a deliberately too-new tab,
  review edits mobile→pc and sure→not-web, export.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
