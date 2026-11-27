# testign-kit

> **testign** = **test** + **des**ign. The spelling is intentional.

A Claude Code plugin that helps manual testers working on large legacy codebases. Before writing test cases, the tester gets an agent-generated survey of how the feature behaves today, what the current phase has already changed, and where the ticket's spec disagrees with either.

> [!WARNING]
> **Status: v0.6.0, not yet validated on real tickets.** The survey, close, testcase, console and webtest commands, and test suites from Figma, survey reports, Excel and manual entry, are implemented and covered by tests on made-up repositories. The replay check on real released tickets, a round of the console with a real Claude Code session and a web test run from each kind of suite in Chrome are still pending, so treat survey results, generated suites and web test runs as drafts to review.

## Why

On a legacy codebase, a ticket is a change to behavior that already runs in production, not a standalone spec. When testers only read the spec, they catch contradictions inside the spec but miss conflicts with the logic that is already running. The only reliable source of that context is the source code, and developer investigations are rarely written down.

testign-kit makes that investigation an automatic step for every ticket, and turns its results into something a tester can read and a reviewer can check.

## How it works

1. **Scope from the spec.** Extract anchors from the ticket and its designs: screen names, UI labels, API names, business terms.
2. **Survey the source code.**
   - `master` at the merge-base represents **Production** behavior.
   - `git diff master...develop` (three-dot, merge-base) shows what **the current phase** has changed, grouped by ticket ID. Two-dot diffs are avoided because unmerged hotfixes would show up as phantom removals.
   - The survey follows callers and shared logic, and includes migrations and config.
3. **Compare spec against the survey** and classify each finding as a *fact* (what the code does) or an *intent* (what the business wants). When unsure, it is treated as intent.
4. **Route the questions.** Facts go to developers. Intent goes to the BrSE or the customer. Asking a developer about intent only gets the code confirming itself.
5. **Write the survey report** using [`templates/survey-report-template.md`](templates/survey-report-template.md). It describes on-screen behavior, labels every claim with its source, lists what could not be read, and keeps code references in an appendix for developers.
6. **Trace test cases.** Each test case references a report row ID (`B*` for behavior, `R*` for regression scope), so the agent can report gaps (rows with no test case) and orphans (test cases with no row).

## Components

| Component | Purpose |
|---|---|
| `/testign:survey` (skills `spec-qa` + `scout`) | Scout `master` and `develop` for a ticket and write the survey report |
| `/testign:close` (skill `qa-close`) | Classify answers, append approved decisions to the Backlog wiki decisions log, write a new report revision |
| `/testign:testcase` (skill `testcase`) | Fill a copy of your Excel template and run the gap/orphan trace check |
| `/testign:console` (skill `console`) | A local web console for tickets, reports, trace, templates and the scout cache, with a job queue this Claude Code session works through |
| `/testign:webtest` (skill `webtest`) | Build a web test suite from a Figma change table, a survey report, an Excel workbook or by hand, then run a run made from it in your own Chrome and export a workbook and a report |
| Shared rules | [`references/rules.md`](references/rules.md): language, source labels, fact/intent routing, F1–F5 |
| Survey report template | [`templates/survey-report-template.md`](templates/survey-report-template.md) |
| Local scout cache | Reuse the `master` brief per feature (`~/.testign-kit/cache/`), validated by file blob hashes. The `develop` diff always runs fresh |
| Hooks ([`hooks/hooks.json`](hooks/hooks.json)) | Block git writes in the customer repositories you put on the guard list, send a console job's questions to the console instead of the terminal, and keep the agent away from sign-in profiles and saved sessions |

## Installation

### Prerequisites

