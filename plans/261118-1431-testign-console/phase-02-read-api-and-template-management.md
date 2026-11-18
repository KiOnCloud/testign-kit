---
phase: 2
title: "Read API and template management"
status: done
priority: P1
effort: "3d"
dependencies: [1]
---

# Phase 2: Read API and template management

## Goal

JSON routes that read tickets, report revisions, hash checks, trace results, the scout cache and
config, and that register, list, preview, set default and remove templates through the existing
`templates.py` functions.

## Context

- Reports: `<output_dir>/<TICKET>/<TICKET>-survey-r<N>.md` (`report.py`: `_revisions`, `load`, `split`, `section`, `behavior_rows`, `regression_rows`, `question_rows`, `_q_blocks`, `source_files`). `split` raises on missing frontmatter (`report.py:67-72`).
- The conclusion bullet in section 1 uses 🔴 / 🟡 / 🟢 (`templates/survey-report-template.md:33`); the same emojis also mark finding severity (`:44`), so a parser must read the conclusion line only.
- Hash check: `hashcheck.check(report_path, repo)` runs git read-only (5 or more calls per check) and returns `same`, `moved_no_impact` or `stale`. `gitscope._git` runs `subprocess.run` with no creation flags (`gitscope.py:22-25`).
- Trace: `_cmd_trace` takes its layout from `--template` or the default template (`cli.py:123-126`, `202-213`) and has a `--write-revision` branch; `xlsx.read_trace` reads columns by that layout and raises `KeyError` for a missing sheet (`xlsx.py:149-160`).
- Templates: `templates.register` sets `source_name = file.name` (`templates.py:203`), raises one `TemplateError` for a taken name and for failed mapping, and loads workbooks fully in `detect_layout` and `headers_at` (`:111`, `:148`). `preview()` prints merged ranges and dropdowns from a full load (`:277-313`), pinned by `tests/test_templates_xlsx.py:107`.

## Requirements

- [x] Every path segment (ticket, revision, workbook, template, cache entry) is matched against a listing the server built; none is joined into a path.
- [x] Tickets are folders under `output_dir` whose name fully matches `ticket_id_regex` and that hold at least one revision file. A revision counts only when its frontmatter `ticket` equals the folder name and its `revision` equals the number in its file name; others are listed as `inconsistent`. <!-- Red team 2026-11-18: planted files in ~/Downloads -->
- [x] A ticket whose latest revision cannot be read is listed with `error: "unreadable"`; one bad file never fails the listing. <!-- Red team 2026-11-18: report parsing robustness -->
- [x] No route writes outside `~/.testign-kit/console/` and `~/.testign-kit/templates/`; config is read with `load(create=False)`.
- [x] Report text is returned as data (strings); the server never returns HTML.
- [x] `/api/config` returns `output_dir`, `lang`, `master_ref`, `develop_ref`, `backlog.space`, `backlog.project_key`, `backlog.decisions_log_prefix`, and never an environment variable.
- [x] Hash checks: at most two run at the same time (semaphore); results cached for 60 seconds per report path; git runs only in a `repo` that is an absolute existing path for which `git -C <repo> rev-parse --git-dir` succeeds; any error becomes `{status: "unknown", reason}`; the server never fetches. <!-- Red team 2026-11-18: Windows git windows, untrusted repo paths -->
- [x] On Windows, `gitscope._git` passes `creationflags=CREATE_NO_WINDOW` (no change for the CLI elsewhere).
- [x] Trace needs a template: the route takes `template` (from the template list; default: the default template) and returns `{state: "no-template"}` when none is registered; it reports `header_match: false` with both header lists when the workbook's header row differs from the template's; a missing sheet becomes `TemplateError`, never a 500. The per-case result has no status column (no such role). <!-- Red team 2026-11-18: trace template binding -->
- [x] Template upload <!-- Red team 2026-11-18: non-ASCII names, source_name, zip bombs -->
  - body `application/octet-stream`, at most 10 MB; name in `X-Filename: UTF-8''<percent-encoded>` (RFC 5987), decoded on the server;
  - extension `.xlsx` or `.xlsm`; first bytes `PK\x03\x04`; before openpyxl runs, `zipfile` totals: uncompressed at most 200 MB and compression ratio at most 100;
  - stored as `uploads/<id>/<original base name>`, rejecting only path separators, `..` and reserved device names;
  - layout detection for uploads reads at most the first 50 rows of each sheet with `iter_rows(max_row=…)`;
  - deleted after registration; swept when older than one hour at start and hourly.
