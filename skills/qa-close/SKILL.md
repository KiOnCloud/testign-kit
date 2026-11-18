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
report language, Decided by, the **page** it goes to, and its **anchors**). The tester approves, edits or
rejects each row. Write nothing before this. Only approved **decided** rows go further. `approved_by` is
the tester's name.

Page: the report's `cache_feature` (the feature slug) by default; `common` when the decision is about
logic shared by several features (tax, rounding, master data, a shared service). Anchors: the screen
names, JP UI labels, API names and business terms the decision is about, taken from the report; they are
what later surveys match on, so include every screen the decision affects.

Save the approved rows as `<output_dir>/<TICKET>/<TICKET>-approved-decisions.json`, a list of:

```json
{"ticket": "DEMO-12", "ticket_title": "<summary>", "q": "Q2", "feature": "<feature slug | common>",
 "anchors": ["注文確定", "「確定」"], "date": "YYYY-MM-DD", "question": "<as asked, usually the ja draft>",
 "decision": "...", "quote": "<verbatim>", "source": "<link>", "decided_by": "Customer | BrSE (<name>) | Dev (<name>)",
 "approved_by": "<tester>", "report": "<report file name>"}
```

### 4. Diff approval (gate 2) and write

```bash
<run> wiki-append-preview --rows "<approved json>"
```

The preview lists one diff per page that will change: feature/common pages first (a page that does
not exist yet shows `exists: false` and will be created), the index last. Show every diff and the
`added` / `skipped` (already in the log) / `superseded` / `index_repaired` lists. Write only after the
tester approves all of them in the same run:

```bash
<run> wiki-update --rows "<approved json>" --approval "<approval from the preview>"
```

Do not edit the approved rows file between the preview and the update: the update re-reads every page
and refuses to write unless the pages are unchanged and the new contents are exactly the approved diffs.

- If it says the pages or the content differ from the approved diff, run the preview again and ask again.
- If a write fails midway, it lists the pages already written. Run the preview again: entries already on
  a page are skipped and their missing index rows are added; show that diff and update again.
- If the preview fails because `BACKLOG_DOMAIN`/`BACKLOG_API_KEY` are not set in the shell or the key
  cannot edit the pages: with Backlog MCP, read `<prefix>/index` and each target page (and any page the
  index lists for the same ticket and Q), save them as `<output_dir>/<TICKET>/.decisions/<slug>.md`
  (`index.md` for the index; leave a page's file out if it does not exist), run
  `<run> wiki-append-preview --rows "<approved json>" --pages-dir "<that folder>"`, show the diffs, and
  give the tester each page's `new_content` to paste (create missing pages with the name shown). Say
  clearly that nothing was written.
- If it stops because the project uses Backlog notation, tell the tester and stop the wiki part.

Delete the approved rows file and the `.decisions` folder afterwards.

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

## In a console job

When the `console` skill runs this skill for a `close` job, use the report named in `base_revision`
and the job's `tester` as `approved_by` and as the `cache-review --by` name. Pasted answers and source
links come through a `questions` ask, the row approval through a `review-rows` ask, and the diff
approval through `console ask --from-preview`; then write with `wiki-update --job <id> --session <id>`.
The details and the manual-mode and Backlog-notation outcomes are in
`${CLAUDE_PLUGIN_ROOT}/references/console-bridge.md`. Without a console job nothing here changes.
