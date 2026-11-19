---
phase: 6
title: "DevTools client, login runner and evidence capture"
status: pending
priority: P1
effort: "4d"
dependencies: [1, 5]
---

# Phase 6: DevTools client, login runner and evidence capture

## Goal

A debug connection from the console server to the dedicated test Chrome, used for two things
only: running an approved login scenario when the tester presses "Sign in", and capturing the
evidence image of the row a worker is on.

## Context

- Decided by the user on 2026-11-19: the debug connection exists only on a dedicated test profile that holds test accounts. The tester's own profile is never debugged.
- Whether the connection is a pipe or a port, per platform, comes from phase 1, item D. A pipe can be used only by the process that started Chrome. A port is open to every local process for as long as the test Chrome runs; where only the port works, the README states that exposure.
- If phase 1 finds no working connection, this phase is not built: sign-in is manual (phase 5) and evidence comes from the tester (phase 4 image route).
- The standard library has no WebSocket client; the port route needs one written on `socket`. The pipe route needs none.
- The server starts children with a fixed argument list today only for itself (`console/lifecycle.py`); the SIGTERM fallback skips the shutdown hooks (`console/lifecycle.py:363`, `434-441`).

<!-- Updated: Red Team Session 1 - new phase split from the scenarios phase; owns webtest-evidence; server-side capture; runner bound to job, ask and scenario; stop route; no script text; real-browser test -->

## Who holds the connection

Only the console server and the runner it starts. No agent-invoked command contains a DevTools
client: the orchestrator asks the server for a capture and gets back a staged image id and the
tab's URL. The module is not importable from the CLI's agent commands, and a test asserts it.

## Test Chrome

- `POST /api/webtest/chrome/start` (browser group): the tester starts the test Chrome from the console. The server launches it with the dedicated profile folder from the config and the connection phase 1 chose, with password saving off and no first-run prompts.
- The server tracks the process id and stops that Chrome when the server stops, from a shutdown hook and from the SIGTERM path.
- The profile folder is `~/.testign-kit/webtest/chrome-profile/` by default. The tester installs and signs in to the Claude extension there once; the README describes it, including the macOS native-messaging file if phase 1 found it is needed.

## Login runner

1. The orchestrator has an open login question for a scenario (phase 4).
2. The tester presses "Sign in": `POST /api/webtest/login/:project/:scenario/run` with the job and ask id. The server refuses when the scenario is not approved, the credentials are not filled, the ask is not open or names another scenario, or a runner is already active (409).
3. The server runs the approved steps in a login tab it opens:
   - `fill`: find the element with `DOM.querySelector`, focus it, type with `Input.insertText`. The selector and the value travel as protocol parameters, never inside script text.
   - A field marked `secret` is typed only into an element whose type is `password`; otherwise the step fails.
   - `manual`: the runner waits and the console shows the note; the tester presses "Continue".
   - `expect`: the tab's URL has the prefix within the timeout.
4. On success or failure the runner closes the login tab's fields (a failed step clears what it typed) and reports the step number and an error class only.
5. The console shows the result. The tester presses "Signed in" on the login question; the server does not answer it.

`POST /api/webtest/login/run/stop` ends an active runner. Socket and step timeouts end a runner
that hangs. One runner at a time.

While a login question is open the skill makes no Chrome tool call (phase 7), so the agent does
not read a page that holds typed credentials.

## Evidence capture

`webtest-evidence --run <id> --row <r> --job <j> --session <s> --url <u> [--selector <css>]`:

1. Calls `POST /agent/webtest/runs/:run/capture`. The server finds the tab whose URL equals `<u>`, brings it to the front, and captures it, clipped to the selector when given.
2. The server stores the image under the run's server folder and returns `{image, url, title}` with the URL the browser reports.
3. The command moves the image into the run's `evidence/` as `<row>-a<attempt>-<n>.png` and records it against the row's current attempt in `run.json`, with the browser-reported URL.
4. `webtest-row` (phase 2) accepts only evidence recorded for the current attempt, and compares the worker's URL with the recorded one.

