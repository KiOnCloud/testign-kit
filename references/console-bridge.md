# Console bridge

How the attached Claude Code session works the testign console's job queue. The `console` skill
follows this file; `spec-qa`, `qa-close` and `testcase` point here for their "In a console job" parts.
Below, `<run>` means `<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py"`.

## Job loop

1. `<run> console start` → keep the `session` id it prints.
2. `<run> console wait --session <s>` (a held call, see below) → `{session, job}` or `{session, job: null}`.
3. `<run> console claim <job> --session <s>` → `{ok: true}`, or `{ok: false, reason: "revision-moved"}`
   (the job already failed; go back to 2).
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
