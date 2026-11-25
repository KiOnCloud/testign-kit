---
name: webtest
argument-hint: <figma-url> [--name <n>] [--project <p>] | --ticket <T> [--name <n>] | --run <run-id> [--tester <name>]
description: Web UI test suites and runs. Writes the cases of a test suite from a Figma change table or a Backlog survey report (suite-generate job), runs a run made from a confirmed suite one row at a time in the tester's own Chrome through a worker agent, parks what cannot continue, and exports an Excel workbook and a Markdown report (webtest-run job). Used by /testign:webtest and by the console skill for these job kinds.
---

# webtest

Write the cases of a test suite from a Figma change table or a Backlog survey report, run a run
made from a confirmed suite in Chrome one row at a time, and export the results. A suite is a case
list kept apart from runs; the tester reviews and confirms it on the console's Test suites screen,
then copies it into a run for one environment. Everything happens in console jobs: the tester
confirms, answers and signs in on the console, never in the chat. No command confirms a suite, and
a case you add or change with `suite-case-add` or `suite-case-update` sends a ready suite back to
review.

Arguments: `$ARGUMENTS`

## Before you start

1. Read `${CLAUDE_PLUGIN_ROOT}/references/rules.md` (§10 how to call Python, §11 web tests) and
   `${CLAUDE_PLUGIN_ROOT}/references/console-bridge.md` ("Held calls", "sign-in",
   "Web test runs", "Errors"). Below, `<run>` means `<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py"`,
   `<j>` the job id, `<s>` the console session id, `<r>` the run id, `<S>` the suite id.
2. Every subcommand prints JSON and exits 2 with a one-line message on errors. Relay the message;
   never retry the same failing call in a loop.
3. `<run> config` gives `output_dir`; a run's folder is `<output_dir>/webtest/<r>/` and a suite's
   `<output_dir>/webtest/suites/<S>/`. Never write `run.json` or `suite.json`: only the `webtest-*`
   and `suite-*` commands change them.
4. Claude never signs in, reads, types or stores an account value. The tester signs in by hand in
   their own Chrome. Rows run only on the run's hosts, which only the tester sets.
5. Questions, option labels, progress lines, park questions, scenario drafts and job summaries are
   in the job's `ui_lang`. Steps, expected values and `actual` are report content in `report_lang`;
   Japanese UI labels stay verbatim.

## From the command

1. Start the console as the `console` skill's step 1 says (`<run> console start`) and keep its
   `session` id. Start it before queueing, and queue only once the tester's console tab is open: a
   tester action on a web job is accepted only from a console tab older than the job. A job no tab
   can answer fails at claim with `no-older-tab`; queue it again as the bridge's "Errors" says.
