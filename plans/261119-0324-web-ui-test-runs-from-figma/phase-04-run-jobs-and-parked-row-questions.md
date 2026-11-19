---
phase: 4
title: "Run jobs and parked row questions"
status: pending
priority: P1
effort: "3.5d"
dependencies: [2]
---

# Phase 4: Run jobs and parked row questions

## Goal

Two job kinds for web runs, a review-table ask for the one confirmation, run-scoped answers to
parked rows and tester results, and read routes for runs, so the console can show and steer a run
while the orchestrator keeps the queue moving.

## Context

- A job kind is one entry in `KINDS` with its parameter check (`console/jobs.py:381`). `Bridge.create` stores `ticket`, `base_revision`, `params`, `ui_lang` (`console/jobs.py:580-620`); the server side already accepts a job without a ticket.
- Only a browser session can queue a job today (`console/jobs.py:1028`); the agent routes cannot (`console/jobs.py:1015-1024`). An agent that needs to queue would have to mint itself a browser session (`console/server.py:595`), which then passes the session-age rule, because that rule compares with the job's claim (`console/jobs.py:660-668`).
- `Bridge.ask` allows one open question per job; `timeout: 0` returns at once (`console/jobs.py:832-873`, `913`). `Bridge.done` refuses `done` while a question is open (`console/jobs.py:884-886`).
- A job record is pruned after 7 days or 50 finished jobs (`console/jobs.py:474-485`); uploads are swept after one hour and at server start, and only workbooks are accepted (`console/templates_api.py:29`, `62-70`, `87-103`).
- The console plan allowed server writes under `~/.testign-kit/console/` and `~/.testign-kit/templates/` only (`plans/261118-1431-testign-console/plan.md:47`). This plan adds `~/.testign-kit/webtest/`.
- Route parameters are decoded after matching (`console/server.py:125`, `152`); the read API resolves names through a listing and never joins them into a path (`console/readapi.py:1-5`).

<!-- Updated: Red Team Session 1 - agent queue route; run-scoped answers replace job-scoped parks; consumers listed; login as a plain questions ask; stop and heartbeat; name checks -->

## Kinds

| Kind | Parameters (checked when queued) | Route in phase 6 |
|---|---|---|
| `webtest-plan` | `name` (1 to 80 characters); `source` (`figma` with a Figma design URL that has a `node-id`); `base_url` (http or https, absolute); `project` from the project list, whose hosts must include the base URL's host; `template` from the template list (optional when one is registered); `ticket` optional, matching `ticket_id_regex`; `report_lang` in vi, ja, en | import, triage, review table |
| `webtest-run` | `run` an existing run id whose plan is confirmed; `tester` (as for `close`) | recovery, queue execution, export |

- The run's hosts are the project's hosts at the time the plan job is queued. Hosts are edited only in the console (phase 5); no agent command writes them.
- `webtest-run` does not refuse a run with a `running` row: recovery handles it (phase 2).
- The job summary gains `run` and `queued_by` (`tester` or `agent`).

## Queueing from the command

`POST /agent/jobs` (agent group) queues a `webtest-plan` or `webtest-run` job with the same
checks and marks it `queued_by: agent`. The console shows such a job as "queued from the chat"
until the tester opens it. The agent never needs a browser session, and the skill forbids
minting one.

For both web kinds, a tester action (review-table answer, row answer, tester result, finish,
"Signed in") is accepted only from a browser session older than the job's creation, not its claim.
The residual risk stays as the console plan recorded it: the agent runs as the tester and could
have minted a session in an earlier job. The README says so.

## Review-table ask (blocking)

One ask of type `review-table`, used once per `webtest-plan` job. It carries the column plan with
three sample rows, the template's headers, the run's hosts (read-only), the project's scenarios
with their approval state, and one line per case (`row`, `no`, `content`, `screen`, `confidence`,
`class`, `reason`, `runner`, `scenario`, `viewport`). The server validates sizes and passes case
text as data.

