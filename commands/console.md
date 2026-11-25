---
description: Open the testign console in the browser and work through the survey, close, test case, test suite and web test jobs the tester queues there
argument-hint: "[--no-browser]"
---

Run the `console` skill of the testign plugin for these arguments: `$ARGUMENTS`

- The console is a local web page on `127.0.0.1` in English or Japanese, with three groups: Test
  case design (test suites, ticket survey), Test runs (runs, agent and jobs) and Settings
  (projects and hosts, login scenarios, templates, scout cache, preferences). The tester queues
  jobs there that this Claude Code session carries out.
- `--no-browser` starts the server without opening a browser; the tester opens it later with
  `testign console open`.

The console server writes only under `~/.testign-kit/`. Reports, workbooks and the wiki change only
through the jobs this session runs, with the same approvals as the chat commands.
