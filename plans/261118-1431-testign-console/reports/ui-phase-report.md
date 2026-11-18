# Console UI: shell, i18n and screens — implementation report

Date: 2026-11-18. Scope: the browser console on top of the existing server and read/templates API.

## What was built

- `scripts/testign/console/ui/`: `index.html` (one module script, no inline script or style),
  `app.css`, `main.mjs` (prefs → strings → session → shell → route), `api.mjs` (launch code read
  once from `#c=`, removed with `history.replaceState`, token in `sessionStorage` only,
  `X-Testign-Session` on every call, 403 → reopen message), `router.mjs`, `i18n.mjs` (flat keys,
  `{name}` interpolation, `_one` form for n = 1, fallback vi → key), `dom.mjs` (`h()` sets text via
  `textContent`/text nodes, refuses `style` and `on*`, shows U+202A–U+202E and U+2066–U+2069 as
  `⟨U+202E⟩`; SVG icons via `createElementNS`), `format.mjs` (ISO dates, short SHAs, id ranges),
  `palette.mjs` (Ctrl/⌘+K palette over screens and tickets, focus trap, typing-target guard),
  `prefs.mjs` (`testign.uiLang` from `navigator.languages`, `testign.theme` default light,
  `testign.testerName`, all inside try/catch).
- Views: Tickets (filter, conclusion filter, Questions = question count · Block count, test case
  summary, per-row hash after first paint two at a time, stale banner, unreadable/inconsistent
  rows), Report (revision picker, refs, hash, report-language badge, summary strip, section tabs
  with manual activation, selectable B/R/Q rows with a split panel showing the row and its finding,
  Japanese draft with Copy, j/k row movement, Esc closes and returns focus), Trace (workbook picker
  when more than one, template picker with the default preselected, header-mismatch banner listing
  differing columns, no-template and no-workbook states pointing to Templates, hash banner,
  coverage/gap/orphan/waiting cards, case table with All/With issues), Templates (list, detail with
  grid, role row, merged ranges and dropdowns; register dialog: upload → detected layout → sheet,
  header row, roles → name → register, with server error codes mapped to messages; Set default;
  Remove with confirmation), Scout cache (read-only table and detail panel), Settings (language,
  theme, tester name; version and address; read-only config table). Loading, empty and error
  states in every view. No job buttons and no Jobs nav item.
- `i18n/{vi,en,ja}.json`: 277 keys each, seeded from the mockups' string tables.
- `vendor/kestrel/{tokens.css,bundle.css,LOCK.json}`: bundle.css without its Google Fonts
  `@import` (tokens.css had none). LOCK.json records source, version, upstream and vendored sha256
  (over LF line endings, so Windows CRLF checkouts hash the same) and the one change.
- `@font-face` rules for the downloaded Inter and JetBrains Mono subsets with the fontsource
  unicode-range values; Japanese falls through to the system faces in the Kestrel stack.
- `THIRD_PARTY_NOTICES.md` (Kestrel: the artifact states no licence; Inter and JetBrains Mono OFL).
- Tests: `ui/tests/*.test.mjs` (35 node tests), `tests/test_console_ui_assets.py` (32 checks:
  parity, placeholders, every literal `t('key')` exists, no inline style/handlers/markup sinks,
  LOCK drift, no external CSS loads, font licences and faces, relative imports, static manifest),
  `tests/e2e/test_console_smoke.py` + `tests/e2e/conftest.py` (DEMO data builder).
- CI: node test step after setup-node; macOS e2e job with Playwright + Chromium.

## Results

- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`: 35 passed (Node 24.15).
- `python -m pytest tests/test_console_ui_assets.py -v`: 32 passed.
- `python -m pytest -q` (full suite): 313 passed, 3 skipped in 173 s. After the summary the
  process did not exit; `tests/test_console_jobs.py`, `test_console_bridge.py` and
  `test_console_lifecycle.py` alone reproduce it (all pass, then the interpreter stays alive),
  while the UI test files exit at once. `test_concurrent_set_default_leaves_a_valid_index` failed
  once while two suites ran in parallel and passes alone.
- e2e: Playwright is not installed locally, so `TESTIGN_E2E=1 python -m pytest tests/e2e` was not
  run in a browser. It skips cleanly with and without the variable; with a stub `playwright`
  module all 9 tests reach the browser step, so the fixtures, demo data and server start work.
- Live smoke (instead of the built-in browser tools, which were not available to this session):
  headless Chrome over CDP against `console serve --foreground` on a DEMO home. Every screen in
  vi/en/ja at 1440 and 390 px: no console error or warning (CSP included), no horizontal page
  scroll, `<html lang>` follows the choice. Language switch changed the nav label and left the
  report cell (with a visible `⟨U+202E⟩`) unchanged; split panel opens with focus on its title and
  Esc closes it and returns focus to the row; j moves focus and is typed into the search field
  instead of acting; Ctrl+K palette filters and navigates, Esc closes it; register dialog focuses
  the file field; dark theme persists; a reused launch code and a bare URL both show the reopen
  message, and a new launch code pasted into that tab opens the console. Template registration
  end to end with `テスト仕様書_v3.xlsx`: layout detected (sheet, header row 4, item B, trace H), a
  cleared required role is refused before any request, `name-taken` shows its message, a template
  named `khách-A 顧客` registers and is selected, Set default and Remove (Cancel focused) work.
  The only browser log entry was the expected 409 for the taken name. The server and every headless
  Chrome started for these checks were stopped afterwards.

## Deviations

- `node --test scripts/testign/console/ui/tests/` (a directory) fails on Node 21+; CI and the
  verification use the glob `"scripts/testign/console/ui/tests/*.test.mjs"`, which Node 22+
  expands itself.
- The Settings console card shows version and address only; mode, idle time, sessions and agent
  state are not exposed by the read API and belong to the job bridge screens.
- The sidebar keeps an empty, hidden `#agent-status` slot for the agent state.

