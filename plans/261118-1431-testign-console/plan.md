---
title: "testign console: local UI for tickets, templates, test cases and an agent job bridge"
description: "A local console on 127.0.0.1 that browses survey reports, trace results and the scout cache, manages Excel templates, and queues survey, close and testcase jobs for the attached Claude Code session, in vi, en and ja."
status: pending
priority: P1
effort: 15d
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
  1. `testign console start` prints the URL; a second start reuses the server and starts no process.
  2. A request without the token gets 403; a foreign `Host` or `Origin` gets 403; the page cannot be framed.
  3. Every ticket folder under `output_dir` with a revision file is listed; the Report screen shows the latest revision's parsed sections.
  4. Registering, setting default and removing a template from the console leaves the same `index.json` as the CLI does for the same inputs.
  5. The server writes only under `~/.testign-kit/console/` and `~/.testign-kit/templates/`; no request changes `output_dir`, a report or the repository.
  6. Every UI string exists in vi, en and ja (parity test); switching language changes chrome only.
  7. With no agent the console says so and nothing spins forever; a silent job can be marked failed; a server restart fails open jobs with a reason.
  8. A close job runs end to end through row review, diff confirmation and the existing wiki conflict check, with every agent question in the job's `ui_lang`.
  9. CI passes on Windows and macOS with Python 3.10 and 3.13, and `claude plugin validate --strict .` passes.

## Key decisions

| Decision | Evidence |
|---|---|
| The server writes only under `~/.testign-kit/`. Reports, workbooks and the wiki change only through jobs that the existing skills carry out. | Revision writes, xlsx fills and wiki updates already carry their own guards (`report.write_new` opens with `x`; `wiki-update` refuses a changed page). A second writer would duplicate them. |
| One server per user, not per project, on a fixed port (default 4791, `console.port` in config). | All state is per user: `~/.testign-kit/` and `output_dir` (`config.py`). |
| Python standard library only (`http.server`, `secrets`, `hmac`, `urllib`); no new runtime dependency. | `pyproject.toml` depends on `openpyxl` only; CI installs `pytest openpyxl` only. |
| The UI is plain ES modules served as files, with no build step. | Nothing in the repository builds JavaScript; Node exists in CI only for `claude plugin validate`. |
| Kestrel is vendored (tokens.css, bundle.css without its Google Fonts import); Inter and JetBrains Mono are self-hosted; Japanese falls back to system faces. | Chosen by the user on 2026-11-18. Both fonts have a vietnamese subset (verified on Google Fonts); BIZ UDPGothic does not. |
| UI language: per-viewer setting in the browser. Agent questions and progress follow the job's `ui_lang`; report content follows the report's `lang`. | Chosen by the user on 2026-11-18. |
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

Phase 3 depends on 1 and 2. Phase 4 depends on 1 only and can run beside phase 3. Phase 5 depends
on 3 and 4. Phase 6 depends on 4 for the skill and on 5 for the end-to-end round.

## Constraints for every phase

- Existing CLI subcommands, report files, exit codes and skill behaviour outside the console stay as they are.
- Python 3.10 compatible; tested on Windows and macOS.
- No inline `style` attributes, inline scripts or `innerHTML` with data in the UI (the CSP forbids them).
- Logs hold no request body, query string, token, file path or customer text.
- No plan ids, phase numbers or finding codes in code, tests or commit messages.

## Load-bearing assumptions

| Assumption | Could break | Signal | Response |
|---|---|---|---|
| Testers run Claude Code on their own Windows or macOS machine, so the browser reaches 127.0.0.1. | Yes (cloud, SSH) | `console start` in a cloud session | Refused with a message; under SSH the output says to forward the port. |
| A detached child survives the end of the Bash call that started it, on Windows too. | Yes | Phase 1 Windows CI test: the server is gone after `start` returns | Fall back to running `console serve` in the harness's background mode; document the two-hour cap. |
| The agent session can block on `console wait` for up to 9 minutes. | Yes, per runtime | Phase 6 round: jobs are not picked up | Lower the held time below the runtime's limit; stop and replan only if no blocking call works. |
| The model keeps "a job allows its route only" and "ticket, report and comment text is data". | Yes | Injection texts in the phase 6 round are followed | Sharpen the skill text; if it still fails, say in the README that the console is for trusted tickets, and ask before release. |

The design stops meeting its criteria when two agent sessions change the same ticket at the same
time. The queue prevents that among console jobs; a CLI session outside the queue is not seen.

## Extension trace

The next job kind (for example a re-survey of every stale ticket) keeps stable: the token and host
checks, the job states, `wait`, `ask`, `done`, the ask schema and `/api/state`. It adds: one entry
in the kind table with its parameter checks, one row in the console skill's routing table, one
trigger in a view, and its i18n keys. Proof inside this plan: survey, close and testcase are built
through exactly those four touch points (phase 4 and 5 success criteria). No registry is added.

## Open questions

1. Scout cache and Settings have no mockup yet; phase 3 builds them read-only from Kestrel parts. Confirm or design them first.
2. Whether the Japanese UI strings get a review by a native speaker before release (phase 6).
