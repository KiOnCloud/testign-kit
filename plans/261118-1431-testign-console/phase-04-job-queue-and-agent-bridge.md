---
phase: 4
title: "Job queue and agent bridge"
status: pending
priority: P1
effort: "3d"
dependencies: [1]
---

# Phase 4: Job queue and agent bridge

## Goal

A sequential job queue in the server and the agent-side commands `testign console wait|claim|progress|ask|done`,
so the attached Claude Code session picks up survey, close and testcase jobs, asks the tester
through the console in the job's UI language, and closes each job with a result.

## Context

- Model: Zukai Labs phase 3 (`.../phase-03-job-queue-and-agent-bridge.md`): states, sessions, held calls, question files.
- The skills that do the work: `spec-qa` (survey), `qa-close` (close), `testcase`. Their tester interactions are mapped to asks in phase 6.
- Claude Code's Bash tool stops a command after 2 minutes unless the call sets a longer timeout (maximum 10 minutes). A killed client leaves its held HTTP call open on the server, which cannot see the disconnect.
- `report.write_revision` builds the next revision from the revision it reads (`report.py:184-194`); `report-save` sets `previous` to the latest file at save time (`cli.py:249-252`).
- `wiki-append-preview` returns per-page `name`, `exists`, `updated`, a unified `diff` string, the `added`, `skipped`, `superseded`, `index_repaired` lists and an `approval` hash, or `new_content` per page in manual mode (`cli.py:390-394`); `wiki-update` checks the hash against the current plan (`cli.py:397-403`).

## Job record

`~/.testign-kit/console/jobs/<id>.json`, mode 0600, written to a temporary sibling then replaced:

```json
{
  "id": "j20261118-143112-3fa1",
  "kind": "close",
  "ticket": "DEMO-1",
  "base_revision": "DEMO-1-survey-r2.md",
  "params": { "tester": "Asher" },
  "ui_lang": "ja",
  "report_lang": null,
  "state": "queued",
  "created_at": "...", "offered_at": null, "started_at": null, "finished_at": null,
  "session": null,
  "progress": [],
  "ask": null,
  "asked": [],
  "confirmed_approval": null,
  "result": null,
  "reason": null
}
```

## Kinds

| Kind | Parameters (checked when queued) | Route in phase 6 |
|---|---|---|
| `survey` | `ticket` matches `ticket_id_regex`; `repo` an absolute existing path for which `git -C <repo> rev-parse --git-dir` succeeds (worktrees and submodules included); `master_ref`, `develop_ref` optional, `[A-Za-z0-9._/-]{1,200}`; `fetch` bool, only from the tester's form; `feature` optional slug; `report_lang` in vi, ja, en (default: config `lang`) | spec-qa |
| `close` | `ticket` from the listing; `base_revision` = latest at queue time; `tester` (non-empty, at most 100 characters, from Settings) | qa-close |
| `testcase` | `ticket` from the listing; `base_revision` = latest at queue time; `mode` `write` or `trace`; `template` from the template list, required when more than one template is registered and always for `trace`; `workbook` from the ticket folder (required for `trace`, optional for `write`); `focus` optional list of row ids that exist in the report | testcase |

<!-- Red team 2026-11-18: repo check, template required, tester name, base revision -->

`ui_lang` (vi, en, ja) is required on every job. `report_lang` is set for `survey` only; other kinds take the report's `lang`.

## States

```text
queued ──wait──▶ offered ──claim──▶ running ◀──answer── needs-input
   │                │                  │  └──ask──────────▲
   │                │                  └──done──▶ done | failed
   │                └─(not claimed in 60 s, or its held call was replaced)─▶ queued
   ├──cancel──▶ cancelled
   └──(server start)──▶ failed: server-stopped
offered ──▶ failed: revision-moved   (close and testcase: base_revision is no longer the latest when claimed)
running | needs-input ──▶ failed, with reason:
    server-stopped   the server ended while the job was open
    session-lost     another session took over, or the tester pressed "Release agent"
    not-closed       the holding session asked for new work
    marked           the tester marked a silent job failed
```

<!-- Red team 2026-11-18: offered/claim, queued jobs at restart, revision-moved, release -->

Any other transition is 409. A failed job is never resumed; the console offers "Queue again" as a new job with the same parameters and the current latest revision.

## Agent commands

| Command | Route | Stdout |
|---|---|---|
| `console wait --session <id> [--timeout <s>]` | `POST /agent/wait` (held) | `{session, job}` (state `offered`) or `{session, job: null}` |
| `console claim <job> --session <id>` | `POST /agent/jobs/:id/claim` | `{ok: true}` or `{ok: false, reason: "revision-moved"}` |
| `console progress <job> --session <id> --message <text>` | `POST /agent/jobs/:id/progress` | `{ok: true}` |
| `console ask <job> --session <id> (--question <file.json> \| --from-preview <preview.json>) [--timeout <s>]` | `POST /agent/jobs/:id/ask` (held) | `{answers}` or `{answers: null}` |
| `console done <job> --session <id> --result done\|failed [--report <file>]` | `POST /agent/jobs/:id/done` | `{ok: true}` |
| `console approval <job> --session <id>` | `GET /agent/jobs/:id/approval` | `{approval}` confirmed by the tester, or `null` |

- `console start` prints a new `session` id each call; every agent answer repeats it.
- Held time: `--timeout` defaults to 100 seconds (inside the default 2-minute Bash limit); the server caps it at 540 seconds. The skill raises it only together with a matching Bash timeout or background mode (phase 6). <!-- Red team 2026-11-18: held calls vs Bash timeout -->
- A new held call from the same session replaces its old one: the old call is answered "nothing yet" at once and an offered job of that call goes back to `queued`. A job leaves `offered` only by `claim` (or the first `progress`/`ask`/`done`, which claim implicitly).
- Exit 0 for a result, also for "nothing yet"; exit 2 with `{error: {code, message}}` on stderr for `no-server`, `not-this-server`, `session-refused`, `session-replaced`, `transport`, `bad-request`.
- Session takeover as in Zukai (a `wait` from a new session is taken when the attached one has been silent for 60 seconds without a job or 15 minutes with one); the tester can also release a silent session at once from the console (`POST /api/agent/release`), which fails its job with `session-lost`.

