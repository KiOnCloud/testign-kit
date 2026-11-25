# Console bridge

How the attached Claude Code session works the testign console's job queue. The `console` skill
follows this file; `spec-qa`, `qa-close`, `testcase` and `webtest` point here for their "In a console
job" parts.
Below, `<run>` means `<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py"`.

## Job loop

1. `<run> console start` → keep the `session` id it prints. Then `<run> console capabilities
   --session <s> [--has chrome] [--has figma] [--has backlog]` with the tools this session has; the
   Agent & jobs screen shows them, and "not reported" until a session reports.
2. `<run> console wait --session <s>` (a held call, see below) → `{session, job}` or `{session, job: null}`.
3. `<run> console claim <job> --session <s>` → `{ok: true}`, or `{ok: false, reason: "revision-moved"}`
   (the job already failed; go back to 2). Exit 2 with `no-older-tab`: no console tab can answer
   this job, and the server has failed it (see "Errors"); do no work for it.
4. Follow the kind's skill; `console progress`, `console ask` as needed.
5. `<run> console done <job> --session <s> --result done|failed --report <summary file>`.
6. Back to 2. One job at a time: calling `wait` while a job is still open fails that job (`not-closed`).

A job given to you and not claimed within 60 seconds goes back to the queue. `progress`, `ask` and
`done` also claim an offered job, but claim first anyway.

## Held calls

`console wait` and `console ask` hold the HTTP call until something happens or `--timeout` seconds
pass (default 100, server cap 540). A call cut off by the command time limit leaves the server
holding it, so never run a held call longer than the command may run:

- If the runtime can run a command in the background and notify you when it exits, run `wait` that
  way and keep the default `--timeout`.
- Else run it in the foreground. With the default command limit (2 minutes) keep the default
  `--timeout 100`. Only when you also set the Bash timeout to 600000 ms may you pass `--timeout 540`.
- `{job: null}` or `{answers: null}` means "nothing yet": call again. A newer held call from the same
  session replaces the older one, so a lost call never blocks anything.
- A held `console ask` or `webtest-resolve --wait` first checks that some console tab was opened
  before the job (a web job counts from when it was queued, any other job from its claim; a tab
  counts from when it was opened, even if it has been closed since). When none was,
  no one can ever answer it: the server fails the job as `no-older-tab` and the call exits 2 with
  that code instead of returning "nothing yet".

`console ask` with the same ask `id` returns the answer once the tester gave it, also when the earlier
call timed out or its answer was lost with a killed command. An answered `id` keeps returning the same
answer, so the next question always needs a new `id`.

## Ask files

Write the ask as a JSON file and pass it with `--question <file>`. Every ask has a unique `id`
(letters, digits, `.`, `-`, `_`; at most 64). Agent-written text (`body`, questions, labels, progress)
is in the job's `ui_lang`, at most 8000 characters, without control or bidi characters. Quotes,
decisions, anchors and diffs are passed as data, unchanged.

### `questions`

Up to four questions with the fields `AskUserQuestion` takes. `other: "multiline"` gives a multi-line
free-text field (pasted ticket text, pasted answers); the default is one line.

```json
{"type": "questions", "id": "ticket-text", "body": "Backlog MCP không dùng được.",
 "questions": [{"question": "Dán nội dung ticket DEMO-1 vào ô bên dưới.", "header": "Ticket",
   "options": [{"label": "Đã dán", "description": "Nội dung ở ô Khác"}, {"label": "Dừng", "description": "Huỷ job"}],
   "multiSelect": false, "other": "multiline"}]}
```

Answer: `[{selected: ["<label>", …], other?: "<text>"}]`, one entry per question.

### `review-rows`

One row per proposed log entry. `row` is an id you assign (unique in the ask); `q` is the Q ID when
there is one, so two rows may share a Q. `quote_lang: "ja"` marks a Japanese quote.

```json
{"type": "review-rows", "id": "rows-1",
 "rows": [{"row": "q2-a", "q": "Q2", "class": "decided", "feature": "order-confirm", "page": "QA/Decisions/order-confirm",
   "anchors": ["注文確定", "「確定」"], "decision": "Giảm giá áp dụng cho 請求書.", "quote": "請求書にも適用します。",
   "quote_lang": "ja", "source": "https://example.backlog.com/view/DEMO-1#comment-1", "decided_by": "Customer",
   "date": "2026-11-18"}]}
```

