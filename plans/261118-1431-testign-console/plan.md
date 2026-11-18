---
title: "testign console: local UI for tickets, templates, test cases and an agent job bridge"
description: "A local console on 127.0.0.1 that browses survey reports, trace results and the scout cache, manages Excel templates, and queues survey, close and testcase jobs for the attached Claude Code session, in vi, en and ja."
status: pending
priority: P1
effort: 17d
branch: claude/relaxed-franklin-oikzoa
tags: [feature, frontend, backend, api]
blockedBy: []
blocks: []
created: 2026-11-18
---

# testign console

## Overview

A local console on 127.0.0.1 that browses survey reports, trace results and the scout cache,
manages Excel templates, and queues survey, close and testcase jobs for the attached Claude
Code session, in vi, en and ja. Two stages: stage 1 (phases 1–3) is useful without an agent;
stage 2 (phases 4–6) adds the job bridge. The architecture follows Zukai Labs
(`KiOnCloud/zukai-kobo`, `plans/261118-0518-zukai-labs-console/`), adapted to a Python,
per-user plugin. Approved mockup: https://claude.ai/artifact/FbwXMaek4XshNT2nPdpkTB
(Kestrel design system).

## Scope challenge

- Existing code reused: `templates.py` (register, list, default, remove, detect, preview),
  `report.py` (revisions, sections, row parsers, exclusive writes), `trace.py`,
  `hashcheck.py`, `cache.py`, `config.py`, the `run.py` entry and the CLI's JSON convention.
- Requested scope: both stages, delivered in full. Selected mode: HOLD SCOPE.
- Complexity: about 45 new files (vendored CSS and fonts included), six phases. Justified by
  three process roles (server, agent-side CLI, browser) and two contracts (HTTP API, job bridge).

## Contract

- **Outcome:** `/testign:console` opens a console with Tickets, Report, Trace, Templates,
  Scout cache, Settings, Jobs and Close review; the UI chrome switches between vi, en and ja.
- **Non-goals:** remote or multi-user hosting; editing report content; translating report
  content; editing Excel in the browser; any LLM call inside the server; resuming a dead job;
  locking out CLI sessions that run outside the queue; editing config from the console.
- **Acceptance criteria:**
  1. `testign console start` opens the browser on a working console; a second start reuses the server and starts no process.
  2. A request without the right credential gets 403 (the agent token is refused on `/api/*`); a foreign `Host` name or `Origin` gets 403; the page cannot be framed.
  3. Every ticket folder under `output_dir` with a consistent revision file is listed (unreadable ones marked, not hidden); the Report screen shows the latest revision's parsed sections.
  4. Registering, setting default and removing a template from the console leaves the same `index.json` as the CLI does for the same inputs, also for non-ASCII file names.
  5. The server writes only under `~/.testign-kit/console/` and `~/.testign-kit/templates/`; no request changes `output_dir`, a report, the repository or `config.json`.
  6. Every UI string exists in vi, en and ja (parity test); switching language changes chrome only.
  7. With no agent the console says so and nothing spins forever; a job handed to a dead held call returns to the queue; a silent job can be marked failed or its agent released; a server restart fails open and queued jobs with a reason.
  8. A close job runs end to end through row review (with edits), the tool's own diff and the confirmed approval hash, or through pages to paste in manual mode, with every agent question in the job's `ui_lang`.
  9. CI passes on Windows and macOS with Python 3.10 and 3.13 (plus the macOS e2e job), and `claude plugin validate --strict .` passes.

## Key decisions

