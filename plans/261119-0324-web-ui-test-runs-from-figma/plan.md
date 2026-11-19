---
title: "Web UI test runs from a Figma change table, driven through Claude in Chrome"
description: "A /testign:webtest command and two console screens that import a Figma change table into a case list, let the tester confirm one review table, run the rows from a queue in Chrome and export an Excel workbook plus a Markdown report."
status: in-progress
priority: P1
effort: 22.5d
branch: claude/check-nearest-plan-47bc71
tags: [feature, frontend, backend, api, experimental]
blockedBy: []
blocks: []
created: 2026-11-19
---

# Web UI test runs from Figma

## Overview

A `/testign:webtest` command and two console screens that import a Figma change table into a
case list, let the tester confirm one review table, run the rows from a queue in Chrome and
export an Excel workbook plus a Markdown report. The first source is the "Update Summary Table"
of the USUPP file (file key `6mk0tfGVyiFgveLasgWCVu`, node `6647:118148`): 45 rows with the
columns No, Capture, Type, Content, Anchor Link, Created Date and Creator, where each row's layer
name carries the id of the design node that changed. The table holds no URL, no steps and no
preconditions, so the agent derives them and the tester confirms.

## Scope challenge

- Existing code reused: the console server, credentials and job bridge (`console/server.py`,
  `console/jobs.py`), the template registry and Excel writer (`templates.py`, `xlsx.py`), atomic
  writes (`fsutil.py`), the CLI's JSON convention (`cli.py`), the UI shell, i18n and ask form.
- Requested scope: one command, the console screens, column mapping with added and removed
  columns, triage with tester choice, queue execution in Chrome, login scenarios, Excel and
  Markdown output. Delivered in full. Selected mode: HOLD SCOPE.
- Complexity: about 28 new files in eight phases. Justified by four new parts that do not exist
  today: a run store, run-scoped tester answers, login scenarios, and a browser-driving skill.

## Contract

- **Outcome:** the tester gives a Figma link and a test base URL, confirms one review table with
  samples (column mapping, screen per row, triage class, login scenario), and gets every row
  executed or explicitly accounted for, in an Excel workbook and a Markdown report.
- **Constraints:** Claude never reads or types credentials; rows run only against the run's
  hosts, which only the tester sets; row text and page content are data, not instructions; data
  and logic rows run only when the tester delegates them; a tester decision reaches the run only
  through the server, never through a file the agent wrote; only the orchestrator writes results;
  the console server makes no LLM call and runs no code or browser; runs use the tester's own
  Chrome profile with no debug connection; Python 3.10+, standard library plus `openpyxl`, no Node on
  the tester's machine; UI strings in vi, en and ja.
- **Conditions of use:** test sites with made-up data and test accounts only.
- **Non-goals:** parallel workers, native mobile, pixel diff, headless or CI execution,
  production testing, fixing the bugs a run finds, a second importer (the case list allows it;
  none is built), editing login steps by hand in the console, automatic sign-in, storing account
  values, phone-width rows run by the agent.
