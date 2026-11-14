# Decisions log format

> **Status:** Asher accepted the format on 2026-11-14, and on the same day approved splitting it into
> feature pages, a `common` page and a project index. The review questions in §7 were not answered one
> by one, so the plugin implements the defaults listed there. Change §7 (and the code) if any of them
> turns out wrong.

The decisions log records what the customer or BrSE decided for each ticket. It lives only on the
Backlog wiki, never in a local file. `spec-qa` reads it so that already-decided questions are labelled
`[khách chốt]` instead of being asked again. `qa-close` appends to it after the tester approves each row.

## 1. Pages

All pages sit under one prefix in one Backlog project (`backlog.decisions_log_prefix`, default
`QA/Decisions`, in `backlog.project_key`):

| Page | Name | Holds |
|---|---|---|
| Feature page | `<prefix>/<feature>` | Decisions about one feature. `<feature>` is the same slug as the scout cache key (e.g. `order-confirm`) |
| Common page | `<prefix>/common` | Decisions about shared logic used by several features (tax, rounding, master data …) |
| Index | `<prefix>/index` | One row per decision across all pages: ID, page, ticket, Q, anchors, date, status |

Pages are created by `qa-close` the first time a decision is written to them. `index` is reserved and
cannot be a feature name.

Page content is Markdown, so the Backlog project's text formatting rule must be **Markdown**.
`backlog.text_format` records the project's rule (default `markdown`). When it is `backlog` (Backlog
notation), `decisions-parse`, `decisions-lookup`, `wiki-append-preview` and `wiki-update` stop with a
message instead of reading or writing.

## 2. Feature and common page layout

```markdown
# Decisions — DEMO / order-confirm

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
| Heading `### D-<TICKET>-<NNN> · Q<n>` | yes | Entry ID (3-digit counter per ticket across **all** pages, never reused) and the Q ID in the report that asked it |
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
Japanese UI labels stay verbatim (see `rules.md`). Every field except `Quote` is a single line.

## 3. Index layout

```markdown
# Decisions index — DEMO

> Managed by testign `/testign:close`. One row per decision; keep the columns.

| ID | Page | Ticket | Q | Anchors | Date | Status |
|---|---|---|---|---|---|---|
| D-DEMO-12-001 | order-confirm | DEMO-12 | Q1 | 注文確定; 「確定」 | 2026-11-14 | active |
| D-DEMO-12-002 | common | DEMO-12 | Q2 | CalcTotal; TaxRate | 2026-11-14 | active |
```

- `Page` is the page slug (`order-confirm`, `common`), not the full name.
- `Anchors` are the screen names, JP UI labels, API names and business terms the decision is about,
  separated by `; ` (a `|` inside an anchor is written `\|`). They are what survey lookups match on.
- `Status` mirrors the entry's `Status` line.

## 4. Read rules (spec-qa)

1. Look up the index with the ticket's anchors (`decisions-lookup`). A row matches when its ticket is
   the ticket being surveyed, or when one of its anchors overlaps a survey anchor (case-insensitive,
   ignoring spaces and 「」 brackets, either contained in the other).
2. Open **every page that has a matching row**, plus `common` and the survey's own feature page, even
   when the page name differs from the feature, so a decision filed under the wrong feature is still found.
3. Parse each page:
   - a ticket section starts at `^## (<ticket_id_regex>)( · .*)?$` and ends at the next `## ` line;
   - an entry starts at `^### (D-<TICKET>-\d{3}) · (Q\d+)\s*$` and ends at the next heading;
   - fields are lines `^- (<Key>):\s*(.*)$`; `Quote` continues over the following lines that start with
     two spaces and `>`.
4. Only `Status: active` entries count as decisions. Superseded entries are history.
5. Use decisions of the ticket being surveyed and decisions whose anchors overlap the survey's scope.
   Cite them as `[khách chốt]` with the entry ID, and list the entries used in report section 6.
