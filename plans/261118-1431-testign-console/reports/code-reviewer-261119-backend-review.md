# Backend review: testign console (server, lifecycle, read API, templates, job bridge)

Date: 2026-11-19. Scope: `git diff 27dceec..HEAD -- scripts tests`, excluding `scripts/testign/console/ui/**`,
`tests/e2e`, `tests/test_console_ui_assets.py`. Reviewed against `plan.md` and phases 1, 2 and 4.
The focused suites pass: 193 passed, 2 skipped (`test_console_{jobs,bridge,lifecycle,server,readapi,templates_api}.py`,
`test_config.py`, `test_report.py`, `test_templates_xlsx.py`). Every finding below was checked by reading the code,
and the ones marked "reproduced" were also run as scratch scripts against the real modules. No repository file
was changed.

## High

### H1. The agent token can still get a browser session, so the credential split does not stop an injected agent
- `server.py:550-551` (`/agent/launch-code` hands a code to anyone with the agent token), `server.py:539-547`
  (`/api/session` is public and swaps that code for a session), `jobs.py:994` (`/api/jobs/:id/answer` accepts any session).
- Scenario: text injected into the agent runs two `curl` calls with the token from `server.json`: mint a code,
  swap it for a session. It can then `POST /api/jobs/<id>/answer` with `{"confirm": true}` (or answer the
  review-rows itself). It never needs the browser's storage. Phase 1 lists this as "outside this design's reach"
  for "a same-user process", but the Claude agent is exactly that process, and it already has Bash. The threat
  model you gave says the agent must not be able to answer approvals. The server-side checks only make that
  harder; they do not stop it. The only remaining defence is the new-session notice in open tabs, which lives in
  the UI.
- Two more agent-side bypasses with the same root cause: `wiki-update` without `--job` skips the console check
  entirely (`cli.py:397-399`), and the confirm-diff content is whatever the agent sends (M2).
- Suggested fix (needs a user decision, see the questions at the end):
  (a) refuse `/agent/launch-code` while a job is `running`/`needs-input` and a browser session has polled within
  the last ~60 s, so a code is only minted when the tester has no live tab;
  (b) only accept answers to `confirm-diff`, `review-rows` and `paste-pages` from a session created before the
  ask was opened;
  (c) at minimum, say in the plan and README that the split is a speed bump, not a boundary.

### H2. An answer that goes to a dead held `ask` call is used up and cannot be fetched again; `--from-preview` cannot re-ask (reproduced)
- `jobs.py:820-830`: the held call that sees the answer moves it into `asked` and clears `job["ask"]`, whether or
  not its client is still connected.
- `jobs.py:811-812`: re-asking with an id that was already answered fails with `bad-request`.
- `client.py:105,110`: `--from-preview` gives the ask a fixed id (`confirm-<approval[:12]>`, `paste-<digest>`).
- Scenario: the agent's `ask` client dies (Esc, a Bash timeout shorter than `--timeout`, or `--timeout 540`
  without a matching Bash limit). The server keeps holding the call. The tester answers, possibly after a
  200-row review, and the answer is written to the dead socket (on Windows the write usually succeeds into the
  buffer, so nothing is logged). Reproduced: when the agent re-asks with the same ask, it gets
  `400 bad-request "this ask id was already answered; use a new id"`. No agent route can read the answer back.
  For `confirm-diff`/`paste-pages` the agent cannot re-ask the same preview at all. The same happens after the
  tester declines once and the skill wants to show the same diff again. This is the "held calls outlive a killed
  client" failure (red team #1), which `wait` handles but `ask` does not.
- Suggested fix: make re-asking with the same id idempotent. When the id matches the job's last `asked` entry
  with outcome `answered` and the job has not moved on, return that stored answer instead of 400. Add a bridge
  test where the held `ask` thread consumes the answer and a second `ask` with the same id still gets it.

### H3. An uploaded workbook is fully parsed by openpyxl despite the bounded detection; the zip-ratio check can be padded past (reproduced)
- `templates_api.py:134-135`: `detect_layout_bounded` (read-only, 30 rows) is followed straight away by
  `preview_grid`, which loads the whole workbook in normal mode (`templates.py:388`). The same full load happens
  in `upload_preview` (`templates_api.py:155,162`) and in `register` → `detect_layout` (`templates.py:169,229`).