## Jobs and Close review

Date: 2026-11-19. Scope: the job screens on top of the job bridge, and the triggers on Tickets,
Report and Trace.

### What was built

- `ui/store.mjs`: polls `/api/state` every 1.5 s while the tab is visible and not at all while
  hidden. Views redraw only when the change counter moves (or the open job turns silent, or the
  agent attaches or leaves); the sidebar updates on every status change. New browser sessions are
  reported once; the known set is kept in `sessionStorage` so a reload neither repeats nor loses a
  notice. A 403 stops polling.
- Sidebar: Jobs nav item with a needs-input badge (or the open and queued count), the agent line
  (none attached with the `/testign:console` hint, connected, working, waiting for you, silent N
  min, server not answering), and the tab title prefixed with the needs-input count.
- New browser session: a warning banner in every open tab with the time, saying a new console tab
  was opened and offering Release agent; it stays across screens and reloads until dismissed.
- `views/jobs.mjs`: Open and History tabs, rows with Kestrel status glyphs (queued and offered
  hollow, running and needs-input partial, done filled, failed crossed in the danger colour), the
  open job selected by default, a detail panel with parameters, progress steps, the agent's report,
  past questions and actions: Cancel (queued), Mark failed and Release agent (silent), Queue again
  (failed; "Queue again on the latest revision" for `revision-moved`, with the explanation).
  `questions` asks are answered in the panel (radio or checkbox groups, optional Other, multi-line
  where the ask allows, Ctrl+Enter); review asks link to the review screen.
- `views/review.mjs`: `review-rows` table (Q, class, decision with row id, decided by and date,
  quote with its `lang`, source, page, feature, anchors) with Write, Skip and Edit; Edit opens
  decision, anchors and page; the primary button stays disabled until every row has a choice and
  every edit changes something. `confirm-diff` shows the server's diff per page with a "New page"
  badge and the added, skipped, superseded and index-repaired lists; Write confirms, Back declines.
  `views/paste-pages.mjs` shows each page with Copy and states that testign wrote nothing; Done
  answers. Choices survive polling and language switches.
- `views/survey-form.mjs`: ticket, repo path (remembered in `localStorage` as `testign.lastRepo`),
  refs, fetch, feature and report language (default: config `lang`), with checks that mirror the
  server's. "Survey again" (Tickets stale banner) prefills from the report frontmatter, prefers the
  remembered repo, never prefills fetch, and the tester confirms in the dialog.
- `views/job-actions.mjs`: queueing with the viewer's `ui_lang`, server error codes mapped to
  messages (including `session-too-new`, which does not send the tab to the reopen page), the
  tester-name prompt before Close QA (saved to Settings), the template picker when more than one
  template is registered, and Queue again bodies.
- Triggers: Tickets "Survey ticket" (primary, `C`); Report "Close QA" and "Write test cases"
  (primary), both disabled with a note on an older revision; Trace "Write §7 to r{n+1}" (primary;
  shown workbook and selected template) and "Add a case for R…" per gap. Settings shows the agent
  state and the browser session count. One primary button per view.
- Backend changes adopted: upload previews with `complete: false` show a note instead of merged
  cells and dropdowns; `workbook-unreadable` has its own message.
- 196 new keys in each dictionary (473 in all).

### Results

- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`: 54 passed (new: `store.test.mjs`,
  `ask-form.test.mjs`, plus job routes, times and the remembered repo).
- `python -m pytest tests/test_console_ui_assets.py -v`: 41 passed.
- `python -m pytest -q -p no:cacheprovider`: 334 passed, 4 skipped in 159 s (exits normally).
- e2e: `tests/e2e/test_console_jobs_smoke.py` was added (close round in ja with the tester prompt,
  one edited row, a diff with a new page and a superseded entry, manual pages, a late tab refused,
  a survey waiting with no agent, a silent agent released, triggers disabled on an older revision).
  Playwright is not installed locally: the tests skip cleanly, and with a stub `playwright` all 14
  browser tests reach the browser step.
- Live smoke (headless Chrome over CDP, a server in a thread on a DEMO home, the agent played with
  `testign.console.client`): 41 checks passed with no console error or warning. Covered: no agent
  (sidebar, Jobs banner, a queued survey, no spinner), survey form checks and the remembered repo,
  Cancel, Close QA with an empty tester name prompted in ja, needs-input badge and `(1)` title,
  review-rows with one edit (the agent got `{"action": "edit", "decision": …, "anchors": […]}`),
  quote `lang="ja"` with visible bidi marks, 390 px without horizontal scroll, confirm-diff with a
  new page and a superseded entry (the approval matched), the agent's report, paste-pages, a tab
  opened after the job started refused with the `session-too-new` message (the job kept waiting),
  the session warning with Release agent, a questions ask with a multi-line Other, an agent-failed
  job, a silent agent marked failed then queued again then released, revision moved with "Queue
  again on the latest revision", older-revision triggers disabled, Write test cases with the
  template picker, Add a case for R2, Write §7 to r4, Survey again prefilled (repo from the
  remembered value, report language ja, fetch off), and Jobs and Review in vi/en/ja at 1440 and
  390 px without horizontal scroll. The server thread and every headless Chrome were stopped.

### Notes

- A released agent session cannot attach again (server behaviour); the smoke uses a new session
  id after Release agent.