Answer: `{columns: [...], verdict_labels: {...}, rows: {"<row>": {screen?, class?, runner?, scenario?, preconditions?, viewport?}}, confirm: true | false}`.
The server checks that every row is known, that `runner: agent` on a `choice` row comes with
`preconditions`, that scenarios exist, and that every screen is on a run host. This is the one
place the rule is enforced; the UI mirrors it for feedback and the CLI stores what the server
returns. The answered ask stays in the job record as every ask does. `confirm: false` ends the
job as `failed` with reason `not-confirmed`.

`GET /agent/jobs/:id/review` returns the confirmed answer to `webtest-plan` (phase 2), for the
session that owns the job.

## Run-scoped answers

Questions live in `run.json` (phase 2). The tester's answers and results live in
`~/.testign-kit/webtest/runs/<run-id>/answers.json`, written by the server, so they outlive the
job that asked.

| Route | Group | Does |
|---|---|---|
| `POST /api/webtest/runs/:run/answers/:question` | browser | Stores `delegate` (with `preconditions`), `self-run` or `skip` for a question id that is open in `run.json`. |
| `POST /api/webtest/runs/:run/rows/:row/result` | browser | Stores a tester result (`verdict`, `actual`, optional image id) for an `awaiting-tester` row. Works with or without an open job. |
| `PUT /api/webtest/runs/:run/images` | browser | Takes a PNG or JPEG (signature check, size cap), stores it under the run's server folder, returns an image id. Not swept by the one-hour upload sweep. |
| `POST /api/webtest/runs/:run/finish` | browser | The tester ends the run with open rows. Ends an open "Signed in" question on the run's job. |
| `POST /agent/webtest/runs/:run/pending` | agent | Returns answers and results not yet applied, with `finish`, held only with `wait`. |
| `POST /agent/webtest/runs/:run/applied` | agent | Marks question ids as applied; called by `webtest-resolve` after `run.json` is written. |

- Answers are keyed by question id (row plus attempt), so an answer to an earlier park is never applied to a later one.
- A tester result entered while no job is open is applied by `webtest-resolve` at the start of the next run job, or by `webtest-export --apply-pending` when the tester exports from the console without running again.
- `/api/state` counts open run questions and `awaiting-tester` rows in `needs_input` (`console/jobs.py:546`), so the sidebar's "needs you" badge shows them (`ui/views/shell.mjs:143-147`).
- `Bridge.done` with `done` on a `webtest-run` job is refused while the run has an open row and `finish` is not set.

## Login question

A `questions` ask with the scenario's label in the body and the options "Signed in" and "Skip this
scenario". The tester signs in by hand in their own Chrome; the server never answers the question. After the
answer, `webtest-signed-in` reads it from the server and sets `signed_in` in `run.json` (phase 2).

## Stopping and silence

- `console progress` is called as a heartbeat while a worker runs (phase 6), so a long row does not make the job silent (`console/jobs.py:48`, `628-635`).
- "Mark failed" on a web job works while the agent sits in a held call: the silence clock for these kinds counts from the last progress line, not from the last call.
- When the last progress line of a web job is older than two minutes, `/api/state` flags it and the console says the agent may be waiting for a browser permission in the terminal.

## Read routes

| Route | Returns |
|---|---|
| `GET /api/webtest/runs` | Runs under `output_dir/webtest` with name, source, counts by state, export paths; unreadable runs are marked, not hidden. |
| `GET /api/webtest/runs/:run` | The run: project, hosts, column plan, cases with state, class, runner, scenario, question and result. |
| `GET /api/webtest/runs/:run/evidence/:name` | One evidence image, resolved by listing the run's `evidence/`. |
| `GET /api/webtest/runs/:run/captures/:name` | One capture from `source/`, resolved the same way. |

Run ids are resolved by listing `output_dir/webtest`; names with a separator, `..`, an encoded
separator or a Windows reserved name (`console/templates_api.py:31`) are not found.

