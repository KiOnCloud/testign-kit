# Port from qingyi-test-kit, wave 2: record once, replay with Playwright, Login Recipe

Status: done · Requested by Asher (2026-11-26) · Follows wave 1 (PR #8)

## Outcome

The first run of a suite is walked by the agent through a Playwright engine, one step at a time, and
only steps that passed go into the suite's **spec**. After the tester reviews the spec, later runs
of the suite replay it headless without a model. Signed-in cases sign in with a **Login Recipe**: the
scenario's sign-in steps with placeholders, filled from a profile file the tester types, kept
owner-only on the tester's machine.

## Decisions this rests on

- Asher, 2026-11-26: port the Login Recipe as qingyi does it. The password is plaintext in an
  owner-only (0600) profile file, protected by a `secret_guard` hook. This deliberately reverses
  condition 8 of the 2026-11-19 decision ("store no account value"). Only dedicated staging test
  accounts. The tester confirms that when they save a profile.
- Hybrid: only cases with `class: sure`, `runner: agent`, `viewport: pc` and kind `label`,
  `element` or `behaviour` go into a spec. `sure` cases change no data (triage rules), so a replay
  never submits twice.
- The engine is Python Playwright (an optional dependency, needed only for record and replay).

## Design

| Piece | Where |
|---|---|
| Spec per suite, keyed by case id, bound to each case's digest; review gate by hash | `<suite folder>/spec.json`, `webtest_spec.py` |
| Engine: locators, steps, spec error versus fail, host guard, kept replies, page snapshot | `webtest_live.py` |
| First run (record): open, step, done, give up, finish; the recorded rows get their results | `webtest_record.py`, `<run folder>/spec.record.json` |
| Replay a run's queued rows from the reviewed spec | `webtest_replay.py` |
| Login Recipe: steps with `{{placeholders}}` per scenario; profiles; saved sessions | `login_recipe.py`, `~/.testign-kit/webtest/{login/<p>/<s>/recipe.json, profiles/, sessions/}` |
| Secret guard hook | `hooks/secret_guard.py` |
| Job modes | `webtest-run` gets `mode: record` and `mode: replay` |
| Console | suite: spec card (status, steps, warnings, check, Review); run: Record and Replay buttons; login scenario: recipe status |

Outcomes of a step: `ok`; `spec_error` (the locator finds nothing or several elements: the spec is
wrong); `fail` (an `expect_` check failed: the app is wrong). In a replay, a spec error leaves the row
`not-run` with reason `spec-error` (run it again in Chrome or record again), and a sign-in that lands
back on the login page leaves every row `not-run` with reason `session-expired`.

## Non-goals

Several browsers per run, CI runs, recording in the tester's own Chrome, cases that change data,
phone-width replay, a keychain, a console form for passwords (profiles are typed in the tester's own
terminal).

## Acceptance criteria

1. A spec refuses cases that are not eligible, placeholders, and steps without an `expect_` check.
   Editing it clears the review, and a review needs a check with no spec error on the current hash.
2. Recording replays the recorded steps in a fresh context before each new step, and data-changing
   requests of recorded steps get their kept replies.
3. Replay writes pass or fail with a screenshot for every row it runs, `not-run: spec-error` for a
   spec error, and `not-run: session-expired` when the sign-in fails. It never navigates off the run's
   hosts.
4. Profiles are 0600, are never printed, and their values are scrubbed from every error and snapshot
   the agent sees. The secret guard blocks Claude from reading or writing them, and from `profile-set`.
5. Unit tests for the spec, recipe and guard; integration tests on a local demo page with real
   Chromium (skipped without Playwright); the full test suites pass; README and skill docs updated;
   version 0.8.0.

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | Spec model and engine | done |
| 2 | Login Recipe, profiles, secret guard | done |
| 3 | Record and replay, job modes, CLI | done |
| 4 | Console screens | done |
| 5 | Tests on a local demo page, docs, version | done |

## Risks

- A recorded locator holding live data (a date, a count) fails the next run: the spec view warns
  (`live_data_locator`), as qingyi does.
- The guard is text matching, not a security boundary: a profile is plaintext under file
  permissions.