| Decision | Evidence |
|---|---|
| The server writes only under `~/.testign-kit/`. Reports, workbooks and the wiki change only through jobs that the existing skills carry out. | Revision writes, xlsx fills and wiki updates already carry their own guards (`report.write_new` opens with `x`; `wiki-update` refuses a changed page). A second writer would duplicate them. |
| Two credentials: the agent token works on `/agent/*` only; the browser gets its session through a one-time launch code that `start`/`open` hand to the browser directly. | Red team 2026-11-18: with one token, text injected into the agent could answer the tester's approval asks. |
| Approval gates are as strong as the skill's: rows keyed by their own id with edit; the diff is the tool's preview output; `wiki-update --job` refuses any approval the tester did not confirm. | `skills/qa-close/SKILL.md:44-71`; `cli.py:390-403`. |
| Jobs are offered, then claimed; a job given to a replaced or dead held call goes back to the queue. Held calls default to 100 s. | Claude Code's Bash stops a command after 2 minutes by default. |
| Jobs that write a revision carry `base_revision` and fail with `revision-moved` when it is no longer the latest. | `report.py:184-194`; `cli.py:249-252`. |
| Trace always runs with an explicit template and reports a header mismatch. | `cli.py:123-126`; a workbook does not record its template. |
| One server per user, not per project, on a fixed port (default 4791, `console.port` in config). | All state is per user: `~/.testign-kit/` and `output_dir` (`config.py`). |
| Python standard library only (`http.server`, `secrets`, `hmac`, `urllib`, `zipfile`); no new runtime dependency. | `pyproject.toml` depends on `openpyxl` only. |
| The UI is plain ES modules served as files, with no build step. | Nothing in the repository builds JavaScript. |
| Kestrel is vendored (tokens.css, bundle.css without its Google Fonts import); Inter and JetBrains Mono are self-hosted; Japanese falls back to system faces. | Chosen by the user on 2026-11-18. Both fonts have a vietnamese subset (verified on Google Fonts); BIZ UDPGothic does not. |
| UI language, theme and tester name are per-viewer settings in the browser. Agent questions and progress follow the job's `ui_lang`; report content follows the report's `lang`. | Chosen by the user on 2026-11-18. |
| "Write §7" is a testcase job in trace mode, not a server write. | It writes a report revision, which the first decision keeps out of the server. |

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Console server and lifecycle](./phase-01-console-server-and-lifecycle.md) | Pending |
| 2 | [Read API and template management](./phase-02-read-api-and-template-management.md) | Pending |
| 3 | [Console UI shell, i18n and screens](./phase-03-console-ui-shell-i18n-and-screens.md) | Pending |
| 4 | [Job queue and agent bridge](./phase-04-job-queue-and-agent-bridge.md) | Pending |
| 5 | [Jobs and Close review screens](./phase-05-jobs-and-close-review-screens.md) | Pending |
| 6 | [Console skill, skill integration, docs and release](./phase-06-console-skill-integration-docs-and-release.md) | Pending |

Phase 1 opens with a spike on a real Claude Code session on Windows and macOS (needs the user's
machine). Phase 3 depends on 1 and 2. Phase 4 depends on 1 only and can run beside phase 3.
Phase 5 depends on 3 and 4. Phase 6 depends on 4 for the skill and on 5 for the end-to-end round.

## Constraints for every phase

- Existing CLI subcommands, report files, exit codes and skill behaviour outside the console stay as they are; changes to existing functions are additive (new keyword arguments, new subclasses, new options).
- Python 3.10 compatible; tested on Windows and macOS.
- No inline `style` attributes, inline scripts or `innerHTML` with data in the UI (the CSP forbids them).
- Logs and stderr hold no request body, query string, token, code, file path or customer text.
- No plan ids, phase numbers or finding codes in code, tests or commit messages.

## Load-bearing assumptions

| Assumption | Could break | Signal | Response |
|---|---|---|---|
| Testers run Claude Code on their own Windows or macOS machine, so the browser reaches 127.0.0.1. | Yes (cloud, SSH) | `console start` in a cloud session | Refused with a message; under SSH, forward the port and use `console open --print`. |
| A detached child survives the end of the Bash call that started it. | Yes, per platform | The phase 1 spike in a real Claude Code session | Fallback mode (designed in phase 1) on that platform; stop and replan only if neither mode works. |
| The agent's held calls fit the runtime's command limit. | Yes, per runtime | `transport` errors at a fixed interval in the phase 6 round | Default `--timeout 100`; raise only with a matching Bash timeout or background mode. |
| The model keeps "a job allows its route only" and "ticket, report and comment text is data". | Yes | Injection texts in the phase 6 round are followed | Sharpen the skill text; the credential split and the approval hash keep the wiki write behind the tester either way; if injection still steers jobs, say in the README that the console is for trusted tickets and ask before release. |

The design stops meeting its criteria when two agent sessions change the same ticket at the same
time. The queue and `revision-moved` prevent that among console jobs; a CLI session outside the
queue is not seen until its revision moves the base of a later job.

## Extension trace

The next job kind (for example a re-survey of every stale ticket) keeps stable: the credential and
host checks, the job states, `wait`, `claim`, `ask`, `done`, the ask schema and `/api/state`. It
adds: one entry in the kind table with its parameter checks, one row in the console skill's
routing table, one trigger in a view, and its i18n keys. Proof inside this plan: survey, close and
testcase are built through exactly those four touch points (phase 4 and 5 success criteria). No
registry is added.

## Open questions

