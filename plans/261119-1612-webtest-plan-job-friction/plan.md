---
title: "Web test plan job: remove the friction found in the USUPP round"
description: "Six fixes for what slowed or broke the first real webtest-plan round on 2026-11-19: copying an import between runs, reading the Figma table in one call, the too-new console tab, silently dropped review answers, the export cover and captures, and plugin update docs."
status: in-progress
priority: P1
effort: 4.25d
branch: claude/test-figma-design-template-b0daea
tags: [bugfix, feature, frontend, backend, docs]
blockedBy: []
blocks: []
created: 2026-11-19
---

# Web test plan job: remove the friction found in the USUPP round

## Overview

The first real `webtest-plan` round (USUPP table `6647:118139`, 45 rows, 2026-11-19) finished, but
it took three plan jobs and hand-written shell loops. The evidence is in this session's console log
(`~/.testign-kit/console/server.log`: five `403 session-too-new` at 22:10–22:11) and in the runs
`W20261119-2153`, `-2213` (no captures) and `-2215` (complete). The capture-dropping bug in
`webtest-stage` is already fixed (`d08e4cd`, PR #5); this plan covers the rest.

## Contract

- **Outcome:** a plan job that has to be queued again reuses the earlier import (and an
  unconfirmed triage draft) with one command; a Figma table is read with one design-context call
  when it fits; when no console tab can answer a job the agent learns it at claim time and
  re-queues, and a tab that cannot answer says so instead of offering a form; the review table
  refuses what it cannot apply and nothing the tester cannot clear; the exported workbook has no
  template placeholders left and links each row to its capture; the README says how to update the
  installed plugin.
- **Constraints:** keep every safety rule (the tester signs in by hand, the agent never mints a
  console session, a tab must be older than the web job it answers); runs written by 0.5.0 load
  and export unchanged; UI strings in vi, en and ja; dependencies stay `openpyxl` only unless the
  validation step accepts another.
- **Non-goals:** changing the tab-age rule itself; a console button that re-queues a job (the
  agent re-queues); driving the Figma REST API; pixel diff of captures; the testcase (`xlsx-fill`)
  export, except a shared placeholder helper if one falls out naturally.
- **Acceptance criteria:**
  1. `webtest-new --from-run <r>` gives the job's run every staged row, capture and
     `page-index.json` of `<r>`, plus its triage draft when that import was complete and
     unconfirmed; a bad `--from-run` is refused before any run exists, and rows without a
     capture are reported.
  2. `webtest-table` turns one saved `get_design_context` output of a change table into staged
     rows numbered by `No`, each staged once with its capture; only Figma asset URLs are offered
     for download; the skill tries it first and falls back to the per-row reads.
  3. With no browser session older than the job, `console claim` and held calls fail with
     `no-older-tab` and the agent re-queues before any Figma or Chrome work; the UI shows a notice
     instead of answer controls exactly when the server would refuse (`can_answer`), also on the
     run screen.
  4. An explicit `runner` edit on a `not-web` row and a `mobile_method` edit on a `pc` row are
     refused by the UI, the server and `webtest-plan`; inherited agent values never cause a
     refusal (mobile→pc and sure→not-web edits confirm).
  5. The exported workbook has no `<...>` placeholder of the sample template left (tester taken
     from the run), and each row with a capture links to it from its `No` cell, also for runs
     confirmed under 0.5.0; the Markdown report links captures too.
  6. README has an "Update the plugin" section with commands checked against current Claude Code
     docs.
  7. Python tests, UI unit tests and e2e console tests pass.

## Phases

| # | Phase | Effort | Depends on |
|---|---|---|---|
| 1 | [Copy an import between runs](phase-01-copy-import-between-runs.md) | 0.75d | none |
| 2 | [Read the Figma table in one call](phase-02-read-the-figma-table-in-one-call.md) | 1d | 1 |
| 3 | [Console tab age warning](phase-03-console-tab-age-warning.md) | 1d | none |
| 4 | [Review table rules without silent drops](phase-04-review-table-rules-without-silent-drops.md) | 0.5d | 3 |
| 5 | [Export cover and captures](phase-05-export-cover-and-captures.md) | 0.5d | none |
| 6 | [Plugin update docs and verification](phase-06-plugin-update-docs-and-verification.md) | 0.5d | 1–5 |

Phases 1→2 share `cli.py` and `skills/webtest/SKILL.md`; 3→4 share `console/jobs.py`, the console
UI, i18n and `console-bridge.md`; phases 1, 4 and 5 all edit `scripts/testign/webtest.py`
(different functions) and 3 also edits `skills/webtest/SKILL.md`. Run them in the order
1 → 2 → 3 → 4 → 5 → 6, or in parallel only with one owner per shared file.

## Risks

- The Figma MCP output format (JSX with `data-node-id` / `data-name`) is not a published contract:
  the table helper must fail loudly on an unknown shape, and the per-row path stays.
- Capture URLs come from designer-controlled output: only `https` Figma asset hosts are offered,
  downloads stay with `curl` (no Python fetch), with no redirects and a 20 MB cap.
- The agent could mint a console tab and then queue a job it may answer (existing gap, forbidden
  by the rules); auto re-queue adds no capability, and `queued_after` plus the new-tab
  announcement make a re-queue visible.
- Capture links are relative to the run folder: a workbook moved alone loses them (accepted; no
  Pillow dependency).

## Validation Log

### Session 1 (2026-11-19)

Verification: claims checked against source by a scout pass and spot reads (`webtest_export.py`
has no ticket handling; `_initial_state` forces `runner: none` on not-web rows, webtest.py:596;
`_review_answer` drops `emulation` on pc, jobs.py:345; UI tests run with
`node --test "scripts/testign/console/ui/tests/*.test.mjs"`, test.yml:37). Failed: 0.

| Question | Decision | Propagated to |
|---|---|---|
| How does the workbook show a row's capture? | Relative link, no Pillow (Red Team Session 1: on the `No` cell instead of a new column) | Phase 5 |
| What does the agent do when a tab newer than the job was refused? | Fail the job with the reason and queue it again at once (`--from-run` copies the import and an unconfirmed triage draft) | Phase 3; Red Team Session 1 moved detection to claim time |
| Runner on not-web / method on pc in the review answer? | Disable in the UI and refuse in the server and `webtest-plan` | Phase 4 (already written so) |
| Version bump? | 0.5.1 | Phase 6 |

## Red Team Review

### Session — 2026-11-19
**Reviewers:** Security Adversary, Failure Mode Analyst, Assumption Destroyer, Scope & Complexity
Critic (38 raw findings, deduplicated to 15).
**Findings:** 15 (14 accepted, 1 kept as the user's decision with mitigations)
**Severity breakdown:** 1 Critical, 11 High, 3 Medium

| # | Finding | Severity | Disposition | Applied To |
|---|---|---|---|---|
| 1 | Hiding the form means no answer is ever refused, so the agent is never told (and the notice lied) | Critical | Accept: detect "no older tab" on the server at claim and in held calls | Phase 3 |
| 2 | Recording a refusal before the ask/ask_id checks (500 on `ask` None, stale ids, answer vs refusal) | High | Accept: detection no longer depends on refusals; answers always win | Phase 3 |
| 3 | `{answers: null, refused_tab}` reuses "call again"; webtest skill steps not updated | High | Accept: `409 no-older-tab`; webtest step 8 and sign-in | Phase 3 |
| 4 | The race is noticed only at the review table, after all the work | High | Accept: check at `console claim` | Phase 3 |
| 5 | UI compares second-precision ISO strings with float rules, in a payload the ask views do not read; run screen not covered | Medium | Accept: server-computed `can_answer`/`can_act` from one helper | Phase 3 |
| 6 | Auto re-queue turns an agent-minted tab into a sanctioned re-queue | High | User kept auto re-queue; added `queued_after`, chat notice, Risks entry | Phase 3, plan Risks |
| 7 | `--from-run` attaches the run before validating, so a bad id strands the job; wrong error-code claim | High | Accept: validate first, idempotent copy, "no such run" | Phase 1 |
| 8 | `--from-run` copies only the import; the triage draft is redone | High | Accept: re-apply an unconfirmed triage draft | Phase 1 |
| 9 | Copying a capture-less run silently; `find_source` cannot tell; "no test" claim false | High | Accept: `captures` in `find_source`, `missing_captures` reported, facts fixed | Phase 1 |
| 10 | `--download`/urllib fetch of unchecked URLs from untrusted output; capture-less staging | High | Accept: no Python fetch, Figma-host allowlist, `--urls` then `--captures` | Phase 2 |
| 11 | How a 204 KB result reaches disk; header/order assumptions; hostile text; collision with staged rows | High | Accept: tool-results path, order by `No`, skip staged rows, hostile fixtures | Phase 2 |
| 12 | Final-line refusals block mobile→pc and sure→not-web edits the tester cannot clear; missing consumers | High | Accept: UI sends normalized values, refuse explicit edits only, `triage()` rule, `job-actions.mjs`, bridge table | Phase 4 |
| 13 | A Capture column misses confirmed runs and needs UI/i18n/xlsx changes | High | Accept: hyperlink on the `No` cell at export | Phase 5 |
| 14 | `<tester>` has no source; placeholder values unguarded; capture path unvalidated | Medium | Accept: `run.tester` from `recover()`, string writes with formula guard, `capture` validated, link from the row id | Phase 5 |
| 15 | Updating while a 0.5.0 console runs mixes versions; README pins the version | Medium | Accept: stop/start in the update steps, `README.md:8` in the bump | Phases 4, 6 |

Rejected: none. Not applied: configurable header synonyms for other table layouts (no second real
table yet; unknown layouts take the per-row path).

### Whole-Plan Consistency Sweep
- Files reread: plan.md, phase-01 … phase-06
- Decision deltas checked: 9 (claim-time detection and `no-older-tab`; `can_answer`/`can_act`;
  `--from-run` validation, idempotence and triage carry-over; `find_source.captures`; no Python
  download and the `--urls`/`--captures` split; order by `No`; explicit-edit refusals; capture
  link on `No` and `run.tester`; README version pin and restart on update)
- Reconciled stale references: 3 (Validation Log capture row, Validation Log re-queue row,
  parallel-execution note)
- Unresolved contradictions: 0

## Execution Log

### 2026-11-20
- Phases 1–5 implemented and tested; phase 6 done except the browser e2e suite and the live USUPP
  re-run with the console (both need the tester's machine: Playwright is not installed here, and the
  live run needs Figma, Chrome and a signed-in tester).
- Checked on copies of the real runs: `--from-run` of `-2215` gives 45 rows, 45 captures and the page
  index (no triage carried, by design: that run's plan is confirmed); `-2213` reports 45 missing
  captures; the saved USUPP design context parses to the same 45 rows as `-2215`; re-exporting
  `-2215` leaves no placeholder and links all 45 `No` cells to existing captures.
- Code review fixes: the `no-older-tab` re-queue happens once, and `console queue` refuses
  `queued_after` with `no-tab` when the console has no tab at all (a loop would prune job history);
  `webtest-table` refuses row-id collisions before staging, stages rows without an image, offers
  staged rows that lack a capture; capture URLs are limited to plain path characters (they go into
  a quoted `curl` argument); the table must be the run's node or inside it; JSX attribute entities
  are decoded; a canvas-order fallback is reported as `numbered_by: canvas`; deep nesting is refused;
  a case's `capture` must be its own row's file.