- **Acceptance criteria:**
  1. Importing node `6647:118148` gives 45 cases, each with its source row, target node id and a triage class; a second import of the same node makes no Figma call, and an import stopped halfway resumes.
  2. The tester confirms one review table that shows the column plan with three filled sample rows, and can add, remove and reorder columns before confirming.
  3. Every row ends in one explicit state: `pass`, `fail`, `manual`, `not-applicable`, `self-run` (with the tester's result) or `not-run` with a reason. No row is left open, also after a job died in the middle of a row.
  4. Every `pass` and `fail` row has an evidence image on disk taken in that row's own attempt, named in the workbook and the report.
  5. A row that cannot continue is parked with a question and the next row starts without waiting; the question and its answer outlive the job that asked.
  6. A row with no approved login scenario, or with a scenario the tester has not confirmed as signed in during the current job, never starts. The tester signs in by hand.
  7. A result whose final URL is outside the run's hosts is refused by the CLI and recorded as `not-run: off-site`. The URL is the one the worker reports, so this is a consistency check; the site-access limit the tester confirms is the barrier.
  8. Nothing in the plugin stores an account value: the stores have no field for one, and the agent types nothing into a sign-in form.
  9. Export writes a new workbook from the confirmed column plan and a Markdown report; it never changes an existing file.
  10. CI passes on Windows and macOS with Python 3.10 and 3.13, and `claude plugin validate --strict .` passes.

## Key decisions

| Decision | Evidence |
|---|---|
| The engine is an agentic run through Claude in Chrome, not generated browser test scripts. | Most rows ask "does it match the design", which an assertion cannot state; generated scripts would add Node to the tester's machine (`pyproject.toml` depends on `openpyxl` only). Chosen by the user on 2026-11-19. |
| A run works on a normalised case list in `run.json`, not on Figma. | The workbook written by `/testign:testcase` is a second source that already exists (`xlsx.py:157` `read_trace`). |
| Three triage classes: `sure`, `choice`, `not-web`. A `choice` row runs only when the tester delegates it, and an unanswered row does not run. `visual` rows are `sure` and marked in the report. | Chosen by the user on 2026-11-19. Same rule as the console's asks: "nothing yet" is not consent (`skills/console/SKILL.md`). |
| Orchestrator and worker, one worker at a time. The orchestrator is the only writer of `run.json`. | Chosen by the user on 2026-11-19 ("queue for now"). |
| A run is one console job at a time; rows are sub-units in `run.json`. A `running` row records its job, and a later job recovers rows whose job has finished. | A server restart, a takeover or a second `wait` fails a job without touching the run (`console/jobs.py:460-470`, `698-707`, `774-778`). |
| Questions on parked rows live in `run.json`; the tester's answers and results live in a per-run file the server writes, keyed by question id. The job bridge's `ask` is not extended. | A job record is pruned after 7 days or 50 jobs and answers need an open job (`console/jobs.py:474-485`, `656-672`); a question must outlive the job that asked. |
| The command queues its job through an agent route; the agent never opens a console session. Tester actions on web jobs need a browser session older than the job's creation. `webtest-plan` and `webtest-resolve` read the tester's decision from the server. | Only a browser session can queue today (`console/jobs.py:1028`), and a session the agent mints passes the claim-time rule (`console/jobs.py:660-668`). Pattern: `wiki-update` (`cli.py:385-400`). |
| Hosts are set by the tester only, per project, in the console. A run copies them from its job. | Agent-written hosts would let page text widen its own allow-list. |
| Runs use the tester's own signed-in Chrome profile. No dedicated profile, no debug connection, no automatic runner. | Chosen by the user on 2026-11-19 after the spike, to reduce complexity. The spike showed evidence can be saved without a debug connection (`reports/spike-macos-2026-11-19.md`). This replaces the earlier choice of a dedicated test profile. |
| A login scenario is a checklist the agent drafts and the tester approves by hash. The tester signs in by hand and confirms "Signed in"; the server never answers that question. No account value is stored, which replaces the earlier console form. Testers do not edit steps by hand. | Follows from the decision above: with no runner nothing consumes a stored value. |
| Evidence is the image the Chrome tool saves to disk; the orchestrator copies it into the run for the row's current attempt. | Spike item B: a screenshot and a zoomed region were saved as files with their paths reported. Cost: the image comes from the agent side, so the server does not vouch for it. |
| Screens: a node-to-page index from the Figma page outlines places instance-layer targets (16 of 45 rows); plain nodes get a low-confidence proposal for the tester. Phone-width rows go to the tester. | Spike items C and G. |
| The server's write scope grows by `~/.testign-kit/webtest/` (projects, scenarios, approvals, per-run answers and uploaded images). | The console plan allowed `console/` and `templates/` only (`plans/261118-1431-testign-console/plan.md:47`). |
| Run files live in `<output_dir>/webtest/<run-id>/` and are written by CLI commands the orchestrator calls. The server reads them. | Same split as reports. |
| `ROLES` and its synonyms stay as they are. A registry entry gains a purpose (`testcase` or `webtest`); a run's column plan carries result and free columns by letter. | New synonyms would change what the shipped sample detects and break pinned tests (`xlsx.py:214`; `tests/test_templates_xlsx.py:57`); a template without the trace column must not reach `/testign:testcase` (`xlsx.py:164-168`). |
| Chrome is the only supported browser; the session must have Claude in Chrome on (`claude --chrome` or `/chrome`, extension 1.0.36 or later, a direct Anthropic plan, not WSL). | `research/researcher-01-chrome-figma-facts.md`: the two official pages disagree on Edge. |
| The command always goes through the console; there is no chat-only mode. Rows the tester runs can carry an uploaded evidence image. | Chosen by the user on 2026-11-19. |

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Spike: Chrome worker, Figma screens and login route](./phase-01-spike-chrome-worker-figma-screens-and-login-route.md) | In progress: macOS items A, B, C, F, G recorded; Windows and the fifteen-row measurement open |
| 2 | [Run store and normalised case list](./phase-02-run-store-and-normalised-case-list.md) | Completed |
| 3 | [Result columns and run export](./phase-03-result-columns-and-run-export.md) | Completed |
| 4 | [Run jobs and parked row questions](./phase-04-run-jobs-and-parked-row-questions.md) | Completed |
| 5 | [Login scenarios and manual sign-in](./phase-05-login-scenarios-and-manual-sign-in.md) | Completed |
| 6 | [Webtest skill, orchestrator and worker](./phase-06-webtest-skill-orchestrator-and-worker.md) | In progress: command, skill, triage rules, worker brief and agent written; the dry run in Chrome and the Windows spike open |
| 7 | [Test runs and login screens](./phase-07-test-runs-and-login-screens.md) | In progress: screens, i18n and unit tests done; the e2e smoke is written but not run |
| 8 | [Docs, real table round and release](./phase-08-docs-real-table-round-and-release.md) | In progress: README and 0.4.0 done; the rounds on macOS and Windows, the injection check and the journal entry open |