`webtest-evidence --run <id> --row <r> --from-image <image-id>` does step 3 for an image the
tester uploaded (phase 4), for tester-run rows and for the fallback where no connection exists.

## Commands and config

| Item | Does |
|---|---|
| `webtest-evidence` | As above; the only evidence writer |
| Config `webtest.chrome_profile`, `webtest.debug` (`pipe` or `port`), `webtest.port`, `webtest.step_timeout` | Defaults in `config.py`; `debug` per platform from phase 1 |

## Files to Create / Modify

- Create: `scripts/testign/console/devtools_client.py` (pipe transport; WebSocket transport on `socket`: handshake, masked frames, fragments, ping, close; the few protocol calls used)
- Create: `scripts/testign/console/test_chrome.py` (start, track, stop the test Chrome)
- Create: `scripts/testign/console/login_runner.py` (step execution, secret rule, timeouts, stop)
- Create: `scripts/testign/console/capture_api.py` (capture route, runner routes, Chrome start route)
- Modify: `scripts/testign/console/lifecycle.py` (stop the test Chrome on every exit path)
- Modify: `scripts/testign/webtest.py`, `scripts/testign/cli.py` (`webtest-evidence`)
- Modify: `scripts/testign/config.py` (`webtest` defaults)
- Create: `tests/test_devtools_client.py`, `tests/test_login_runner.py`, `tests/test_capture_api.py`
- Create: `tests/e2e/test_login_runner_chromium.py`
- Modify: `.github/workflows/test.yml` (the e2e job already installs Chromium; add the new test file's flag if needed)

## Tasks & Steps

1. Write the transport phase 1 chose first, then the other if both platforms need different ones.
2. Write the test Chrome start, tracking and stop, and hook the stop into every server exit path.
3. Write the runner: steps, the secret rule, timeouts, the stop route, the binding to job, ask and scenario.
4. Write the capture route and `webtest-evidence`, with attempts.
5. Write the unit tests against a small protocol server in the test.
6. Write the real-browser test: Playwright's Chromium started with a temporary profile and the debug switch, a local login page served by the test, made-up credentials.

## Todo

- [ ] Transport (pipe, WebSocket on `socket`)
- [ ] Test Chrome start, tracking, stop on every exit path
- [ ] Runner with the secret rule and timeouts
- [ ] Runner bound to job, ask and scenario; stop route
- [ ] Capture route and `webtest-evidence`
- [ ] Unit tests
- [ ] Real-browser test in the e2e job

## Verification

- `python -m pytest tests/test_devtools_client.py tests/test_login_runner.py tests/test_capture_api.py -v`
- `TESTIGN_E2E=1 python -m pytest tests/e2e/test_login_runner_chromium.py -v`
- Unit tests cover: handshake, a frame longer than 125 bytes, a fragmented frame, close; a start for an unapproved scenario, an unfilled one, a closed ask or another scenario is refused; a second start gets 409; a secret field aimed at a text input fails the step and types nothing; a selector with quotes cannot change the protocol call; a hung step ends at the timeout; stop ends the runner; the runner's output, `server.log` and the job record hold none of the made-up credential values, including values with quotes and backslashes; the CLI's agent commands cannot import the client.
- The real-browser test covers: sign-in on a local page reaches the expected URL; a capture clipped to an element is a PNG of that element's size; the capture reports the tab's real URL after a redirect; after the server stops, no test Chrome and no runner process is left (the test checks the process ids it started).

## Risks

- A login form built with a framework that ignores inserted text until key events fire. The runner dispatches key events for the last character; the real-browser test includes such an input. Forms that still fail use a `manual` step.
- Bringing a tab to the front for a capture interrupts what the worker is doing. Captures are requested by the orchestrator after the worker has returned, never during a row.
- Chrome started by the server ends when the server's idle limit stops the server. A run job keeps the server busy; outside a run the tester starts the test Chrome again from the console.