Answer: `{rows: {"<row>": {action: "write" | "skip" | "edit", decision?, anchors?, page?}}}` with every
row answered. Apply edits to the rows before the preview; only `write` and `edit` rows go further.

### `confirm-diff` and `paste-pages`

Never write these by hand. Save the `wiki-append-preview` output to a file and run
`<run> console ask <job> --session <s> --from-preview <file>`:

- API mode → `confirm-diff`: the server computes each page's diff from the preview's `old_content`
  and `new_content`, checks that they give the preview's approval hash (else `approval-mismatch`),
  and shows those diffs with the `added`, `skipped`, `superseded`, `index_repaired` lists. Answer
  `{confirm: true | false}`. On `true` the server keeps the approval as the job's confirmed approval.
- Manual mode (`--pages-dir`) → `paste-pages`: the tester sees each page's new content to paste.
  Answer `{done: true}`. The job ends `done` and its summary says nothing was written by testign.

Then write with `<run> wiki-update --rows <file> --approval <approval> --job <job> --session <s>`. It
refuses unless the tester confirmed exactly that approval in the console.

### `sign-in` (web test run)

`{"type": "sign-in", "id": "signin-<scenario>-<n>", "scenario": "<name>", "switching_from"?: "<name>"}`.
The scenario must be approved by the tester (else `scenario-not-approved`); the server attaches its
checklist, account hint and sign-out link, and the previous scenario's sign-out link when
switching. The tester signs in by hand in their own Chrome. Answer `{choice: "signed-in" | "skip"}`,
or `{choice: "finish"}` when the tester ended the run from the run screen. Then run
`<run> webtest-signed-in --run <r> --job <j> --session <s> --scenario <name>`. Make no Chrome tool
call while this question is open.

## Web test suites and runs

- A test suite is a case list kept apart from runs, in `<output_dir>/webtest/suites/<S>/`. The
  tester makes one on the Test suites screen from a Figma table, a Backlog survey report, an Excel
  workbook or by hand, reviews and edits the cases on its Cases tab, and confirms it (`ready`). A
  run copies a ready suite onto one environment (base URL on the project's hosts, template,
  tester); the run is confirmed and has its columns when it is made.
- `<run> console queue --file <job.json>` queues a `suite-generate` or `webtest-run` job from the
  chat with the same checks as the console; the agent cannot queue any other kind. The console shows
  it as "queued from the chat" until the tester opens it. Never mint a browser session for yourself.
  A job queued again after `no-older-tab` adds `"queued_after": "no-older-tab"` to the job file;
  the console shows it on the job card.
- `suite-generate` parameters: `suite`, a suite in state `generating` from a Figma or Backlog source
  that no other active job generates (`unknown-suite`, `suite-not-generating`, `suite-busy`,
  `bad-source`). The job's `params.source` is the suite's source. Only the claimed job writes the
  suite, through `POST /agent/suites/:suite/stage` (`<run> suite-stage`) and
  `POST /agent/suites/:suite/generated` (`<run> suite-generated`); a call from any other job or
  session is refused with `conflict`. When the job ends without `suite-generated`, the server keeps
  what was staged and hands the suite to the tester (`review`).
- `webtest-run` parameters: `run` (a run whose plan is confirmed), `tester`, `mode: run | export`.
- The tester answers parked rows (`delegate` with preconditions, `self-run`, `skip`) and enters
  results for rows they run on the run screen. Those answers live on the server, keyed by
  `<row>-a<attempt>` (answers) and `<row>-r<attempt>` (results), and outlive the job. `<run> webtest-resolve --run <r> --job <j> --session <s>`
  applies them to `run.json` and marks them applied; `--wait` holds until one arrives or the tester
  presses "Finish".
- `console done --result done` on a `webtest-run` job is refused with `open-rows` while the run has
  an open row and the tester has not finished it. Close the run (`webtest-close`) first.
- Call `console progress` at least every two minutes while a worker runs: a web job's silence counts
  from its last progress line, and after two minutes the console tells the tester the agent may be
  waiting for a browser permission in the terminal.
