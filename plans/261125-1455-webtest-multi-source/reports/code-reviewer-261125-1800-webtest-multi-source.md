# Code review: web test suites from many sources and the console redesign

Plan: `plans/261125-1455-webtest-multi-source/plan.md`. Read-only review of the uncommitted worktree diff.
The `tests/e2e` folder was skipped on request.

## Scope

- Python: `webtest_sources.py`, `webtest_suite.py`, `console/suite_api.py` (new); `webtest.py`, `webtest_export.py`,
  `cli.py`, `console/jobs.py`, `console/webtest_api.py`, `console/readapi.py`, `console/client.py` (changed).
- UI: `router.mjs`, `api.mjs`, `main.mjs`, `dom.mjs`, `hosts.mjs`, `views/suite*.mjs`, `views/new-run.mjs`,
  `views/run*.mjs`, `views/jobs.mjs`, i18n files.
- Docs: `skills/webtest/SKILL.md`, `skills/webtest/triage-rules.md`, `references/console-bridge.md`, `README.md`.
- Tests: Python 606 passed, 2 skipped; UI 117 passed. I confirmed findings 2, 4 and 6 with small probe scripts in
  the session scratchpad. I did not change any repository file except this report.

## Verified clean (no finding)

- Route guards: every new `/api/webtest/suites*`, `/api/webtest/runs` and `.../columns` route is in the
  `browser` group. Every new `/agent/suites/*` and `/agent/capabilities` route is in the `agent` group.
  `server._handle` checks Host, Origin and Sec-Fetch-Site before any group check, and the agent token is
  accepted only on `agent` routes.
- Path traversal:
  - Suite ids must match `SUITE_ID_RE` and are looked up by listing the folder, with linked folders refused.
  - Case ids are matched against stored ids.
  - Capture names must match `c\d{1,4}\.(png|jpg)`, and linked `source/` folders or files are refused.
  - Upload names pass `decode_filename` and then `safe_file_name`.
  - Excel sheet names are only checked for membership in `wb.sheetnames`.
- Upload limits: 10 MB `max_body`, the zip bomb checks in `check_zip`, `.xlsx`/`.xlsm` only, `[Content_Types].xml`
  required, then `check_workbook_file` (10 MB on disk, 5 MB unzipped).
- Off-host checks:
  - `check_run_target` uses `url_on_hosts`, which refuses backslashes, user info and escaped hosts.
  - Suite screens must be paths. The run joins the base URL and the path, and `check_run` checks the joined
    URL with `url_on_hosts` again.
- XSS: `dom.h` sets text only through `textContent` or text nodes and refuses `style` and `on*`. Nothing uses
  `innerHTML`. The only link with data in it (`suite.mjs:355`, the Figma URL) is limited by the server regex to
  `https://(www.)figma.com/...`. The CSP stays `script-src 'self'; style-src 'self'`.
- Version 1 runs: `check_run` accepts `VERSIONS = (1, 2)`, and every new `run["suite"]` read is guarded.
  `test_a_version_1_run_loads_shows_and_exports` covers load, status, close and export against a stored v1 fixture.
- Locking:
  - `suite_api._changed` holds `bridge.cond` around `run_changed`.
  - `LOCK` is never taken while `cond` is held, and `cond` is never taken while `LOCK` is held, so the two locks
    cannot deadlock.
  - `_load`/`_reconcile` is never called with `LOCK` held, and `threading.Lock` is not re-entrant, so this matters.
- Only the claimed job writes: `suite_job` → `_open_web` requires the job to be in this session, of kind
  `suite-generate`, for this suite, and running or needs-input. `webtest-table` checks the same thing through
  `/agent/jobs/:id/info`.
- Project rules: no plan ids or phase numbers in code or test comments. Python uses openpyxl only. The UI has no
  build step. The en and ja key sets match (1175 keys each), and `vi.json` is removed.

## Critical

None found.

## Important

### 1. The agent can confirm a suite and change its cases without the tester (trust boundary, needs a decision)

- `scripts/testign/cli.py:779-811` (`suite-case-add`, `suite-case-update`, `suite-case-delete`, `suite-confirm`)
- `scripts/testign/webtest_suite.py:403,415` (`by="tester"` by default)
- `scripts/testign/console/suite_api.py:250-255`

**Before this change:** a run's plan could be confirmed only by the tester's answer to a `review-table` ask. The
server held that answer, and it had to come from a tab older than the job (`apply_plan` with `server.review`).

**Now:** suite cases and the confirmation are plain CLI writes from the agent process:

- `suite-case-add` and `suite-case-update` apply the tester's rules (`by="tester"`). The agent can therefore write
  `{"class":"choice","runner":"agent","preconditions":"..."}`, which `CHOICE_BY_AGENT` is meant to prevent, or
  `mobile_method: emulation`.
