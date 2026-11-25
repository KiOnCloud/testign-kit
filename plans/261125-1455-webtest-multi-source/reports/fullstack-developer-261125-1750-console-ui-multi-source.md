# Console UI for multi-source web tests (phase 6 and phase 7 UI)

Plan: `plans/261125-1455-webtest-multi-source/`
Scope: all of phase 6. From phase 7: steps 1–6 and 8, plus the UI part of step 7 (the UI no longer queues `webtest-plan`).
Status: done. The UI work is finished, but the end-to-end tests are out of date (see the concerns below).

## Outcome

The console now follows the mockups `mockup/multi-source.html` and `mockup/console-redesign.html`.

**Menu.** The menu has three groups:
- Test case design: Test suites, Ticket survey.
- Test runs: Runs, Agent.
- Settings: Projects & hosts, Login scenarios, Templates, Scout cache, Preferences.

**Old links.** Links to the old screens are redirected:
- `#/tickets` goes to `#/survey`.
- `#/jobs` goes to `#/agent`.
- `#/login` goes to `#/scenarios`.
- `#/jobs/<id>/review(-table)` goes to the job's run.

**Screens built:**
- The suite list.
- The four-step suite wizard for figma, backlog, excel and manual.
- The suite detail page, with case editing, bulk edits, confirm, export and its runs.
- The New run dialog, which goes from a confirmed suite to a project and hosts, then to the run.
- The runs list, with a needs-you alert, filters and result icons.
- The run page, including a columns editor.
- The Agent page, which shows the agent's tools and the jobs, and marks legacy plan jobs.
- Projects & hosts, Login scenarios, Templates, Scout cache and Preferences.

Every status is an icon with a tooltip. Tables scroll sideways. The safety alerts stay visible in New run and in the project dialog.

**Removed:** `tickets.mjs`, `review.mjs`, `review-table.mjs`, `login.mjs` and `run-form.mjs`, with their tests.

## Verification

- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`: 117 passed.
- `pytest -q tests/test_console_ui_assets.py tests/test_console_server.py`: 94 passed.
- rg checks:
  - `#/tickets|#/jobs|#/login` appears only in the redirect table comment in `router.mjs`.
  - `webtest-plan` appears only in `LEGACY_KINDS`.
  - The `'vi'` check and the inline-style check find nothing.
  - Every `t('key')` exists in en and ja, and the two files have the same keys.
- Browser check in headless Chromium, against a demo console with two projects, two scenarios, a ready suite, a suite waiting for review, and a run:
  - Covered: en and ja, at 1440 px and 390 px, on all 13 screens. At 390 px I also opened the menu, the New run dialog, wizard step 2, the project dialog and the template panel.
  - Result: no page-level sideways scroll, no raw i18n keys, no console errors.

## Fixes from the browser check

- At 390 px the run page's action buttons pushed the page sideways. The action row can now shrink and wrap.
- Under 1200 px a split layout could grow to the width of its widest child, which made the template panel 962 px wide. The single column is now `minmax(0, 1fr)`.
- The new-tab session notices had extra side padding, so at 1440 px they did not line up with the page. At 390 px the text was squeezed into a thin column. The padding is removed and the buttons now drop under the text.
- The run page and the suite page used different words for the same case class. Both now use the `case_class_*` labels through one `classBadge`. The unused `wt_class_*` keys were removed.
- The "needs you" badge in the menu cut the Agent label short. It now shows only the count; the full wording is in the tooltip and in screen-reader text. Menu labels have a tooltip.
- In English, "1 things need you" now reads "1 thing needs you" (`runs_needs_t_one`).

## Concerns

- The end-to-end tests in `tests/e2e/*.py` still use the old routes and selectors, for example `data-ready='tickets'`, `#/login`, `#/jobs`, review-table and `data-save-hosts`. They will fail against the new UI until they are updated. They are Python files, which were outside my ownership.
- The server has no API to add a login scenario. The Scenarios screen can review, approve, reject and remove scenarios, but new ones still come from the agent's sign-in flow.
- The scout cache has no clear endpoint, so the Cache screen is read only.

All processes started for the browser check (the demo server and headless Chromium) have been stopped. Their temporary home folder has been removed.
