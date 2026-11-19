---
title: Plan web UI test runs from a Figma change table
date: 2026-11-19
summary: "Brainstormed and planned Chrome-driven web test runs for the testign plugin; eight phases, the first a spike that waits for the test base URL."
---

# Plan web UI test runs from a Figma change table

## What happened

- The request was automated web testing through Claude in Chrome, with a Figma node as the test definition, one command and a console screen.
- The Figma node (`6mk0tfGVyiFgveLasgWCVu`, `6647:118148`) turned out to be a 45-row design change table, not a test case list. It has no URL, steps or preconditions; each row's layer name carries the id of the changed design node.
- The plan is at `plans/261119-0324-web-ui-test-runs-from-figma/` with nine phases after the red-team review (eight before it).

## Decisions

- Agentic run through Claude in Chrome, not generated browser scripts: most rows ask whether the page matches the design.
- Runs work on a normalised case list, so the `/testign:testcase` workbook can become a second source later.
- Three triage classes. Rows that touch data or logic run only when the tester delegates them; an unanswered row does not run.
- Orchestrator and one worker at a time. A row that cannot continue is parked with a question and the next row starts. Parked questions are a non-blocking channel beside the console's blocking ask.
- Login is a step list written by the agent and run by a fixed runner in the plugin. The tester starts it from the console and types the test account into a console form. The server runs no agent-written code.
- Output is an Excel workbook from a per-run column plan plus a Markdown report.

## Research findings

- Subagents inherit the session's MCP tools; a plugin agent with a `tools:` list must name the Chrome tools.
- Chrome 136 and later ignore the debug port on the default profile. Chrome 144 and later have an approval mode with a dialog per connection.
- On macOS a non-default profile may not find the Claude extension's native-messaging file.
- Figma call limits follow the plan that owns the file: a Full seat has 200 calls a day on Professional, a View seat 20 a month.

## Next steps

- Get the test base URL and run the phase 1 spike (worker tools, evidence files, screen guessing, login route).
- A red-team review with four reviewers ran afterwards: 39 findings merged into 15, all applied (`reports/red-team-adjudication.md` in the plan folder). The main changes: runs recover after a dead job, tester answers are stored per run, the agent cannot write hosts or approve for the tester, and the debug connection is limited to a dedicated test profile held by the server.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