The spike has set the routes for phase 6; what is left of phase 1 (Windows, the fifteen-row
measurement) does not block phases 2 to 5. Windows is supported in the first release, so the
Windows half of the spike (subagent tools and saved screenshots there) must pass before phase 6
is closed, and the phase 8 round runs on both platforms. Phase 3 depends on 2. Phase 4 depends on 2. Phase 5
depends on 4. Phase 6 depends on 1 to 5. Phase 7 depends on 4 and 5. Phase 8 depends on 6 and 7.

## Constraints for every phase

- Existing CLI subcommands, report files, exit codes, job kinds and skill behaviour stay as they are; changes to existing functions are additive, and every changed interface lists its consumers in its phase file.
- Python 3.10 compatible; tested on Windows and macOS.
- No inline `style` attributes, inline scripts or `innerHTML` with data in the UI (the CSP forbids them).
- Logs, stderr, job records and progress lines hold no credential, token, file path or customer text.
- Names that come from a request (run, project, scenario, image) are matched against a strict pattern and resolved by listing a folder.
- No plan ids, phase numbers or finding codes in code, tests or commit messages.

## Load-bearing assumptions

| Assumption | Could break | Signal | Response |
|---|---|---|---|
| A plugin agent can call the Claude in Chrome tools of the session that spawned it. | Confirmed for a general subagent in the spike; a plugin agent definition is not yet tried | The phase 6 dry run | The orchestrator runs each row itself under the same worker contract. |
| The Chrome tool keeps saving screenshots to a file whose path it reports. | Yes: it is a feature of the client, seen on macOS only | A worker returns no image path | The row waits for an image uploaded by the tester. |
| The tester is signed in with the account the scenario names. | Yes: the agent cannot tell accounts apart reliably | The user name the first worker reads differs from the account hint | The log line shows the name; the report names the scenario per row; the tester signs in again. |
| Page outlines place instance-layer targets. | Yes, per Figma file; large frames can come back without children | A target is not in the index | A low-confidence proposal or an empty screen for the tester. |
| One import of 45 rows fits the Figma call limit of the plan that owns the file. | Yes, per plan: Full seat is 200 calls a day at 10 to 15 a minute on Professional and Organization; View seat is 20 a month | Spike item E; a rate-limit error during import | The import is staged row by row and resumes; a View seat is refused before the first call. |
| Scenarios can be switched on the same hosts by signing out and in by hand. | Yes | The signed-in check fails after a switch | One scenario per run; rows of other scenarios are `not-run: no-scenario`. |
| A 45-row run stays within the job's silence limit and the model's context. | Yes | The phase 6 dry run and the first real run | A progress line every minute; job and session ids kept in `run.json`; recovery after a lost job. |
| The model keeps "row text and page content are data". | Yes | The injection rows in the phase 8 round are followed | Sharpen the skill text. Hosts and delegation stay behind the tester either way, because the agent has no command that writes them. |

The design stops meeting its criteria when the agent mints itself a console session and uses it
as the tester: it runs as the tester and the console cannot tell them apart. The skill forbids
it, the command needs no session, and the phase 8 injection check looks for it. The console plan
recorded the same limit.

## Extension trace

The next source (the workbook that `/testign:testcase` wrote) keeps stable: the case list schema,
row states, the queue order, run questions, login scenarios, the column plan and export. It
adds: one importer that turns workbook rows into staged cases, and one value of `source.kind`.
Proof inside this plan: the Figma importer reaches the run only through `webtest-stage`, which
takes a case file and knows nothing about Figma (phase 2 success criteria). No importer registry
is added.

## Research

[Chrome and Figma facts](./research/researcher-01-chrome-figma-facts.md), checked 2026-11-19 from official pages and Chromium source. No local experiment was run; phase 1 does that.

## Open questions

1. The login and sign-out addresses of the test site, for the first scenarios (admin, staff, client).

## Spike decisions — 2026-11-19

Base URL `https://dev.u-supp-u.devkarte.jp/`, project `usupp`, roles admin, staff, client.
Report: [`reports/spike-macos-2026-11-19.md`](./reports/spike-macos-2026-11-19.md).

