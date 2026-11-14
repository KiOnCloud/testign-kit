# testign-kit

> **testign** = **test** + **des**ign. The spelling is intentional.

A Claude Code plugin that helps manual testers working on large legacy codebases. Before writing test cases, the tester gets an agent-generated survey of how the feature behaves today, what the current phase has already changed, and where the ticket's spec disagrees with either.

> [!WARNING]
> **Status: skeleton (v0.1.0).** The plugin installs and its commands are listed, but they only say "not implemented yet". Everything under [Planned components](#planned-components) describes intended behavior, not shipped features.

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

## Planned components

| Component | Purpose |
|---|---|
| Survey skill | Scout `master` and `develop` for a ticket and produce the survey brief |
| QA routing rules | Fact/intent classification, finding types, routing to Dev or BrSE/customer, with Japanese drafts for customer-facing questions |
| Survey report template | Already available in [`templates/`](templates/survey-report-template.md) |
| Test case trace check | Gap and orphan check between test cases and report rows |
| Local scout cache | Reuse the `master` survey per feature on the tester's machine (`~/.testign-kit/cache/`), validated by file blob hashes. The `develop` diff always runs fresh |

## Installation

### Prerequisites

- Claude Code.
- **Python 3.10 or newer** on `PATH` (`python3` on macOS; `py -3` or `python` on Windows). The skills call a small stdlib-only Python package for git and file work. Install it from [python.org](https://www.python.org/downloads/) if `python3 --version` or `py -3 --version` fails.
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

The MCP server has no wiki update tool, so `/testign:close` writes the decisions log through the Backlog REST API (`PATCH /api/v2/wikis/:wikiId`) using the same `BACKLOG_DOMAIN` and `BACKLOG_API_KEY` environment variables. Without a key that can edit the page, it prints the approved Markdown for you to paste. The page layout is in [`references/decisions-log-format.md`](references/decisions-log-format.md).

### Tester settings

Settings live in `~/.testign-kit/config.json` (`%USERPROFILE%\.testign-kit\config.json` on Windows). The file is created with defaults the first time a command runs:

| Key | Default | Meaning |
|---|---|---|
| `output_dir` | `~/Downloads` | Where reports and test case files are written |
| `lang` | `vi` | Report language (`vi`, `ja`, `en`) |
| `master_ref` / `develop_ref` | `master` / `develop` | Branch names for Production and the current phase |
| `ticket_id_regex` | Backlog keys like `PROJ-123` | How commits are grouped by ticket |
| `backlog.space`, `backlog.project_key`, `backlog.decisions_log_page` | empty | Backlog space, project and the decisions log wiki page |

## Usage

Until the plugin exists, you can use the report template directly: give it to Claude Code together with the ticket spec and access to the repository, and ask for a survey report that follows it.

The planned flow for a tester is:

1. Run the survey on a ticket against a read-only checkout of the repository.
2. Review the report and the routed questions, then send them to Dev or the BrSE.
3. Record the answers, update the report, and write test cases that reference `B*`/`R*` row IDs.
4. Run the trace check to find gaps and orphans before review.

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
│   └── survey-report-template.md   # survey report structure
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
python -m pip install pytest
python -m pytest
claude plugin validate --strict .
```

## Contributing

This repository is public. **Never commit real customer source code, specs or data**, including in examples, test fixtures or issues. Use made-up tickets and screens instead.

## License

[MIT](LICENSE)
