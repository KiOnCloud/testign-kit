# Red team adjudication — 2026-11-19

Four reviewers returned 39 findings: security (9), failure modes (10), assumptions (10), scope (10).
Their reports are beside this file. Overlapping findings are merged below into 15, sorted by
severity. Every merged finding carries `file:line` evidence in its source report. Nothing has
been applied to the plan yet.

Source keys: SEC = `red-team-security.md`, FM = `red-team-failure-modes.md`,
AD = `red-team-assumptions.md`, SC = `red-team-scope.md`.

## Findings

### 1. A row left `running` locks the run for good — Critical
**Sources:** FM1, AD1. **Location:** phase 2 states and commands; phase 3 export; phase 4 kinds.
**Flaw:** every command that moves a run forward refuses a run with a `running` row, and only the dead job's orchestrator could move that row. The server never touches `run.json` (`console/jobs.py:460-470`, `698-707`, `774-778`).
**Disposition:** Accept.
**Change:** the `running` row stores its job id. A new `webtest-run` job puts rows owned by a finished job back to `queued`, marked interrupted. A restart-mid-row test is added.

### 2. Parked questions, answers and self-run results die with the job — Critical
**Sources:** FM2, FM3, FM9, AD2, SC1. **Location:** phase 4 parks; phase 6 run loop.
**Flaw:** the row's `parked` state lives as long as the run, its question and answer only as long as the job, the uploaded image one hour (`console/jobs.py:474-485`, `656-672`; `console/templates_api.py:29`, `87-103`). A continued run closes parked rows as `unanswered` without asking. Answers keyed by row are re-applied to a later park. The plan's premise that `ask` cannot return at once is wrong (`console/jobs.py:864-868`, `913`).
**Disposition:** Accept (modified).
**Change:** questions are stored in `run.json`; answers and self-run results in a per-run answers file the server writes under `~/.testign-kit/webtest/`. Both are keyed by a park id (row plus attempt). Routes are scoped to the run, not the job. The job-scoped parks store, its three agent routes and the acknowledge protocol are dropped; the CLI fetches answers from the server and applies each id once. A new `awaiting-tester` state counts as open for close and export. Open run questions feed the console's "needs you" count.
**Why not SC1's fix (several open asks per job):** it keeps the lifetime problem of AD2.

### 3. The agent can give the tester's approvals itself — Critical
**Sources:** SEC1, SEC4, FM7, SC7. **Location:** phase 6 command; phase 2 `webtest-plan`, `webtest-resolve`; phase 4 answers.
**Flaw:** no agent route can queue a job (`console/jobs.py:1015-1028`), so the agent would mint a browser session, which then passes the session-age rule (`console/jobs.py:660-668`). The CLI applies "tester answers" from files the agent wrote.
**Disposition:** Accept (modified).
**Change:** an agent route queues a `webtest-plan` job and marks it agent-queued, so the agent never needs a browser session. For web runs the session-age rule is measured against the job's creation. `webtest-plan` and `webtest-resolve` take `--job` and `--session` and read the confirmed answer from the server, as `wiki-update` does (`cli.py:385-400`); `run.json` records who answered each delegated row.
**Rejected part:** a lifetime limit on browser sessions. It changes the existing console for all job kinds, and the user decided on 2026-11-19 to "document and harden lightly" there (`plans/261118-1431-testign-console/plan.md`, key decisions). The residual risk is stated in the README: the agent runs as the tester.

### 4. The agent writes both the login scenario and the hosts it is checked against — Critical
**Sources:** SEC2, SEC6, SC6, AD5. **Location:** phase 5 store, scenario creation, commands; phase 2 `webtest-new --host`.
**Flaw:** a `fill` step can put the password into any field, for example a search box that shows it back. Hosts live in three lists, two of them agent-writable. A run does not record its project, so a run job cannot open its login. How `fill` reaches the page is unspecified; built as script text it runs agent-written selectors with the password in scope.
**Disposition:** Accept.
**Change:** hosts are typed by the tester only (job form, console); `run.json` copies them from the job and records the project; `--host` and `login-project-set` are removed from the agent's commands. The tester approves a hash of each scenario and the runner refuses a scenario that differs. Fields are marked secret or not; a secret field is typed only into a password input. Selectors pass as protocol parameters (`DOM.querySelector`, `Input.insertText`), never as script text, and are checked against a small grammar.

