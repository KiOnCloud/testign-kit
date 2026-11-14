# Decisions log format

> **Status:** Asher accepted this format on 2026-11-14. The four review questions in §6 were not
> answered one by one, so the plugin implements the defaults this draft proposed. Change §6 (and the
> code) if any of them turns out wrong.

The decisions log is one shared page on the Backlog wiki that records what the customer or BrSE
decided for each ticket. It lives only on the wiki, never in a local file. `spec-qa` reads it so that
already-decided questions are labelled `[khách chốt]` instead of being asked again. `qa-close`
appends to it after the tester approves each row.

## 1. Where the page is

- One page per Backlog project, named in `~/.testign-kit/config.json` → `backlog.decisions_log_page`
  (for example `QA/Decisions log`), inside `backlog.project_key`.
- The page content is Markdown, so the Backlog project's text formatting rule must be **Markdown**.
  `backlog.text_format` in the config records the project's rule (default `markdown`). When it is
  `backlog` (Backlog notation), `decisions-parse`, `wiki-get`, `wiki-append-preview` and `wiki-update`
  stop with a message instead of reading or writing the page.
- The page is found by `backlog.decisions_log_wiki_id`, or by `backlog.project_key` plus the exact
  page name in `backlog.decisions_log_page`.

## 2. Page layout

```markdown
# Decisions log — DEMO

> Managed by testign `/testign:close`. You may edit the text of a field by hand.
> Keep headings, entry IDs and the `- Key:` field names as they are, or the plugin cannot read the page.

## DEMO-12 · 注文確定画面の確認ダイアログ

### D-DEMO-12-001 · Q1
- Date: 2026-11-14
- Question: 「確定」ボタン押下時に確認ダイアログを表示するか
- Decision: Hiển thị dialog xác nhận; bấm 「キャンセル」 thì giữ nguyên màn hình.
- Quote:
  > 確認ダイアログを表示してください。キャンセル時は画面をそのままにしてください。
- Source: https://demo.backlog.com/view/DEMO-12#comment-1001
- Decided by: BrSE (Tanaka)
- Approved by: Asher
- Report: DEMO-12-survey-r1.md
- Status: active

### D-DEMO-12-002 · Q3
- Date: 2026-11-15
- Question: ...
- Decision: ...
- Quote:
  > ...
- Source: https://demo.backlog.com/view/DEMO-12#comment-1010
- Decided by: Customer
- Approved by: Asher
- Report: DEMO-12-survey-r2.md
- Status: superseded by D-DEMO-12-004

## DEMO-15 · ...
```

### Field rules

| Field | Required | Content |
|---|---|---|
| Heading `### D-<TICKET>-<NNN> · Q<n>` | yes | Entry ID (3-digit counter per ticket, never reused) and the Q ID in the report that asked it |
| `Date` | yes | Date the decision was made (comment date), `YYYY-MM-DD` |
| `Question` | yes | The question as asked, in the language it was asked (usually the ja draft) |
| `Decision` | yes | One or two sentences in the report language, describing on-screen behavior |
| `Quote` | yes | Verbatim text from the source, as indented `>` lines, never translated or shortened in the middle |
| `Source` | yes | Link to the Backlog comment (or wiki page / meeting note) the quote comes from |
| `Decided by` | yes | Role, and name if the comment shows one: `Customer`, `BrSE (<name>)`, `Dev (<name>)` |
| `Approved by` | yes | The tester who approved writing this row in `/testign:close` |
| `Report` | yes | Report revision file the question came from |
| `Status` | yes | `active`, or `superseded by D-<TICKET>-<NNN>` |

Field names stay in English so the parser is language-independent. Values keep their own language;
Japanese UI labels stay verbatim (see `rules.md`).

## 3. Read rules (spec-qa)

1. Fetch the page with Backlog MCP `get_wiki` (find its ID with `get_wiki_pages`).
2. A ticket section starts at a line matching `^## (<ticket_id_regex>)( · .*)?$` and ends at the next
   `## ` line or end of page.
