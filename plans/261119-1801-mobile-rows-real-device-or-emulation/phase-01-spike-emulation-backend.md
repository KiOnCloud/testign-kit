---
phase: 1
title: "Spike: emulation backend"
status: done
priority: P1
effort: "1d"
dependencies: []
---

# Phase 1: Spike: emulation backend

## Goal

Find one way for the agent to load a run host's page in a phone-width viewport (under 600 px),
read it, click in it and save a screenshot of it, and record the result as a spike report.

## Context

- Spike item G (`plans/261119-0324-web-ui-test-runs-from-figma/reports/spike-macos-2026-11-19.md`):
  `mcp__claude-in-chrome__resize_window` to 390, 520 and 1440 left `outerWidth` at 606 or 1680.
- The site under test (`dev.u-supp-u.devkarte.jp`) switches to its phone layout under 600 px; the
  About page (`/about-us`) and the booking form (`/reservation`, signed in as `client`) have
  separate Mobile frames in Figma (rows r32, r33, r37–r40 of the USUPP table).

## Candidates (try in this order)

| # | Backend | Sign-in reuse | Debug connection | Notes |
|---|---|---|---|---|
| A | Chrome DevTools MCP (`chrome-devtools-mcp`) attached to the tester's Chrome; `emulate` / `resize_page` per page | yes (same profile) | yes | Needs Chrome with remote debugging (or `--autoConnect` on recent Chrome); emulation is per page and can be reset |
| B | Claude in Chrome on a separate normal (not maximised) window, `resize_window` again | yes | no | Re-test item G with a fresh window opened by `tabs_create_mcp` |
| C | Built-in browser pane of the Claude desktop app, `resize_window` preset `mobile` | no (own cookie jar; tester signs in there) | no | Desktop app only; emulates UA and touch too |

For each: page `innerWidth` and the phone menu layout visible; `read_page` and `find` work;
a click works; a screenshot saves to disk; emulation can be undone; the tester's other tabs are
unaffected; what the tester must set up once.

## Steps

1. Try A, B, C on `/about-us` (public), then on `/reservation` signed in (tester signs in by hand).
2. Write `reports/spike-emulation-2026-11-19.md`: result per candidate, setup steps, the chosen
   backend, and whether it needs a debug connection.
3. Ask the tester to accept the chosen backend when it needs a debug connection or the desktop
   app; record the answer in the report.

## Validation

The report names one backend that meets every check, or says none did; the plan's phase 4 scope
is adjusted to match.

## Rollback

Nothing to roll back; no product code changes.

## As built

Report: [reports/spike-emulation-2026-11-19.md](reports/spike-emulation-2026-11-19.md). Backend D
(same-origin 390×844 iframe in the tester's Chrome) was chosen by the tester on 2026-11-19; no
debug connection, so the earlier plan's "no debug connection" constraint holds.