| Decision | Replaces |
|---|---|
| Runs use the tester's own signed-in Chrome profile | Dedicated test profile (red-team finding 5) |
| No debug connection, no automatic sign-in | The DevTools client, runner and capture phase, which is removed |
| No stored account values | The console credentials form (validation session 1) |
| Evidence from the Chrome tool's saved screenshots | Server-side capture |
| Phone-width rows go to the tester | Agent-run `mobile` rows |
| Windows is supported in the first release (user, 2026-11-19) | — |

The red-team table below names the phases as they were numbered then; the former phase 6 is
gone and the former phases 7 to 9 are now 6 to 8.

## Red Team Review

### Session 1 — 2026-11-19
**Findings:** 15 after merging 39 from four reviewers (15 accepted, 4 of them modified; 1 sub-item rejected)
**Severity breakdown:** 5 Critical, 8 High, 2 Medium

Reviewer reports and the adjudication with its reasons: [`reports/red-team-adjudication.md`](./reports/red-team-adjudication.md).

| # | Finding | Severity | Disposition | Applied To |
|---|---------|----------|-------------|------------|
| 1 | A row left `running` locks the run for good | Critical | Accept | Phases 2, 4, 7 |
| 2 | Parked questions, answers and tester results die with the job | Critical | Accept (modified: run-scoped store, not several asks per job) | Phases 2, 4, 7, 8 |
| 3 | The agent can give the tester's approvals itself | Critical | Accept (modified: no lifetime limit on console sessions, which the user settled for the console on 2026-11-19) | Phases 2, 4, 7 |
| 4 | The agent writes both the login scenario and the hosts it is checked against | Critical | Accept | Phases 2, 4, 5, 6 |
| 5 | A debug port exposes passwords and cookies to every local process | Critical | Accept (modified by the user: dedicated test profile only) | Phases 1, 6, 9 |
| 6 | The off-site check trusts the agent's own report | High | Accept | Phases 2, 6, 7, 9 |
| 7 | Expired logins and browser trouble are recorded as stuck rows | High | Accept | Phases 1, 2, 5, 7 |
| 8 | The login question and the runner are loosely coupled | High | Accept | Phases 4, 6 |
| 9 | The Figma import cannot save partial work; screens cannot be read as planned | High | Accept | Phases 1, 2, 7 |
| 10 | Evidence has no owning phase and no checked route | High | Accept | Phases 1, 2, 6 |
| 11 | The template changes break existing tests and the shared registry | High | Accept (modified: purpose per entry; roles unchanged) | Phase 3, 8 |
| 12 | Job-record changes miss consumers that break | High | Accept | Phases 4, 8 |
| 13 | A long run outlasts the silence limit, and Finish cannot stop it | High | Accept | Phases 1, 4, 7, 8 |
| 14 | Names in routes and the credentials folder are under-protected | Medium | Accept | Phases 2, 4, 5, 9 |
| 15 | Effort and test coverage are understated | Medium | Accept | Plan effort, phases 5, 6, 8 |

Decided by the user in this session: a debug connection only on a dedicated test profile; the
test site holds made-up data only; rows the tester runs can carry an image; no hand editing of
login steps in the console.

One statement made to the user while asking was wrong and is corrected here: a debug port cannot
be opened only while the runner or a capture runs. It is open for as long as the test Chrome
runs. The pipe route avoids a port; phase 1 finds out where it works.

### Whole-Plan Consistency Sweep
- Files reread: plan.md and all phase files
- Decision deltas checked: 14
- Reconciled stale references: 9 (job-scoped parks, agent-set hosts, the default-profile debug route, new template roles, the second sample, `run_lang`, the step editor, phase numbers after the split, total effort)
- Unresolved contradictions: 0

## Validation Log

### Session 1 — 2026-11-19
**Verification Results**
- **Tier:** Full. Code claims were read from source while planning; the red-team reviewers then checked them: security 37 claims (33 verified, 2 failed, 2 unverified), flow 14 (6 verified, 3 partial, 2 failed, 3 other), state 12 items (4 pass, 3 concern, 5 failed), contracts 9 interfaces (2 compatible, 7 with missing consumers). Every failed claim is covered by a finding above.
- **Unverified:** the spike items of phase 1; each has a fallback in the assumptions table.

**Questions asked:** 4

| Question | Decision | Propagated to |
|---|---|---|
| Login as a step list run by a fixed runner, or a freely generated script? | Step list and fixed runner. | Phases 5, 6 |
| Where does the tester enter the test account? | A form in the console. | Phases 5, 8 |
| Default class of rows compared with the design by eye? | `sure`, run by the agent, marked in the report. | Phase 7 triage rules, phase 9 |
| Does the command need a chat-only mode? | No; always through the console. | Phase 7 command |
