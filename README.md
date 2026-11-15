# testign-kit

> **testign** = **test** + **des**ign. The spelling is intentional.

A Claude Code plugin that helps manual testers working on large legacy codebases. Before writing test cases, the tester gets an agent-generated survey of how the feature behaves today, what the current phase has already changed, and where the ticket's spec disagrees with either.

> [!WARNING]
> **Status: v0.2.0, not yet validated on real tickets.** All three commands are implemented and covered by tests on made-up repositories. The replay check on real released tickets is still pending, so treat survey results as a draft to review.

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
| Shared rules | [`references/rules.md`](references/rules.md): language, source labels, fact/intent routing, F1–F5 |
| Survey report template | [`templates/survey-report-template.md`](templates/survey-report-template.md) |
| Local scout cache | Reuse the `master` brief per feature (`~/.testign-kit/cache/`), validated by file blob hashes. The `develop` diff always runs fresh |

## Installation

### Prerequisites

- Claude Code.
- **Python 3.10 or newer** on `PATH` (`python3` on macOS; `py -3` or `python` on Windows). The skills call a small Python package for git and file work. Install it from [python.org](https://www.python.org/downloads/) if `python3 --version` or `py -3 --version` fails.
- **openpyxl** for `/testign:testcase`: `python3 -m pip install openpyxl` (or `py -3 -m pip install openpyxl` on Windows).
- Git, and a local clone of the customer repository. The plugin only reads it (`git show`, `git diff`, `git log`, `git grep`) and never checks out or changes the working tree.
- The Backlog MCP server (see below) for reading tickets and the wiki.

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
| `lang` | `vi` | Report language (`vi`, `ja`, `en`) |
| `master_ref` / `develop_ref` | `master` / `develop` | Branch names for Production and the current phase |
| `ticket_id_regex` | Backlog keys like `PROJ-123` | How commits are grouped by ticket |
| `backlog.space`, `backlog.project_key` | empty | Backlog space and the project that holds the decisions log |
| `backlog.decisions_log_prefix` | `QA/Decisions` | Wiki name prefix of the decisions log: `<prefix>/index`, `<prefix>/common` and one `<prefix>/<feature>` page per feature |
| `backlog.text_format` | `markdown` | The Backlog project's text formatting rule; `backlog` (Backlog notation) disables the decisions log commands |

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

Registered templates are copied to `~/.testign-kit/templates/` with an `index.json` that records each name, sheet, header row and column mapping. They live there, not inside the installed plugin folder, so plugin updates keep them and customer templates never end up in this public repository.

If you have no template yet, a basic made-up one ships with the plugin: [`templates/testcase-template-sample.xlsx`](templates/testcase-template-sample.xlsx).

## Usage

1. **Survey:** `/testign:survey PROJ-123 --repo <path to your clone>`. Reads the ticket, scouts the repo, reads the decisions log and writes `PROJ-123-survey-r1.md`. Add `--master-ref <sha> --develop-ref <sha>` to replay an old ticket, `--fetch` to update refs first.
2. **Send the questions:** the report lists questions for Dev and for the BrSE/customer (with Japanese drafts). Send them yourself; the plugin never posts to Backlog.
3. **Close:** `/testign:close PROJ-123`. Collects answers from the ticket's comments and from you, asks you to approve each decision and then the wiki diff, appends the approved decisions to the decisions log, and writes the next report revision.
4. **Test cases:** `/testign:testcase PROJ-123`. Checks that the report's pinned commits are still current, fills a copy of your template (each case carries its `B*`/`R*` ID in 備考), and writes gaps, orphans and cases waiting on QA into a new report revision.

The report defaults to Vietnamese (falling back to Japanese, then English), and Japanese UI labels are kept verbatim so testers can match them against the screen.

## Repository layout

```text
.
├── .claude-plugin/
│   ├── plugin.json                 # plugin "testign"
│   └── marketplace.json            # marketplace "testign-kit"
├── .github/workflows/test.yml      # pytest + claude plugin validate on Windows and macOS
├── commands/                       # /testign:survey, /testign:close
├── skills/                         # scout (internal), spec-qa, qa-close, testcase (/testign:testcase)
├── references/
│   ├── rules.md                    # shared rules every skill reads
│   └── decisions-log-format.md     # Backlog wiki decisions log format
├── templates/
│   ├── survey-report-template.md   # survey report structure
│   └── testcase-template-sample.xlsx # basic sample test case template
├── scripts/
│   ├── run.py                      # single entry point the skills call
│   └── testign/                    # python package (config, git scoping, ...)
├── tests/                          # pytest
├── pyproject.toml
├── LICENSE
└── README.md
```

### Development

```bash
python -m pip install pytest openpyxl
python -m pytest
claude plugin validate --strict .
```

## Contributing

This repository is public. **Never commit real customer source code, specs or data**, including in examples, test fixtures or issues. Use made-up tickets and screens instead.

## License

[MIT](LICENSE)