- [x] `templates.register` gains a keyword-only `source_name: str | None = None` (default keeps today's behaviour); the console passes the original file name, so console and CLI produce the same `index.json` entry for the same file and name, including non-ASCII names.
- [x] `TemplateError` gains subclasses `TemplateNameTaken`, `TemplateMappingFailed`, `TemplateFileClash` (CLI output unchanged); the API maps them to 409, 400 (with headers found), 409.
- [x] Template changes from the server run under one process-wide lock; `_save_index` writes a temporary sibling then replaces it (retried on Windows `PermissionError`); `register(replace=True)` writes the new workbook to a temporary sibling and replaces the stored file in one step.
- [x] `templates.preview()` and its CLI output stay exactly as they are; the console uses a new `preview_grid()`. <!-- Red team 2026-11-18: preview regression -->

## Routes

| Method | Route | Result |
|---|---|---|
| GET | `/api/config` | the fields above |
| GET | `/api/tickets` | per ticket: id, title (report H1), latest revision, report `lang`, `generated_at`, conclusion (`open`, `needs-qa`, `clear`, `unknown`), finding counts by severity and block, question count and block count (section 2), workbooks (name, mtime), section 7 summary when filled, or `error` / `inconsistent` |
| GET | `/api/tickets/:ticket` | revisions (name, revision, `generated_at`) and the latest parsed revision |
| GET | `/api/tickets/:ticket/revisions/:rev` | frontmatter, title, sections 1–8 (structured where a parser exists, plain text lines otherwise), findings by Q id |
| GET | `/api/tickets/:ticket/hash` | `hashcheck.check` result for the latest revision |
| GET | `/api/tickets/:ticket/trace?workbook=&template=` | trace summary, per-case rows (no, item, trace ids), `header_match`, or `no-template` |
| GET | `/api/cache` | per entry: root commit, feature, file count, row ids, scout model, saved at, reviewed by |
| GET | `/api/templates` | `list_templates()` |
| GET | `/api/templates/:name/preview` | `preview_grid`: sheet, header row, columns with roles, up to 8 rows of cell text, merged ranges and dropdown lists |
| POST | `/api/templates/uploads` | upload id, sheets, detected layout, grid preview |
| POST | `/api/templates` | `{upload, name, sheet?, header_row?, map?, make_default?, replace?}` → `register(..., source_name=<original>)` |
| POST | `/api/templates/:name/default` | `set_default` |
| DELETE | `/api/templates/:name` | `remove` |

## Files to Create / Modify

- Create: `scripts/testign/console/readapi.py` (ticket listing with consistency checks, report projection, hash semaphore and cache, trace projection, cache listing, config projection)
- Create: `scripts/testign/console/templates_api.py` (uploads, zip checks, registration under a lock, preview grid)
- Modify: `scripts/testign/console/server.py` (routes)
- Modify: `scripts/testign/templates.py` (`preview_grid()`; `register(..., source_name=None)`; error subclasses; atomic `_save_index`; atomic replace of the stored workbook; bounded detection helper for uploads)
- Modify: `scripts/testign/cli.py` (move the read part of `_cmd_trace` into `trace_for(report_path, xlsx_path, layout, sheet)` that never writes; `--write-revision` stays in the CLI; output unchanged)
- Modify: `scripts/testign/xlsx.py` (missing sheet raises `TemplateError`)
- Modify: `scripts/testign/report.py` (`title(body)`; `conclusion(body)` reading only the section 1 line labelled `Kết luận`, `結論` or `Conclusion`, else `unknown`)
- Modify: `scripts/testign/gitscope.py` (Windows creation flag)
- Modify: `scripts/testign/config.py` (already in phase 1: `load(create=False)`)
- Modify: `tests/fixtures/make_report.py` (a conclusion line; ja and en variants)
- Create: `tests/test_console_readapi.py`, `tests/test_console_templates_api.py`
- Modify: `tests/test_templates_xlsx.py` (golden test pinning today's `template-preview` Markdown, added before any change to `templates.py`)

## Tasks & Steps

1. Golden test for `template-preview` output; then `preview_grid` as a separate function.
2. `report.conclusion` and `report.title`; fixtures in vi, ja, en with a conclusion line and a severity line before it.
3. Refactor the read part of `_cmd_trace` into `trace_for`; the existing trace test (`tests/test_templates_xlsx.py:235`) passes unchanged.
4. `register(source_name=…)`, error subclasses, atomic writes; existing template tests pass unchanged.
5. `readapi.py` projections; every list built from the file system at request time.
6. Upload handling with the name decoding, zip checks, bounded detection and the sweep.
7. Route wiring and error mapping.

## Verification

- `python -m pytest tests/test_console_readapi.py tests/test_console_templates_api.py tests/test_templates_xlsx.py tests/test_report.py -v`
- A test hashes the `output_dir` and repository trees, and checks that no `config.json` appears in a fresh home, before and after calling every route.
- A test registers the sample template renamed to `結合テスト仕様書_v3.xlsx` via the API and via `templates.register` into two homes and compares the `index.json` entries (ignoring `registered_at`).
- Path traversal attempts (`..`, encoded slashes, absolute paths, unknown names) get 404; a planted `DEMO-1-survey-r9.md` whose frontmatter says another ticket is listed as `inconsistent`, not as latest.
- A zip whose entries expand past the cap is refused before openpyxl opens it.
- Trace with the wrong template reports `header_match: false`; with no template registered it returns `no-template`.
- Two concurrent `set_default` calls leave a valid `index.json` naming one of them.

## Success Criteria

Acceptance criteria 3, 4 and 5 of the plan pass.

## Risk Assessment

- A large customer workbook in a ticket folder makes trace slow. Signal: trace over 3 seconds on a realistic file. Response: `read_trace` is read-only already for data; add a row cap if needed.
- CLI and console register a template at the same moment and one entry is lost. Accepted: rare, visible in the list; the atomic write prevents a torn file.

## Security Considerations

- Reports and workbooks hold customer data: nothing of them is logged; uploads are deleted after use and live in a 0700 folder.
- The Backlog API key never reaches the server; only the agent side uses it.
- `output_dir` defaults to `~/Downloads`, where unrelated files appear; the consistency check and the repo check limit what a planted file can do, and the README says so.
