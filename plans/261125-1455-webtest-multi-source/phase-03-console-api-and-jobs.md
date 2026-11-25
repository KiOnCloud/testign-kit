---
phase: 3
title: "Console API and jobs"
status: completed
priority: P1
effort: "1.5d"
dependencies: [1, 2]
---

# Phase 3: Console API and jobs

<!-- Updated: Validation Session 1 - WEB_KINDS and a separate AGENT_KINDS; webtest-plan is retired in phase 7 together with the run form, not here; freshness enum corrected; hash route lines corrected -->

## Goal

The console server exposes suites, creates runs from suites, queues a `suite-generate` job for
sources that need the agent, and returns survey freshness in the ticket list.

## Context

- Browser routes live in `readapi.py:540-546`, `templates_api.py:271-277`, `login_api.py:57-69`,
  `webtest_api.py:383-398`, `jobs.py:1552-1561`; agent routes in `jobs.py:1532-1549`.
- Job kinds `survey`, `close`, `testcase`, `webtest-plan`, `webtest-run` (`jobs.py:625-631`).
  `WEB_KINDS = ("webtest-plan", "webtest-run")` (`jobs.py:45`) does two jobs: the tab-age cutoff
  (`answer_cutoff`, `jobs.py:683-688`) and the agent allow list (`jobs.py:875`).
- Freshness per ticket is a separate call today (`GET /api/tickets/:ticket/hash`, route at
  `readapi.py:544`, handler `get_hash` at `readapi.py:517-521`). `hashcheck` returns `same`,
  `moved_no_impact` or `stale` (`hashcheck.py:58, 73`); `readapi.hash_status` adds `unknown` with a
  reason such as `busy` (not cached) and caches the rest by path and mtime (`readapi.py:359-389`).
- `Bridge.startup` already fails every active job with `server-stopped` (`jobs.py:725-737`).

## Design

New module `scripts/testign/console/suite_api.py`, registered like the other route groups:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/webtest/sources` | registry list: kind, mode, needs_agent (drives the wizard) |
| GET | `/api/webtest/suites` | list: name, source label, cases, state, runs count, project, updated |
| POST | `/api/webtest/suites` | create; for `excel` reads the uploaded file now; for `manual` creates empty; for `figma` / `backlog` creates in `generating` and queues `suite-generate` |
| GET | `/api/webtest/suites/:suite` | suite with cases, coverage and runs made from it |
| PATCH | `/api/webtest/suites/:suite` | rename, project |
| POST | `/api/webtest/suites/:suite/duplicate` | copy |
| DELETE | `/api/webtest/suites/:suite` | remove; refused while a run made from it is open |
| POST | `/api/webtest/suites/:suite/cases` | add case |
| PUT | `/api/webtest/suites/:suite/cases/:case` | edit case (returns per-field rule errors) |
| POST | `/api/webtest/suites/:suite/cases/bulk` | change class, runner or scenario, or delete, for many |
| POST | `/api/webtest/suites/:suite/confirm` | review to ready |
| GET | `/api/webtest/suites/:suite/captures/:name` | capture image |
| POST | `/api/webtest/suites/:suite/export` | test case workbook through a test case template |
| POST | `/api/webtest/runs` | create a run from a ready suite (`new_run_from_suite`) |

- Excel upload reuses the capped upload path of templates (`templates_api.py:273`, 10 MB).
- Job kind `suite-generate` (payload: `suite`, plus `figma_url` or `ticket` + `revision`), checked
  by the registry's `check`. It joins `WEB_KINDS` so the tab-age cutoff applies; a new
  `AGENT_KINDS = ("suite-generate", "webtest-run")` replaces `WEB_KINDS` in the agent allow list
  (`jobs.py:875`), so the two meanings no longer share one tuple.
- Agent routes: `POST /agent/suites/:suite/stage` and `/agent/suites/:suite/generated`, accepted only
  while the suite is `generating` and from the claimed generate job.
- `webtest-plan` keeps working in this phase, because the console's run form still posts it until
  phase 7 replaces that form; phase 7 retires the kind and everything that serves it.
- `GET /api/tickets` adds each ticket's latest revision freshness (`same` | `moved_no_impact` |
  `stale` | `unknown`, plus its reason when unknown) from the cached `hash_status`, the open question
  count and the suites made from it, so the survey table needs one request. `/hash` stays for the
  report view.

## Files to Create / Modify

- Create: `scripts/testign/console/suite_api.py`, `tests/test_console_suite_api.py`
- Modify: `scripts/testign/console/server.py` (route group), `jobs.py` (`suite-generate` kind and
  check, `WEB_KINDS`, `AGENT_KINDS`), `readapi.py` (ticket list fields), `webtest_api.py` (run create,
  `suite` in run summaries)
- Modify: `scripts/testign/console/ui/api.mjs` (client calls; UI screens come in phases 6–7)
- Modify: `tests/test_console_jobs.py`, `tests/test_console_webtest_jobs.py`,
  `tests/test_console_readapi.py`

## Tasks & Steps

1. Add the route group with session checks identical to the other browser routes.
2. Add `suite-generate`, split `AGENT_KINDS` from `WEB_KINDS`, update their tests.
3. Add the agent stage routes and refuse writes from any job other than the claimed generate job.
4. Extend the ticket list.
5. Tests: every route's happy path and refusals (no session, unknown suite, edit while generating,
   run from a suite in review, delete with an open run, upload over the cap, agent creating a
   `survey` job is still refused).

## Verification

- `python -m pytest tests -k "console"`