### 5. A debug port exposes passwords and cookies to every local process — Critical
**Sources:** SEC3, SEC8, AD3. **Location:** phase 1 items B and D; phase 5 runner.
**Flaw:** route D1 turns on debugging in the tester's own profile, with every real account in it. Route D2's port takes any local connection. The evidence command the agent calls would share the runner's client. The typed password stays in the page Claude reads during a manual step, and Chrome may offer to save it.
**Disposition:** Needs the user's decision (question 1).
**Recommended:** drop D1. Keep a dedicated test profile that holds only test accounts; open its port only while the runner or a capture runs; captures are taken by the console server, not by an agent command; password saving is off in that profile; no Chrome tool call while a login is open. Manual sign-in stays the fallback.

### 6. The off-site check trusts the agent's own report — High
**Sources:** SEC5. **Location:** phase 2 `webtest-row`; phase 8 check 7 and injection check.
**Flaw:** the page has already loaded before the CLI reads a URL the agent supplies. Phase 8 check 7 can never reach `webtest-row`, because import refuses an off-host screen first. The injection check has two rows.
**Disposition:** Accept.
**Change:** the plan calls the CLI check a consistency check, not a barrier. The barrier is the site permission the tester grants Claude in Chrome for the run's hosts only; the capture records the tab's real URL. Check 7 is rewritten and the injection set grows. Severity depends on question 2.

### 7. Expired logins and browser trouble are recorded as stuck rows — High
**Sources:** FM5, AD6. **Location:** phase 6 worker brief; phase 2 states; acceptance 6.
**Flaw:** a login page parks the row and turns `sure` into `choice` for good; one expired session parks every later row. "Signed in" exists only in the model's context. Switching scenarios on the same hosts has no sign-out.
**Disposition:** Accept.
**Change:** a `blocked-env` outcome requeues the row unchanged and re-opens the login question; three in a row stop the queue. `signed_in` is stored in `run.json`, set from the server-confirmed answer and reset per job. Scenario switches sign out first. The spike tests a switch.

### 8. The login question and the runner are loosely coupled — High
**Sources:** FM4, SC7. **Location:** phase 4 login prompts; phase 5 starting a login.
**Flaw:** any runner success answers whatever login ask is open; a success before the ask exists is dropped; no stop route; the child outlives the server (`console/lifecycle.py:363`, `434-441`).
**Disposition:** Accept.
**Change:** the login question is an ordinary `questions` ask with "Signed in" and "Skip" on both routes; the server never answers it. A runner start names the job, ask and scenario. A stop route, process tracking, socket timeouts and a shutdown hook are added.

### 9. The Figma import cannot save partial work, and screens cannot be read as planned — High
**Sources:** FM6, AD4. **Location:** phase 6 plan job; phase 1 item C.
**Flaw:** rows are "saved" before the run folder exists; a retry starts from row 1 and passes the daily cap. No Figma tool returns a node's parents; many targets are components or instance layers with no screen above them. Captures must be files, and the screenshot tool returns an image to the model.
**Disposition:** Accept.
**Change:** `webtest-new` runs first and a staging command saves one row at a time; `webtest-find` reports partial imports; the import sends progress regularly. The spike gains two items: on ten random rows, how many targets are components and how a screen is actually found; and how a Figma capture becomes a file. Figma calls are counted against the daily cap, the spike's included.

### 10. Evidence has no owning phase and no checked route — High
**Sources:** SC4, FM10, AD3, AD9. **Location:** phases 1, 2, 4, 6.
**Flaw:** four phases call `webtest-evidence` and none defines it. Any old file satisfies the evidence check. Phases 2 to 4 hard-code what the spike has yet to find. "Stop and replan" ignores the plan's own upload route.
**Disposition:** Accept.
**Change:** one phase owns the capture command. A capture is recorded against the row's current attempt and only those count. Tester-uploaded evidence is the fallback instead of stopping. The evidence and login parts of phases 2 and 4 wait for the spike; the dependency paragraph is corrected. A viewport item joins the spike.

