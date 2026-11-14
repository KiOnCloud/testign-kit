---
description: Close QA for a ticket, record approved customer decisions in the Backlog wiki decisions log, and write a new report revision
argument-hint: <TICKET-ID> [--report <path>]
---

Run the `qa-close` skill of the testign plugin for these arguments: `$ARGUMENTS`

- The first argument is the ticket ID. If it is missing, ask for it.
- `--report` picks a specific report revision; by default the highest revision in
  `<output_dir>/<TICKET>/` is used.

Nothing is written to the Backlog wiki without the tester approving each row and then the diff.
