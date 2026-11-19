---
phase: 3
title: "Result columns and run export"
status: pending
priority: P1
effort: "2.5d"
dependencies: [2]
---

# Phase 3: Result columns and run export

## Goal

A column plan per run that maps case fields to template columns, with columns added, removed and
reordered by the tester, and an export that writes a new workbook and a Markdown report from it.

## Context

- Template roles are fixed: `ROLES = ["no", "item", "steps", "expected", "evidence", "trace"]`, with `item` and `trace` required (`templates.py:20-21`). Header detection and the registry's consumers depend on them: `console/templates_api.py:162`, `188`; `console/ui/views/templates.mjs:11-12`, `305-355`; `cli.py:129-141`; the role labels in the three language files; the preview golden files under `tests/fixtures/`.
- `xlsx._write_rows` writes one value per role and copies the style of the first data row (`xlsx.py:72-98`); `fill_copy` loads the template, never saves it, and writes a new file (`xlsx.py:101`). `read_trace` reads the trace column without a guard (`xlsx.py:164-168`).
- The shipped sample already has 結果 and 実施日 columns and a fixed list `OK,NG,保留,対象外` on the result column (`xlsx.py:214`, `227-228`).
- `.gitignore` ignores `*.xlsx` except under `tests/` and `templates/`.

<!-- Updated: Red Team Session 1 - roles and synonyms left unchanged; purpose per registry entry; one writer; shipped sample reused; verdict labels from the column's fixed list -->

## Column plan

Stored in `run.json` when the tester confirms the review table:

```json
{"template": "customer-a", "sheet": "TC", "header_row": 3,
 "verdict_labels": {"pass": "OK", "fail": "NG", "not-run": "保留", "not-applicable": "対象外"},
 "columns": [
   {"field": "no",        "letter": "A"},
   {"field": "content",   "letter": "B"},
   {"field": "expected",  "letter": "D"},
   {"field": "verdict",   "letter": "F"},
   {"field": "screen",    "letter": "H", "header": "画面", "new": true},
   {"field": "evidence",  "letter": "I", "header": "Evidence", "new": true}
 ]}
```

- Fields a column can take: every case field (`no`, `type`, `content`, `creator`, `screen`, `viewport`, `kind`, `class`, `reason`, `scenario`, `runner`, `preconditions`, `steps`, `expected`, `target_node`) and every result field (`verdict`, `actual`, `evidence`, `executed_at`, `by`).
- A column with `new: true` is added to the copy: the header cell is written in `header_row` with the style of the last existing header cell. The registered template file is never changed.
- Removing a column means leaving its field out of the plan; the template's column stays in the sheet, empty.
- The first guess: the template's existing roles give `item`←`content`, `steps`, `expected`, `evidence` and `no`. For `verdict`, `actual` and `executed_at` the guess matches the sheet's header texts against a small synonym list kept in the export module (結果 / 判定 / result / kết quả; 実際の結果 / actual / thực tế; 実施日 / executed / ngày chạy). The registry's `ROLES` and `HEADER_SYNONYMS` are not changed. Fields with no match are proposed as new columns to the right of the last used column.
- `verdict_labels` defaults to the result column's fixed list when it has one (the first two entries for pass and fail, shown to the tester to confirm), else `Pass` / `Fail`.

## Template purpose (additive)

- Each registry entry gains `purpose`: `testcase` (the default, also for entries written before this change) or `webtest`.
- `register` takes the purpose. A `webtest` entry requires the `item` role only; a `testcase` entry keeps `item` and `trace`.
- Header detection for a `webtest` entry accepts a row with `item` and any second mapped role, since it cannot key on the trace column.
- `/testign:testcase`, the `testcase` job check (`console/jobs.py:346-378`) and the trace view list `testcase` entries only; the web run lists both.
- The console's register route and the Templates screen take the purpose (`console/templates_api.py:172-205`; `console/ui/views/templates.mjs`).
- No second sample is shipped: `templates/testcase-template-sample.xlsx` already has the result and date columns and serves a first web run.

