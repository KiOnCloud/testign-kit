---
phase: 2
title: "Run model, CLI and server rules"
status: done
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Run model, CLI and server rules

## Goal

A `mobile_method` field (`device` | `emulation`) on cases, carried from triage through the review
table to the confirmed plan, with the runner rule moved from "mobile never agent" to "device never
agent".

## Files

- `scripts/testign/webtest.py`: `MOBILE_METHODS = ("device", "emulation")`; add `mobile_method` to
  the case keys (`:74`), `TRIAGE_KEYS` (`:80`), `check_triage` (`:271`), `PLAN_LINE_KEYS` (`:394`),
  the plan apply loop (`:599`), the agent rule (`:611`) and `worker_view` (`:685`, plus
  `emulation: true` for agent rows with `emulation`). A mobile case with no method reads as
  `device`; pc cases carry none (a method on a pc row is dropped). `webtest-columns --ask` lines
  include the field.
- `scripts/testign/console/jobs.py`: `REVIEW_LINE_KEYS` (`:235`), `REVIEW_EDIT_KEYS` (`:236`),
  line validation (`:256`, `:261`) and answer validation (`:318`, `:338`): refuse `agent` only
  when the final method is `device`; new error code `mobile-device-agent`, keep `mobile-agent` as
  an alias for old clients.
- `scripts/testign/console/webtest_api.py`: `CASE_VIEW` (`:165`) shows the field.
- Tests: `tests/test_webtest.py`, `tests/test_console_webtest_jobs.py`,
  `tests/test_console_webtest_api.py`.

## Steps

1. Model and normaliser (missing → `device` on mobile rows, dropped on pc rows).
2. Triage, columns ask, plan apply and agent rule in the CLI.
3. Server validation of ask lines and answers; error codes.
4. Tests for: default, round trip, device+agent refused at all three layers, emulation+agent
   accepted, 0.4.0 run file without the field.

## Validation

`python -m pytest tests/test_webtest.py tests/test_console_webtest_jobs.py tests/test_console_webtest_api.py`.

## Risk and rollback

The rule change widens what the agent may run; the default stays `device`, so an unedited table
behaves as today. Revert the commit to roll back; run files stay readable either way.

## As built

- `mobile_method(viewport, method)` and `agent_may_run(viewport, method)` in `webtest.py` are the
  one rule; triage, `apply_plan`, `worker_view` and the server's line and answer checks call them.
- `worker_view` carries `mobile_method` itself instead of an `emulation: true` flag.
- Error codes kept: the server still answers `mobile-agent` and the UI key stays
  `rt_err_mobile_agent`; only the message changed to "phone-width rows on a real device go to the
  tester". No `mobile-device-agent` code, so old clients need no alias.
