---
phase: 2
title: "Run store and normalised case list"
status: pending
priority: P1
effort: "3d"
dependencies: []
---

# Phase 2: Run store and normalised case list

## Goal

A run folder with one `run.json` that holds the case list, the row states, the open questions and
the results, and the CLI commands the orchestrator uses to create a run, stage an import, pick the
next row and record a result.

## Context

- Reports live in `<output_dir>/<TICKET>/` and are written only by CLI commands (`report.py:223` `write_new`). Runs follow the same split: `<output_dir>/webtest/<run-id>/`.
- Atomic writes: `fsutil.atomic_write_bytes` (`fsutil.py:27`).
- Every subcommand prints JSON and exits 2 with a one-line message on errors (`skills/testcase/SKILL.md`, "Before you start").
- A command that applies a tester decision reads it from the server with the job and session, as `wiki-update` does (`cli.py:385-400`). It never takes the decision from a file the agent wrote.

<!-- Updated: Red Team Session 1 - row ownership and recovery, attempts, park ids, staged import, server-fetched decisions, blocked-env, awaiting-tester -->

## Run folder

```text
<output_dir>/webtest/<run-id>/
  run.json            the run: source, project, hosts, column plan, cases, states, questions, results
  source/             the import as received, one file per row plus captures; never re-fetched
  evidence/           <row>-a<attempt>-<n>.png, moved here by the evidence command
  <run-id>.xlsx       written by export (phase 3)
  <run-id>-report.md  written by export (phase 3)
```

`<run-id>` is `W<yyyymmdd>-<hhmm>-<slug>`. The slug matches `[a-z0-9-]{1,40}` and is made by the
command from the tester's run name; a name that leaves nothing gets `run`.

## Case schema

```json
{
  "row": "r02",
  "source": {"kind": "figma", "file": "6mk0tfGVyiFgveLasgWCVu", "table_node": "6647:118148",
             "row_node": "6647:118793", "target_node": "194:5977", "no": "2"},
  "type": "Modified",
  "content": "予約確認 update lại thành 予約履歴",
  "creator": "hoang_ntm",
  "capture": "source/r02.png",
  "screen": {"url": "/mypage", "name": "My Page", "confidence": "high"},
  "viewport": "pc",
  "kind": "label",
  "class": "sure",
  "reason": "text change on a visible link",
  "scenario": "member",
  "runner": "agent",
  "preconditions": "",
  "steps": "1. Open My Page",
  "expected": "The link reads 予約履歴",
  "state": "queued",
  "attempt": 0,
  "owner_job": null,
  "question": null,
  "decided_by": null,
  "result": null
}
```

- `kind`: `label`, `element`, `visual`, `behaviour`, `data-rule`, `motion`, `design-only`.
- `class`: `sure`, `choice`, `not-web`. `runner`: `agent`, `tester`, `none`.
- `viewport`: `pc` or `mobile` (a viewport size, not a device).
- `question`: `{id: "<row>-a<attempt>", body, asked_at}` while the row is parked.
- `decided_by`: the fingerprint of the console session that delegated the row, with the time.
- `result`: `{verdict, actual, url, evidence: [...], executed_at, by}`.

The run also holds `project`, `hosts`, `signed_in` (scenario and the job that confirmed it) and
`import` (`staged` rows, `complete`).

## Row states

```text
queued ──next──▶ running ──row──▶ pass | fail
   ▲                 ├──park──▶ parked ──answer──▶ queued | awaiting-tester | not-run
   │                 └──blocked-env──▶ queued            (class and attempt count kept)
   └── recover: running rows whose owner job has finished
   ├─ class not-web ─▶ manual | not-applicable           (set at confirmation)
   ├─ runner tester ─▶ awaiting-tester ──result──▶ self-run
   └─ run closed ───▶ not-run: unanswered | no-result | no-scenario | off-site | no-screen | stopped
```

A `sure` row that parks moves to class `choice`; a `blocked-env` row does not. Each `next`
raises `attempt`. Any other transition is refused. `parked` and `awaiting-tester` are open states.

## Commands

