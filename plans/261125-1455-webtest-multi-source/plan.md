---
title: "Web test: reusable suites from many sources, and the console redesign"
description: "Split a reusable test suite (cases from Figma, a Backlog survey report, Excel or by hand) from a run, behind one source registry, and rebuild the console as three menu groups on the Yohaku design system in English and Japanese."
status: in-progress
priority: P1
effort: 11d
branch: claude/usuppu-testing-kit-console-649776
tags: [feature, frontend, backend, docs]
blockedBy: []
blocks: []
created: 2026-11-25
---

# Web test: reusable suites from many sources, and the console redesign

## Overview

Testers asked to generate web test cases from a Backlog ticket (example CKWEB-3366, which has source
code) and run them, next to the Figma change table that works today. Today a run owns its own case
list and only Figma can fill it (`SOURCE_KINDS = ("figma", "workbook")`, `webtest.py:89`; nothing
creates `workbook`). This plan adds a **suite**: a case list kept apart from runs, filled from one
source through a registry, edited in the console, then run any number of times. The console is
rebuilt around it, following the mockup the user approved on 2026-11-25:
[mockup/console-redesign.html](./mockup/console-redesign.html).

## Contract

- **Outcome:** a tester creates a suite in four steps (source, input, details, review) from Figma,
  a Backlog survey report, an Excel file or nothing; the agent writes the cases for Figma and
  Backlog; the tester edits, adds, deletes and confirms cases; a run copies a confirmed suite onto
  one environment and runs as today. The console has three groups: Test case design (Test suites,
  Ticket survey), Test runs (Runs, Agent & jobs), Settings (Projects & hosts, Login scenarios,
  Templates, Scout cache, Preferences). It uses Yohaku, speaks English by default and Japanese on
  request, uses tables that scroll sideways with tall rows, and shows statuses as icons whose meaning
  appears on hover.
- **Constraints:** keep every safety rule (the tester signs in by hand, the agent stays inside the
  run's hosts, a console tab must be older than the job it answers); runs written before this plan
  load, show and export; Python stays on `openpyxl` only; the UI stays vanilla ES modules with no
  build step; the static asset test (`tests/test_console_ui_assets.py`) keeps passing.
- **Non-goals:** turning old runs into suites; a theme toggle in the top bar; changing the report
  language (`config.lang`, `report_lang`), which may still be Vietnamese; any source beyond the four
  named; syncing a suite back into Backlog or Figma.
- **Acceptance criteria:**
  1. A Backlog suite made from `CKWEB-3366-survey-r2.md` has every B* and R* row covered by at least
     one case with a matching trace, and the Source tab shows any row left without a case.
  2. A Figma suite holds the same cases a `webtest-plan` import would have produced for the same node.
  3. An Excel suite reads a file with a registered test case template and needs no agent job.
  4. A run made from a confirmed suite keeps its own copy: editing the suite afterwards leaves the
     run unchanged, and the run's export lists the suite name and each case's trace or Figma node.
  5. The console has no Vietnamese UI text, no `vi.json`, and defaults to English; switching to
     Japanese changes every screen.
  6. `python -m pytest`, `node --test "scripts/testign/console/ui/tests/*.test.mjs"` and
     `claude plugin validate --strict .` pass on macOS and Windows in CI.

## Decisions taken with the mockup

The user approved the mockup with these defaults: the case library is called **Test suites**;
**Ticket survey** sits under Test case design; **Settings** is the last group; a Backlog source
**requires** a survey report.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Source registry and suite store](./phase-01-source-registry-and-suite-store.md) | Completed |
| 2 | [Runs from suites](./phase-02-runs-from-suites.md) | Completed |
| 3 | [Console API and jobs](./phase-03-console-api-and-jobs.md) | Completed |
| 4 | [Skills and bridge docs](./phase-04-skills-and-bridge-docs.md) | Completed |
| 5 | [Yohaku, English and Japanese](./phase-05-yohaku-and-english-japanese.md) | Completed |
| 6 | [Test case design screens](./phase-06-test-case-design-screens.md) | Completed |
| 7 | [Test run and settings screens](./phase-07-test-run-and-settings-screens.md) | Completed |
| 8 | [Docs and verification](./phase-08-docs-and-verification.md) | In progress |

