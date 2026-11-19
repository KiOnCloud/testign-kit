---
phase: 4
title: "Worker, skill and capability check"
status: done
priority: P1
effort: "1d"
dependencies: [1, 2]
---

# Phase 4: Worker, skill and capability check

## Goal

The worker runs an `emulation` row in the backend chosen by the spike, and a run job without a
working backend hands those rows to the tester instead of failing them.

## Files

- `agents/webtest-worker.md`: add the backend's tools (only the emulation and page tools the
  spike needs), keep every existing "never" rule.
- `skills/webtest/worker-brief.md`: replace "A `mobile` row is `stuck`" with the emulation steps:
  turn on emulation for the worker's own page before opening the screen, check `innerWidth` is
  under 600, do the row, save evidence, undo emulation, close the page; name the emulated device
  and width in `actual`; a row with `emulation` absent stays `stuck` on mobile.
- `skills/webtest/SKILL.md`: a capability check "Emulation" in "Checks before a job" (`mode: run`,
  only when the run has agent `emulation` rows); on failure the orchestrator moves those rows to
  the tester with `webtest-park` reason `no-emulation` (or a new `webtest-requeue --to-tester`
  if the park question does not fit), and the job continues.
- `skills/webtest/triage-rules.md` (viewport section): mobile rows get `mobile_method: device` and
  `runner: tester`; the tester switches to emulation in the review table.
- `scripts/testign/webtest.py`: the fallback command if one is needed (state change only; the
  server-side answer flow is unchanged).
- Tests: `tests/test_webtest.py` for the fallback state change.

## Steps

1. Wire the backend into the worker per the spike report.
2. Update the brief and triage rules.
3. Capability check and fallback in the skill; CLI support if needed.
4. Dry run on the USUPP site: r37 (About, public) and r33 (booking form, `client`) with
   `emulation`; one row with the backend switched off to see the fallback.

## Validation

Acceptance criteria 3 and 4 of the plan, observed on the dry run; unit tests green.

## Risk and rollback

A worker that leaves emulation on would make the next pc row wrong: the brief undoes it in every
exit path and the next row's worker checks `innerWidth` on pc rows too. Revert to roll back.

## As built

- No capability check and no new CLI command. The worker frames the screen itself with the two
  scripts quoted verbatim in `skills/webtest/worker-brief.md` ("Phone frame"); a separate
  `webtest-phone-worker` agent holds `javascript_tool` for those rows; `webtest-worker` has none.
- Fallback per row: a frame that does not load or is 600 px wide or more, or a step that opens a
  new tab, returns `stuck` with a phone frame reason (a frame that leaves the run's origin is
  `fail` / `off-site`); the skill parks the row and its
  question tells the tester that running it themselves means a real phone or Chrome's device mode.
  The run screen shows the matching how-to. This replaces the planned `no-emulation` park reason.
- Dry run 2026-11-19 on `https://dev.u-supp-u.devkarte.jp/about-us` with the brief's scripts
  unchanged: frame `{ok: true, width: 390, phone: true}`, text read returned the frame URL and
  951 characters, zoom on x 0–390 showed the phone layout. Not done: the signed-in `/reservation`
  row (r33), which needs the tester signed in as `client`, and a worker subagent run end to end.