- `suite-confirm --by <any name>` marks the suite `ready`.
- `webtest-new` then copies it into a confirmed run.
- `console queue` with `webtest-run` starts it.

**Failure scenario:** text in a ticket or a Figma frame misleads the agent. It adds a data-writing `choice` case for
itself, confirms the suite, creates the run and queues it. The run then executes that case with no tester action
on the plan. The only tester action left is a tab that exists, which the claim check needs.

**Docs that contradict this:**
- README:255 says "No case runs before you confirm."
- `skills/webtest/SKILL.md:13` says the tester confirms "on the console, never in the chat".
- No skill tells the agent to use these four commands, so they add risk and are not used.

The phase 1 plan lists these commands explicitly, so this is a decision for the user, not a silent fix. Options:

- (a) Remove `suite-case-*` and `suite-confirm` from the CLI. The tester edits and confirms in the console only.
- (b) Keep them, but make the case commands use `by="agent"` and drop `suite-confirm`.
- (c) Keep everything and correct README and SKILL to say the agent can confirm.

(a) restores the old guarantee.

**Same area:** the `suite_api` module docstring says "Every suite change runs under `LOCK`, so a tester edit and an
agent write never interleave." That is false for these CLI writers and for `webtest-table`
(`cli.py:654`, which calls `stage_rows` directly from another process).

### 2. A confirmed suite can produce a run whose agent rows are all `not-run` immediately

- `scripts/testign/webtest_suite.py:213-222` (`confirm_errors`)
- `scripts/testign/webtest.py:603-621` (`_initial_state`)

`confirm_errors` checks only that a screen is present, and only for `sure` + `agent` cases. It does not check:
- `scenario` on agent cases;
- `screen` on delegated `choice` + `agent` cases.

`_initial_state` turns those cases into `not-run` (`no-scenario` / `no-screen`) when the run is created.
`not-run` is a terminal state (`TRANSITIONS`, `webtest.py:74-80`), so they cannot be requeued.

**Failure scenario:** the SKILL (Figma step 5) tells the agent to leave `scenario` out when the suite has no project,
and a suite made from the chat usually has none. The tester confirms, makes a run, and every agent row is already
`not-run`. The tester must fix the suite and create a new run.

Probe result for one `sure`/agent case with a screen and one `choice`/agent case without a screen, both without a
scenario: `[('r01','not-run','no-scenario'), ('r02','not-run','no-scenario')]`.

**Fix:**
- In `confirm_errors`, add `scenario: "an agent case needs a login scenario (none for public pages)"` when
  `runner == "agent"` and there is no scenario.
- Extend the screen rule to `class in ("sure", "choice") and runner == "agent"`.
- Alternatively, have `new-run.mjs` block or warn when a ready suite has agent cases without a scenario.

### 3. The generate job for any report revision except the latest fails at claim with `revision-moved`

- `scripts/testign/console/jobs.py:470`
- `scripts/testign/webtest_sources.py:128-138`

`_check_suite_generate` sets `base_revision` to `source["report"]`. `claim_implicit` (`jobs.py:988-992`) fails the
job when that differs from the ticket's current latest revision. Two cases hit this:

- **An explicit older revision:** `_check_backlog` accepts `revision`, through the API body or the CLI
  `suite-new --input`. A suite made from r1 while r2 exists always gets a job that fails at claim.
- **A new revision after the suite is made:** the tester surveys again (r3) after making a suite from r2 but before
  the agent claims the job. The job fails. `_reconcile` then moves the suite to `review` with zero cases, and
  `_check_suite_generate` refuses a new job because the suite is no longer `generating`. The tester must delete it
  and make a new suite.

**Fix:** choose one.
- Set `base_revision: None` for `suite-generate`. The suite pins its own report file, which `report_file` still
  checks.
- Or refuse a `revision` other than the latest in `_check_backlog`, and document that a suite needs the latest
  report.

### 4. `skills/webtest/triage-rules.md` still describes the removed flow

- `skills/webtest/triage-rules.md:3-5,21-24`

The SKILL sends the agent to this file for the case rules of a generate job. The file says to "Write the result with
`webtest-triage`", which was removed, and refers to "the review table", which is retired.

**Failure scenario:** the agent follows it, runs a command that no longer exists, and the job stalls or fails.

**Fix:** reword it for `suite-stage` items and the suite's Cases tab.

## Minor

### 5. A malformed workbook gives a 500 "internal error" instead of `bad-file`

- `scripts/testign/webtest_sources.py:220`

`load_workbook` sits outside the `try`, and the `except` catches only `KeyError`, `ValueError` and `TypeError`.
Probe results:
- A zip that has `[Content_Types].xml` but no workbook part passes `check_zip`, then raises
  `OSError: File contains no valid workbook part`.
- A sheet name that refers to a chartsheet raises `AttributeError`.

Both reach `server._dispatch` as a 500. No traceback leaks.

