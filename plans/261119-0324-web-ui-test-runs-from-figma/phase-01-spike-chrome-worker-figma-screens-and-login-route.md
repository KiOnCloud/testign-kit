---
phase: 1
title: "Spike: Chrome worker, Figma screens and login route"
status: in-progress
priority: P1
effort: "2.5d"
dependencies: []
---

# Phase 1: Spike: Chrome worker, Figma screens and login route

## Goal

Settle what this plan cannot know from the repository, on the real Figma file and the real test
site, and write down which route phases 6 and 7 take.

## Context

- Blocked until the user gives the test base URL.
- Convention: the console plan kept its spike script in `spike/` and its results in `reports/` (the script itself was removed from the tree later; the reports remain in `plans/261118-1431-testign-console/reports/`).
- Desk research on the same points: `research/researcher-01-chrome-figma-facts.md`. The spike confirms or corrects it on the user's machine.
- Decided by the user on 2026-11-19: the debug connection is allowed only on a dedicated test profile that holds test accounts and nothing else. The tester's own Chrome profile is never opened for debugging.
- The test site holds made-up data only (user, 2026-11-19).

<!-- Updated: Red Team Session 1 - items F, G, H added; D1 removed; item C on random rows; item E on fifteen rows -->

## Results so far

See `reports/spike-macos-2026-11-19.md`. On macOS: A passes for a general subagent; B passes
without a debug connection (the Chrome tool saves screenshots to a file); C works for instance
layers only; F passes; G fails (the window would not take a phone width); one real row ran end to
end with evidence. The user then chose the tester's own Chrome profile with sign-in by hand, so
items D and H as written (runner, dedicated profile) are dropped; H becomes a manual check in the
phase 8 round. `spike/webtest_spike.py` was written for item D and is kept unrun as a record.

Still open: item A with a plugin agent definition and item E on fifteen rows (both in the phase 6
dry run), and Windows.

## Spike items (as planned)

| Item | Question | How | Pass | Fallback when it fails |
|---|---|---|---|---|
| A | Can a plugin agent call the Claude in Chrome tools? | Spawn one subagent from a plugin agent definition whose `tools:` list names the Chrome tools; it opens a page in its own tab and reads a label. | It returns the label text and the final URL. | The orchestrator runs rows itself under the worker contract. |
| B | Can the console server save a screenshot of the tab a worker is on? | Through the debug connection of item D: find the target by the URL the worker reports, bring it to the front if needed, capture it clipped to an element. | A PNG of the checked area exists on disk on macOS and Windows, and the capture reports the tab's real URL. | Evidence comes from the tester: the row waits for an uploaded image. Decide with the user whether to continue, because most automation is lost. |
| C | How is the screen of a target node found? | On ten rows picked at random: is the target a frame on a page, a main component or an instance layer (ids such as `I625:18321;294:4398;…`)? Which Figma calls reach a parent or the instances of a component? | A written method that finds the right page for at least seven of ten rows, with its call count. | The screen column starts empty and the tester fills it. |
| D | Can a fixed runner sign in to the Chrome that Claude drives? | A dedicated `--user-data-dir` with the Claude extension installed and signed in there. Try the pipe first (`--remote-debugging-pipe`, Chrome started by the script, so only that process can talk to it), then a port (`--remote-debugging-port`). Run a hand-written step list against the login page with a test account the tester types into a local file. | After the runner ends, a Claude in Chrome tab of the session shows the signed-in page. | The tester signs in by hand in that Chrome; the console shows the scenario's checklist. |
| E | What does a run cost? | Fifteen rows in a row on each worker route: time, tool calls and context use per row, and where browser permission prompts appear. Figma calls for one import of 45 rows. | Numbers recorded. | None; it sets the heartbeat interval and the progress estimate. |
| F | How does a Figma capture become a file? | Download the image the screenshot tool points to, with the command line, into a folder. | The capture of one row exists as a PNG. | Captures are left out; the review table shows the row text only. |
| G | Can the viewport be set to a phone width? | Set a mobile size in the test Chrome and read the layout width the page sees. | The page reports the mobile width. | `mobile` rows are class `not-web` and run by the tester. |
| H | Does switching scenarios work? | Sign in as one scenario, sign out, sign in as a second, on the same hosts. | The second sign-in ends on its expected page. | One scenario per run; rows of other scenarios are `not-run: no-scenario`. |

Known from the research report, to confirm here:

- Chrome 136 and later ignore both debug switches on the default profile; a non-default profile works.
- On macOS Chrome looks for native-messaging host files inside the user data directory, and Claude Code writes its file only for the default one. Check whether the session reaches the extension in the dedicated profile; if not, record whether copying that file is enough.
- With two Chromes connected, the session must select the test one. Record how the skill can check which browser a tab belongs to.
- A port is open for as long as the test Chrome runs, to every local process. The pipe has no such exposure. If only the port works, the report says so and the README states it.
- Figma limits follow the plan that owns the file: record the plan, and count every call the spike makes against the daily limit before starting an import.

## Files to Create / Modify

- Create: `plans/261119-0324-web-ui-test-runs-from-figma/spike/webtest_spike.py` (standard library only: start the test Chrome, connect by pipe or by a WebSocket client written on `socket`, run a step list, save one clipped screenshot)
- Create: `plans/261119-0324-web-ui-test-runs-from-figma/reports/spike-macos-<date>.md`
- Create: `plans/261119-0324-web-ui-test-runs-from-figma/reports/spike-windows-<date>.md`

No file under `scripts/`, `skills/` or `commands/` changes in this phase.

## Tasks & Steps

1. Ask the user for the base URL, the project name and which account roles exist on the test site. Never ask for the credentials themselves.
2. Run items A, C, E, F and G with the Figma and Chrome tools of the session.
3. Write `webtest_spike.py` and have the tester run items D, B and H on macOS. The tester types the account into the local file; Claude does not open it.
4. Repeat B, D and H on Windows through the user's machine, as in the console plan's spike.
5. Write both reports: for each item the result, the evidence, and the chosen route.
6. Update phases 6 and 7 with the chosen routes and tick the matching assumption rows in `plan.md`.

## Todo

- [x] Base URL, project name and account roles received
- [ ] Item A result recorded with a plugin agent definition
- [ ] Item B result recorded on macOS and Windows
- [x] Item C method and counts recorded for ten random rows
- [ ] Item D result recorded on macOS and Windows, pipe and port
- [ ] Item E numbers recorded for fifteen rows on each route
- [x] Items F and G recorded (H dropped with the runner)
- [x] Later phases updated with the chosen routes

## Verification

- Both spike reports exist and name one route each for the worker, the debug connection, evidence, screens and scenario switching.
- The credentials file used in item D appears in no report, no transcript and no commit (`git status` shows it untracked and outside the repository).

## Risks

- The Claude extension may not be allowed in a second profile by the user's organisation. Then D fails by policy; record it as such and take the manual route with tester-supplied evidence.
- The pipe on Windows needs inherited handles that the standard library does not offer directly. If it cannot be done in a day, record it as not available on Windows and use the port there.