- Claude Code.
- **Python 3.10 or newer** on `PATH` (`python3` on macOS; `py -3` or `python` on Windows). The skills call a small Python package for git and file work. Install it from [python.org](https://www.python.org/downloads/) if `python3 --version` or `py -3 --version` fails.
- **openpyxl** for `/testign:testcase`: `python3 -m pip install openpyxl` (or `py -3 -m pip install openpyxl` on Windows).
- Git, and a local clone of the customer repository. The plugin only reads it (`git show`, `git diff`, `git log`, `git grep`) and never checks out or changes the working tree.
- The Backlog MCP server (see below) for reading tickets and the wiki.
- Optional, for recording and replaying web tests: **Playwright for Python** and its Chromium. Set
  `TESTIGN_BROWSER_EXECUTABLE` to use another Chromium build. Nothing else needs it.

`python3 scripts/run.py setup` (in the installed plugin folder; `py -3` on Windows) checks Python and
openpyxl; add `--webtest`, or `--browser chromium --browser firefox ...`, to check Playwright and each
browser too. `--install` installs what it can without admin rights (`pip install --user`, `playwright
install <browser>`) and prints the commands left for you: Microsoft Edge is the system's Edge, and on
Linux the browsers' system libraries need `sudo python3 -m playwright install-deps`.

### Install the plugin

This repository is its own plugin marketplace. In Claude Code:

```text
/plugin marketplace add KiOnCloud/testign-kit
/plugin install testign@testign-kit
```

Or in one step on Claude Code 2.1.275 or later:

```text
/plugin install testign --marketplace KiOnCloud/testign-kit
```

The commands are namespaced by the plugin name: `/testign:survey`, `/testign:close`, `/testign:testcase`. See the official docs on [installing plugins](https://code.claude.com/docs/en/discover-plugins) for scopes, updates and removal.

### Update the plugin

This marketplace does not update by itself: Claude Code turns auto-update off for third-party
marketplaces unless you turn it on (`/plugin` → **Marketplaces** → `testign-kit`). To update by
hand, without mixing an old console with new commands:

1. Finish or cancel the open console jobs, then stop the console with `console stop` (see
   [Console](#console); it refuses while a job is open).
2. Update the marketplace listing and the plugin from your shell:

   ```bash
   claude plugin marketplace update testign-kit
   claude plugin update testign@testign-kit
   ```

   Or in a session: `/plugin` → **Marketplaces** → `testign-kit` → **Update marketplace**, which also
   updates the installed plugin.
3. Run `/reload-plugins` in the open session, or start a new session.
4. Start the console again (`/testign:console`, or `console start`) and check the version with
   `<python> scripts/run.py --version`.

`claude plugin list` shows the installed version. A console server still running from the old
version keeps serving the old pages until it is stopped, so always stop it before updating.

### Backlog MCP server

Tickets, comments and the wiki are read through Nulab's official [`backlog-mcp-server`](https://github.com/nulab/backlog-mcp-server). Add it to your own Claude Code MCP config with your own credentials; this repository never ships API keys or an `.mcp.json`.

```bash
claude mcp add backlog -e BACKLOG_DOMAIN=<space>.backlog.com -e BACKLOG_API_KEY=<your key> -- npx backlog-mcp-server
```

Tools the plugin uses: `get_issue`, `get_issue_comments`, `get_issue_attachment`, `get_wiki_pages`, `get_wiki`.

The decisions log is split into one wiki page per feature (same name as the scout cache feature), a `common` page for shared logic, and an index that lists every decision with its anchors. `/testign:survey` looks up the index by the ticket's anchors and opens every matching page, so a decision filed under another feature is still found.

The MCP server has no wiki update tool, so `/testign:close` writes the decisions log through the Backlog REST API (`PATCH` / `POST /api/v2/wikis`), creating feature pages and the index when they do not exist yet. The helper reads `BACKLOG_DOMAIN` and `BACKLOG_API_KEY` from your **shell environment**; values passed only to the MCP server with `-e` are not visible to it, so set them as user environment variables as well (`export ...` in your shell profile on macOS, `setx BACKLOG_API_KEY ...` on Windows, then restart Claude Code). The key is never printed or logged. Without these variables, or without a key that can edit the pages, `/testign:close` shows the diffs and prints the new page contents for you to paste. The page layout is in [`references/decisions-log-format.md`](references/decisions-log-format.md); the Backlog project's text formatting rule must be Markdown.

### Tester settings

Settings live in `~/.testign-kit/config.json` (`%USERPROFILE%\.testign-kit\config.json` on Windows). The file is created with defaults the first time a command runs:

| Key | Default | Meaning |
|---|---|---|
| `output_dir` | `~/Downloads` | Where reports and test case files are written |
| `lang` | `vi` | Report language (`vi`, `ja`, `en`); the console's own language is chosen in the console |
| `master_ref` / `develop_ref` | `master` / `develop` | Branch names for Production and the current phase |
| `ticket_id_regex` | Backlog keys like `PROJ-123` | How commits are grouped by ticket |
| `backlog.space`, `backlog.project_key` | empty | Backlog space and the project that holds the decisions log |
| `backlog.decisions_log_prefix` | `QA/Decisions` | Wiki name prefix of the decisions log: `<prefix>/index`, `<prefix>/common` and one `<prefix>/<feature>` page per feature |
| `backlog.text_format` | `markdown` | The Backlog project's text formatting rule; `backlog` (Backlog notation) disables the decisions log commands |
| `console.port` | `4791` | Port of the local console on `127.0.0.1` |
| `console.idle_minutes` | `30` | The console server ends after this many minutes without use when no job is open |

Reports, briefs and test case files for a ticket go to `<output_dir>/<TICKET>/`. Report revisions are named `<TICKET>-survey-r<N>.md` and are never overwritten.

### Scout cache

The Production part of a survey (the master brief) is cached per repository and feature in `~/.testign-kit/cache/<root-commit>/<feature>/`. It is reused only when every source file's blob hash at the new merge-base still matches; rows whose files changed are re-read, and the report's coverage section says whether the cache was a hit, partial or miss. To clear it, delete that folder (or the whole `~/.testign-kit/cache/`).

### Models and token use

Most of a survey's tokens go into scouting: reading up to 40 source files and the phase diff. So
`scout` runs as a separate subagent (`context: fork` in its `SKILL.md`) pinned to `model: sonnet`
with `effort: medium`. The source code it reads stays in that subagent; `/testign:survey` only gets
back the brief file. The other skills (`spec-qa`, `qa-close`, `testcase`) read little but make the
judgment calls (fact or intent, verbatim quotes, writes to the shared wiki), so they run on whatever
model your session uses.

The pin is an alias, so it follows the current Sonnet without plugin updates. Each cache entry
records the model its brief was written with (`scout_model` in `manifest.json`), and the report's
coverage section shows it when a cached brief is reused, so a brief can be traced back if a model
turns out too weak for a codebase.

To run `scout` on another model, set both variables in your Claude Code settings `env`:

```json
{ "env": { "CLAUDE_CODE_SUBAGENT_MODEL": "opus", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1" } }
```

`CLAUDE_CODE_SUBAGENT_MODEL` alone does not override a model pinned in a skill, and the force flag
applies to every subagent in your sessions, not only this plugin's. Remove it when you are done.

### Test case templates

`/testign:testcase` fills a copy of your own Excel test case template. On the first run it asks for the template file and a name, detects the header row and which column holds each field (`No`, 確認項目, 手順, 期待結果, エビデンス, 備考), and registers it. You can register several templates (for example one per customer) and pick one per run; `template-preview` shows a template's sheets, header and column mapping as a small Markdown table in chat instead of having the model read the workbook.

Registering a template again under the same name (`--replace`, or *Replace* on the Templates screen)
makes a new version and keeps the earlier ones (up to ten). A web test run records the version its
export columns were made for and keeps exporting with it, so a changed template never shifts the
columns of an older run; a new run takes the current version.

Registered templates are copied to `~/.testign-kit/templates/` with an `index.json` that records each name, sheet, header row and column mapping. They live there, not inside the installed plugin folder, so plugin updates keep them and customer templates never end up in this public repository.

If you have no template yet, a basic made-up one ships with the plugin: [`templates/testcase-template-sample.xlsx`](templates/testcase-template-sample.xlsx).

## Usage

1. **Survey:** `/testign:survey PROJ-123 --repo <path to your clone>`. Reads the ticket, scouts the repo, reads the decisions log and writes `PROJ-123-survey-r1.md`. Add `--master-ref <sha> --develop-ref <sha>` to replay an old ticket, `--fetch` to update refs first.
2. **Send the questions:** the report lists questions for Dev and for the BrSE/customer (with Japanese drafts). Send them yourself; the plugin never posts to Backlog.
3. **Close:** `/testign:close PROJ-123`. Collects answers from the ticket's comments and from you, asks you to approve each decision and then the wiki diff, appends the approved decisions to the decisions log, and writes the next report revision.
4. **Test cases:** `/testign:testcase PROJ-123`. Checks that the report's pinned commits are still current, fills a copy of your template (each case carries its `B*`/`R*` ID in 備考), and writes gaps, orphans and cases waiting on QA into a new report revision.

The report defaults to Vietnamese (falling back to Japanese, then English), and Japanese UI labels are kept verbatim so testers can match them against the screen.

When `/testign:close` previews the decisions log, it checks every quote whose source links a Backlog
comment (`https://<your space>/view/PROJ-123#comment-<id>`) against that comment's text, ignoring
whitespace and full-width/half-width differences. A quote that is not in the comment, or a link to a
comment that does not exist, stops the preview; quotes from other sources are listed as unchecked.

### Guard a customer repository

The survey only reads the customer's repository. To make sure nothing in a Claude Code session
writes to it, put the clone on the guard list:

```bash
python "<plugin root>/scripts/run.py" guard enable --repo <path to your clone>
python "<plugin root>/scripts/run.py" guard status --repo <path to your clone>
python "<plugin root>/scripts/run.py" guard disable --repo <path to your clone>
```

While a repository is on the list, the plugin's `PreToolUse` hook blocks commands that change it
(commit, push, merge, rebase, reset, checkout, switch, new branches, tags, stash, worktree removal,
`gh pr` writes …), writes into its `.git` folder, and any change to the guard list itself, from Bash
and from the file tools. Read-only commands (`status`, `log`, `diff`, `show`, `fetch`, `gh pr view` …)
still work. The list lives in `~/.testign-kit/guarded_repos.json`, so nothing is written into the
customer repository. Only you enable or disable a repository: the hook blocks the agent from running
`guard disable`. When the list is empty the hook does nothing, and when it cannot find Python 3.10 it
blocks only while the list has repositories on it. The guard catches accidental and habitual
source-control changes; it is not a security boundary, since a script file or another interpreter
can still reach git.

## Console

`/testign:console` opens a local web page on `127.0.0.1` (port 4791 by default) and keeps the Claude
Code session attached to it. Its menu has three groups:

- **Test case design:** *Test suites* (the cases of a web test, see below) and *Ticket survey* (every
  ticket under `output_dir` with its latest survey report and the trace between a report and a
  filled workbook).
- **Test runs:** *Runs* (web test runs made from a suite, their results and exports) and *Agent &
  jobs* (the attached session, the tools it reported and the job queue).
- **Settings:** *Projects & hosts*, *Login scenarios*, *Templates* (register, set default, remove),
  *Scout cache* and *Preferences* (theme, interface language, your tester name; the `config.json`
  values are shown read-only).

The console is in English or Japanese; report content, quotes and template headers stay as written.
Japanese text uses the system's Japanese font, so on Linux install one (for example Noto Sans CJK).

From the console you queue jobs: survey a ticket, close QA, write test cases, write §7, generate a
test suite, run or export a web test. The attached
session takes them one at a time, follows the same skills as the chat commands and asks you its
questions in the console (row review with edits, the wiki diff as the tool computed it, pasted
answers). The session must be running `/testign:console`; with no session attached, queued jobs wait.

```bash
<python> scripts/run.py console start     # start or reuse the server and open the browser
<python> scripts/run.py console open      # a fresh single-use link, e.g. after closing the tab
<python> scripts/run.py console status
<python> scripts/run.py console stop      # --force while jobs are open (they fail)
```

What it can and cannot change:

- The server itself writes only under `~/.testign-kit/console/` (its state, job records, temporary
  uploads), `~/.testign-kit/templates/` (template registration), `~/.testign-kit/webtest/`
  (projects, login scenarios, your answers and images for web test runs) and
  `<output_dir>/webtest/`, where it keeps test suites, creates a run from a confirmed suite and
  changes a run's export columns while no job works on it. It never changes a report, a repository
  or `config.json`.
- Reports, workbooks and the Backlog wiki change only through jobs the session runs, with the same
  guards as the chat commands: report revisions are never overwritten, and the wiki is written only
  after you confirmed the exact diff in the console.

Security model:

- The server listens on `127.0.0.1` only and refuses requests from other host names, other origins
  and cross-site pages. The browser gets its session through a single-use link that `console start`
  and `console open` hand to the browser; the agent's own token works only on the agent routes.
- Limit: the agent runs as you, so an agent misled by text in a ticket could still mint itself a
  console link and open a browser session. Two guards make that visible and harder: every new console
  tab is announced in the tabs already open (if you did not open it, press "Release agent"), and a tab
  opened after a job started cannot answer that job's questions.
- The wiki diff you confirm is computed by the server from the page contents the approval hash covers,
  not taken from the agent, and `wiki-update --job` writes only that confirmed approval.
- The console lists folders under `output_dir`, which defaults to `~/Downloads`. Only folders named
  like a ticket with a consistent report revision are shown; other files are not read. Ticket text,
  comments and reports are treated as data, but use the console for tickets you trust.
- It ends by itself after 30 minutes without use (`console.idle_minutes`) when no job is open.

Limits:

- Run it on your own Windows or macOS machine, where the browser reaches `127.0.0.1`. In a cloud
  session it refuses to start. Over SSH, forward the port (`ssh -L 4791:127.0.0.1:4791 …`) and run
  `console open --print` for a single-use URL.
- If another program holds the port, set another one in `console.port` of `config.json`.

### Web test suites and runs

`/testign:webtest` tests a web change in your own Chrome. The cases live in a **test suite**; a run
copies a confirmed suite, so editing the suite later never changes a run. Running needs the Claude in
Chrome extension; a Figma suite needs the Figma MCP server (a seat that can read the file). The
session tells the console which of these tools it has, and *Agent & jobs* shows them.

1. **Projects & hosts:** create a project and its allowed hosts. Only you edit hosts, and only here;
   the agent runs cases on those hosts and nowhere else.
2. **Login scenarios:** a scenario is a checklist for signing in by hand. The agent drafts one when
   a case needs it, and you approve or reject it with a note.
3. **Test suites → New suite:** pick where the cases come from.
   - *Figma:* a change table link with `node-id`. The agent reads the table once, one case per row
     with its capture, and guesses each case's screen and login scenario.
   - *Ticket survey:* a survey report revision. The agent writes cases from its behavior (`B*`) and
     regression (`R*`) rows; the suite's coverage shows which rows have a case.
   - *Excel:* a workbook (`.xlsx` or `.xlsm`, up to 10 MB and 2000 rows) laid out as one of your
     registered templates. The server reads it itself; no agent job is needed.
   - *Manual:* you type every case.

   A suite generated by the agent stays *generating* until the job ends, then waits for your
   *review*. On its Cases tab you edit cases (one at a time or in bulk), duplicate or delete them,
   then confirm; a confirmed suite is *ready*. No case runs before you confirm. A case the agent runs
   that writes data needs the preconditions you name.

   **Test depth.** Each suite has a test depth, picked in the wizard: *Smoke* (display and the
   normal action of each control), *Standard*, the default (adds button state with empty, missing
   or wrong input, limits and the values next to them, message text, each role) or *Thorough* (adds
   refill, character types, length, every pair of input values, double press, leaving with unsaved
   input). The agent lists the controls the change touches and tags each case with the kit check it
   covers. The suite's *Checks* tab lists every check per control with its status; a check that
   does not apply is skipped there with a reason, and a suite with a missing check cannot be
   confirmed. *Change depth* stores a new depth; when it requires more checks, *Add missing cases*
   queues a job that adds only those cases. The suite's Excel export adds a *Coverage* sheet. A
   suite made before test depth tracks nothing until you set one. `/testign:testcase` takes the
   same depth (`--depth`) and reports the missing checks in its output.
4. **Runs → New run:** pick a ready suite, the test base URL on one of the project's hosts, your
   name and a template. The run's export columns can be changed on the run while no job works on it.
5. **Run:** the agent works one case at a time in your Chrome and saves a screenshot per case. It
   stops at a sign-in card when the scenario changes; you sign in yourself and press "Signed in". It
   parks cases it should not decide (you delegate them with preconditions, run them yourself, or
   skip them), and cases you run yourself wait for your result and an optional image.
6. **Defects:** every failed row (the agent's fail or your own) has a defect draft built from the
   row: title, steps, expected, actual, page URL and evidence. Edit it in the row's panel, copy it
   as text into Backlog or any tracker, file it there yourself, then mark it *Sent* with the
   tracker key, or *Not a defect* with the reason. testign posts nothing anywhere. The *Defects*
   screen lists the defects of every run, drafts first. A saved defect stays when the row passes
   later and is marked as written for an earlier failure.
7. **Results across runs:** a row that failed in the previous run of the same suite on the same
   project, with the case unchanged, and passes now is marked *Fixed*; the row panel shows the
   previous run's result. The suite's Runs tab has a case-by-run table of its newest eight runs.
8. **Export:** the run's workbook (a copy of your template) and a report, written next to the run.
   The cover placeholders `<project>`, `<TICKET-ID>`, `<tester>`, `<YYYY-MM-DD>` and `<suite>` are
   filled from the run where the template has them, a run from a survey suite adds a `Trace` column
   with the `B*`/`R*` rows each case covers, and each Figma row's `No` cell (its content cell when the
   column plan has no `No` column) links to its capture. The links point into the run folder, so keep
   the workbook next to its `source` folder. The report also lists the rows fixed since the
   previous run and the run's defects with their status and tracker key.

9. **Record once, replay later:** a sure case the agent runs on PC (a label, element or behaviour
   change) can be replayed without the agent. Press *Record (Playwright)* on a run: the agent walks
   each such row step by step in a Playwright browser, and every step is tried from a fresh page, so
   what it saves is what replay does. A submit the app received while recording is answered from
   the kept reply afterwards, so the app sees it once. The steps go into the suite's *Replay spec*
   tab as a draft, with warnings for checks that may not hold next time (a date or count in a
   locator, a value not in the expected result, an expected "disabled" that no step checks). A
   control's state is checked as such (enabled, disabled, checked, read-only…), and a "disabled"
   button is also pressed anyway: if it still sends data, changes the page or shows the success
   message, the row fails, so a button that only looks disabled is caught. After you review them there (*Mark reviewed*), a
   later run shows *Replay N*: the rows run from the spec with no agent and no Chrome. A failed check
   is a *fail* with a screenshot; a step that cannot run marks the row *not run: spec error* (fix the
   spec, not the app); a failed sign-in marks the rows of that scenario *not run: session expired*.
   Editing a case or a step clears the review, and a changed case is not replayed.

   A row that fails or cannot run is tried once more; if it passes then, it is a pass marked
   *Flaky* (in the row, the report's flaky list and an optional *Flaky mark* export column).

   *Browsers for replay* on New run picks where replay runs each row: Chromium (default), Microsoft
   Edge, Firefox and WebKit (Safari's engine). The row fails if one browser fails, the export gets a
   result column per browser, and a browser that is not installed leaves its column *Pending*
   (`setup --browser <name> --install` adds it). Runs in your own Chrome are not affected.

   **Replay with nobody at the console.** A scheduler can run a suite's reviewed spec on its own:

   ```bash
   python3 scripts/run.py webtest-replay-new --suite <suite id> --base-url https://staging.example.test/ \
       --project <project> --tester nightly --browser chromium --export
   ```

   It makes a new run, replays every row with a reviewed spec, and with `--export` closes and exports
   the run when no row is left open (rows without a spec stay queued for a run in Chrome).
   `webtest-replay --run <run id>` without `--job` replays the queued rows of an existing run; it
   refuses while a console job has a row running. Schedule it with cron
   (`0 2 * * 1-5 cd <plugin folder> && python3 scripts/run.py webtest-replay-new ...`) or the
   Windows Task Scheduler (`schtasks /Create /SC DAILY /ST 02:00 /TN testign-nightly /TR "py -3
   <plugin folder>\scripts\run.py webtest-replay-new ..."`). It signs in with the approved Login
   Recipe, so the computer must stay on and signed in to your account.

#### Login Recipe

Record and replay sign in by themselves with a scenario's **Login Recipe**: the sign-in steps the
agent drafts (`login-recipe-save`), with `{{username}}` and `{{password}}` placeholders instead of
values. You type the values yourself: in the scenario's dialog on the *Login scenarios* screen
(*Account values of profile …*, with the staging box ticked), or in your own terminal:

```bash
python3 scripts/run.py profile-set --project <project> --profile <profile> --key username --key password
```

Both ask you to confirm the account is a **dedicated staging test account** (use nothing else). The
console form is write-only: it starts empty, the server never sends a value back, and only your
console tab may call it. The terminal command reads each value without echo, refuses piped input,
and both write
`~/.testign-kit/webtest/profiles/<project>/<profile>.json` readable by you only (mode 600; the
values are plain text in that file). The agent then tests the recipe (`login-recipe-test`), and you
check the steps and press *Approve recipe* in the scenario's dialog. A recipe is used only with its
values set, a passing test and your approval; saving it again clears both. The signed-in browser
session is kept in `~/.testign-kit/webtest/sessions/` (mode 600) and refreshed when it expires.

The plugin's secret guard hook blocks the agent from reading, searching or editing the profiles and
sessions folders, from running `profile-set` or `profile-remove`, and from approving a recipe or
writing a profile through the console API. Errors and recordings are redacted of profile values. Runs in your own Chrome
(*Run*) still never use a profile: you sign in by hand.

Runs made before suites existed (run file version 1, imported straight from a Figma table) still
open, run and export; the old import job (`webtest-plan`) is retired, and a queued one fails with
`retired-kind` when the console starts.

Helpers the agent uses so a Figma table is read once:

- `webtest-table --urls`, then `--captures <dir>`: the whole change table read with one
  `get_design_context` call when it fits, with only Figma asset URLs downloaded. A table of another
  shape is read row by row.
- When every console tab was opened after a job was queued, no one may answer it: the job fails
  at claim with `no-older-tab` before any work, the agent queues it again once (the job card says
  "Queued again"), and a newer tab shows a notice instead of answer buttons. If that fails too, or
  the console has no tab at all, the agent asks you to open the console. A tab that was opened
  earlier and then closed still counts, so keep the tab you queued from open.

A template's purpose is set when you register it: *test cases* (needs the item and trace columns) or
*web test* (needs the item column; result columns can be added on the run's export columns). An
Excel suite reads a workbook through a template's item, steps, expected and trace columns.

Where things live:

- Suites: `<output_dir>/webtest/suites/<suite id>/` holds `suite.json`, the Figma captures, an
  uploaded Excel source and the replay spec (`spec.json`).
- Runs: `<output_dir>/webtest/<run id>/` holds `run.json`, the captures, the evidence screenshots
  and the exports. The agent's commands write there; the console only creates `run.json` from a
  suite and changes its export columns.
- `~/.testign-kit/webtest/` holds the projects, login scenarios, your answers to parked rows, your
  results, your saved defects and the images you upload. It is created readable by you only (mode 700 on macOS and
  Linux). On Windows, mode bits do nothing: the folder takes the ACL of your user profile, which by
  default lets only you and administrators read it.
- No screen takes or shows an account name or password. Only `profile-set`, typed by you, stores
  one (see Login Recipe), and the agent never types into a sign-in form in your Chrome.

Limits:

- Page text and Figma text are data. The agent does not follow instructions it reads on a page, and
  it presses a button that changes data only on a row you delegated with preconditions.
- A tester action on a run is accepted only from a console tab older than the run's queued or open
  job. That keeps a tab opened during a job from acting on it, but not a tab opened before the job:
  an agent misled into minting itself a console link before the job started would pass this check.
  The new-tab notice above still shows such a tab.
- Cases at phone width are checked on a real phone by you unless you switch a case to emulation in
  the suite; the agent then checks it in a 390 px phone frame inside your Chrome (same
  sign-in, desktop user agent, no touch). For those rows only, a separate worker agent runs two
  fixed page scripts in your signed-in tab: one that draws the frame and one that reads the
  frame's text. The rule that it runs nothing else is written in its instructions, not enforced by
  a tool, so give the agent emulation rows only on sites you would let it script.
- The secret guard matches what a tool call names: a file path, a search folder, or the text of a
  command. A command that reaches the profiles folder without naming it (a script that builds the
  path) is not caught. That is why a profile may hold only a dedicated staging test account.
- A scheduled replay runs as you, with your profiles, whenever the computer is on: schedule it only
  against a staging environment, and remember it changes data the same way the recorded steps did.

## Repository layout

```text
.
├── .claude-plugin/
│   ├── plugin.json                 # plugin "testign"
│   └── marketplace.json            # marketplace "testign-kit"
├── .github/workflows/test.yml      # pytest + claude plugin validate on Windows and macOS
├── commands/                       # /testign:survey, /testign:close, /testign:console, /testign:webtest
├── skills/                         # scout (internal), spec-qa, qa-close, testcase (/testign:testcase), console, webtest
├── agents/                         # web test workers that check one case in Chrome
├── hooks/                          # PreToolUse hooks: git guard, console questions, secret guard
├── references/
│   ├── rules.md                    # shared rules every skill reads
│   ├── decisions-log-format.md     # Backlog wiki decisions log format
│   └── console-bridge.md           # how the session works the console's job queue
├── templates/
│   ├── survey-report-template.md   # survey report structure
│   └── testcase-template-sample.xlsx # basic sample test case template
├── scripts/
│   ├── run.py                      # single entry point the skills call
│   └── testign/                    # python package (config, git scoping, ...)
│       ├── webtest_sources.py      # where suite cases come from (figma, backlog, excel, manual)
│       ├── webtest_suite.py        # test suites: cases, review and confirmation
│       ├── coverage_rules.py       # test depth: the kit checks each control needs
│       ├── webtest.py              # web test runs, copied from a suite
│       ├── webtest_history.py      # results across runs and the Fixed mark
│       ├── webtest_defects.py      # defect drafts for failed rows
│       ├── webtest_spec.py         # a suite's replay spec and its review
│       ├── webtest_record.py       # record mode: steps tried one by one in Playwright
│       ├── webtest_replay.py       # replay mode: queued rows from the reviewed spec
│       ├── webtest_live.py         # the Playwright engine (optional dependency)
│       ├── login_recipe.py         # Login Recipes, profiles and saved sessions
│       ├── secret_guard.py         # the hook that keeps the agent away from profiles
│       ├── setup_check.py          # the setup command: dependencies and browsers
│       ├── git_guard.py            # guard list and the git write guard hook
│       └── console/                # console server, read API, job queue, suite API
│           └── ui/                 # browser UI: ES modules, no build step, Yohaku styles, en/ja
├── tests/                          # pytest
├── pyproject.toml
├── LICENSE
└── README.md
```

### Development

```bash
python -m pip install pytest openpyxl
python -m pytest
node --test "scripts/testign/console/ui/tests/*.test.mjs"
claude plugin validate --strict .
```

## Contributing

This repository is public. **Never commit real customer source code, specs or data**, including in examples, test fixtures or issues. Use made-up tickets and screens instead.

## License

[MIT](LICENSE)