**Fix:** move `load_workbook` inside the `try`, catch `Exception` (or `(OSError, KeyError, ValueError, TypeError,
AttributeError, zipfile.BadZipFile)`), and map it to `SourceError(..., "bad-file")`. Also refuse a sheet that has
no `iter_rows`.

### 6. A suite name longer than 80 characters blocks run creation

- `scripts/testign/webtest.py:512`

Suite names can be up to 120 characters (`NAME_CAP`). The run name defaults to the suite name, but `_text(..., 80)`
raises "name is longer than 80 characters". The New run dialog's name field is optional, so a tester who leaves it
empty gets this error. I confirmed it with a probe.

**Fix:** `name or (suite.get("name") or "")[:80]`.

### 7. Race between the run-busy check and the save in `put_columns`

- `scripts/testign/console/webtest_api.py:349-361`

The busy check releases `bridge.cond` before `load_run`, `replace_plan` and `save`. `replace_plan` reads the
template workbook, which takes time. A `webtest-run` job queued and claimed in that window can have its first CLI
write overwritten, because the whole `run.json` is saved again. The window is short, so this is unlikely.

**Fix:** check `busy` again under `cond` just before `webtest.save`. Alternatively, have job creation for a run take
`COLUMNS_LOCK`.

### 8. `attach_suite` writes `suite.json` without `suite_api.LOCK`

- `scripts/testign/console/jobs.py:1339-1343`, called at `jobs.py:781`

`_reconcile` (`suite_api.py:76-88`) can check that no job is active, then a new `suite-generate` job is attached,
then `stop_generating` runs under `LOCK`. The result is a queued job for a suite already in `review`, and the
agent's stage calls are refused. This needs a suite whose earlier job ended to be queued again at that exact moment.

**Fix:** take `suite_api.LOCK` inside `attach_suite`. This keeps the lock order `cond` → `LOCK`, and `LOCK` is never
held while `cond` is taken. Then re-check the state inside it.

### 9. `retired-kind` has no UI label

- No `job_reason_retired_kind` key in `i18n/en.json` or `i18n/ja.json`.

`reasonShort` falls back to a generic "Failed", while README:271 and the bridge docs name `retired-kind`. Add the
keys in both languages.

### 10. The Excel trace is lost in the run export

- `scripts/testign/webtest_sources.py:294-296`

The Excel entry's `trace_value` shows the row `no`, even when a case has B*/R* `trace` ids from the workbook's trace
column. The suite export (`trace_text`) shows the ids, but the run export shows the row number in the "Row" column.
The two exports of the same cases disagree.

**Fix:** have `value_for("trace")` prefer `source["trace"]` when it is present.

### 11. The trace column header added by `suite_plan` is always English

- `scripts/testign/webtest_export.py:225-228`

It writes `"Figma node"`, `"Trace"` or `"Row"` whatever the `report_lang`. `HEADERS[lang]["trace"]` exists and could
be used.

### 12. The listing's hash budget is not a hard limit

- `scripts/testign/console/readapi.py:401-425`

The deadline is checked before each call. A `hash_status` call started just before the deadline can still wait up to
30 s on `HASH_SLOTS` and then run git. Every uncached ticket after the deadline also starts its own thread; these are
deduplicated per path but not capped in number.

**Fix:** call `HASH_SLOTS.acquire(blocking=False)` on the listing path, and warm with a single worker that processes a
queue.

## Plan follow-ups

| Contract item | State |
|---|---|
| Phases 1-5 (marked Completed) | The code matches the claims I checked. |
| Acceptance 1 (coverage) | Covered by `coverage()`: all B*/R* rows, `uncovered`, `orphans`. |
| Acceptance 2 (Figma suite matches the old import) | Covered by `stage_rows`. |
| Acceptance 3 (Excel without an agent) | Covered. |
| Acceptance 4 (run keeps its own copy, export lists suite and trace) | Covered and tested. Finding 10 is the Excel gap in the trace column. |
| Acceptance 5 (no Vietnamese UI, English default, Japanese on request) | The key sets match. |
| Phases 6-8 (marked Pending) | The UI views for them exist in the diff. The plan status was not updated; I left it unchanged. |

## Unresolved questions

1. Was it intended that the agent can confirm a suite (finding 1)? The phase 1 plan lists `suite-confirm` and
   `suite-case-*`, but README and SKILL say only the tester confirms.
2. Should a backlog suite allow a report revision other than the latest (finding 3)?

Status: DONE_WITH_CONCERNS
Summary: No critical defects. Route guards, path checks, upload limits, off-host checks, XSS safety and version 1
run compatibility hold up. Four important issues: agent-side CLI confirmation weakens the tester-confirms
guarantee; confirm accepts agent cases that the run turns `not-run` at once; generate jobs fail for
non-latest revisions; triage-rules.md still describes the removed flow.
Concerns/Blockers: Finding 1 needs a user decision because the plan lists the CLI commands while README and SKILL
promise the opposite.
