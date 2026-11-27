---
description: Make a web test suite from a Figma change table or a Backlog survey report, get it confirmed in the console, run a run made from it in Chrome one row at a time and export an Excel workbook and a Markdown report
argument-hint: <figma-url> [--name <n>] [--project <p>] [--depth <d>] | --ticket <T> [--name <n>] [--depth <d>] | --run <run-id> [--tester <name>]
---

Run the `webtest` skill of the testign plugin for these arguments: `$ARGUMENTS`

- `<figma-url>` is the change table's Figma link with its `node-id`. The command creates a Figma test
  suite and queues the job that writes its cases; the tester reviews and confirms them on the
  suite's Cases tab in the console. `--name` names the suite, `--project` links it to a project of
  the console's Projects screen.
- `--ticket <T>` does the same from the ticket's latest survey report: one case or more per B* and
  R* row, each traced to its row. Survey the ticket first (`/testign:survey`).
- `--depth smoke|standard|thorough` is the suite's test depth (default standard): which kit checks
  the cases must cover for each control the change touches (display, action, button state, limits,
  messages, roles, pairs, double press…). The tester sees them on the suite's Checks tab and can
  change the depth there; a deeper depth adds only the missing cases.
- `--run <run-id>` runs a run, or continues a stopped one. Runs are made from a confirmed suite on
  the console's Runs screen, where the tester picks the base URL (on one of the project's hosts),
  the template and the tester's name. The console needs the tester's name for the job (`--tester`,
  else asked once in the chat).

The command queues the job in the console and the tester continues there; there is no chat-only
mode. Claude never signs in, reads or types an account value: the tester signs in by hand in their
own Chrome. Rows run only on the project's hosts, which only the tester sets.
