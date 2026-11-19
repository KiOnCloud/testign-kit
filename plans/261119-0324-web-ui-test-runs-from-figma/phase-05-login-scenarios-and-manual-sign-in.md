---
phase: 5
title: "Login scenarios and manual sign-in"
status: pending
priority: P1
effort: "1.5d"
dependencies: [4]
---

# Phase 5: Login scenarios and manual sign-in

## Goal

Named login scenarios per project that the tester picks per row. A scenario is a checklist the
agent drafts and the tester approves; the tester signs in by hand in their own Chrome and confirms
it in the console.

## Context

- The user's rule: Claude never touches authentication. Login differs per project, a project can have several scenarios, and when none is chosen or created the agent asks whether to create one.
- Decided by the user on 2026-11-19 after the spike: runs use the tester's own signed-in Chrome profile (the work profile). There is no dedicated test profile, no debug connection and no automatic runner.
- With no runner nothing consumes stored account values, so none are stored. The tester types them into the site, or lets the browser's own password manager fill them. This replaces the earlier decision to enter them in a console form.
- The spike found the tester's Chrome already signed in on the test site (`reports/spike-macos-2026-11-19.md`). A scenario therefore also says how to tell which account is signed in.
- The existing approval pattern: the tester confirms a hash in the console (`cli.py:385-400`; `console/jobs.py:896-902`).

<!-- Updated: Red Team Session 1 - hosts tester-only; scenario approval by hash; name checks; owner-only folder; no step editor -->
<!-- Updated: Spike 2026-11-19 - no runner, no stored account values, no selectors; sign-in by hand in the tester's own profile; account check -->

## Store

```text
~/.testign-kit/webtest/                 created owner-only
  projects.json                         {"<project>": {"hosts": [...], "signin_hosts": [...]}}
  login/<project>/<scenario>/
    scenario.json                       the draft or approved checklist
    approval.json                       {"hash": "...", "approved_at": "...", "by": "<session fingerprint>"}
```

Project and scenario names match `[a-z0-9][a-z0-9-]{0,39}`, are never a Windows reserved name
(`console/templates_api.py:31`), and are resolved by listing the folder, never joined into a path
from a request.

`scenario.json`:

```json
{"name": "client", "label": "Client account",
 "login_url": "https://dev.example.jp/login",
 "signout_url": "https://dev.example.jp/logout",
 "steps": ["Open the login page", "Sign in with the client test account", "Enter the one-time code if asked"],
 "signed_in_check": {"url": "https://dev.example.jp/", "text": "予約履歴"},
 "account_hint": "The header menu shows the client user's name",
 "created_at": "..."}
```

- `steps` are plain lines for the tester to read. They hold no selector, no field value and no script.
- Every URL is on one of the project's `hosts` or `signin_hosts`.
- `signed_in_check` is a page and a text the worker can read after sign-in to tell that a session exists. It cannot tell which account is signed in; `account_hint` tells the tester what to look at.
- The scenario `none` is built in for public pages.

## Who writes what

| Data | Written by | Through |
|---|---|---|
| Project hosts, sign-in hosts | Tester | Console only (`/api/webtest/projects`); no CLI command writes them |
| Scenario draft | Agent | `login-scenario-save`, which validates against the tester's hosts |
| Scenario approval | Tester | Console: the tester sees the checklist and approves its hash |

A scenario is usable only while `approval.json` holds the hash of the current `scenario.json`.
Saving a new draft makes it unapproved again. When a line is wrong the tester rejects the draft
with a note, and the agent redrafts it in the next plan or run job.

## Signing in

1. The orchestrator opens the login question (phase 4) that names the scenario. It makes no Chrome tool call while the question is open.
2. The console shows the approved checklist, the account hint, and, when the queue is switching scenarios, "Sign out first" with the sign-out URL.
3. The tester signs out and in by hand in their own Chrome, checks the account, and presses "Signed in", or "Skip this scenario".
4. The orchestrator reads the answer through `webtest-signed-in` (phase 2). The first worker of that scenario runs the `signed_in_check`; a failed check is a `blocked-env` outcome and the login question opens again.

## Creating a scenario

When a row needs a scenario that does not exist, the orchestrator asks (a `questions` ask)
"Create a login scenario for this project?". On yes it reads the site's navigation for the login
and sign-out addresses, without typing anything, and writes the draft with `login-scenario-save`.
When the tester's Chrome is signed in, the login page may not be reachable; the draft then holds
what could be read and the tester's rejection note fills the gap. The draft waits for approval.

## Commands

| Command | Does |
|---|---|
| `login-scenario-list --project <p>` | Names, labels, `approved`. |
| `login-scenario-save --project <p> --file <draft>` | Validates and stores `scenario.json`; refuses off-host URLs and unknown keys; clears the approval. |
| `login-scenario-remove --project <p> --name <s>` | Removes the scenario and its approval. |

## Routes

| Route | Group | Does |
|---|---|---|
| `GET /api/webtest/projects`, `PUT /api/webtest/projects/:project` | browser | List; create or edit hosts and sign-in hosts |
| `GET /api/webtest/login/:project` | browser | Scenarios with their checklist and `approved` |
| `POST /api/webtest/login/:project/:scenario/approve` | browser | Stores the approval for the hash the tester saw; 409 when the scenario changed since |
| `POST /api/webtest/login/:project/:scenario/reject` | browser | Stores a note for the agent; no approval |
| `DELETE /api/webtest/login/:project/:scenario` | browser | Removes the scenario |

## Files to Create / Modify

- Create: `scripts/testign/login_scenarios.py` (store, validation, host checks, hash)
- Create: `scripts/testign/console/login_api.py` (the routes above)
- Modify: `scripts/testign/cli.py` (the three commands)
- Create: `tests/test_login_scenarios.py`, `tests/test_console_login_api.py`

## Tasks & Steps

1. Write the store, the name checks and the validators.
2. Write the hash and the approval rule; a saved draft clears the approval.
3. Write the project and scenario routes.
4. Write the three commands.
5. Write the tests listed below.

## Todo

- [ ] Store, name checks, validators
- [ ] Approval by hash
- [ ] Project and scenario routes
- [ ] Scenario commands
- [ ] Tests

## Verification

- `python -m pytest tests/test_login_scenarios.py tests/test_console_login_api.py -v`
- Tests cover: a scenario with an off-host URL or an unknown key is refused; no CLI command changes a project's hosts; a saved draft is unapproved; an approval for an older hash gets 409; removing a scenario removes its approval; project and scenario names with `..`, `%2F`, `\` or a reserved name get 404; the store has no field that can hold an account value.

## Risks

- The tester signs in with the wrong account and confirms. Rows then run with other rights and may pass or fail for the wrong reason. The account hint and the user name read by the signed-in check, shown in the run's log line, are the guard; the report names the scenario each row ran under.
- The tester's work profile holds other signed-in sites. The run's host limit and the site-access confirmation (phase 6) are what keep the agent on the test site.
