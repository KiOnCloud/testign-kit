# Scout brief format

The scout brief is an intermediate file for `spec-qa`, not the tester-facing report. It is written in
the report language (see `rules.md` §1) and saved next to the facts file as
`<TICKET>-scout-brief.md` in the output folder.

```markdown
---
ticket: <TICKET-ID>
repo: <absolute repo path>
master_ref: <as given>
develop_ref: <as given>
merge_base: <full SHA>
develop_head: <full SHA>
root_commit: <full SHA>
facts_file: <path to scout-facts JSON>
anchors: [<anchor>, ...]
---

# Scout brief — <TICKET-ID> <feature name>

## 1. Production behavior (merge-base)

| ID | Hành vi trên màn hình | Nguồn | Source files |
|---|---|---|---|
| B1 | <what the user sees / what happens, in screen terms> | `[code]` | `src/screens/OrderConfirm.cs@<blob8>`, `src/services/OrderService.cs@<blob8>` |
| B2 | <behavior that depends on a stored procedure> | `[suy luận]` | `db/sp_order_total.sql@<blob8>` |

Rules:
- Every B* row lists every file it was derived from as `path@<first 8 chars of the blob hash at the
  merge-base>`, taken from `blob_hashes_at_merge_base` in the facts file. A row with no source file is
  not allowed.
- A row that depends on a stored procedure, config, batch job or master data is `[suy luận]`.

## 2. Changes in this phase (git diff master...develop)

### <TICKET> — <one line on what the ticket changes, from its commits>
- Commits: `<sha8>` <subject>, ...
- Files: `<status> <path>` (reason: scoped path | term `<term>`)
- Behavior change: <screen-level description> → affects B<n> / new behavior `[code]`

### unlinked
- Commits without a ticket ID: `<sha8>` <subject>
- Files and behavior change as above.

Anchors reported `new_in_phase` (only on develop) are listed here with the ticket that added them;
they are input for F3 findings.

## 3. Coverage

- ✅ **Đã đọc:** <files read at the merge-base and on develop>
- ⛔ **Chưa đọc được:** <each `unreadable` item from the facts file, with its kind, plus files skipped
  because the read cap was reached> → <B-ID / change entries that stay `[suy luận]`>
- 🔍 **Grep không ra:** <anchors with status `not_found`>
- ➖ **Bỏ qua trong diff:** <count of `changed_files.dropped`, and up to 10 paths>
```

Section 3 is always present, even when every list is empty (write "Không có").
