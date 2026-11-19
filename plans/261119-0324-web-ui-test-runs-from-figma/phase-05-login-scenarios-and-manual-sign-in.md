---
phase: 5
title: "Login scenarios, credentials and manual sign-in"
status: pending
priority: P1
effort: "2.5d"
dependencies: [4]
---

# Phase 5: Login scenarios, credentials and manual sign-in

## Goal

Named login scenarios per project that the tester picks per row: drafted by the agent from the
login form's structure, approved by the tester, filled with credentials only by the tester, and
usable at once through manual sign-in with a checklist.

## Context

- The user's rule: Claude never touches authentication. Login differs per project, a project can have several scenarios, and when none is chosen or created the agent asks whether to create one.
- Decided by the user on 2026-11-19: a scenario is a step list run by a fixed runner (not a generated script); credentials are typed into a console form; testers do not write or edit steps by hand in the console, they approve or reject the agent's draft.
- This phase needs no browser connection. The runner that executes a scenario is phase 6; everything here works with the manual route alone.
- The existing approval pattern: the tester confirms a hash in the console and the writing command refuses anything else (`cli.py:385-400`; `console/jobs.py:896-902`).

<!-- Updated: Red Team Session 1 - split from the runner; hosts tester-only; scenario approval by hash; secret fields; name checks; owner-only folder; no step editor -->

## Store

```text
~/.testign-kit/webtest/                 created owner-only
  projects.json                         {"<project>": {"hosts": [...], "signin_hosts": [...]}}
  login/<project>/<scenario>/
    scenario.json                       the draft or approved step list
    approval.json                       {"hash": "...", "approved_at": "...", "by": "<session fingerprint>"}
    credentials.json                    written only by the console's credentials form
```

Project and scenario names match `[a-z0-9][a-z0-9-]{0,39}`, are never a Windows reserved name
(`console/templates_api.py:31`), and are resolved by listing the folder, never joined into a path
from a request.

`scenario.json`:

```json
{"name": "member", "label": "Member account", "login_url": "https://test.example.com/login",
 "fields": [{"name": "email", "secret": false}, {"name": "password", "secret": true}],
 "steps": [
   {"do": "goto", "url": "https://test.example.com/login"},
   {"do": "fill", "selector": "#email", "field": "email"},
   {"do": "fill", "selector": "#password", "field": "password"},
   {"do": "click", "selector": "button[type=submit]"},
   {"do": "manual", "note": "Enter the one-time code"},
   {"do": "expect", "url_prefix": "https://test.example.com/mypage", "timeout": 20}
 ],
 "signout": [{"do": "goto", "url": "https://test.example.com/logout"}],
 "created_at": "..."}
```

- Step kinds are closed: `goto`, `fill`, `click`, `wait`, `manual`, `expect`. A `fill` names a field, never a value. No step carries script text.
- Selectors match a small grammar: tag, `#id`, `.class`, `[attr=value]` and descendant or child combinators; anything else is refused when the draft is saved.
- Every URL is on one of the project's `hosts` or `signin_hosts`.
- `signout` is used when the queue switches to another scenario on the same hosts.

## Who writes what

| Data | Written by | Through |
|---|---|---|
| Project hosts, sign-in hosts | Tester | Console only (`/api/webtest/projects`); no CLI command writes them |
| Scenario draft | Agent | `login-scenario-save`, which validates against the tester's hosts |
| Scenario approval | Tester | Console: the tester sees the steps and approves their hash |
| Credentials | Tester | Console form |

A scenario is usable only while `approval.json` holds the hash of the current `scenario.json`.
Saving a new draft makes it unapproved again. The runner (phase 6) and the manual checklist both
refuse an unapproved scenario. When a step is wrong the tester rejects the draft with a note, and
the agent redrafts it in the next plan or run job.

## Credentials