2. Queue the job. Write the job file to a temporary file and run `<run> console queue --file <file>`.
   `ui_lang` (en or ja) is the language the tester writes in the chat when it is one of them, else
   `en`.
   - `<figma-url>`: create the suite, then queue its generate job at once (a suite left without a
     job for ten minutes is handed to the tester as it is):
     `<run> suite-new --kind figma --name "<--name, else the node id>" --figma-url "<figma-url>"
     [--project <p>]` → `{id, state: "generating"}`, then
     `{"kind": "suite-generate", "ui_lang": "en", "suite": "<S>"}`.
   - `--ticket <T>`: the same with `<run> suite-new --kind backlog --name "<--name, else T>" --ticket
     <T>`. `no-report`: tell the tester to survey the ticket first (`/testign:survey`), and stop.
   - `--run <r>`: `{"kind": "webtest-run", "ui_lang": "en", "run": "<r>", "tester": "<name>", "mode": "run"}`.
     The name is `--tester`, else ask the tester for it once in the chat. A run is made from a ready
     suite on the console's Runs screen, or with `<run> webtest-new --suite <S> --base-url <url>
     --project <p> --tester <name> [--template <t>] [--name <n>]`.
   - An error (`bad-source`, `bad-ticket`, `unknown-suite`, `suite-busy`, `unknown-run`,
     `plan-not-confirmed`, `tester-required`, and from `webtest-new`: `unknown-project`, `off-host`,
     `bad-base-url`, `template-required`, `unknown-template`): relay the message and stop. For
     `template-required`, say a template is registered on the Templates screen or with
     `<run> template-register --file <xlsx> --name <n> --purpose webtest`.
3. Tell the tester in one line that the job is queued and that they continue in the console. Then
   work the queue as the `console` skill's steps 2 to 5 say, with the same session id; the job
   comes back to this skill.

Never ask for a launch code and never open a console session of your own.

## Checks before a job

Run them once per session, before the job's first step; fail the job (`console done --result
failed` with the reason and the fix in the summary) when one fails.

- **Chrome** (`mode: run`): the session has the Claude in Chrome tools
  (`mcp__claude-in-chrome__…`, loaded or deferred). Else: "Turn on Claude in Chrome: start Claude
  Code with `claude --chrome` or run `/chrome`. It needs Google Chrome with the Claude extension
  1.0.36 or later."
- **Figma** (a Figma generate job, before the first Figma call): the session has a Figma MCP server with
  `get_metadata`, `get_design_context` and `get_screenshot`. Read the seat with `whoami` (it does
  not count against the limits); when it does not say, ask in a `questions` ask. A View or Collab
  seat, or a Starter plan, allows 20 calls a month: fail the job before any read call.
- **Site access** (`mode: run`, once per run): a `questions` ask that lists the run's hosts (from
  `<run> webtest-status --run <r>`) and asks the tester to confirm that Claude in Chrome's site
  access is limited to them. Options: "Limited to these hosts", "Stop". Stop fails the job.

## Generate job (`suite-generate`)

`params`: `suite`, `source` (`{kind: "figma", url, file, node}` or `{kind: "backlog", ticket, report,
revision, develop_head?, merge_base?}`). The suite is `generating`: only this job writes it, and
the tester cannot edit it until the job ends. Cases are checked by the same rules as a run's rows
(`${CLAUDE_PLUGIN_ROOT}/skills/webtest/triage-rules.md`): the agent never sets
`mobile_method: emulation`, never gives a real-device or `choice` case to itself, and a `not-web`
case has `runner: none`. A refused stage prints every field's message; fix those cases and stage
them again.

Stage cases with `<run> suite-stage --suite <S> --job <j> --session <s> --file <file>`, where the
file is a list of cases. An item without `case` adds a case; an item with `case` changes that
case's fields:

```json
[{"content": "<what changed>", "trace": ["B2"], "class": "sure", "kind": "text", "reason": "…",
  "viewport": "pc", "runner": "agent", "scenario": "none", "screen": "/reservations",
  "steps": "…", "expected": "…"},
 {"case": "c3", "class": "not-web", "runner": "none", "reason": "only the batch log shows it"}]
