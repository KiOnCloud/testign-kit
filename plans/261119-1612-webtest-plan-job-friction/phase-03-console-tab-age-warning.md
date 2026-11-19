---
phase: 3
title: "Console tab age warning"
status: completed
priority: P1
effort: "1d"
dependencies: []
---

# Phase 3: Console tab age warning

<!-- Updated: Red Team Session 1 - server-side detection at claim and ask, can_answer boolean, distinct error code, run screen covered, webtest skill steps, re-queue risk -->

## Goal

When no console tab can answer a job, the agent learns it at claim time, before any work, and
re-queues; a tab that cannot answer says so instead of offering a form.

## Context

- Rule: `answer()` (`scripts/testign/console/jobs.py:929-947`) refuses a tab created at or after
  the job's `created_ts` (web jobs) or `started_ts` (others) with `403 session-too-new`; the age
  check runs before the `ask is None` / `ask_id` checks (:939 vs :943-947). Run-screen actions use
  `check_run_session` (:988-997; `webtest_api.py:221-227`). The rule stays.
- The server knows every session's creation time (`session_times`, `server.py:269-272`; floats
  from `exchange_code`, :243), kept in memory only (:213).
- Today the refusal reaches only the browser; the held `console ask` loop (:1221-1238) keeps
  returning `{answers: null}`, which the docs define as "call again" (`console-bridge.md:31`).
- `console start` returns once it opens the browser; the session is created later when the tab
  trades in the launch code (`lifecycle.py:254-290`, `server.py:229-244`), so a job queued right
  after start, or after a hand-opened URL, can have no older tab.

## Files to Create / Modify

- Modify: `scripts/testign/console/jobs.py` (shared `tab_can_answer(job, created)` helper used by
  `answer()`, `check_run_session`, `get()`, claim and held ask)
- Modify: `scripts/testign/console/server.py` (pass the requesting session's creation time to
  `get()`; expose `session_times` to the bridge)
- Modify: `scripts/testign/console/client.py` (`ask`, :74; claim) and the `console` CLI commands
- Modify: `scripts/testign/console/ui/views/jobs.mjs`, `review.mjs`, `review-table.mjs`,
  `login.mjs`, `run.mjs`, `job-actions.mjs`
- Modify: `scripts/testign/console/ui/i18n/{en,vi,ja}.json`
- Modify: `references/console-bridge.md` ("Held calls", "Errors"), `skills/console/SKILL.md`
  step 2–3, `skills/webtest/SKILL.md` step 8 (review table) and the sign-in step
- Modify: tests `tests/test_console_jobs.py`, `tests/test_console_bridge.py`,
  `tests/test_console_webtest_jobs.py`, `tests/test_console_webtest_api.py`, UI tests in
  `scripts/testign/console/ui/tests/`

## Tasks & Steps

- [x] `tab_can_answer`: one helper with the exact float rule; `answer()` and
      `check_run_session` call it (no behaviour change).
- [x] `no_older_tab(job)`: true when no browser session is older than the job's cutoff. `console
      claim` and every held `console ask` / `webtest-resolve --wait` check it and fail with
      `409 no-older-tab` (a new code old clients relay instead of looping), not a null-answer
      variant. Claim-time failure means no Figma or Chrome work is spent.
- [x] `get()` returns `can_answer: bool` for the requesting session (computed by the helper), and
      the run view a `can_act: bool`; the UI shows the notice (existing `job_err_session_too_new`
      text, without "the agent has been told") instead of answer controls when false, on the job
      panel, review screen, review table, sign-in card and run screen.
- [x] A refused `answer()` stays a 403 and records nothing beyond today (detection no longer
      depends on it); an answer always wins.
- [x] Agent side: on `no-older-tab` the agent fails the job with that reason, re-queues it at
      once, says so in the chat, and the new job carries `queued_after: "no-older-tab"` shown on
      the job card. Bridge doc row and console skill updated; webtest skill steps 8 and sign-in
      point to the row.
- [x] Tests: helper parity with `answer()` at sub-second gaps; claim refused with no older tab and
      accepted with one; held ask returns `no-older-tab`; `can_answer`/`can_act` per session;
      run-screen action from a too-new tab still 403; UI notice replaces the form; i18n parity.

## Verification

- `python -m pytest tests/test_console_jobs.py tests/test_console_bridge.py tests/test_console_webtest_jobs.py tests/test_console_webtest_api.py tests/test_console_ui_assets.py -q`
- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`
- e2e: `python -m pytest tests/e2e -q`

## Security

- `can_answer` is a boolean for the requesting tab only; no session token or time leaves the
  server beyond the existing `browser_sessions` list.
- Known gap, unchanged by this phase: the agent holds the agent token and could mint a tab and
  then queue a job that tab may answer (`server.py:595`, rules.md forbids it). Auto re-queue does
  not add that capability; `queued_after` and the existing new-tab announcement
  (`ui/store.mjs:77`) make a re-queue visible to the tester.