- `templates_api.py:74-79`: the ratio is checked on the totals of the whole zip, not per entry.
- Reproduced: a 2.5 MB upload whose `sheet1.xml` expands to 124 MB (ratio 229, about 4.5 M cells) passes
  `check_zip` once a 2 MB stored random entry is added. openpyxl's normal mode uses roughly 50 times the file size
  in memory, and far more for highly compressed sheets. One upload can therefore pin GBs of RAM and minutes of
  CPU in the server thread, freezing the tester's machine. Phase 2 promised "layout detection for uploads reads at
  most the first 50 rows"; the preview breaks that promise.
- Suggested fix: check the ratio and size per entry (for example each `xl/worksheets/*.xml` at most 20 MB
  uncompressed and at most 100:1), and lower `UNZIPPED_CAP`. Build the upload grid from a `read_only=True` pass
  (cells come from `iter_rows(max_row=header_row+8)`). Read merged ranges and data validations from the sheet XML
  only when that sheet entry is under the per-sheet cap; otherwise leave them out.

## Medium

### M1. `approval` is still served after the job was released, marked failed or finished; a released session re-attaches silently (reproduced)
- `jobs.py:866-870` returns `confirmed_approval` for a job in any state.
- `jobs.py:695-701`: when `attached is None`, `_agent` re-attaches whichever session calls.
- Scenario: the tester confirms a diff, then presses "Release agent" (or marks the silent job failed) because the
  agent looks wrong. The job is `failed: session-lost`. The old agent comes back. Its `console approval` / `wiki-update --job`
  re-attaches it (reproduced: `attached` becomes the released session again) and gets the hash, so the wiki write
  goes through after the tester stopped the job. It also takes the console back from any new session for 60 s.
- Suggested fix: in `approval`, return `{approval: null}` (or 409) unless the job is `running`/`needs-input`.
  After `release()`, refuse the released session id in `_agent`/`_contact` for the rest of the server's life:
  keep a `released` set and answer `session-replaced`.

### M2. `confirm-diff` accepts any preview the agent writes; the approval is not tied to what the tester sees (reproduced)
- `jobs.py:179-196` checks only the shape. `cli.py:526-531` lets `--question <file>` send `type: confirm-diff` /
  `paste-pages`, although phase 4 says they are "built only by `--from-preview`".
- Scenario: an injected agent sends a confirm-diff whose `diff` shows harmless text and whose `approval` is the
  hash of a different plan. Reproduced: the fabricated ask is accepted and the job goes to `needs-input`. The
  tester confirms, `confirmed_approval` gets the attacker's hash, and `wiki-update --job` passes.
- Suggested fix: refuse `confirm-diff`/`paste-pages` from `--question` in the client (this keeps an honest model
  on the intended path). Server-side, have the API-mode `wiki-append-preview` also output per-page `new_content`
  (an additive field). The server can then recompute `sha256(json.dumps([[name, updated, new_content], ...], ensure_ascii=False))`
  (the formula at `cli.py:362`), refuse the ask when it differs from `approval`, and show the tester the bound
  `new_content`.

## Low

### L1. `serve` changes the job store before the bind, so a second server on a busy port fails the live server's jobs on disk (reproduced)
- `lifecycle.py:393-401`: `install_routes` → `jobs.install` → `bridge.startup()` runs before `ConsoleServer(port)`.
- Reproduced: with a live server holding a queued job, `lifecycle.serve(home, port=<same>)` returns 2, and the
  job file now says `failed / server-stopped` while the live server's memory still says `queued`. Triggers: the
  documented fallback `console serve --foreground` started while a detached server runs, or two `start` calls at
  the same moment. The live server rewrites the file on its next save, so the damage is usually short-lived. It
  still breaks "writes only after the bind".
- Suggested fix: bind first (create `ConsoleServer` before `install_routes`, or call `bridge.startup()` from the
  `ready` path after the bind).