Phases 1 → 2 → 3 → 4 are the backend chain. Phase 5 depends on nothing and can run beside 1–4.
Phase 6 needs 3 and 5; phase 7 needs 4 and 6 because it retires `webtest-plan` together with the
run form that still posts it. Phase 8 closes. Eight phases exceed the usual three because the work
crosses storage, API, agent skills, design system and UI; each phase ends with green tests.

## Dependencies

- Survey parsers `report.behavior_rows`, `regression_rows` (`report.py:153-177`) and the covered-set logic
  in `trace.py:10-26` for Backlog cases and coverage.
- Freshness `hashcheck.check` (`hashcheck.py:28-73`) via `readapi.hash_status` for survey icons.
- Template layout detection (`templates.detect_layout`, `templates.resolve`) under a new Excel
  case-row reader, and the capped upload path of `templates_api.py`, for the Excel source.
- Yohaku files copied from qingyi lab in [mockup/ds/yohaku/](./mockup/ds/yohaku/).

## Validation Log

### Session 1 — 2026-11-25
**Trigger:** `/ak-plan validate` before implementation. The user asked to approve every finding, so
each question below took its recommended option without an interview.
**Questions asked:** 6 (answered by the user's blanket approval)

### Verification Results
- **Tier:** Full (8 phases), two independent reviewers (phases 1–4 and 5–8)
- **Claims checked:** 102
- **Verified:** 85 | **Failed:** 12 | **Unverified:** 5 (Kestrel `LOCK.json` and vendor CSS, which a
  local hook blocks from being read; `CKWEB-3366-survey-r2.md`, which lives in the tester's output
  folder, not the repo; `claude plugin validate` and the Windows CI run, which need execution)

#### Failures (all corrected in the phase files)
1. [Fact Checker] `templates.py` has no case-row reader; Excel import needs a new reader on
   `detect_layout` / `resolve` (`templates.py:178, 315`). Phase 1.
2. [Fact Checker] Hash route is `readapi.py:544`, handler `517-521`. Phase 3.
3. [Fact Checker] Report frontmatter keys are `report.py:14-25`. Phase 1.
4. [Flow Tracer] Freshness values are `same | moved_no_impact | stale | unknown` (reason `busy`). Phases 3, 6.
5. [Flow Tracer] Active jobs already fail with `server-stopped` at startup (`jobs.py:725-737`); only
   queued `webtest-plan` jobs need a new `retired-kind` reason. Phase 7.
6. [Flow Tracer] No version 1 run fixture exists; one is now stored first. Phase 2.
7. [Flow Tracer] `new_run` is not used for suite runs, so its `ui_lang` edit was dropped. Phase 2.
8. [Fact Checker] No `#/review` route; the hashes are `#/jobs/:id/review` and `#/jobs/:id/review-table`
   (`router.mjs:47-48`). Phase 6.
9. [Fact Checker] Language radio is `shell.mjs:96-101`. Phase 5.
10. [Flow Tracer] The mockup has no theme control, contrary to "per the mockup". Phases 5, 7.
11. [Contract Verifier] Views slated for deletion are still imported (`run.mjs:11, 13`, `jobs.mjs:10`,
    `runs.mjs:7` and three tests). Phases 6, 7.
12. [Contract Verifier] The asset test keys fonts on Inter and JetBrains Mono only
    (`test_console_ui_assets.py:108-115, 130-131`). Phase 5.

#### Questions & Answers

1. **[Architecture]** A run made from a suite has no review step, but export needs `columns`. How are they set?
   - Options: `first_guess` + `check_columns` at creation, editable later (Recommended) | keep a review-table ask in the run job
   - **Answer:** `first_guess` at creation, editable on the run page
   - **Rationale:** keeps run creation free of an agent step, which is the point of the suite split.
2. **[Architecture]** `_check_source` accepts only text or numbers, but a case may trace several rows. Where does `trace` live in a run?
   - Options: text inside `source` such as `"B4,R1"` (Recommended) | widen `_check_source` to lists | new top-level case key
   - **Answer:** text inside `source`; the suite keeps a list
   - **Rationale:** no change to the strict run schema beyond the version bump.
3. **[Tradeoffs]** Rename the export `target_node` field to `trace`?
   - Options: add `trace`, keep `target_node` for legacy runs (Recommended) | rename
   - **Answer:** add `trace`, keep `target_node`
   - **Rationale:** legacy runs store `target_node` in their columns and `check_columns` rejects unknown fields.
4. **[Scope]** When is `webtest-plan` retired, and what happens to the Figma re-import helpers?
   - Options: retire in phase 7 with the run form, and remove `copy_import`, `new_run_from`, `find_source`, `webtest-find`, `--from-run` and the run-targeted import commands (Recommended) | retire in phase 3 | keep the helpers for legacy runs
   - **Answer:** retire in phase 7 and remove the helpers; keep `webtest-recover`, `webtest-run` and export
   - **Rationale:** the console run form posts `webtest-plan` until phase 7, and the helpers only serve the run-owned import.
5. **[Assumptions]** The mockup has no theme control, but the console saves a light/dark choice today. Keep it?
   - Options: keep a light/dark control in Preferences as an explicit addition (Recommended) | honour the saved value with no control
   - **Answer:** keep it in Preferences, with the tester name
   - **Rationale:** dropping it would remove a current feature the user did not ask to remove.
6. **[Risks]** Japanese text relies on system fonts because Yohaku ships Noto Sans Latin only. Bundle Noto Sans JP?
   - Options: rely on system fonts and document the Linux gap (Recommended) | bundle Noto Sans JP
   - **Answer:** rely on system fonts; README notes the Linux gap
   - **Rationale:** macOS and Windows have Japanese fonts and no test checks glyphs; a JP font adds several MB.

#### Confirmed Decisions
- Suite cases keep a per-case `source` block and `mobile_method`; each save runs the run rules; confirm re-checks the list.
- `WEB_KINDS` keeps the tab-age cutoff and gains `suite-generate`; a new `AGENT_KINDS` holds the agent allow list.
- Suite captures are copied into the run through the import checks; caps and the link guard are named.
- Mockup inline styles become classes; Yohaku fonts get absolute `/fonts/` faces in `app.css`.
- Shared UI helpers move to their own modules in phase 6; old views are deleted at the end of phase 7.
- The redirect table covers `#/`, `#c=`, job detail and legacy review links (through `job.run`).

#### Impact on Phases
- Phase 1: Excel reader, suite case schema, confirm rules, caps, `suite_digest`.
- Phase 2: columns, captures, `confirmed` and `digest`, trace as text, `trace` export field, VERSION 1 and 2, stored fixture.
- Phase 3: `AGENT_KINDS`, freshness enum, `webtest-plan` kept until phase 7.
- Phase 4: `webtest-table --suite`; Plan job section stays until phase 7.
- Phase 5: fonts and asset test, inline styles, LOCK source, `--font-mono`, `statusIcon`, every vi consumer, theme, notices.
- Phase 6: helper extraction, full redirect table, deletions moved to phase 7.
- Phase 7: `webtest-plan` retirement with every consumer, helper removal, deletions, Preferences fields; now depends on phases 4 and 6.
- Phase 8: e2e sites listed, README font note. Total effort 9.5d → 11d.

### Whole-Plan Consistency Sweep
- Files reread: plan.md, phase-01 to phase-08
- Decision deltas checked: 12
- Reconciled stale references: 6 (effort total, phase dependencies, Excel dependency line, `trace.gaps` wording, deletion timing in phase 6, phase 8 step numbering)
- Unresolved contradictions: 0