- A tester action on a run is accepted only from a console tab older than the run's queued or open
  job. A newer tab shows a notice instead of the answer controls (the job view's `can_answer`, the
  run view's `can_act`).

## Interaction mapping

| Skill and moment | In a console job |
|---|---|
| spec-qa: repo missing | Never happens: `repo` is a required survey parameter |
| spec-qa: ticket text when Backlog MCP is unavailable | `questions` ask with `other: "multiline"` for the pasted ticket text |
| qa-close: pasted answers, source link | `questions` ask with `other: "multiline"` |
| qa-close: per-row approve, edit or reject | `review-rows` ask (row ids, page, anchors; edits are applied before the preview) |
| qa-close: diff approval | `wiki-append-preview` output passed with `console ask --from-preview` (`confirm-diff`); then `wiki-update --job <id> --session <id>` |
| qa-close: no API key (manual mode) | `console ask --from-preview` packs `paste-pages`; the job ends `done` with "nothing written by testign" |
| qa-close: Backlog notation project | Job fails with reason "Backlog project uses Backlog notation; decisions log needs Markdown" |
| qa-close: `approved_by`, `cache-review --by` | The job's `tester` parameter |
| testcase: no template registered | Job fails with reason "no template: register one on the Templates screen" |
| testcase: several templates, none named | Never happens: the console requires `template` when more than one is registered |
| testcase: preview confirmation | `questions` ask whose `body` is the `template-preview` output; "Not right" fails the job with a pointer to the Templates screen |
| testcase: column roles not detected | Job fails with the same pointer; registration happens on the Templates screen |
| testcase: hash check stale | `questions` ask: "Continue on this revision" or "Stop"; Stop fails the job with reason `stale` (the console offers "Survey again"; a testcase job never runs spec-qa) |
| testcase `mode: trace` | `trace --template <t> --xlsx <workbook> --write-revision` only; no case writing |
| testcase `focus` | Write cases only for the listed rows, into `--into <workbook>` |
| webtest: project or hosts missing | Never asked in the chat: the tester creates the project and its hosts on the Projects & hosts screen, then queues again |
| suite generate: a case needs a login scenario that does not exist | The agent drafts it with `login-scenario-save`; the tester approves it on the Login scenarios screen |
| webtest run: sign in or switch accounts | `sign-in` ask; then `webtest-signed-in`. No Chrome call while it is open |
| webtest run: a parked row, a row the tester runs | Answered on the run screen; `webtest-resolve` applies them |
| webtest run: the tester stops with rows open | "Finish with open rows" on the run screen; `webtest-resolve` reports it, then `webtest-close` and the export |

## Errors

`console` commands exit 2 and print `{error: {code, message}}` on stderr.

| Code | Meaning | Do |
|---|---|---|
| `no-server` | The console is not running | Run `console start` again (it keeps the queue's records) and tell the tester |
| `not-this-server` | Another program answers on the console port | Relay the message and stop |
| `session-refused` | Another Claude Code session is attached | Tell the tester; they can press "Release agent" in the console |
| `session-replaced` | Another session took over, or the tester released this one | Stop working on the job; tell the tester. This session id stays refused: run `console start` for a new one |
| `transport` | The call was cut off | Call again once; if it repeats at a fixed interval, lower `--timeout` |
| `bad-request` | The ask or parameters are not valid | Fix the file (the message says what) and call again |
| `conflict`, `revision-moved` | The job is no longer open, or the report moved on | Leave the job; go back to `wait` |
| `no-older-tab` | No console tab was opened before the job, so no one can answer it (a tab opened after the job was queued, or `console start` still opening its tab). The server has failed the job | Queue the same job again once with `"queued_after": "no-older-tab"`, say so in one line in the chat, and go back to `wait`. When the job you queued again also fails with `no-older-tab`, do not queue it a third time: ask the tester in the chat to open the console themselves, and wait for their go |
| `no-tab` | `console queue` with `queued_after` while the console has no tab at all (it was restarted, or its tab never opened) | Ask the tester in the chat to open the console themselves; queue again once they say it is open. Never open a console tab of your own |
| `open-rows` | `done` on a run job with open rows | Wait with `webtest-resolve --wait`, or close the run, then call `done` again |
| `scenario-not-approved` | The sign-in question names a scenario the tester has not approved | Ask the tester to approve it on the Login scenarios screen, or skip its rows |
| `unknown-project`, `off-host`, `bad-source`, `plan-not-confirmed`, `unknown-run` | A web job's parameters are not valid | Fix the job file (the message says what) and queue again |
| `preconditions-required`, `unknown-scenario`, `bad-columns`, `mobile-agent`, `not-web-runner`, `pc-method`, `too-long` | A tester answer (a parked row or a column change) broke a rule | Only the console sends answers; the tester sees the message there |