### L2. The job ticker thread is unguarded
- `jobs.py:959-962`: if `bridge.tick()` raises (for example `PermissionError` from `replace_retry` while an
  antivirus or indexer holds a job file on Windows), the thread dies. Offered jobs then go back to the queue only
  through the `wait`/`state_view` ticks. In foreground mode `threading.excepthook` prints a traceback with the job
  file path to stderr, against "stderr holds no file path".
- Suggested fix: wrap the loop body in `try/except Exception` and log only `type(exc).__name__` to `server.log`.

### L3. Pruning keeps the oldest of the finished jobs created in the same second; its test cannot catch that (reproduced)
- `jobs.py:463-471` sorts by `created_at` at second precision with `reverse=True`. A stable sort keeps insertion
  order on ties, so the newest job is pruned first. Reproduced with 55 cancelled jobs: newest dropped, oldest kept.
- `tests/test_console_jobs.py:397-405` (`test_pruning_keeps_the_newest_finished_jobs`) only checks the count.
- Suggested fix: sort on `(created_at, id)` or keep a creation counter, and assert which ids survive.

### L4. Trace on the ticket's own workbooks: open handle on Windows and 500 on broken files
- `xlsx.py:143` (`pick_sheet`, reached from `readapi.py:406`) opens the workbook `read_only=True` and never
  closes it. Workbook ↔ sheet references form a cycle, so the handle is only released by the cyclic GC.
  Reproduced with GC paused: `os.replace` on the workbook raises `PermissionError`. In the long-lived server this
  can briefly stop Excel from saving the tester's file.
- `readapi.py:521-528` maps only `TemplateError`/`ReportError`. A corrupt or non-zip `.xlsx` in the ticket folder
  raises `BadZipFile`/`InvalidFileException` and gets a 500. These workbooks are also loaded fully with no zip
  check (same exposure as H3, but only for files the tester put there).
- Suggested fix: close the read-only workbook in `pick_sheet` (`wb.close()` in `finally`; the CLI output does
  not change). Map openpyxl/zip errors to `400 template-error`.

### L5. The upload sweeper thread never stops
- `templates_api.py:209-214`: `while True: sleep(3600)` per `serve` call. It is harmless in a dedicated server
  process, but it leaks one thread per `serve_in_thread` in the test process and ignores shutdown. Suggested fix:
  loop on an `Event` set by a shutdown hook.

## Checked, no finding
- Check order, Host/Origin/Sec-Fetch-Site, 415/413 before the body is read, the CSP and frame headers, and
  `OPTIONS` → 403 all match phase 1. Path params are matched against listings and never joined into paths.
- `server.log` holds only method, route pattern, status, duration and the error code. Error messages carry no
  paths or customer text. The handler's log methods are silenced.
- Locks: `ConsoleState.lock` and `Bridge.cond` are never nested (arguments are evaluated before the bridge
  call), so lock order cannot invert. Held calls wake on `notify_all`, and `shutdown()` closes them all.
- State machine: `TRANSITIONS` matches the phase 4 diagram; implicit claim, revision-moved at claim only,
  takeover limits (60 s / 15 min, 0 while a held call is open), release, restart failing queued and open jobs,
  idle end requiring no held call and `busy()` false.
- Stale `server.json`: removed only on connection refused and only while it names the same instance. A foreign
  listener gets exit 2 and the file is left as it was. `stop` uses the pid the server reports for itself.
- Existing CLI: `trace` output is unchanged through `trace_for`. `TemplateError` subclasses keep the CLI
  messages. `config.load()` keeps creating the file by default. `wiki-update` without `--job` is unchanged.
- Windows: `SO_EXCLUSIVEADDRUSE`, `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB`
  with a retry, no `DETACHED_PROCESS`, and `CREATE_NO_WINDOW` on git.

## Unresolved questions
1. H1 reverses a risk the plan accepted ("outside this design's reach"). Should the console add mitigation (a)
   and/or (b), or should the plan and README state that the credential split does not hold against an injected
   agent?
2. M2's server-side binding adds `new_content` to the API-mode `wiki-append-preview` output (an additive CLI
   change). Is that acceptable under "existing CLI outputs unchanged"?