- The tester fills `fields` in a console form. The browser posts them to `PUT /api/webtest/login/:project/:scenario/credentials`; the server writes `credentials.json` and answers `{filled: true}`.
- No route, command or log returns the values. `GET` routes return only `filled` and the field names.
- The agent has no command that reads the file. The skill forbids opening anything under `~/.testign-kit/webtest/login/`, and the README gives the deny rules for the tester's Claude Code settings that cover the read tool and shell reads of that folder. This is a policy guard: the agent runs as the tester, so nothing on disk can stop a read. The README says so.
- Removing a scenario deletes its credentials and approval.

## Manual sign-in

1. The orchestrator opens the login question (phase 4) that names the scenario.
2. The console shows the approved steps as a checklist, with the field names but no values.
3. The tester signs in in the test browser and presses "Signed in", or "Skip this scenario".

## Creating a scenario

When a row needs a scenario that does not exist, the orchestrator asks (a `questions` ask)
"Create a login scenario for this project?". On yes it opens the login URL, reads the form's
structure with the Chrome tools, and writes the draft with `login-scenario-save`. It types nothing
into the form. The draft then waits for the tester's approval and credentials in the console.

## Commands

| Command | Does |
|---|---|
| `login-scenario-list --project <p>` | Names, labels, `approved`, `filled`. Never field values. |
| `login-scenario-save --project <p> --file <draft>` | Validates and stores `scenario.json`; refuses unknown step kinds, selectors outside the grammar and off-host URLs; clears the approval. |
| `login-scenario-remove --project <p> --name <s>` | Removes the scenario, its approval and its credentials. |

## Routes

| Route | Group | Does |
|---|---|---|
| `GET /api/webtest/projects`, `PUT /api/webtest/projects/:project` | browser | List; create or edit hosts and sign-in hosts |
| `GET /api/webtest/login/:project` | browser | Scenarios with steps, `approved`, `filled` |
| `POST /api/webtest/login/:project/:scenario/approve` | browser | Stores the approval for the hash the tester saw; 409 when the scenario changed since |
| `POST /api/webtest/login/:project/:scenario/reject` | browser | Stores a note for the agent; no approval |
| `PUT /api/webtest/login/:project/:scenario/credentials` | browser | Writes the credentials |
| `DELETE /api/webtest/login/:project/:scenario` | browser | Removes the scenario |

## Files to Create / Modify

- Create: `scripts/testign/login_scenarios.py` (store, validation, selector grammar, host checks, hash)
- Create: `scripts/testign/console/login_api.py` (the routes above)
- Modify: `scripts/testign/cli.py` (the three commands)
- Create: `tests/test_login_scenarios.py`, `tests/test_console_login_api.py`

## Tasks & Steps

1. Write the store, the name checks and the validators.
2. Write the hash and the approval rule; a saved draft clears the approval.
3. Write the project and scenario routes.
4. Write the credentials route; assert in tests that no response body, log line or job record contains a posted value.
5. Write the three commands.
6. Write the tests listed below.

## Todo

- [ ] Store, name checks, validators, selector grammar
- [ ] Approval by hash
- [ ] Project and scenario routes
- [ ] Credentials route with no read path
- [ ] Scenario commands
- [ ] Tests

## Verification

- `python -m pytest tests/test_login_scenarios.py tests/test_console_login_api.py -v`
- Tests cover: a scenario with an unknown step kind, a selector outside the grammar or an off-host URL is refused; no CLI command changes a project's hosts; a saved draft is unapproved; an approval for an older hash gets 409; after posting credentials (including values with quotes and backslashes), a search of every response, `server.log` and the job records for the posted values finds nothing; removing a scenario removes its credentials and approval; project and scenario names with `..`, `%2F`, `\` or a reserved name get 404.

## Risks

- The agent's draft is wrong and the tester cannot edit it. The tester rejects with a note and uses manual sign-in meanwhile; the checklist is only a guide there, so a wrong step does not block the run.
- Credentials at rest are in a plain file in an owner-only folder, as the Backlog key is in the shell profile today. Test accounts only; the README says so.
