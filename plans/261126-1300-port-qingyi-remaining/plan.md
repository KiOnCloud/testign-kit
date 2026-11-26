# Port from qingyi-test-kit: the remaining pieces

Status: done · Requested by Asher (2026-11-26) · Follows the replay and Login Recipe work (PR #9)

## Outcome

Everything left open by the port assessment and the replay work, in one PR: browsers per run, flaky
rows, replay with nobody at the console, a console form for profile values, a `setup` command, and
template versions. Knowledge and the `design.json` renderer stay out (decided in the assessment).

## Design

| Piece | Where |
|---|---|
| Browsers per run (`chromium`, `msedge`, `firefox`, `webkit`); a result column per browser; a browser that cannot start is Pending | `webtest.check_browsers`, `run.browsers`, `webtest_live.launch(browser=)`, `webtest_replay._replay_row`, `webtest_export` (`verdict_<browser>`) |
| Flaky: a failed or unrunnable row is tried once more; a pass then is marked flaky | `webtest_replay._replay_row`, `result.flaky`, report section, `flaky` export field |
| Replay with nobody at the console | `webtest-replay --run` without `--job` (refused while a row runs), `webtest-replay-new` for cron / Task Scheduler |
| Console form for profile values: write-only, staging box required, browser session only, blocked by the secret guard | `PUT/DELETE /api/webtest/profiles/:project/:profile`, scenario dialog |
| `setup`: checks Python, openpyxl, Playwright and each browser; `--install` without admin rights | `setup_check.py`; CI e2e on macOS and Windows uses it |
| Template versions: registering again keeps up to ten earlier versions; a run's column plan pins its version | `templates.register/resolve(version=)`, `plan.template_version` |

## Acceptance criteria

1. A run made with several browsers replays each row in each; one failing browser fails the row; a
   missing browser is Pending in its column.
2. A row that passes only on the retry is a pass marked flaky in the run, the report and the export.
3. `webtest-replay-new` refuses a suite without a reviewed spec; `webtest-replay` without a job refuses
   while a row runs.
4. The profile form never returns a value, needs the staging box and the console tab's session, and
   the secret guard blocks it from the agent's commands.
5. `setup` lists what is missing and installs only with `--install`; CI runs the browser tests on
   macOS and Windows after `setup --install`.
6. A replaced template keeps the earlier file; a pinned run exports with the version it was made for.

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | Browsers, flaky retry, export columns | done |
| 2 | Replay with nobody at the console | done |
| 3 | Profile form and guard | done |
| 4 | setup command and CI | done |
| 5 | Template versions | done |
| 6 | Tests, docs, version 0.9.0 | done |
