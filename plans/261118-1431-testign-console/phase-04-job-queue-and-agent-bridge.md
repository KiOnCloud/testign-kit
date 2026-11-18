---
phase: 4
title: "Job queue and agent bridge"
status: pending
priority: P1
effort: "2.5d"
dependencies: [1]
---

# Phase 4: Job queue and agent bridge

## Goal

A sequential job queue in the server and the agent-side commands `testign console wait|progress|ask|done`,
so the attached Claude Code session picks up survey, close and testcase jobs, asks the tester
through the console in the job's UI language, and closes each job with a result.

## Context

- Model: Zukai Labs phase 3 (`.../phase-03-job-queue-and-agent-bridge.md`): states, sessions, held calls, question files.
- The skills that do the work: `spec-qa` (survey), `qa-close` (close), `testcase`. Their tester interactions are mapped to asks in phase 6.

## Job record

`~/.testign-kit/console/jobs/<id>.json`, written to a temporary sibling then replaced:

```json
{
  "id": "j20261118-143112-3fa1",
  "kind": "close",
  "ticket": "DEMO-1",
  "params": { "revision": "DEMO-1-survey-r2.md" },
  "ui_lang": "ja",
  "report_lang": null,
  "state": "queued",
  "created_at": "...", "started_at": null, "finished_at": null,
  "session": null,
  "progress": [],
  "ask": null,
  "asked": [],
  "result": null,
  "reason": null
}
```

## Kinds

| Kind | Parameters (checked when queued) | Route in phase 6 |
|---|---|---|
| `survey` | `ticket` matches `ticket_id_regex`; `repo` an existing directory that holds `.git`; `master_ref`, `develop_ref` optional, `[A-Za-z0-9._/-]{1,200}`; `fetch` bool; `feature` optional slug; `report_lang` in vi, ja, en (default: config `lang`) | spec-qa |
| `close` | `ticket` and `revision` from the server's listings (default: latest) | qa-close |
| `testcase` | `ticket`, `revision` from listings; `mode` `write` or `trace`; `template` from the template list (optional); `workbook` from the ticket folder (required for `trace`, optional for `write`); `focus` optional list of row ids that exist in the report | testcase |

`ui_lang` (vi, en, ja) is required on every job. `report_lang` is set for `survey` only; other kinds take the report's `lang`.

## States

```text
queued ──wait──▶ running ◀──answer── needs-input
   │                │  └──ask──────────▲
   │                └──done──▶ done | failed
   └──cancel──▶ cancelled
running | needs-input ──▶ failed, with reason:
    server-stopped   the server ended while the job was open
    session-lost     another session took over
    not-closed       the holding session asked for new work
    marked           the tester marked a silent job failed
```

Any other transition is 409. A failed job is never resumed; the console offers "Queue again" as a new job with the same parameters.

## Agent commands

| Command | Route | Stdout |
|---|---|---|
| `console wait --session <id> [--timeout <s>]` | `POST /agent/wait` (held) | `{session, job}` or `{session, job: null}` |
| `console progress <job> --session <id> --message <text>` | `POST /agent/jobs/:id/progress` | `{ok: true}` |
| `console ask <job> --session <id> --question <file.json> [--timeout <s>]` | `POST /agent/jobs/:id/ask` (held) | `{answers}` or `{answers: null}` |
| `console done <job> --session <id> --result done\|failed [--report <file>]` | `POST /agent/jobs/:id/done` | `{ok: true}` |

