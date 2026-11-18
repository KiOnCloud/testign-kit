---
title: Build the testign console through the job bridge
date: 2026-11-18
summary: "Phases 1-5 of the console built; pytest hang, Windows reset and review findings fixed; manual round and release pending"
---

# Build the testign console through the job bridge

## What happened

Implemented phases 1 to 5 of `plans/261118-1431-testign-console/` on branch
`claude/relaxed-franklin-oikzoa`: the per-user console server and lifecycle, the read API and
template management, the browser UI (built by a subagent, vendored Kestrel, self-hosted fonts),
the job queue and agent bridge, and the Jobs and Close review screens. The console skill,
`references/console-bridge.md`, the three skills' console sections and the README Console section
are written. Full suite: 334 passed, 4 skipped; 54 node UI tests; plugin validation passes.

Problems found on the way:

- pytest did not exit after printing its summary. Cause: a threaded test ran `Bridge.wait()` on a
  fake clock, so its deadline never came. Fixed by running threaded held-call tests on the real
  clock with daemon threads.
- On Windows, a request refused before its body was read (415, 403) closed the connection with
  unread data, which Windows turns into a reset; the client saw a dropped connection instead of
  the error. The server now reads and drops small unread bodies before answering.
- A backend code review reported 3 High findings: an injected agent can mint itself a browser
  session through the launch-code route; an answer delivered to a killed `ask` command was lost
  for good; one crafted upload could exhaust memory (whole-zip ratio check, full openpyxl load).
  Plus approval after release, an agent-supplied wiki diff, and five smaller items.

## Decision

- Lost answers: an already answered ask id returns its stored answer (this replaces the plan's
  "refuse a reused id").
- Uploads: per-entry size and ratio checks, bounded read-only detection and preview.
- Agent-minted sessions (user decision): document the limit and harden lightly; a browser
  session created after a job was claimed cannot answer it (`session-too-new`), and new sessions
  are announced until dismissed.
- Wiki diff (user decision): `wiki-append-preview` in API mode adds `old_content` and
  `new_content`; the server computes the diff the tester sees and checks the approval hash.

## Next steps

- macOS spike (planned for 2026-11-19).
- Phase 6 manual round with a real Claude Code session on Windows and macOS, and the injection
  check.
- First real run of the Playwright e2e job in CI; version 0.3.0 release after the round.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
