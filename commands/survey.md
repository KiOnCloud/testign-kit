---
description: Survey a Backlog ticket against master (merge-base) and develop, and write the survey report
argument-hint: <TICKET-ID> [--repo <path>] [--master-ref <ref>] [--develop-ref <ref>] [--fetch] [--lang vi|ja|en] [--feature <name>]
---

Run the `spec-qa` skill of the testign plugin for these arguments: `$ARGUMENTS`

- The first argument is the ticket ID. If it is missing, ask for it.
- `--repo` is the tester's local clone of the customer repository. It is only read, never checked out.
- `--master-ref` / `--develop-ref` accept branch names or commit SHAs (use SHAs to replay an old ticket).
  Defaults come from `~/.testign-kit/config.json`.
- `--fetch` runs `git fetch` first; without it, nothing touches the network.
- `--lang` overrides the report language (default from config, then vi > ja > en).
- `--feature` names the scout cache entry (default: the main screen in the spec).

The report is written to `<output_dir>/<TICKET>/<TICKET>-survey-r<N>.md` and existing revisions are
never overwritten.
