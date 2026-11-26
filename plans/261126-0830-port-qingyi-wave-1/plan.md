---
status: in-progress
created: 2026-11-26
---

# Port the first batch of qingyi-test-kit features

Five features from qingyi-test-kit that do not depend on the replay engine or on how replay signs in.
The assessment that chose them is in the project's shared files (`docs/qingyi-port-assessment-261126.md`).

- **Outcome:** testign keeps its current flows and gains a git write guard for customer repositories,
  console routing of `AskUserQuestion` during a job, defect drafts from failed rows, results across the
  runs of a suite with a Fixed mark, and a verbatim check of decision quotes before the wiki is written.
- **Constraints:** Python 3.10+, standard library plus `openpyxl`; nothing written into the customer
  repository (the guard list lives in `~/.testign-kit/`); defects are never posted anywhere; the console
  server still makes no LLM call; UI strings in en and ja.
- **Non-goals:** the record/replay engine and Login Recipe (second batch), `flaky` (only meaningful
  with automatic retries, which the agentic run does not do), a defect tracker integration, Knowledge.
- **Acceptance criteria:**
  1. With a repository on the guard list, `git commit`, `push`, `reset`, `checkout`, `switch`, writes into
     `.git/` and the hidden forms (`git -C`, `bash -c`, aliases) are blocked for Claude; read-only git
     passes; repositories not on the list are untouched. `guard enable|disable|status` manage the list.
  2. While this Claude Code session holds an open console job, `AskUserQuestion` is denied with the exact
     `console ask` command and a ready ask file; with no console or no job the question goes through.
  3. Every failed row (agent fail or the tester's own fail) shows a defect draft prefilled from the row;
     the tester edits it, marks it sent with a tracker key or not a defect with a reason; a Defects screen
     lists them across runs; the export report lists them.
  4. A row that failed in the previous run of the same suite and project, with unchanged content, and
     passes now is marked Fixed on the run screen and in the export report; the suite's Runs tab shows a
     case-by-run result matrix.
  5. `wiki-append-preview` and `wiki-update` check every quote whose source is a Backlog comment of the
     configured space against that comment and refuse to go on when the quote is not in it; other sources
     are listed as unchecked.
  6. CI stays green on Windows and macOS; new behaviour has tests.

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | Git write guard hook and `guard` commands | done |
| 2 | `AskUserQuestion` to the console | done |
| 3 | Results across runs and Fixed | done |
| 4 | Defect drafts | done |
| 5 | Quote check for the decisions log | done |
| 6 | README, version, full test run | done |

Test strategy: unit tests for the guard policy (ported cases plus repository scoping), the history and
defect modules and the quote check; console API tests for the new routes; UI unit tests for the new pure
functions; the existing e2e smoke tests unchanged.