3. An entry starts at `^### (D-<TICKET>-\d{3}) · (Q\d+)\s*$` and ends at the next `###`/`##` heading.
4. Fields are lines `^- (<Key>):\s*(.*)$`. `Quote` continues over the following lines that start with
   two spaces and `>`; strip the `  > ` prefix and join them with newlines.
5. Only `Status: active` entries count as decisions. Superseded entries are history.
6. Use decisions of the ticket being surveyed and, when the scoped area overlaps, of other tickets
   (match by screen name or JP label in `Question`/`Decision`). Cite them as `[khách chốt]` with the
   entry ID, and list the entries used in report section 6 ("Decisions log đã tham chiếu").
7. Anything that does not parse (hand-written notes, broken entries) is read as free text, cited as
   `[wiki]` at most, and reported to the tester as "không parse được" with the line number. It is never
   treated as `[khách chốt]`.

## 4. Write rules (qa-close)

1. Only rows the tester approved one by one in `/testign:close` are written. Classification
   `undecided` and `irrelevant` rows are never written.
2. **De-duplicate** before appending:
   - Same ticket + same `Source` link + same Q ID as an existing entry → skip (already recorded).
   - Same ticket + same Q ID, different `Source` → new entry; the older active entry for that Q gets
     `Status: superseded by <new ID>`. Entries are never deleted.
3. New entry ID = highest existing `NNN` for that ticket + 1, zero-padded to 3 digits.
4. A ticket without a section gets a new `## <TICKET> · <ticket title>` section appended at the end of
   the page. Entries inside a section stay in ID order.
5. Text outside the managed sections (the page title, the intro note, anything a human added) is kept
   byte for byte.
6. Show the tester a unified diff of the whole page and write only after approval.

## 5. Backlog API used for writing

The Backlog MCP server has no wiki update tool, so `qa-close` writes through a small Python helper
over the Backlog REST API with the same `BACKLOG_DOMAIN` and `BACKLOG_API_KEY` as the MCP server.
The helper reads them from the shell environment. Values set only inside the MCP server's config are
not visible to it, so the tester also sets them as environment variables (see README).

Checked against the Backlog API docs on 2026-11-14
(<https://developer.nulab.com/docs/backlog/api/2/update-wiki-page/>):

| Item | Value |
|---|---|
| Endpoint | `PATCH https://<BACKLOG_DOMAIN>/api/v2/wikis/:wikiId?apiKey=<key>` |
| Content type | `application/x-www-form-urlencoded` |
| Parameters | `name` (String), `content` (String), `mailNotify` (Boolean) |
| Response | The updated wiki page (`id`, `projectId`, `name`, `content`, …, `updated`) |
| Read | `GET /api/v2/wikis/:wikiId` (or MCP `get_wiki`) |

Gaps the docs do not state, handled in P4:

- The docs do not say outright that `content` replaces the whole page (it is the usual behavior). The
  helper always sends the full page and compares the response `content` with what it sent; a mismatch
  is reported as an error.
- The API has no optimistic locking. Right before writing, the helper reads the page again and stops if
  its `updated` timestamp changed since the diff was shown, so a teammate's edit is never overwritten.
- `mailNotify` is sent as `false` unless the tester asks for notifications.
- Without an API key that can edit the page, `qa-close` prints the approved Markdown for manual paste.

## 6. Review questions and the defaults in use

These were open in the draft. Asher accepted the format without answering them individually, so the
draft's defaults are implemented:

1. **Text formatting rule.** Markdown is supported. Backlog notation is not parsed; it is declared with
   `backlog.text_format: "backlog"`, and the decisions commands then stop with a message.
2. **Page scope.** One page per Backlog project, not per release or phase.
3. **`Decided by`.** The role, plus the person's name when the source comment shows it.
4. **Language of `Decision`.** The report language only. `Question` keeps the language it was asked in
   (usually the ja draft) and `Quote` stays verbatim.
