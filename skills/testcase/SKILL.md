---
name: testcase
argument-hint: <report-path | TICKET-ID> [--template <name>] [--into <filled.xlsx>] [--register <xlsx>]
description: Check the latest survey report's pinned commit hashes, fill a copy of the customer's Excel test case template with B*/R* row IDs in the 備考 column, never overwrite tester edits, and report gaps and orphans. Manages the tester's registered templates (register, choose, preview). Invoked by the tester as /testign:testcase.
---

# testcase

Write test cases for one survey report into a copy of the tester's Excel template, then run the
trace check and write report section 7 into a new revision.

Arguments: `$ARGUMENTS`

## Before you start

1. Read `${CLAUDE_PLUGIN_ROOT}/references/rules.md` (§8 trace IDs, §9 revisions, §10 how to call
   Python). Below, `<run>` means `<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py"`.
2. Every subcommand prints JSON (except `template-preview`, which prints Markdown) and exits with 2
   and a one-line message on errors. Show that message to the tester; do not retry blindly.
3. **Never open or read an `.xlsx` yourself.** Use `template-preview` to show a layout and `trace` to
   read a filled workbook. This keeps token use low and avoids misreading cells.

## Step 1 — pick the template

Run `<run> template-list`.

- **No template registered (first run):** ask the tester for the path of their test case template
  (`.xlsx`/`.xlsm`) and a short name for it (for example the customer or project name). If they do not
  have one yet, offer the basic sample shipped with the plugin:
  `${CLAUDE_PLUGIN_ROOT}/templates/testcase-template-sample.xlsx`. Then register it:

  ```bash
  <run> template-register --file "<path>" --name "<name>"
  ```

  If registration fails because columns could not be mapped, the error lists the headers it found.
  Ask the tester which column holds each role (at least `item` and `trace`; also `no`, `steps`,
  `expected`, `evidence` when present) and rerun with `--sheet`, `--header-row` and
  `--map role=COLUMN` (one `--map` per role).
- **One or more registered:** use `--template` from the arguments, else the default. When several are
  registered and the tester did not name one, list them (name, original file name, default) and ask.
- `--register <xlsx>` in the arguments: register that file first (ask for a name), then continue.

Always show the chosen template with `<run> template-preview --template "<name>"` and paste its
Markdown output as is, so the tester can confirm the sheet, header row and column mapping. If the
mapping is wrong, re-register with `--replace` and the corrected `--map` values.

Other template commands the tester may ask for: `template-default --name`, `template-remove --name`,
`template-preview --file <xlsx>` (look at a file before registering it).

Registered templates are stored in `~/.testign-kit/templates/` with `index.json`, outside the plugin
folder, so plugin updates do not remove them and customer files never enter the plugin repository.

## Step 2 — choose the report and check its hashes

If the argument is a ticket ID, use `latest` from `<run> report-path --ticket <TICKET>` (the highest
`<output_dir>/<TICKET>/<TICKET>-survey-r<N>.md`). Then:

```bash
<run> hash-check --report "<report>"
```

- `status: same` → continue.
- `status: moved_no_impact` (exit 0) → tell the tester which refs moved and that none of the report's
  source files changed; continue.
- `status: stale` (exit 1) → stop. Show `stale_rows`, `stale_files` and the commits in `moves`, and
  suggest re-running `/testign:survey`. Continue only if the tester explicitly says so.

## Step 3 — write the cases

Read the report (it is Markdown, so reading it is fine). Generate cases from:

- every B* row in section 3 that changed on develop or has ⚠️ in "Lệch?",
- every R* row in section 5,
- the Q rows in section 2, applying "Chặn test case?":
  - **Block** → no cases for the area that depends on that Q; it will show up as a gap.
  - **Partial** → placeholder cases for the affected group, with `waiting_on: ["Q<n>"]`.
  - **No** → write the case with the current expected value and `waiting_on: ["Q<n>"]`.

Write the cases in the report language; keep JP UI labels verbatim. Each case is one JSON object:

```json
{"item": "...", "steps": "1. ...\n2. ...", "expected": "...", "evidence": "...", "trace": ["B2", "R1"], "waiting_on": ["Q1"]}
```

`trace` must contain at least one B*/R* ID that exists in the report; the script refuses cases
without one. Save the list as `<output_dir>/<TICKET>/<TICKET>-cases-<YYYYMMDD-HHMM>.json`, then:

```bash
<run> xlsx-fill --report "<report>" --cases "<cases.json>" [--template "<name>"]
```

If the tester points at a workbook they already filled (`--into`), pass `--into "<filled.xlsx>"`: the
script copies that workbook and adds a new `TC-<stamp>` sheet, leaving their sheets unchanged. The
script never writes to an existing file or sheet name.

## Step 4 — trace check and new revision

```bash
<run> trace --report "<report>" --xlsx "<written workbook>" [--template "<name>"] --write-revision
```

This writes section 7 (totals, gaps, orphans, cases waiting on QA) into `r<N+1>` with `previous`
pointing at the report you read. Report to the tester: the workbook path, the new revision path, and
the gaps, orphans and waiting cases. Explain that gaps from Block questions are expected until the
question is answered.

## In a console job

When the `console` skill runs this skill for a `testcase` job, use the report named in
`base_revision`, the job's `template`, and its `mode`: `trace` runs only
`trace --template <t> --xlsx <workbook> --write-revision`; `write` writes cases (only for the `focus`
rows when given, into `--into <workbook>` when a workbook is given), then runs the trace step. The
preview confirmation and a stale hash check become `questions` asks; a missing template or unmapped
columns fail the job with a pointer to the Templates screen, as
`${CLAUDE_PLUGIN_ROOT}/references/console-bridge.md` says. Without a console job nothing here changes.
