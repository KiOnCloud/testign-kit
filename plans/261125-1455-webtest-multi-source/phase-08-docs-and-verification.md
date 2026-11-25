---
phase: 8
title: "Docs and verification"
status: in-progress
priority: P2
effort: "0.5d"
dependencies: [4, 6, 7]
---

# Phase 8: Docs and verification

## Goal

The README describes suites, sources and the new console, and the whole change is proven on a real
Backlog ticket and a real Figma table.

## Tasks & Steps

1. README: tester settings table (the UI language is no longer a setting there; `lang` stays the
   report language), Console section (three groups, English and Japanese, line 172 no longer names
   Vietnamese), Web test runs section rewritten as suites then runs, repository layout (`ui/` tree,
   new modules), development commands, and a note that Japanese text uses the system's Japanese
   font, so Linux needs one installed.
2. Bump the plugin version in the plugin manifest and note the retired `webtest-plan` job and the
   run file version 2 in the changelog section, if the repo keeps one.
3. End-to-end check with the tester's own Chrome:
   - Backlog suite from `CKWEB-3366-survey-r2.md`: coverage shows every B*/R* row covered; edit one
     case, confirm, create a run on the staging host, run two rows, export; the workbook has a
     `Trace` column.
   - Figma suite from the USUPP node used on 2026-11-19: same case count as that run; one run.
   - Excel suite from a carekarte test case file; Manual suite with two cases.
   - A version 1 run from before the update opens and exports.
4. Full test suite and plugin validation; e2e with `TESTIGN_E2E=1`, updating its hashes and
   selectors to the new screens (`tests/e2e/test_console_smoke.py:60-68, 102, 118, 141-147`,
   `test_console_jobs_smoke.py:97, 140, 191, 198, 214, 224, 227`,
   `test_console_webtest_smoke.py:112, 119, 125, 128, 139, 158, 172, 188`); the webtest smoke test
   creates a suite and a run from it instead of a plan job.
   <!-- Updated: Validation Session 1 - e2e hash and plan-job sites listed; README font note -->
5. Compare the result with the plan's acceptance criteria and record any gap in this phase file.

## Files to Create / Modify

- Modify: `README.md`, plugin manifest, `tests/e2e/*`

## Verification

- `python -m pytest`
- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`
- `TESTIGN_E2E=1 python -m pytest tests/e2e -v`
- `claude plugin validate --strict .`

## Result (2026-11-25)

Done in this session: README (settings note, console groups, English and Japanese with the Linux
font note, suites then runs, layout, development commands), plugin version 0.6.0 in the manifest,
`pyproject.toml` and `testign.__version__` (the repository keeps no changelog; the README records
the retired `webtest-plan` job and run file version 2), and e2e tests moved to the new routes and
selectors. Checks: `pytest` 608 passed, 2 skipped; node tests 117 passed; `claude plugin validate
--strict .` passed; `TESTIGN_E2E=1 pytest tests/e2e` 16 passed (Playwright Chromium, macOS).

Not done, so this phase stays in progress:

- Step 3 (end-to-end with the tester's Chrome, a real Backlog ticket, the USUPP Figma node, a
  carekarte workbook and a version 1 run) needs the tester's machine and accounts.
- CI on Windows has not run (nothing is committed).

Acceptance criteria:

1. Backlog coverage: covered by unit tests (coverage shows rows without a case); real report not
   tried.
2. Figma parity with a `webtest-plan` import: same table reader (`webtest-table --suite`) and the
   same `r01` row ids; not compared on the real node.
3. Excel suite with no agent job: met (API and unit tests).
4. Run keeps its own copy, export lists the suite name and each case's trace or Figma node: met
   (the Markdown report names the suite; the workbook adds the source's trace column; the cover
   `<suite>` placeholder is filled only when the template has it).
5. No Vietnamese UI, no `vi.json`, English default, Japanese on every screen: met (asset test, en/ja
   key parity, subagent browser check at 1440 and 390 px).
6. Tests and validation: met on macOS locally; CI not run.

Review follow-ups applied: confirm now requires a screen and a login scenario on every case the agent
runs; `suite-generate` jobs no longer fail when the ticket is surveyed again; `triage-rules.md`
describes the suite flow; a bad or chart-only workbook is refused as `bad-file`/`bad-sheet`; a long
suite name no longer breaks run creation; the column edit keeps the job queue locked through its
write; the `retired-kind` reason has a label. The user decided that only the tester confirms a suite:
`suite-confirm` is removed from the command line, and `suite-case-add`/`suite-case-update` apply the
agent's rules (an edit sends a ready suite back to review). Not fixed (minor): Excel cases show their row
number rather than B*/R* ids in a run export; the run export's trace header is English only; the
hash-check budget is soft.