### 11. The template changes break existing tests and the shared registry — High
**Sources:** SC2, SC3, AD7. **Location:** phase 3.
**Flaw:** new role synonyms change what the shipped sample detects (`xlsx.py:214`; `tests/test_templates_xlsx.py:57`, `251-253`), so "passes without edits" is false. A template registered without the trace column would be offered to `/testign:testcase` and fail there (`xlsx.py:164-168`). A second writer and a second sample duplicate what exists. Default labels `Pass`/`Fail` break the sample's fixed list.
**Disposition:** Accept (modified).
**Change:** `ROLES` and its synonyms stay as they are; the column plan carries result columns by letter. Each registry entry gains a purpose; web entries need the item column only and `/testign:testcase` does not list them. The console's register route and screen take the purpose. The existing writer is generalised instead of copied. The shipped sample is reused. Default verdict labels come from the result column's fixed list when it has one.

### 12. Job-record changes miss consumers that break — High
**Sources:** SC8, SC9. **Location:** phases 4 and 7.
**Flaw:** "Queue again" builds a survey request for unknown kinds (`ui/views/job-actions.mjs:162-175`); a test pins the kind set (`tests/test_console_jobs.py:123`); the new fail reason is missing from `FAIL_REASONS` (`console/jobs.py:44`); the review table has no render path (`ui/views/jobs.mjs:16`, `220`; `ui/views/review.mjs:13`; `ui/main.mjs:22`).
**Disposition:** Accept.
**Change:** the consumers are listed in the phase files with their edits; `run_lang` is replaced by the existing `report_lang`.

### 13. A long run outlasts the silence limit, and Finish cannot stop it — High
**Sources:** AD8, FM8. **Location:** phase 6 run job; phase 4 finish.
**Flaw:** a row over 15 minutes lets the job be marked failed or taken over (`console/jobs.py:48`, `628-635`). Browser permission prompts appear in the terminal while the tester watches the console. Finish is read only when the queue is empty and not at all during a login question. "Mark failed" is refused during held calls (`console/jobs.py:526-527`).
**Disposition:** Accept.
**Change:** a heartbeat while a worker runs; Finish is checked after every row and ends an open login question; the `stopped` reason gets a command; a banner says the agent may be waiting in the terminal. Spike item E becomes fifteen rows in a row on both worker routes.

### 14. Names in routes and the credentials folder are under-protected — Medium
**Sources:** SEC7, SEC9. **Location:** phases 4 and 5.
**Flaw:** route segments are decoded after matching (`console/server.py:125`, `152`), and only evidence names are checked. The credentials folder is not created owner-only; mode bits do nothing on Windows (`fsutil.py:30`). The plan restates the console's write scope more broadly than the original (`plans/261118-1431-testign-console/plan.md:47`).
**Disposition:** Accept.
**Change:** a strict pattern for project, scenario and run names, resolved through a folder listing; an owner-only folder, with the Windows limit stated; a deny rule that covers shell reads; acceptance 8 is called a regression check. The widened write scope is stated as a decision.

### 15. Effort and test coverage are understated — Medium
**Sources:** AD10. **Location:** plan frontmatter; phases 5 and 7.
**Flaw:** the phases add up to 22 days, not 20. Phase 5 holds a protocol client, a runner, a server child process and a credentials route in 3 days. The runner never meets a browser in CI. The parity test cited is the wrong one (`tests/test_console_ui_assets.py:32`). The spike file cited in phase 1 is gone from the tree.
**Disposition:** Accept.
**Change:** effort is restated after the changes above. Phase 5 is split into a store, credentials and manual part and a client and runner part. A runner test against a real Chromium joins the macOS e2e job. The two citations are fixed.

## Questions for the user

1. Finding 5: is a debug port on a dedicated test profile acceptable, or no debug port at all?
2. Finding 6: can the test site hold real customer data?
3. SC5: do rows the tester runs by hand need an evidence image? No acceptance criterion asks for one.
4. SC10: must testers be able to write login steps by hand in the console, or only review the agent's draft?
