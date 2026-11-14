# testign-kit

> **testign** = **test** + **des**ign. The spelling is intentional.

A Claude Code plugin that helps manual testers working on large legacy codebases. Before writing test cases, the tester gets an agent-generated survey of how the feature behaves today, what the current phase has already changed, and where the ticket's spec disagrees with either.

> [!WARNING]
> **Status: early design.** The plugin itself is not written yet. This repository currently holds only the survey report template. Everything under [Planned components](#planned-components) describes intended behavior, not shipped features.

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

The plugin is not published yet, so there is nothing to install today. Once it ships, this repository will also act as its own plugin marketplace, and installation will follow the standard Claude Code flow:

```text
/plugin marketplace add KiOnCloud/testign-kit
/plugin install testign-kit@testign-kit
```

Or from your shell:

```bash
claude plugin install testign-kit --marketplace KiOnCloud/testign-kit
```

The final plugin and marketplace names may change before release. See the official docs on [installing plugins](https://code.claude.com/docs/en/discover-plugins) for scopes, updates and removal.

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
├── templates/
│   └── survey-report-template.md   # survey report structure and agent instructions
├── LICENSE
└── README.md
```

## Contributing

This repository is public. **Never commit real customer source code, specs or data**, including in examples, test fixtures or issues. Use made-up tickets and screens instead.

## License

[MIT](LICENSE)
