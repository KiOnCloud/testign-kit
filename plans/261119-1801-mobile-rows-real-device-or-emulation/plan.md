---
title: "Mobile rows: real device or agent emulation"
description: "Phone-width rows of a web test run get a check method, real device (default, run by the tester) or browser emulation (run by the agent), chosen per row in the review table."
status: done
priority: P1
effort: 5d
branch: claude/check-nearest-plan-47bc71
tags: [feature, frontend, backend, experimental]
blockedBy: []
blocks: []
created: 2026-11-19
---

# Mobile rows: real device or agent emulation

## Overview

Today every `viewport: mobile` row of a web test run goes to the tester, and the console, the
server and the CLI refuse `runner: agent` on such a row (`rt_err_mobile_agent`,
`console/jobs.py:261`, `:338`, `webtest.py:611`). The reason is the macOS spike, item G: Claude in
Chrome's `resize_window` reports success but the page keeps its width, so the agent never sees the
site's phone layout (breakpoint 600 px).

The tester asked, during the USUPP round on 2026-11-19, for a choice per mobile row: check it on a
**real phone** or by **browser emulation**, with the real phone preferred. Emulation is run by the
agent automatically; the real phone is always the tester's.

## Contract

- **Outcome:** each mobile row carries a method. `device` (default) is run by the tester on a phone
  and entered on the run screen. `emulation` is run by the agent in an emulated phone viewport and
  gets a verdict with evidence like any agent row, with the emulated device named in `actual`.
- **Constraints:** the tester picks the method per row (or in bulk) in the review table; the
  default for every mobile row is `device`; the agent still never signs in, never leaves the run's
  hosts and never reads input values; the console server still runs no browser; when the session
  has no working emulation backend, `emulation` rows are not lost: they go to the tester with the
  DevTools how-to; UI strings in vi, en and ja; existing runs without the field keep working
  (missing method on a mobile row reads as `device`).
- **Non-goals:** driving a real phone (Appium, adb, remote device farms); a per-project default
  (the tester chose per-row only); pixel diff; changing pc rows; a release or version bump.
- **Decision to confirm before phase 2:** the earlier web test plan
  (`plans/261119-0324-web-ui-test-runs-from-figma/plan.md`) lists "runs use the tester's own Chrome
  profile with no debug connection" as a constraint and "phone-width rows run by the agent" as a
  non-goal. The tester has now asked for the second. The spike may show that the only working
  backend needs a debug connection; that choice is the tester's.
- **Acceptance criteria:**
  1. In the review table every mobile row shows a method select defaulting to "Real device";
     pc rows show none. Bulk edit sets the method on selected mobile rows.
  2. A mobile row with `device` and `runner: agent` is refused by the UI, the server and
     `webtest-plan`; a mobile row with `emulation` and `runner: agent` is accepted.
  3. With a working emulation backend, an `emulation` row runs in a viewport under 600 px wide
     (the worker reports the page's width) and returns pass or fail with an evidence image taken
     in that viewport; the emulation is undone before the next row.
  4. Without a working backend, the run job's capability check moves `emulation` rows to
     `awaiting-tester` with reason `no-emulation`, and the run screen shows the DevTools how-to.
  5. The run screen shows the method on each mobile row and, for `device` rows, how to open the
     screen on a phone.
  6. The exported workbook and Markdown report name the method of every mobile row's result.
  7. Runs written by 0.4.0 load, run and export unchanged.
  8. Python tests, UI tests and the e2e console tests pass.

## Phases

| # | Phase | Effort | Depends on |
|---|---|---|---|
| 1 | [Spike: emulation backend](phase-01-spike-emulation-backend.md) | 1d | none |
| 2 | [Run model, CLI and server rules](phase-02-run-model-cli-and-server.md) | 1d | 1 |
| 3 | [Console: review table and run screen](phase-03-console-review-and-run-screens.md) | 1d | 2 |
| 4 | [Worker, skill and capability check](phase-04-worker-skill-and-capability-check.md) | 1d | 1, 2 |
| 5 | [Export, docs and verification](phase-05-export-docs-and-verification.md) | 1d | 2, 3, 4 |

Phases 3 and 4 touch different files and may run in parallel after phase 2.

## Risks

- No backend passes the spike: phases 2, 3, 5 still ship (method field, tester-run emulation with
  the DevTools how-to); phase 4 ships only the capability check and the fallback.
- A backend that needs a debug connection changes the security posture of the tester's Chrome:
  documented, opt-in, never turned on by the agent.
- Emulation differs from a real phone (fonts, touch, address bar): the method is recorded in the
  export so a reader knows which evidence came from emulation.

## Status (2026-11-19)

Built and code-reviewed; review fixes applied (below); not committed. Per-phase "As built" notes record where the build
differs from the phases above (iframe backend, park instead of a capability check, error codes
kept).

| # | Criterion | Status |
|---|---|---|
| 1 | Method select on mobile rows, default real device, bulk edit | Done; UI unit tests |
| 2 | device+agent refused in UI, server, `webtest-plan`; emulation+agent accepted | Done; unit tests at all three layers |
| 3 | Emulation row runs under 600 px with evidence | Frame scripts dry-run on `/about-us` (390 px, phone layout, zoom saved); no worker run end to end, signed-in row not tried |
| 4 | Fallback to the tester with the how-to | Changed: a framing failure parks the row (`stuck`), run screen shows the how-to; no `no-emulation` reason |
| 5 | Run screen method and how-to | Done; not seen in a browser |
| 6 | Workbook and report name the method | Done; export tests |
| 7 | 0.4.0 runs load unchanged | Done; unit test for a run without the field |
| 8 | Python, UI and e2e tests pass | 524 passed / 91 passed / e2e 16 passed, 1 already failing at HEAD (stale `next_row` call) |

## Review fixes (2026-11-19)

- Only the tester picks emulation: `webtest-triage` refuses `mobile_method: emulation`, and the
  server refuses a review-table ask line with `emulation` or with `runner: agent` on a mobile row.
  An unedited table therefore confirms every mobile row as real device, tester-run.
- Page scripts only where needed: `webtest-worker` lost the JavaScript tool; a separate
  `webtest-phone-worker` has it and is spawned only for `mobile` + `emulation` rows. The two-script
  limit is still enforced by its instructions, not by a tool; the README says so.
- `run.json` with an agent row on a real device no longer loads, so a hand edit cannot send one to
  a worker. `webtest-plan` takes the method from the confirmed line and answer only, as the server.
- Export: the agent is named only on its own pass/fail; a tester result reads "Tester (real phone
  or device mode)"; an unchecked emulation row reads "Emulation (planned)"; rows of runs written
  before the field show nothing. The column plan proposes a "Phone check" column when the run has
  phone rows.
- Console: the method label is "Emulation" (no runner), and the run screen's emulation how-to no
  longer says the agent tried.
- Brief: the second frame script also reports whether the frame still exists; a lost frame is
  `stuck` ("opens outside the phone frame"), a frame off the origin is `off-site`, and a phone
  row's `url` is the frame's address. Re-run in Chrome on `/about-us`: both cases behave as written.