## Export

`webtest-export --run <id>`:

1. Refuses a run that still has a `queued`, `running`, `parked` or `awaiting-tester` row (the orchestrator closes the run first).
2. Loads the registered template, writes one row per case through the column plan, and saves `<run-id>.xlsx` in the run folder with `_unique` naming, so an existing file is never replaced (`xlsx.py:26`).
3. Evidence cells hold the file names relative to the run folder, one per line.
4. Writes `<run-id>-report.md`: source and hosts, counts by state, the `fail` rows with expected, actual and evidence, the `not-run` rows with their reason, the `self-run` rows, the rows whose class changed during the run, and a note on `visual` rows ("compared by the agent with the capture"). Report language is the job's `report_lang`.
5. Prints both paths as JSON.

`webtest-columns --run <id> [--template <name>]` prints the first-guess column plan and three sample rows as JSON, for the review table in phase 4.

## Files to Create / Modify

- Modify: `scripts/testign/templates.py` (`purpose` on entries, required roles by purpose, header detection for `webtest`)
- Modify: `scripts/testign/xlsx.py` (`_write_rows` takes the values per column from the caller, so both the role-based fill and the plan-based fill use it; new header cells)
- Create: `scripts/testign/webtest_export.py` (column plan checks, first guess, verdict labels, Markdown report)
- Modify: `scripts/testign/cli.py` (`webtest-columns`, `webtest-export`, `template-register --purpose`, `template-list` shows the purpose)
- Modify: `scripts/testign/console/templates_api.py`, `scripts/testign/console/jobs.py` (`_check_testcase` filters by purpose)
- Create: `tests/test_webtest_export.py`
- Modify: `tests/test_templates_xlsx.py`, `tests/test_console_templates_api.py`, `tests/test_console_jobs.py` (purpose cases added; existing assertions stay)

## Tasks & Steps

1. Run the existing template, console template and job tests; record that they pass before any edit.
2. Add `purpose` with its default, the required roles by purpose, and the `webtest` header detection.
3. Change `_write_rows` to take a value-per-column mapping; keep `fill_copy` and `add_sheet` behaviour byte-for-byte on the existing fixtures.
4. Write the column plan checks: known fields, each letter used once, `new` columns to the right of the sheet's last used column, at least `content` and `verdict` present.
5. Write the first guess, the verdict-label default and the three sample rows (the first `sure`, the first `choice` and the first `not-web` row).
6. Write the Markdown report and the export command.

## Todo

- [ ] Baseline test run recorded
- [ ] `purpose` on registry entries and its filters
- [ ] One writer for both fills
- [ ] Column plan checks and first guess
- [ ] Verdict labels from the column's fixed list
- [ ] Markdown report and export command
- [ ] Tests

## Verification

- `python -m pytest tests/test_templates_xlsx.py tests/test_console_templates_api.py tests/test_console_jobs.py tests/test_webtest_export.py -v`
- Tests cover: every assertion that existed before this phase still passes unedited, the preview golden files included; an entry without `purpose` loads as `testcase`; a `webtest` entry without a trace column registers and is not offered to a `testcase` job; a plan with a new column writes its header and values and leaves the registered template's bytes unchanged; a removed column leaves the template column empty; on the shipped sample the default labels are `OK` and `NG` and the written cells pass the column's validation; a second export writes a second file; export refuses a run with an open row; the report lists every `fail` and `not-run` row; `.xlsm` templates keep their macros (`keep_vba`).

## Risks

- Merged header cells or a header spread over two rows make "the last header cell" ambiguous. The checks refuse a new column when the header row has merged cells past the last mapped column, with a message that names the cell; the tester then adds the column in the template and registers it again.
- A fixed list whose first two entries are not pass and fail. The tester sees the guessed labels in the review table and corrects them there.
