---
name: webtest
argument-hint: <figma-url> --base-url <url> --project <p> [--name <n>] [--template <t>] [--ticket <T>] | --run <run-id> [--tester <name>]
description: Web UI test runs from a Figma change table. Queues a webtest-plan or webtest-run job in the testign console; the plan job imports and triages the table and gets one review table confirmed, the run job checks the rows one at a time in the tester's own Chrome through a worker agent, parks what cannot continue, and exports an Excel workbook and a Markdown report. Used by /testign:webtest and by the console skill for both job kinds.
---

# webtest

Turn a Figma change table into a web test run, get its review table confirmed by the tester, run
the rows in Chrome one at a time, and export the results. Everything happens in console jobs: the
tester confirms, answers and signs in on the console, never in the chat.

Arguments: `$ARGUMENTS`

## Before you start

1. Read `${CLAUDE_PLUGIN_ROOT}/references/rules.md` (§10 how to call Python, §11 web tests) and
   `${CLAUDE_PLUGIN_ROOT}/references/console-bridge.md` ("Held calls", "review-table", "sign-in",
   "Web test runs", "Errors"). Below, `<run>` means `<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py"`,
   `<j>` the job id, `<s>` the console session id, `<r>` the run id.
2. Every subcommand prints JSON and exits 2 with a one-line message on errors. Relay the message;
   never retry the same failing call in a loop.
3. `<run> config` gives `output_dir`; a run's folder is `<output_dir>/webtest/<r>/`. Never write
   `run.json`: only the `webtest-*` commands change a run.
4. Claude never signs in, reads, types or stores an account value. The tester signs in by hand in
   their own Chrome. Rows run only on the run's hosts, which only the tester sets.
5. Questions, option labels, progress lines, park questions, scenario drafts and job summaries are
   in the job's `ui_lang`. Steps, expected values and `actual` are report content in `report_lang`;
   Japanese UI labels stay verbatim.

## From the command

1. Start the console as the `console` skill's step 1 says (`<run> console start`) and keep its
   `session` id. Start it before queueing: a tester action on a web job is accepted only from a
   console tab older than the job.
2. Queue the job. Write the job file to a temporary file and run `<run> console queue --file <file>`.
   - New run: first `<run> login-scenario-list --project <p>`. "no such project": tell the tester to
     create the project with its hosts on the console's Login screen, and stop.

     ```json
     {"kind": "webtest-plan", "ui_lang": "vi", "name": "<--name, else the project and the node id>",
      "figma_url": "<figma-url>", "base_url": "<--base-url>", "project": "<p>",
      "template": "<--template>", "ticket": "<--ticket>"}
     ```

     Leave out `template` and `ticket` when not given. `ui_lang` (vi, en or ja) is the language the
     tester writes in the chat, else config `lang`.
   - `--run <r>`: `{"kind": "webtest-run", "ui_lang": "vi", "run": "<r>", "tester": "<name>", "mode": "run"}`.
     The name is `--tester`, else ask the tester for it once in the chat.
   - An error (`unknown-project`, `off-host`, `bad-source`, `bad-base-url`, `template-required`,
     `unknown-template`, `unknown-run`, `plan-not-confirmed`, `tester-required`): relay the message
     and stop. For `template-required`, say a template is registered on the Templates screen or
     with `<run> template-register --file <xlsx> --name <n> --purpose webtest`.
3. Tell the tester in one line that the job is queued and that they continue in the console. Then
   work the queue as the `console` skill's steps 2 to 5 say, with the same session id; the job
   comes back to this skill.

Never ask for a launch code and never open a console session of your own.

## Checks before a job

