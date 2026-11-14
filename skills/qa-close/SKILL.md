---
name: qa-close
description: Pull answers for a ticket's open questions from Backlog comments and tester input, classify each as decided, undecided or irrelevant with a verbatim quote and link, get per-row tester approval, append approved decisions to the shared Backlog wiki decisions log, and write a new survey report revision. Used by /testign:close.
---

# qa-close

Close the open questions of one survey report. There are two separate outputs:

- **Shared:** approved customer decisions are appended to the decisions log page on the Backlog wiki.
  Nothing about decisions is stored locally.
- **Local:** a new report revision, and the `reviewed_by` mark on the scout cache entry the report used.

Inputs from `/testign:close`: `ticket`, optionally `report` (path of a specific revision).

## Before you start

1. Read `${CLAUDE_PLUGIN_ROOT}/references/rules.md` and
   `${CLAUDE_PLUGIN_ROOT}/references/decisions-log-format.md`. Below, `<run>` means
   `<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py"`.
2. Find the report: `report` if given, else `latest` from `<run> report-path --ticket <TICKET>`.
   Read it (frontmatter, section 2 Q rows, section 4 details).

## Steps

### 1. Collect answers

- Backlog MCP `get_issue_comments` for the ticket. Build each comment's link as
  `https://<backlog.space>/view/<TICKET>#comment-<comment id>`.
- Tester input: pasted answers or lines like `Q3: …`. Ask the tester for the source link of a pasted
  answer (meeting note, chat, comment); without a link it can be used in the report but not written to
  the wiki.

### 2. Classify

For each comment or answer: **decided** (a clear decision on a Q), **undecided** (discussed, no
decision) or **irrelevant**. Link it to a Q ID when possible. Keep the quote **verbatim** (copy the
exact text; you may cut whole sentences from the start or end, never in the middle, never translate).
Fact questions answered by Dev are decided facts; they update the report but are written to the wiki
only when they settle an intent question.

### 3. Row approval (gate 1)

Show one table: Q ID, classification, verbatim quote, link, and the proposed log entry (Decision in the
report language, Decided by). The tester approves, edits or rejects each row. Write nothing before this.
Only approved **decided** rows go further. `approved_by` is the tester's name.

Save the approved rows as `<output_dir>/<TICKET>/<TICKET>-approved-decisions.json`, a list of:

```json
{"ticket": "DEMO-12", "ticket_title": "<summary>", "q": "Q2", "date": "YYYY-MM-DD", "question": "<as asked, usually the ja draft>",
 "decision": "...", "quote": "<verbatim>", "source": "<link>", "decided_by": "Customer | BrSE (<name>) | Dev (<name>)",
 "approved_by": "<tester>", "report": "<report file name>"}
```

### 4. Diff approval (gate 2) and write

```bash
<run> wiki-append-preview --rows "<approved json>"
```

Show the tester the `diff` and the `added` / `skipped` (already in the log) / `superseded` lists.
Write only after the tester approves this diff in the same run:

```bash
<run> wiki-update --rows "<approved json>" --expected-updated "<updated from the preview>" --expected-hash "<new_sha256 from the preview>"
```

Do not edit the approved rows file between the preview and the update: the update recomputes the
page and refuses to write unless it is exactly the content whose diff the tester approved.

- If it says the page changed since the diff was shown, or that the content differs from the approved
  diff, run the preview again and ask again.
- If the preview fails because `BACKLOG_DOMAIN`/`BACKLOG_API_KEY` are not set in the shell or the key
  cannot edit the page: fetch the page with Backlog MCP `get_wiki`, save it to
  `<output_dir>/<TICKET>/.decisions-page.md`, run
  `<run> wiki-append-preview --rows "<approved json>" --page-file "<that file>"`, show the diff, and
  give the tester `new_content` to paste into the wiki by hand. Say clearly that nothing was written.
- If it stops because the project uses Backlog notation, tell the tester and stop the wiki part.

Delete the approved rows file and any `.decisions-page.md` copy afterwards.

### 5. New report revision

Copy the report you read to `<output_dir>/<TICKET>/<TICKET>-survey-draft.md` and update it:

- answered Q rows: mark them answered with the decision and `[khách chốt]` plus the log entry ID (or
  the link when it was not written to the wiki); remove them from "Việc cần làm ngay" if nothing is left
  to ask;
- B*/R* rows the answers change; the "Spec yêu cầu" and "Lệch?" columns;
- section 1 counts and conclusion; undecided questions stay open.

Keep the frontmatter (refs, hashes, cache keys) as is, then run `<run> report-save --draft "<draft>"`.
It sets `revision` and `previous` and refuses to overwrite.

### 6. Mark the cache entry reviewed (local)

```bash
<run> cache-review --report "<new revision path>" --by "<tester name>"
```

If the report did not use the cache, it says so; that is fine.

### 7. Report back

Tell the tester which entries were written to the wiki (or that they must paste them), which
questions are still open, and the new revision path.