## Consumers of the changed interfaces

| Interface | Consumer | Edit |
|---|---|---|
| `KINDS` | `tests/test_console_jobs.py:123` pins the kind set | Add the two kinds to the assertion |
| Job kinds in the UI | `ui/views/job-actions.mjs:162-175` builds a survey request for unknown kinds on "Queue again" | Add the two kinds; `webtest-run` re-queues with the same run |
| Fail reasons | `FAIL_REASONS` (`console/jobs.py:44`); reason labels built at `ui/views/jobs.mjs:211` | Add `not-confirmed`; keys in vi, en, ja (phase 7) |
| Ask types | `ui/views/jobs.mjs:16`, `220`; `ui/views/review.mjs:13`; `ui/main.mjs:22` | Route `review-table` to its own view (phase 7) |
| `validate_ask` / `validate_answer` | `console/jobs.py:116-281` | Add `review-table` |
| `needs_input` | `console/jobs.py:546`; `ui/views/shell.mjs:143-147` | Count run questions and tester rows |
| Job language | `report_lang` (`skills/console/SKILL.md:66`) | Reused; no `run_lang` |

## Files to Create / Modify

- Modify: `scripts/testign/console/jobs.py` (two kinds, agent queue route, `queued_by`, session-age rule for web kinds, `review-table`, `not-confirmed`, `done` guard, silence clock)
- Create: `scripts/testign/console/webtest_api.py` (read routes, answers, results, images, finish, pending and applied)
- Modify: `scripts/testign/console/client.py` and `scripts/testign/cli.py` (`console queue`, the server readers used by the phase 2 commands)
- Modify: `scripts/testign/console/lifecycle.py` (the `webtest/` folder created owner-only)
- Modify: `references/console-bridge.md` (queueing, the review table, run answers, the login question, errors)
- Create: `tests/test_console_webtest_jobs.py`, `tests/test_console_webtest_api.py`

## Tasks & Steps

1. Add the two kind checks, the agent queue route and `queued_by`; run the existing job tests and update the pinned kind set.
2. Add the `review-table` validators and the review reader route.
3. Add the run-scoped answers store and its routes, the image route and the finish flag.
4. Add the `done` guard, the silence clock for web kinds and the `needs_input` count.
5. Add the read routes with name resolution by listing.
6. Wire the phase 2 commands to the server readers and document the bridge.
7. Write the tests listed below.

## Todo

- [ ] Two kinds, agent queue route, `queued_by`
- [ ] Session-age rule against job creation for web kinds
- [ ] `review-table` ask and review reader
- [ ] Run-scoped answers, results, images, finish
- [ ] `done` guard, silence clock, `needs_input`
- [ ] Read routes and name checks
- [ ] Phase 2 commands wired to the server
- [ ] Bridge reference
- [ ] Tests

## Verification

- `python -m pytest tests/test_console_jobs.py tests/test_console_webtest_jobs.py tests/test_console_webtest_api.py -v`
- Tests cover: the three existing kinds behave as before; the agent route queues only the two web kinds; a browser session created after a web job was created cannot answer its review table, a row question, a result, finish or "Signed in"; `webtest-plan` stores exactly the answer the server holds and refuses when there is none; an answer given before a server restart is still delivered to the next job; an answer to `r05-a1` is not applied to `r05-a2`; a tester result with an image survives two hours and a server restart; `done` is refused with an open row and accepted after finish; finish ends an open "Signed in" question; run and image names with `..`, `%2F`, `\` or a reserved name get 404; a file that is not an image is refused; the `webtest/` folder is created with owner-only mode on macOS.

## Risks

- Two places hold run data: `run.json` (cases, questions, results) and the server's `answers.json` (what the tester said). The rule is one direction only: the server never reads its own answers back into a decision; the CLI applies them to `run.json` and marks them applied.
- Mode bits do not restrict access on Windows (`fsutil.py:30`). The README states that the folder is protected by the user profile's own access rules there.