```

`screen` is a path on the site (the run adds its base URL). `<run> suite-show --suite <S>` prints
the cases and, for a Backlog suite, `coverage` (`uncovered` source rows, `orphans` traces).

### Figma

1. **Earlier suites.** `<run> suite-list` shows the other suites; when one of the same Figma link is
   `ready` or `review`, say in a progress line that the tester can duplicate it instead (the job
   goes on).
2. **Read the table.** `get_metadata` on the table node gives the header and one layer per row; the
   row's layer name carries the id of the design node that changed.
   - **One call first.** `get_design_context` on the table frame (the frame holding the `Header`
     row). Claude Code saves a large result to a file and reports its path: pass that path as
     `--context`, and the path of the saved `get_metadata` result as `--metadata`; never retype or
     copy the output. `<run> webtest-table --suite <S> --job <j> --session <s> --context <file>
     --metadata <file> --urls` → `{rows: [{row, capture_url}], skipped, numbered_by}`: rows not
     staged yet, and staged rows still without their capture. Download each URL that is not `null`
     into one new temporary folder as `<row>.png`:
     `curl -sS --fail --max-redirs 0 --max-filesize 20M -o <dir>/<row>.png "<capture_url>"`.
     Then the same command with `--captures <dir>` in place of `--urls` stages every listed row as
     a case with its `source {table_node, row_node, target_node, no}` block and its capture
     (nothing is staged while one is missing; a row whose cell holds no image is staged without one
     and listed in `without_capture`). Download no other URL from the output. `numbered_by:
     canvas` means the `No` column was not a set of distinct numbers and rows were numbered top to
     bottom; say so in a progress line.
   - **Row by row** when either result came back inline instead of as a saved file, without a
     component (metadata only), or `webtest-table` refused it ("read the table row by row: …"): the
     call still counted. Per row, `get_design_context` on the row for its text, then stage it with
     `suite-stage` as a case with its `source` block (`{"table_node", "row_node", "target_node",
     "no"}`), `type`, `content` and `creator`. Captures are kept only through `webtest-table`; say
     in the summary which cases have none.
   - Keep under the per-minute limit (10 read calls a minute; 15 on Organization, 20 on Enterprise
     when `whoami` says so). Send a progress line ("12/45 rows read") at least every two minutes.
     On a rate-limit error stop reading and close the job as failed with the count staged: what was
     staged stays in the suite for the tester.
3. **Screens.** Build a node-to-page index once per Figma file: `get_metadata` without a node lists
   the pages, then one `get_metadata` per screen page (top-level instance id → page, frame,
   viewport from the frame name). Per case: a target id starting with `I` gives its page and frame
   through its first id segment, so propose the screen path the page names and the viewport the
   frame names; a plain node gets a path proposed from the row's text and capture, or none. The
   tester checks every path on the Cases tab; open no site for this.
4. **Triage** each case by `${CLAUDE_PLUGIN_ROOT}/skills/webtest/triage-rules.md`: `kind`, `class`,
   `reason`, `viewport` (with `mobile_method: device` for a phone case), `runner`, `steps`,
   `expected`.
5. **Scenarios** (only when the suite has a project; else leave `scenario` out for the tester).
   `<run> login-scenario-list --project <p>`. Give each case the scenario its screen needs (`none`
   for public pages). When a needed scenario does not exist, ask in a `questions` ask whether to
   create it. On yes, write the draft from what the design and the tester's answers say (type
   nothing on any site) and save it:

   ```json
   {"name": "client", "label": "Client account", "login_url": "https://…/login",
    "signout_url": "https://…/logout", "steps": ["Open the login page", "Sign in with the client test account"],
    "signed_in_check": {"url": "https://…/", "text": "予約履歴"}, "account_hint": "The header shows the client user's name"}
   ```

   `<run> login-scenario-save --project <p> --file <file>`. Every URL is on the project's hosts or
   sign-in hosts; no account name, password, code or selector. A scenario with a `rejection` note
   is redrafted from that note and saved again. Tell the tester in a progress line to approve
   drafts on the Login scenarios screen.
6. Stage steps 3 to 5 on the cases with `suite-stage` items that name `case`.
7. Finish with `<run> suite-generated --suite <S> --job <j> --session <s>` and close the job with a
   summary: the suite id, counts by class, cases without a screen, a scenario or a capture,
   scenarios waiting for approval, and that the tester reviews and confirms the cases on the
   suite's Cases tab.

### Backlog

1. Read the survey report named in `params.source.report` from
   `<output_dir>/<ticket>/` (it is Markdown; read it, never edit it).
2. Write at least one case per B* row of section 3 and per R* row of section 5, with `trace` set to
   the row id (`["B2"]`; a case may trace several rows). Write only behaviour the report states;
   never invent behaviour, values or screens it does not name. A row that only the app, a batch or
   the database shows is `class: not-web`, `runner: none`, with the reason.
3. Guess each case's `screen` path from the routes and pages the report's source labels name; leave
   it out when nothing points to one (the tester fills it in). Give each case a scenario as the
   Figma step 5 says.
4. Stage the cases (in batches when there are many), then check `<run> suite-show --suite <S>`:
   every row in `coverage.uncovered` gets a case, or a line in the summary saying why not.
5. Finish with `suite-generated` and close the job as for Figma, adding the uncovered rows.

## Run job (`webtest-run`, `mode: run`)

`params`: `run`, `tester`, `mode`. A run made from a suite is already confirmed and has its columns:
there is no review table to wait for. Start with `<run> webtest-recover --run <r> --job <j> --session
<s>` (refused while a row runs in another open job: fail this job with the message), then
`<run> webtest-resolve --run <r> --job <j> --session <s>` to apply what the tester answered while no
job was open.

Loop on `<run> webtest-next --run <r> --job <j> --session <s>`:

- `{row, attempt, case}`: hand the row to the worker (below), record the outcome, send
  `console progress` with the row and the counts, then `webtest-resolve` (no `--wait`). Delegated
  answers put rows back in the queue by themselves. `finish: true` → **Finish**.
- `{row: null, need: <scenario>}` → **Sign in**, then loop.
- `{row: null, halted: true}` → **Halted**.
- `{row: null}`: when no row is open (`open` from the last resolve) → **End**. Else
  `webtest-resolve --wait` as a held call, with progress lines in between, until it applies
  something (loop again), `open` is 0 (**End**) or `finish` is true (**Finish**).

### The worker

Spawn the `testign:webtest-phone-worker` agent for a row whose `case` has `viewport: mobile` and
`mobile_method: emulation`, and the `testign:webtest-worker` agent for every other row, with: the
absolute path of
`${CLAUDE_PLUGIN_ROOT}/skills/webtest/worker-brief.md`, the `case` JSON as `webtest-next` printed
it, the capture as `<folder>/<case.capture>` when set, `report_lang`, and on the first row after a
sign-in the scenario's `signed_in_check` (from `login-scenario-list`). Run it in the background
when the runtime can, and send `console progress` at least every two minutes until it returns.

Fallback: when the agent cannot be spawned or returns "no Chrome tools in the worker", follow the
worker brief yourself, one row at a time, for the rest of the job.

| Worker outcome | Do |
|---|---|
| `pass` or `fail` with images | `<run> webtest-evidence --run <r> --row <row> --file <path>` for each path, then write `{"verdict", "actual", "url"}` and run `<run> webtest-row --run <r> --row <row> --result <file>` |
| `fail` with `reason: off-site` | `webtest-row` directly; the CLI records the row as `not-run: off-site` |
| `pass` or `fail` without an image | Treat as `stuck` |
| `stuck` | `<run> webtest-park --run <r> --row <row> --question <file>` with `{"body": "…"}`: what could not be done (reason, what the page shows) and the tester's choices (delegate with preconditions, run it themselves, skip). For a phone frame reason ("the site refuses the phone frame", "the step opens outside the phone frame"), say that running it themselves means a real phone or Chrome's device mode. The next row starts at once |
| `blocked-env` | `<run> webtest-requeue --run <r> --row <row> --reason "<reason>"`, with `--signed-out` for a login page or a failed signed-in check |
| `signed_in_as` set | A progress line: the scenario and the name the page shows |

Never rewrite a row's steps or expected value during a run.

### Sign in

1. `<run> login-scenario-list --project <project>`. When the scenario is not approved (redraft it
   first when it has a rejection note), a `questions` ask tells the tester to approve it on the
   Login scenarios screen; options "Approved" and "Stop the run" (→ **Finish**).
2. Ask `{"type": "sign-in", "id": "signin-<scenario>-<n>", "scenario": "<scenario>"}`, with
   `"switching_from": "<signed_in>"` when `webtest-next` named another signed-in scenario. Repeat
   the held call until it answers, with progress lines in between; `no-older-tab` follows the
   bridge's "Errors" row. Make no Chrome tool call, and
   start no worker, while it is open.
3. `<run> webtest-signed-in --run <r> --job <j> --session <s> --scenario <scenario>`: `signed_in`
   set → the next row of that scenario carries the signed-in check; `skipped` → those rows are
   `not-run: no-scenario`; `finish: true` → **Finish**.

### Halted

Three rows in a row were blocked by the environment. Ask in a `questions` ask with the last reason:
"Continue later" fails the job and leaves the run open (the next run job recovers it, from the run
screen or `/testign:webtest --run <r>`); "Finish the run" → **Finish**.

### Finish and End

- **Finish** (the tester ended the run): `<run> webtest-close --run <r> --stopped`, then **End**.
- **End**: `<run> webtest-close --run <r>` (skip when Finish closed it), `<run> webtest-export
  --run <r>` → `{workbook, report, counts}`. Close the job with the paths, the counts and the
  `visual` rows the tester may want to spot-check. `open-rows` on `done`: see the bridge's "Errors".

## Export job (`webtest-run`, `mode: export`)

No Chrome. `<run> webtest-recover …`, `<run> webtest-resolve …`, `<run> webtest-close --run <r>
--stopped`, `<run> webtest-export --run <r>`, then close the job with the paths and counts.

## Heartbeat and recovery

- A web job's silence counts from its last progress line, also during held calls; after two
  minutes the console warns the tester, after fifteen the job can be marked failed. Send a
  progress line at least every two minutes. Progress lines hold no account value and no file path.
- After a context compaction, `<run> webtest-status --run <r>` gives back `jobs` (job and session
  ids), the counts and the rows. A row of this job still `running` that you lost track of goes back
  with `webtest-requeue --reason "lost track of the row"`.
- A job that died leaves its run as it was; the next run job's `webtest-recover` requeues its row.
