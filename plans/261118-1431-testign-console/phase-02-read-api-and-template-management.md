---
phase: 2
title: "Read API and template management"
status: pending
priority: P1
effort: "2.5d"
dependencies: [1]
---

# Phase 2: Read API and template management

## Goal

JSON routes that read tickets, report revisions, hash checks, trace results, the scout cache and
config, and that register, list, preview, set default and remove templates through the existing
`templates.py` functions.

## Context

- Reports: `<output_dir>/<TICKET>/<TICKET>-survey-r<N>.md` (`report.py`: `_revisions`, `load`, `section`, `behavior_rows`, `regression_rows`, `question_rows`, `_q_blocks`, `source_files`).
- Conclusion is the emoji in section 1 (🔴 / 🟡 / 🟢; `templates/survey-report-template.md`), which reads the same in every report `lang`.
- Hash check: `hashcheck.check(report_path, repo)` runs git read-only and returns `same`, `moved_no_impact` or `stale`.
- Trace: `_cmd_trace` in `cli.py` builds rows and cases, then `trace.summarize`.
- Templates: `templates.register(file, name, sheet, header_row, overrides, make_default, replace)` raises `TemplateError` with the headers found when it cannot map columns.

## Requirements

- [ ] Every path segment (ticket, revision, workbook, template, cache entry) is matched against a listing the server built; none is joined into a path.
- [ ] Tickets are folders under `output_dir` whose name fully matches `ticket_id_regex` and that hold at least one revision file.
- [ ] No route writes outside `~/.testign-kit/console/` and `~/.testign-kit/templates/`.
- [ ] Report text is returned as data (strings); the server never returns HTML.
- [ ] `/api/config` returns `output_dir`, `lang`, `master_ref`, `develop_ref`, `backlog.space`, `backlog.project_key`, `backlog.decisions_log_prefix`, and never an environment variable.
- [ ] Hash results are cached in memory for 60 seconds per report path; a git error becomes `{status: "unknown", reason}`, not a 500.
- [ ] Template upload: raw body with `X-Filename`; at most 10 MB; extension `.xlsx` or `.xlsm`; first bytes `PK\x03\x04`; stored as `uploads/<id>/<sanitised base name>`; deleted after registration and swept when older than one hour.
- [ ] Template registration from the console and from the CLI produce the same `index.json` entry for the same inputs.
- [ ] `index.json` is written to a temporary sibling then replaced, so a crash never leaves it torn.

## Routes

| Method | Route | Result |
|---|---|---|
| GET | `/api/config` | the fields above |
| GET | `/api/tickets` | per ticket: id, title (report H1), latest revision, report `lang`, `generated_at`, conclusion (`open`, `needs-qa`, `clear`, `unknown`), finding counts by severity and block, open question count, workbooks (name, mtime), section 7 summary when filled |
| GET | `/api/tickets/:ticket` | revisions (name, revision, `generated_at`) and the latest parsed revision |
| GET | `/api/tickets/:ticket/revisions/:rev` | frontmatter, title, sections 1–8 (structured where a parser exists, plain text lines otherwise), findings by Q id |
| GET | `/api/tickets/:ticket/hash` | `hashcheck.check` result for the latest revision |
| GET | `/api/tickets/:ticket/trace?workbook=` | trace summary plus per-case rows (no, item, trace ids, status) for a workbook of the ticket folder |
| GET | `/api/cache` | per entry: root commit, feature, file count, row ids, scout model, saved at, reviewed by |
| GET | `/api/templates` | `list_templates()` |
| GET | `/api/templates/:name/preview` | structured grid: sheet, header row, columns with roles, up to 8 rows of cell text |
| POST | `/api/templates/uploads` | upload id, sheets, detected layout, grid preview |
| POST | `/api/templates` | `{upload, name, sheet?, header_row?, map?, make_default?, replace?}` → `register`; 409 on a taken name without `replace`; 400 with headers found when mapping fails |
| POST | `/api/templates/:name/default` | `set_default` |
| DELETE | `/api/templates/:name` | `remove` |

## Files to Create / Modify

- Create: `scripts/testign/console/readapi.py` (ticket listing, report projection, hash cache, trace projection, cache listing, config projection)
- Create: `scripts/testign/console/templates_api.py` (uploads, registration, preview grid)
- Modify: `scripts/testign/console/server.py` (routes)
- Modify: `scripts/testign/templates.py` (`preview_grid()` returning cells; `preview()` renders Markdown from it; atomic `_save_index`)
- Modify: `scripts/testign/cli.py` (move the body of `_cmd_trace` into a function the console reuses; output unchanged)
- Modify: `scripts/testign/report.py` (`conclusion(body)` and `title(body)` helpers)
- Create: `tests/test_console_readapi.py`, `tests/test_console_templates_api.py`

## Tasks & Steps

1. `report.conclusion` and `report.title`; unit tests over the fixture report in each of vi, ja, en.
2. Refactor `_cmd_trace` into `trace_for(report_path, xlsx_path, template, sheet)`; existing trace tests still pass unchanged.
3. `templates.preview_grid` with `openpyxl` in read-only mode; `preview` uses it.
4. `readapi.py` projections; every list built from the file system at request time.
5. Upload handling with the caps and the sweep; registration through `templates.register` with the stored file, preserving the original name as `source_name`.
6. Route wiring and error mapping (`TemplateError` → 400/409 with its message).

## Verification

- `python -m pytest tests/test_console_readapi.py tests/test_console_templates_api.py tests/test_templates_xlsx.py tests/test_report.py -v`
- A test hashes the `output_dir` and repository trees before and after calling every route and asserts they are unchanged.
- A test registers the sample template via the API and via `templates.register` into two homes and compares the `index.json` entries (ignoring `registered_at`).
- Path traversal attempts (`..`, encoded slashes, absolute paths, unknown names) all get 404.

## Success Criteria

Acceptance criteria 3, 4 and 5 of the plan pass.

## Risk Assessment

- A large customer workbook makes preview slow. Signal: preview over 2 seconds on the sample-sized check. Response: read-only mode and an 8-row cap are already in the design; add a sheet-size guard if needed.
- CLI and console register a template at the same moment and one entry is lost. Accepted: rare, visible in the list, and the atomic write prevents a torn file.

## Security Considerations

- Reports and workbooks hold customer data: nothing of them is logged; uploads are deleted after use.
- The Backlog API key never reaches the server; only the agent side uses it.