- `console start` prints a new `session` id each call; every agent answer repeats it.
- Held calls end after 9 minutes with "nothing yet" (inside Claude Code's 10-minute Bash limit); `--timeout` can only shorten that. The client uses `urllib` with no timeout on held calls.
- Exit 0 for a result, also for "nothing yet"; exit 2 with `{error: {code, message}}` on stderr for `no-server`, `not-this-server`, `session-refused`, `session-replaced`, `transport`, `bad-request`.
- Session takeover as in Zukai: a `wait` from a new session is taken when the attached one has been silent for 60 seconds without a job or 15 minutes with one; the old job fails with `session-lost`.

## Ask file

```json
{ "id": "q2-basis", "type": "questions", "body": "…",
  "questions": [{ "header": "…", "question": "…", "options": [{"label": "…", "description": "…"}], "multiSelect": false }] }
```

| `type` | Extra fields | Answer |
|---|---|---|
| `questions` | 1–4 questions, the fields `AskUserQuestion` takes | `[{selected: [labels], other?: text}]` per question |
| `review-rows` | `rows`: `[{q, class, decision, quote, source, page, decision_id, decided_by, date}]` | `{rows: {"Q1": "write" \| "skip"}}`, every row answered |
| `confirm-diff` | `pages`: `[{page, added, lines: [{op: "+" \| " " \| "-", text}]}]` | `{confirm: true \| false}` |

- `body` and every text: at most 8000 characters, no control characters except newline. Text is written by the agent in the job's `ui_lang`; quotes, decisions and diff lines stay as they are.
- An `id` names one ask; while open, the same call fetches its answer after a timeout; once answered, the same `id` is refused (`bad-request`).
- "Nothing yet" is never an answer and never consent.

## Console routes

`GET /api/state` (agent attached, waiting, last contact; queue; open job with `silent` after 15 minutes without contact; change counter), `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/:id`, `POST /api/jobs/:id/answer`, `POST /api/jobs/:id/cancel` (queued only), `POST /api/jobs/:id/fail` (silent only).

## Files to Create / Modify

- Create: `scripts/testign/console/jobs.py` (records, kind checks, state machine, queue, sessions, asks; pure over a store interface)
- Create: `scripts/testign/console/client.py` (agent-side calls, proof before sending the token)
- Modify: `scripts/testign/console/server.py` (agent and job routes, held calls)
- Modify: `scripts/testign/console/lifecycle.py` (`session` in `start` output; open jobs failed as `server-stopped` at start; `busy()` from the queue; idle rule extended)
- Modify: `scripts/testign/cli.py` (`console wait|progress|ask|done`)
- Create: `tests/test_console_jobs.py`, `tests/test_console_bridge.py`

## Tasks & Steps

1. `jobs.py` state machine: every arrow above allowed, every other pair refused; tested without a server.
2. Kind checks against config, listings and the template list.
3. Persistence, pruning to the 50 newest finished jobs, and failing open jobs at start.
4. Sessions, takeover, held `wait` and `ask` with condition variables; release on shutdown.
5. Client and CLI commands.
6. `/api/state` and console job routes.

## Verification

- `python -m pytest tests/test_console_jobs.py tests/test_console_bridge.py -v`
- Bridge test: a fake agent thread runs `wait` → `progress` → `ask` (`review-rows`) → the test answers through `/api/jobs/:id/answer` → `ask` (`confirm-diff`) → answer → `done`; the job record shows each state and the asks keep the job's `ui_lang` field.
- Also: a held `wait` with `--timeout 1` returns `job: null`; takeover after the silence window; a server restart fails an open job with `server-stopped`; a queued job with a `repo` outside a git checkout, an unknown template or a row id not in the report gets 400; a second answer to the same ask id is refused.

## Success Criteria

Acceptance criterion 7 passes at the API level; survey, close and testcase are three entries of one kind table with no per-kind code outside it.

## Risk Assessment

- Held calls exhaust threads. Signal: more than a few held connections in tests. Response: one attached session holds at most one call at a time by design; refuse a second held call from the same session.
- The agent's Bash call is cut before 9 minutes. Signal: phase 6 round shows `transport` errors at a fixed interval. Response: lower the held time.

## Security Considerations

- The agent commands send the token only after the server proved it holds the same token (`/health` proof), so a foreign listener never receives it.
- Job parameters are checked against listings and patterns; free text (`message`, ask text) is length-capped and stored as data.