| Command | Does | Refuses |
|---|---|---|
| `webtest-new --job <j> --session <s> --name <n>` | Creates the run folder and `run.json`. Base URL, hosts, project, ticket and source come from the job's parameters on the server; the command takes none of them as arguments. | A job that is not an open `webtest-plan` job of this session; an existing run id. |
| `webtest-find --source-ref <file>:<node>` | Lists runs that hold a complete or partial import of that source. | — |
| `webtest-stage --run <id> --row <r> --case <file> [--capture <png>]` | Saves one imported row to `source/`, so an import can stop and resume. | A row already staged with other content; a case that fails the schema. |
| `webtest-import --run <id>` | Turns the staged rows into the case list and marks the import complete. | A second import; duplicate rows; a `screen.url` on a host outside the run's hosts. |
| `webtest-plan --run <id> --job <j> --session <s>` | Reads the confirmed review-table answer from the server and stores it: per-row edits, the column plan, `decided_by` on delegated rows, the initial states. | A job with no confirmed answer; a `choice` row with `runner: agent` and empty `preconditions`. A row with `runner: agent` and no scenario or no screen is set to `not-run`, not refused. |
| `webtest-recover --run <id> --job <j> --session <s>` | At the start of a run job: puts `running` rows whose `owner_job` has finished back to `queued`, and clears `signed_in`. | A `running` row owned by a job that is still open. |
| `webtest-next --run <id> --job <j> --session <s>` | Returns the next `queued` row whose runner is `agent`, in queue order, marks it `running` with `owner_job` and raises `attempt`; keeps the job and session ids in the run so the skill can read them back. Returns `{row: null, need: "<scenario>"}` when the remaining rows need a scenario other than `signed_in`. | A run that already has a `running` row. |
| `webtest-row --run <id> --row <r> --result <file>` | Records `pass` or `fail` with `actual`, `url` and the evidence of the current attempt. | A row that is not `running`; a `url` outside the run's hosts (the row becomes `not-run: off-site`); `pass` or `fail` with no evidence recorded for the current attempt. |
| `webtest-requeue --run <id> --row <r> --reason <text>` | The `blocked-env` outcome: back to `queued`, class unchanged. Three in a row across rows set `halted` on the run. | A row that is not `running`. |
| `webtest-park --run <id> --row <r> --question <file>` | Moves a `running` row to `parked`, its class to `choice`, and stores the question with its id. | A row that is not `running`. |
| `webtest-resolve --run <id> --job <j> --session <s> [--wait]` | Fetches the answers and self-run results the tester gave for this run from the server and applies each question id once: `delegate` to `queued` with preconditions and `decided_by`, `self-run` to `awaiting-tester`, `skip` to `not-run`, a tester result to `self-run`. Applying an id twice is a no-op. Reports `finish` when the tester ended the run. With `--wait` it holds until something new arrives. | — |
| `webtest-signed-in --run <id> --job <j> --session <s> --scenario <sc>` | Sets `signed_in` when the server holds the tester's "Signed in" answer for that scenario in this job. | An answer that is missing or names another scenario. |
| `webtest-close --run <id> [--stopped]` | Turns every remaining `queued`, `parked` and `awaiting-tester` row into `not-run` with its reason (`stopped` when the tester ended the run). | A run with a `running` row owned by an open job. |
| `webtest-status --run <id>` | Counts by state and the list of rows with state and class. | — |

All commands take the run by id and resolve it by listing `<output_dir>/webtest/`; a path is never
accepted and the id is never joined into a path unchecked.

The `url` in a result is what the worker reports. The check on it is a consistency check: it
catches a row that ended on the wrong site, it does not stop a page from loading. What limits
navigation is the site permission the tester grants Claude in Chrome (phase 7) and the real URL
the capture records (phase 6).

## Files to Create / Modify

- Create: `scripts/testign/webtest.py` (schema checks, states, queue order, host check, recovery)
- Modify: `scripts/testign/cli.py` (the subcommands above, additive)
- Create: `tests/test_webtest.py`
- Create: `tests/fixtures/make_webtest_run.py` (a made-up 8-row case list covering every `kind`)

The commands that read from the server (`webtest-new`, `-plan`, `-recover`, `-resolve`,
`-signed-in`) get their server calls in phase 4; here they are written against an injected reader
and tested with a fake.

## Tasks & Steps

1. Write the schema checks and the state table in `webtest.py`, with the transitions as data.
2. Write the queue order: scenario, then screen, then source order; rows of the signed-in scenario first.
3. Write the host check: scheme http or https, host equal to a run host, compared case-insensitively after IDNA encoding; no suffix matching.
4. Write recovery, attempts and question ids.
5. Add the subcommands; each prints JSON and writes `run.json` through `fsutil.atomic_write_bytes`.
6. Write the tests listed below.

## Todo

- [ ] Schema checks and state table
- [ ] Queue order and scenario grouping
- [ ] Host check and run id resolution by listing
- [ ] Staged import and resume
- [ ] Recovery, attempts, question ids
- [ ] CLI subcommands
- [ ] Tests

## Verification

- `python -m pytest tests/test_webtest.py -v`
- Tests cover: an import stopped after three staged rows resumes and completes; a second import is refused; a job that dies with a row `running` is followed by a new job whose `webtest-recover` requeues that row, and the run then closes and exports; `webtest-next` never returns a row whose runner is not `agent`, a row without a scenario, or a row whose scenario is not `signed_in`; a result on another host becomes `not-run: off-site`; `pass` with only an earlier attempt's evidence is refused; a parked `sure` row becomes `choice` and a requeued one does not; three requeues in a row halt the run; applying the same answer id twice changes nothing; `webtest-close` leaves no open row; a run id with `..`, a separator or an encoded separator is not found.
- A case with `source.kind: "workbook"` is accepted by `webtest-stage` (the extension trace's proof).

## Risks

- `run.json` grows with 45 rows of text and their questions; it stays well under the size where atomic rewrites matter. No database is added.
- A tester edits `run.json` by hand. The commands validate on every load and exit 2 with the first error.
