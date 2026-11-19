---
description: Import a Figma change table into a web test run, get its review table confirmed in the console, run the rows in Chrome one at a time and export an Excel workbook and a Markdown report
argument-hint: <figma-url> --base-url <url> --project <p> [--name <n>] [--template <t>] [--ticket <T>] | --run <run-id> [--tester <name>]
---

Run the `webtest` skill of the testign plugin for these arguments: `$ARGUMENTS`

- `<figma-url>` is the change table's Figma link with its `node-id`. `--base-url` is the test site's
  address and must be on one of the project's hosts.
- `--project` names a project the tester created on the console's Login screen with its hosts. The
  command never writes hosts; when the project does not exist it says so and stops.
- `--name` names the run, `--template` picks a registered template for the export (default: the
  default template), `--ticket` links the run to a ticket.
- `--run <run-id>` runs a run whose review table is confirmed, or continues a stopped one. The
  console needs the tester's name for it (`--tester`, else asked once in the chat).

The command queues the job in the console and the tester continues there; there is no chat-only
mode. Claude never signs in, reads or types an account value: the tester signs in by hand in their
own Chrome. Rows run only on the project's hosts, which only the tester sets.
