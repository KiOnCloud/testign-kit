---
title: Web test runs implemented; review found host-parser and id bugs
date: 2026-11-19
summary: "Phases 2-7 of the web test plan implemented; code review found a URL parser mismatch, colliding answer/result ids and a stale sign-in, all fixed with tests"
---

# Web test runs implemented; review found host-parser and id bugs

## What happened

Implemented the web UI test run plan (`plans/261119-0324-web-ui-test-runs-from-figma/`), phases 2 to 7 plus the README:
run store and case list, result columns and export, run jobs and parked-row questions, login scenarios,
the `/testign:webtest` command, skill and worker, and the Test runs, Review table and Login screens.

An independent code review then found three serious bugs, each confirmed with a probe:

- **Host check bypass.** `urlsplit("https://evil.example\@dev.example.test/").hostname` is
  `dev.example.test`, but Chrome reads the host as `evil.example`. A login scenario's sign-in link could
  have sent the tester to an outside site to type a password. `url_on_hosts` (and the UI's `hostOf`)
  now refuse backslashes, whitespace, control characters, user info and `%` in the host.
- **Lost tester results.** A row that was parked and then run by the tester used `r02-a1` both as its
  question id and as its result id, and both shared one applied list, so the result was filtered out as
  already applied. Results are now keyed `<row>-r<attempt>`.
- **Stale sign-in.** `webtest-next` trusted `run.json`'s `signed_in` from any job and never asked the
  server whether the job was open. It now checks the job and run and trusts only a sign-in from the
  current job. A requeue with `--signed-out` uses up that sign-in.

Medium findings, also fixed:

- The review table is now checked against the registered template's headers and merged cells, which the
  server reads itself.
- A `choice` row offered with `runner: agent`, or an agent row at phone width, is refused.
- The digest is computed on the server from the lines the tester was shown.
- Text starting with `=` is written to the export as text, not as a formula.
- Job records keep no case text.
- Over-long preconditions get their own `too-long` error.
- File errors no longer print paths.
- Staged row ids are validated.
- Project saves take a lock.

Separately, openpyxl's `keep_vba=True` leaves `wb.vba_archive`, an in-memory `ZipFile`, open. It
surfaced as a `PytestUnraisableExceptionWarning`. `xlsx._editable` now closes it.

## Decision

The server, the CLI and the UI each checked the same rule in their own way, and the bugs sat where
they disagreed. Where a rule guards consent or security, the server now derives the facts it checks
(template headers, the digest, the job) and does not trust values the agent sends.

## Next steps

- Phase 1: the Windows spike and the fifteen-row measurement.
- Phase 6: a dry run with a live Claude in Chrome session, and a check that a plugin agent definition can call the Chrome tools.
- Phase 7: run `tests/e2e/test_console_webtest_smoke.py` (needs Playwright).
- Phase 8: the real-table rounds on macOS and Windows, the injection check, the version bump.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
