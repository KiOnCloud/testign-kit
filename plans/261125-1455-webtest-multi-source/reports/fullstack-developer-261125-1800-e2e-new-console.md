# E2E browser tests moved to the redesigned console

Status: done, not run in a browser (Playwright is not installed). `python3 -m py_compile tests/e2e/*.py`
passes; `pytest tests/e2e` without `TESTIGN_E2E=1` gives 3 skipped.

## Files

- `tests/e2e/test_console_smoke.py`: UI languages en and ja, `NAV_SURVEY` (`nav_survey`: "Ticket survey" / "チケット調査"),
  home `#/suites` with ready name `suites`, routes for suites, new suite, survey, report, trace, runs, agent, projects,
  scenarios, templates, cache and settings. The language control is the top bar select `#ui-lang` (shell.mjs
  `LANG_SELECT_ID`). New test `test_old_hashes_land_on_their_new_screens` covers `#/tickets`, `#/tickets/<t>`,
  `#/tickets/<t>/trace`, `#/jobs` and `#/login`. These are the only old hashes left in tests/e2e.
- `tests/e2e/test_console_jobs_smoke.py`: `#/survey`, `#/survey/<t>` and `#/agent/<job>`. The Close review is
  answered on the job page through `[data-close-review=…]` and `.review-footer .yh-btn--primary`. The job
  actions are `[data-job-action=cancel|fail|release]`.
- `tests/e2e/test_console_webtest_smoke.py`: rewritten. The project is saved on `#/projects`. A manual suite
  is made in the `#/suites/new` wizard, given one case and confirmed, and a run is started with the New run
  dialog, all in the UI. The fixture's Figma suite gives two runs: one from `build()`, and a second from
  `suite_api.create_run`, because `ready_suite` has a fixed id and cannot be built twice. These two runs cover
  the sign-in card, the export and the parked row.
- `tests/e2e/conftest.py`: unchanged. Its vi content is report data, not UI language.

## Old assertions dropped or replaced

1. `#view .k-spinner` count 0 on a queued job: dropped. The job page has no spinner (progress uses status icons).
2. `"/testign:console"` in `.k-banner--warning` on a queued job: the queued notice no longer names the command.
   It now checks the ja `agent_none_queued` text in `#view .yh-alert`. The top bar `#agent-status` check stays.
3. `[data-open-review]` and `.review-table`: the review is shown inline on the job page. It now waits for
   `[data-close-review='review-rows' | 'confirm-diff' | 'paste-pages']`.
4. Late tab clicks send and gets `.k-toast--danger`: the new UI hides the controls instead. It now checks that
   the late tab shows `[data-too-new]` and no `.review-footer`.
5. `.k-split__panel-head .k-btn--danger/--secondary/--ghost` and `.k-banner--danger` on the job page: replaced
   by `[data-job-action=…]` and `#view .yh-alert--danger`.
6. Login screen `#login-project-name`, `#login-hosts`, `[data-save-hosts]` and `[data-project='demo'].is-selected`:
   moved to the Projects screen. The `.is-selected` check is dropped, and the test now checks that
   `tr[data-project='demo']` exists.
7. Run form plan job (`#runform-*`, `kind == "webtest-plan"`, `params.source.node == "12:34"`, `params.hosts`):
   dropped. Parsing a Figma node now happens in a suite-generate job, which this test does not drive.
8. Whole review-table test (`#rt-runner-r05`, `[data-confirm-table]`, a delegated row needs preconditions,
   landing on `#/runs/<run>`): dropped. The matching rule (a choice case run by the agent needs preconditions)
   now sits in the suite case form, and no e2e test covers it.

Added: sign-in card and export on the Run screen. The brief said to keep them, but the old file had neither.

## Selectors or behaviour I was unsure of

- `#view .yh-alert`: the test reads the first match. This assumes the queued notice is the first alert on
  the job page (jobs.mjs `jobPage` notice order).
- `[data-run-action=export]`: it appears only after `bridge.done(…, "failed", …)` and a store-driven reload
  of the run.
- The sign-in card is expected to detach after the answer. This depends on store polling re-rendering the run.
- The New run template defaults to `mẫu` (a test case template). `check_run_target` accepts any registered
  template.
- The scenarios screen with no projects, and horizontal scroll at 390 px on the new screens, were not checked
  in a browser.
