---
description: Survey a Backlog ticket against master (merge-base) and develop, and write the survey report
argument-hint: <TICKET-ID> [--repo <path>] [--master-ref <ref>] [--develop-ref <ref>] [--fetch] [--lang vi|ja|en]
---

Not implemented yet (planned for phase P2).

When implemented, this command runs the `spec-qa` skill of the testign plugin for ticket `$ARGUMENTS`.
`spec-qa` calls the internal `scout` skill, then writes `<TICKET>-survey-r<N>.md` to the configured
output folder.

For now, tell the tester that `/testign:survey` is not available yet and stop.