## Ask file

| `type` | Fields | Answer |
|---|---|---|
| `questions` | `id`, `body?`, 1–4 questions with the fields `AskUserQuestion` takes; an option may allow multi-line "Other" text (pasted ticket text, pasted answers) | `[{selected: [labels], other?: text}]` per question |
| `review-rows` | `id`, `rows`: `[{row, q?, class, feature, page, anchors[], decision, quote, source, decided_by, date}]`; `row` is a unique id the agent assigns, `q` optional | `{rows: {"<row>": {action: "write" \| "skip" \| "edit", decision?, anchors?, page?}}}`, every row answered |
| `confirm-diff` | built only by `--from-preview`: the preview JSON as returned (per page `name`, `exists`, `updated`, `diff`; `added`, `skipped`, `superseded`, `index_repaired`; `approval`) | `{confirm: true \| false}`; on `true` the server stores `confirmed_approval` |
| `paste-pages` | built only by `--from-preview` in manual mode: per page `name` and `new_content` | `{done: true}` after the tester pasted them; the job result says nothing was written by testign |

<!-- Red team 2026-11-18: close gates as strong as the skill's, manual wiki mode -->

- Agent-authored text (`body`, questions, labels, progress): at most 8000 characters, no control characters except newline, no bidi control characters; written in the job's `ui_lang`. Quotes, decisions, anchors and diff text are passed as data.
- An `id` names one ask; while open, the same call fetches its answer after a timeout; once answered, the same `id` is refused (`bad-request`).
- Every answer records which browser session gave it.
- "Nothing yet" is never an answer and never consent.

## Wiki write guard

`wiki-update` gains an optional `--job <id> --session <id>`: when given, it fetches the job's `confirmed_approval` from the server and refuses unless it equals the approval it is about to write. The console skill always passes it (phase 6); without `--job` the CLI behaves as today.

## Console routes

`GET /api/state` (agent attached, waiting, last contact; queue; open job with `silent` after 15 minutes without contact; new browser sessions; change counter), `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/:id`, `POST /api/jobs/:id/answer`, `POST /api/jobs/:id/cancel` (queued only), `POST /api/jobs/:id/fail` (silent only), `POST /api/agent/release`.

## Files to Create / Modify

- Create: `scripts/testign/console/jobs.py` (records, kind checks, state machine, queue, sessions, asks; pure over a store interface)
- Create: `scripts/testign/console/client.py` (agent-side calls, proof before sending the agent token)
- Modify: `scripts/testign/console/server.py` (agent and job routes, held calls with replacement)
- Modify: `scripts/testign/console/lifecycle.py` (`session` in `start` output; open and queued jobs failed as `server-stopped` at start; `busy()`; pruning)
- Modify: `scripts/testign/cli.py` (`console wait|claim|progress|ask|done|approval`; `wiki-update --job --session`)
- Create: `tests/test_console_jobs.py`, `tests/test_console_bridge.py`

## Tasks & Steps

1. `jobs.py` state machine: every arrow above allowed, every other pair refused; tested without a server.
2. Kind checks against config, listings, the template list and `git rev-parse`.
3. Persistence, pruning (finished jobs older than 7 days, and beyond the 50 newest), failing open and queued jobs at start.
4. Sessions, takeover, release, held `wait` and `ask` with condition variables and replacement; release on shutdown.
5. Client and CLI commands, `--from-preview` packing, `wiki-update --job`.
6. `/api/state` and console job routes.

## Verification

- `python -m pytest tests/test_console_jobs.py tests/test_console_bridge.py -v`
- Bridge test: a fake agent runs `wait` → `claim` → `progress` → `ask` (`review-rows` with two rows for one Q, one edited) → the test answers as the browser → `ask --from-preview` → confirm → `approval` returns the hash → `done`; the record shows each state.
- Also: a client killed during a held `wait` followed by a new `wait` from the same session gets the queued job; a job offered to a replaced call returns to `queued`; an unclaimed offered job returns to `queued` after 60 s (shortened in the test); a close job queued on r2 fails with `revision-moved` when r3 exists at claim; `wiki-update --job` refuses a different approval; the agent token cannot call `/api/jobs/:id/answer`; a server restart fails open and queued jobs with `server-stopped`; release fails the silent job with `session-lost`; a `repo` that is a worktree is accepted and a plain folder refused; an unknown template, a missing template for `trace`, or a row id not in the report gets 400; a second answer to the same ask id is refused; job files have mode 0600.

## Success Criteria

Acceptance criterion 7 passes at the API level; survey, close and testcase are three entries of one kind table with no per-kind code outside it.

## Risk Assessment

- The model forgets to claim. Signal: jobs bounce between `queued` and `offered` in the phase 6 round. Response: `progress`, `ask` and `done` claim implicitly; the skill's first step after `wait` is `claim`.
- The Bash timeout differs on a runtime. Signal: `transport` errors at a fixed interval. Response: lower the default `--timeout`.

## Security Considerations

- The agent commands send the agent token only after the server proved it holds the same token (`/health` proof), so a foreign listener never receives it; the agent token cannot answer asks.
- The diff the tester confirms is the tool's own preview output, and the write is refused unless its approval hash is the confirmed one.
- Job parameters are checked against listings and patterns; free text is length-capped and stored as data.