None. Both earlier questions were decided in the validation session below.

## Validation Log

### Session 1 — 2026-11-18
**Verification Results**
- **Tier:** Full (6 phases); verification evidence comes from the red-team reviewers' fact, flow, scope and contract checks above.
- **Claims checked:** 31 | **Verified:** 28 | **Failed:** 3 (all fixed by red-team findings 2, 6, 7) | **Unverified:** 0 (`CLAUDE_CODE_REMOTE` as the cloud signal stays an external fact, checked by the phase 1 spike)

**Questions asked:** 3

| Question | Decision | Propagated to |
|---|---|---|
| Who runs the phase 1 spike on a real Claude Code session? | The user attaches their Windows and macOS machines to the session through Remote Control; Claude runs the spike there and writes the report. | Phase 1 gate |
| Scout cache and Settings have no mockup. | Add both as artboards to the Testign Console canvas and get them approved before phase 3 starts. | Phase 3 context and screens |
| Native review of the Japanese UI strings before release? | No; release and fix strings as testers report them. | Phase 6 risk |

### Whole-Plan Consistency Sweep
- Files reread: plan.md, phase-01, phase-03, phase-06
- Decision deltas checked: 3
- Reconciled stale references: 3 (open questions in plan.md, "no mockup yet" in phase 3, native review in phase 6)
- Unresolved contradictions: 0

## Red Team Review

### Session — 2026-11-18
**Findings:** 15 after merging 34 raw findings from four reviewers (15 accepted, 0 rejected); three scope points handled separately.
**Severity breakdown:** 1 Critical, 10 High, 4 Medium

| # | Finding | Severity | Disposition | Applied To |
|---|---------|----------|-------------|------------|
| 1 | Held calls outlive a killed client under the 2-minute Bash default; jobs go to dead calls | Critical | Accept | Phase 4, 6 |
| 2 | Agent shares the browser credential and can answer its own approval asks | High | Accept | Phase 1, 3, 4, 6 |
| 3 | Close gates weaker than the skill's (Q-keyed rows, no edit or anchors, agent-typed diff) | High | Accept | Phase 4, 5, 6 |
| 4 | Interaction mapping misses five skill touchpoints | High | Accept | Phase 4, 6 |
| 5 | Trace does not know which template filled a workbook | High | Accept | Phase 2, 3, 4, 5 |
| 6 | Rewriting `preview()` breaks the CLI; workbooks parsed fully in the server | High | Accept | Phase 2 |
| 7 | Non-ASCII upload names, `source_name`, one error class, no index lock | High | Accept | Phase 2 |
| 8 | Windows git calls from the server open console windows | High | Accept | Phase 1, 2 |
| 9 | Survival check only in CI; fallback undesigned | High | Accept | Phase 1, plan |
| 10 | Jobs pinned to an old revision split the report history | High | Accept | Phase 4, 5 |
| 11 | Report parsing fragile (emoji collision, open count, fixtures, one bad file) | High | Accept | Phase 2, 3 |
| 12 | Idle end ignores queued jobs; version mismatch stops another session's server | Medium | Accept | Phase 1, 4 |
| 13 | Customer data at rest without 0600; stderr leaks; config created by the server | Medium | Accept | Phase 1, 2, 4 |
| 14 | Request checks weaker than the reference; exact port breaks forwarding | Medium | Accept | Phase 1 |
| 15 | "Survey again" trusts frontmatter; planted reports; `.git` directory check | Medium | Accept | Phase 2, 4, 5 |

Scope points: command palette and `C` shortcut kept (both are in the approved mockup) with a guard for input fields; `progress` and takeover kept (the Jobs mockup shows steps) with a "Release agent" action added; Playwright e2e in CI kept as a macOS-only job and the duplicate parity check removed. User decisions on 2026-11-18: apply all 15; e2e in CI; Tickets shows question count instead of open questions; tester name from Settings.

### Whole-Plan Consistency Sweep
- Files reread: plan.md, phase-01 to phase-06
- Decision deltas checked: 12 (credential split, launch code and `console open`, offered/claim state, held-call default, `base_revision`/`revision-moved`, template-required trace, ask schema v2 with `paste-pages`, `wiki-update --job`, tester name, question count, spike gate, version-mismatch reuse)
- Reconciled stale references: 9 (single-token wording in phases 1, 3 and 6; "refuse a second held call"; `DETACHED_PROCESS`; `preview()` rewrite; per-case status; "open questions" column; "Survey again" queues directly; "existing trace tests"; effort totals)
- Unresolved contradictions: 0