Run them once per session, before the job's first step; fail the job (`console done --result
failed` with the reason and the fix in the summary) when one fails.

- **Chrome** (plan job and `mode: run`): the session has the Claude in Chrome tools
  (`mcp__claude-in-chrome__…`, loaded or deferred). Else: "Turn on Claude in Chrome: start Claude
  Code with `claude --chrome` or run `/chrome`. It needs Google Chrome with the Claude extension
  1.0.36 or later."
- **Figma** (plan job, before the first Figma call): the session has a Figma MCP server with
  `get_metadata`, `get_design_context` and `get_screenshot`. Read the seat with `whoami` (it does
  not count against the limits); when it does not say, ask in a `questions` ask. A View or Collab
  seat, or a Starter plan, allows 20 calls a month: fail the job before any read call.
- **Site access** (`mode: run`, once per run): a `questions` ask that lists the run's hosts (from
  `<run> webtest-status --run <r>`) and asks the tester to confirm that Claude in Chrome's site
  access is limited to them. Options: "Limited to these hosts", "Stop". Stop fails the job.

## Plan job (`webtest-plan`)

`params`: `name`, `source` (`{kind, url, file, node}`), `base_url`, `project`, `hosts`, `template`,
optional `ticket`.

1. **Earlier imports.** `<run> webtest-find --source-ref "<file>:<node>"`.
   - A run with `complete: true`: a `questions` ask offers to reuse its import. Reuse makes no
     Figma call.
   - Only partial runs: resume from the one with the most rows staged.
2. **New run.** `<run> webtest-new --job <j> --session <s> [--name <n>]` → `{run, folder, hosts,
   project}`. When reusing or resuming, stage each row the earlier run holds from its folder:
   `<run> webtest-stage --run <r> --row <row> --case <earlier>/source/<row>.json [--capture
   <earlier>/source/<row>.png|.jpg]`, and copy its `source/page-index.json` when present.
3. **Read the table** (rows not staged yet only). `get_metadata` on the table node gives the header
   and one layer per row; the row's layer name carries the id of the design node that changed.
   Then per row: `get_design_context` on the row for its text, `get_screenshot` on its capture cell
   (download the short-lived image URL with `curl` to a temporary file). Save each row as it
   arrives, in table order `r01`, `r02`, …:

   ```json
   {"row": "r02", "source": {"kind": "figma", "file": "<file>", "table_node": "<node>",
    "row_node": "<row layer id>", "target_node": "<id from the layer name>", "no": "2"},
    "type": "Modified", "content": "<the row's text>", "creator": "<Creator>"}
   ```

   `<run> webtest-stage --run <r> --row <row> --case <file> --capture <image>`. Keep under the
   per-minute limit (10 read calls a minute; 15 on Organization, 20 on Enterprise when `whoami`
   says so). Send a progress line ("12/45 rows read") at least every two minutes. On a rate-limit
   error stop reading and fail the job with the count staged: the next plan job for the same link
   resumes. Then `<run> webtest-import --run <r>`.
4. **Screens.** Build a node-to-page index once per Figma file: `get_metadata` without a node lists
   the pages, then one `get_metadata` per screen page; save it as `<folder>/source/page-index.json`
   (top-level instance id → page, frame, viewport from the frame name). Read the site's navigation
   once: open `base_url` in a tab of your own, read its links and menus, close the tab; submit
   nothing, sign in nowhere. Then per case:
   - target id starting with `I`: look up its first id segment; page and frame give the screen and
     the viewport. Map the page to a navigation URL: `confidence: high` when both match clearly.
   - plain node: propose a screen from the row's text and capture against the navigation with
     `confidence: low`, or leave it empty (`url: ""`, `confidence: none`).
5. **Triage** each case by `${CLAUDE_PLUGIN_ROOT}/skills/webtest/triage-rules.md`: `kind`, `class`,
   `reason`, `viewport`, `runner`, `steps`, `expected`.
6. **Scenarios.** `<run> login-scenario-list --project <p>`. Give each case the scenario its screen
   needs (`none` for public pages). When a needed scenario does not exist, ask in a `questions` ask
   whether to create it. On yes, read the site's navigation for the login and sign-out addresses
   (type nothing), write the draft and save it:

   ```json
   {"name": "client", "label": "Client account", "login_url": "https://…/login",
    "signout_url": "https://…/logout", "steps": ["Open the login page", "Sign in with the client test account"],
    "signed_in_check": {"url": "https://…/", "text": "予約履歴"}, "account_hint": "The header shows the client user's name"}
   ```

   `<run> login-scenario-save --project <p> --file <file>`. Every URL is on the project's hosts or
   sign-in hosts; no account name, password, code or selector. A scenario with a `rejection` note
   is redrafted from that note and saved again. Tell the tester in a progress line to approve
   drafts on the Login screen.
7. **Store the draft.** Write `{"<row>": {kind, class, reason, viewport, runner, steps, expected,
   screen, scenario}}` and run `<run> webtest-triage --run <r> --file <file>` (again as often as
   needed before the review table).
8. **Review table.** `<run> webtest-columns --run <r> --ask > <file>`, then
   `<run> console ask <j> --session <s> --question <file>` as a held call, again with the same file
   until it answers (progress lines in between). `confirm: false`: the server has failed the job as
   `not-confirmed`; go back to waiting for jobs without `done`. Else
   `<run> webtest-plan --run <r> --job <j> --session <s>` stores what the tester confirmed.
9. **Close** with a summary: the run id, counts by class (`<run> webtest-status --run <r>`), rows
   without a screen or a scenario, scenarios waiting for approval, and that the run starts from the
   run screen or with `/testign:webtest --run <r>`.

## Run job (`webtest-run`, `mode: run`)

`params`: `run`, `tester`, `mode`. Start with `<run> webtest-recover --run <r> --job <j> --session
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
   Login screen; options "Approved" and "Stop the run" (→ **Finish**).
2. Ask `{"type": "sign-in", "id": "signin-<scenario>-<n>", "scenario": "<scenario>"}`, with
   `"switching_from": "<signed_in>"` when `webtest-next` named another signed-in scenario. Repeat
   the held call until it answers, with progress lines in between. Make no Chrome tool call, and
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
