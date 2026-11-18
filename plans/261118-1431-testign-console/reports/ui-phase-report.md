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