6. Anything that does not parse is read as free text, cited as `[wiki]` at most, and reported to the
   tester as "không parse được" with the line number. It is never treated as `[khách chốt]`.

## 5. Write rules (qa-close)

1. Only rows the tester approved one by one in `/testign:close` are written. `undecided` and
   `irrelevant` rows are never written. Each approved row names its `feature` (a feature slug or
   `common`) and its `anchors`.
2. The plugin loads the index, each row's target page, and every page that already holds an entry for
   the same ticket and Q.
3. **De-duplicate** across those pages:
   - same ticket + Q ID + `Source` as an existing entry → skip; if the index has no row for that entry
     (an earlier run stopped between the page and the index write), the index row is added;
   - same ticket + Q ID, different `Source` → new entry; the older active entry for that Q, on whatever
     page it lives, gets `Status: superseded by <new ID>`, and its index row's status changes too.
     Entries are never deleted.
4. New entry ID = highest `D-<TICKET>-NNN` found in the index and the loaded pages, + 1.
5. A ticket without a section on the target page gets a new `## <TICKET> · <ticket title>` section at
   the end of the page; a page that does not exist yet is created with a `# Decisions — …` title.
6. Existing lines are kept byte for byte, with their own line endings, except a superseded entry's
   `Status` line and its index row. Pages with broken entry headings or an entry without a `Status`
   line are refused until they are fixed on the wiki.
7. The tester sees one diff per page (feature/common pages first, the index last) and approves them
   together. The approval covers exactly those contents and the pages' `updated` timestamps; if any
   page changed meanwhile, or the rows file changed, nothing is written and the preview must be re-run.
8. Writes go page by page, the index last. If a write fails midway, the result lists the pages already
   written; re-running the preview skips entries already on a page and repairs missing index rows.

## 6. Backlog API

The Backlog MCP server has no wiki update tool, so `qa-close` writes through a small Python helper
over the Backlog REST API with the same `BACKLOG_DOMAIN` and `BACKLOG_API_KEY` as the MCP server.
The helper reads them from the shell environment. Values set only inside the MCP server's config are
not visible to it, so the tester also sets them as environment variables (see README).

Checked against the Backlog API docs on 2026-11-14:

| Use | Call |
|---|---|
| List pages (metadata only: `id`, `name`, `updated`) | `GET /api/v2/wikis?projectIdOrKey=<key>&keyword=<prefix>` |
| Read a page | `GET /api/v2/wikis/:wikiId` (or MCP `get_wiki`) |
| Update a page | `PATCH /api/v2/wikis/:wikiId`, form `content`, `mailNotify` |
| Create a page | `POST /api/v2/wikis`, form `projectId` (number, from `GET /api/v2/projects/:key`), `name`, `content`, `mailNotify` |

Gaps the docs do not state, and how the helper handles them:

- The docs do not say outright that `content` replaces the whole page. The helper always sends the full
  page and compares the response `content` with what it sent.
- The API has no optimistic locking. Right before each write the helper reads the page again and stops
  if its `updated` timestamp changed; before creating a page it checks that no page with that name
  appeared.
- `mailNotify` is `false` unless the tester asks for notifications.
- The docs note that Wiki is being discontinued for **new** Backlog spaces from 2026-07-14; existing
  spaces keep the Wiki API.
- Without the environment variables or a key that can edit the pages, `qa-close` shows the diffs and
  prints the new page contents for manual paste.

## 7. Review questions and the defaults in use

1. **Text formatting rule.** Markdown is supported. Backlog notation is not parsed; it is declared with
   `backlog.text_format: "backlog"`, and the decisions commands then stop with a message.
2. **Page scope.** Approved on 2026-11-14: one page per feature (same slug as the scout cache), a
   `common` page for shared logic, and a project index.
3. **`Decided by`.** The role, plus the person's name when the source comment shows it.
4. **Language of `Decision`.** The report language only. `Question` keeps the language it was asked in
   (usually the ja draft) and `Quote` stays verbatim.
