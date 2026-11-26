---
name: spec-qa
description: Compare a Backlog ticket's spec with the scout brief and write the survey report (behavior table B*, regression scope R*, findings F1-F5 routed to Dev or BrSE with Japanese drafts). Used by /testign:survey.
---

# spec-qa

Write the survey report for one ticket: what Production does today (master at the merge-base), what
this phase already changed (`git diff master...develop`), and where the spec disagrees with either.

Inputs from `/testign:survey`: `ticket`, and optionally `repo`, `lang`, `master_ref`, `develop_ref`
(branch names or SHAs, used for replays), `fetch`, `feature` (cache name).

## Before you start

1. Read `${CLAUDE_PLUGIN_ROOT}/references/rules.md` and follow it throughout. Below, `<run>` means
   `<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py"` (rules §10).
2. Read `${CLAUDE_PLUGIN_ROOT}/templates/survey-report-template.md`. The report must follow its
   frontmatter and section order exactly.
3. Read `<run> config`: `output_dir`, `lang`, refs, `backlog.*`. Report files live in
   `<output_dir>/<TICKET>/` (get the paths with `<run> report-path --ticket <TICKET>`).
4. If `repo` was not given, ask the tester for the path of their local clone once, and remember it in
   the report frontmatter.
5. `<run> guard status --repo <repo>`. When `guarded` is false, tell the tester once, in one line, that
   `<run> guard enable --repo <repo>` makes the plugin block git commands that would change this
   repository (commit, push, checkout, reset, …). Never run `guard enable` or `guard disable` yourself.

## Steps

### 1. Read the ticket

Use Backlog MCP: `get_issue` (summary, description), `get_issue_comments`, and list attachments with
`get_issue_attachment` where useful. Figma links, images and files you cannot read go to section 6
"Chưa đọc được"; F1 checks cover only what was read. If the Backlog MCP server is not available, ask
the tester to paste the ticket text and continue.

### 2. Anchors

Extract anchors from the spec: screen names, JP UI labels (verbatim, e.g. 「確定」), API names,
business terms, table names. Show them to the tester in one line and continue without waiting.
Write them to `<output_dir>/<TICKET>/<TICKET>-anchors.json` as `{"anchors": [...]}` (create the folder
if needed). Also save the ticket's summary and description, as read, to
`<output_dir>/<TICKET>/<TICKET>-spec.md`; scout reads it to know which behaviors matter.

### 3. Scout

Invoke the `scout` skill. It runs in its own subagent and sees only its arguments, so pass everything
on one line, quoting values that contain spaces:

```text
<TICKET> --repo "<repo>" --anchors-file "<output_dir>/<TICKET>/<TICKET>-anchors.json" --spec-file "<output_dir>/<TICKET>/<TICKET>-spec.md" [--master-ref <ref>] [--develop-ref <ref>] [--fetch] [--feature "<feature>"]
```

`--feature` defaults to the main screen name. Scout replies with a short `SCOUT_DONE` block (brief
path, facts path, cache result) or `SCOUT_FAILED: <message>`; on failure show the message to the
tester and stop. Read the brief. Its frontmatter carries the refs, SHAs and cache fields; open the
facts file only for a field the brief does not have. Read source code yourself only when a finding
needs a detail the brief lacks, and name that file in section 6.

### 4. Decisions log (read only)

The log is split into one wiki page per feature, a `common` page and an index (format:
`${CLAUDE_PLUGIN_ROOT}/references/decisions-log-format.md`). Look decisions up through the index with
the anchors file (scout adds `paths` and `symbols` to it):

```bash
<run> decisions-lookup --anchors-file "<output_dir>/<TICKET>/<ticket>-anchors.json" --ticket <TICKET> --feature "<feature>"
```

It matches index rows by ticket and by overlapping anchors, then opens every matching page plus
`common` and the feature's own page, so a decision filed under another feature is still found. Each
returned page has its parsed entries.

If it fails because `BACKLOG_DOMAIN`/`BACKLOG_API_KEY` are not set in the shell, use Backlog MCP
instead: find `<prefix>/index` with `get_wiki_pages` and read it with `get_wiki`, save it to
`<output_dir>/<TICKET>/.decisions-index.md`, and run the same command with `--index-file "<that file>"`. It prints
`page_names`; read each existing one with `get_wiki`, save it to `<output_dir>/<TICKET>/.decisions-page.md`, run
`<run> decisions-parse --file <that file>`, and delete the saved copies afterwards.

Use only `active` entries:

- entries of this ticket, and entries matched by anchors that concern the scoped screens or logic,
  become `[khách chốt]` with the entry ID;
- `unparsed` lines may be cited as `[wiki]` at most, never `[khách chốt]`; mention them to the tester.

If the decisions commands stop because the project uses Backlog notation, or no index exists yet, say
so in section 6 and continue without it.

### 5. Findings

Compare the spec with B* rows (Production) and the develop changes:

- F1 spec contradicts itself (ticket text vs attachments/Figma),
- F2 spec silent on or contradicting Production behavior,
- F3 another ticket in this phase changed the same place (use `commits_by_ticket` and anchors with
  status `new_in_phase`),
- F4 shared logic outside the spec's scope is affected,
- F5 the answer depends on something unreadable (SP, config, batch, master data).

For each: fact or intent (unsure → intent), severity, "Chặn test case?", routing (fact → Dev,
intent → BrSE/khách, hybrid → Dev confirms the fact first, then escalate the intent with that fact),
and a question. Every question routed to BrSE/khách gets a ja draft line. A point already decided in
the decisions log is not asked again; cite the entry instead.

### 6. Write the report

Fill sections 1–6 and 8 of the template in the report language; leave section 7 as in the template.
Every B* row and every finding carries a source label. B* rows come from the brief (keep their IDs);
R* rows come from shared logic, other tickets in the phase, and dropped-but-related files. Section 6
lists what was read, what could not be read (including the brief's coverage), anchors not found, the
decisions log entries used, and the scout cache result (hit / partial with re-read rows / miss).

Frontmatter: `ticket`, `repo`, `master_ref`/`develop_ref` as given, `merge_base` and `develop_head`
as full SHAs from the brief frontmatter, `lang`, and `cache_root`/`cache_feature` from the scout result (null
when the cache was not used). `revision`, `previous`, `plugin_version` and `generated_at` are set by
the save command.

Write the draft to `<output_dir>/<TICKET>/<TICKET>-survey-draft.md`, then:

```bash
<run> report-save --draft "<draft path>"
```

It validates the draft (sections 1, 2, 3, 6 present and in order, source labels on every B* row and
finding, fact/intent on every finding, ja draft for every BrSE question, full SHAs) and saves it as the
next revision without overwriting anything. If it exits 1, fix the listed errors in the draft and run it
again. Warnings about leftover `<...>` placeholders should also be fixed.

### 7. Hand back

Tell the tester the report path, the conclusion line from section 1, and the questions to send (Dev
and BrSE separately, with the ja drafts). Do not send anything to Backlog yourself.

## In a console job

When the `console` skill runs this skill for a `survey` job, the job's parameters replace the
arguments (`repo` is always given) and the report is written in `report_lang`. Where a step would ask
the tester (for example for the ticket text when Backlog MCP is unavailable), use `console ask` as
`${CLAUDE_PLUGIN_ROOT}/references/console-bridge.md` says. Without a console job nothing here changes.
