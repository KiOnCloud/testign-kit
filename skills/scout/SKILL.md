---
name: scout
user-invocable: false
description: Internal skill of the testign plugin, invoked by spec-qa and not by the tester directly. Given anchors from a spec and a local repo, it surveys Production behavior at the merge-base of master and develop, the current phase's changes from git diff master...develop grouped by ticket ID, and writes a brief with an honest coverage section.
---

# scout

Produce a scout brief for one ticket. The caller (`spec-qa`) gives you:

- `ticket` — the ticket ID.
- `repo` — path to the tester's local clone of the customer repo.
- `anchors` — screen names, JP UI labels (verbatim), API names and business terms from the spec.
- optional `master_ref`, `develop_ref` (branch names or SHAs), `fetch` (true only if the tester
  passed `--fetch`).

## Before you start

1. Read `${CLAUDE_PLUGIN_ROOT}/references/rules.md` and follow it. Pay attention to §2 (git is
   read-only) and §10 (how to call Python).
2. Read `${CLAUDE_PLUGIN_ROOT}/skills/scout/brief-format.md`. The brief must follow it.
3. Read the output folder from `<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py" config` (`output_dir`).

## Hard rules

- **Never** run `git checkout`, `switch`, `reset`, `stash`, `pull`, `commit`, `merge`, `rebase`, or
  anything that writes to the customer repo's working tree, index or refs. Read files only with
  `git -C <repo> show <sha>:<path>`; search only with `git -C <repo> grep <sha>`. Do not open files
  from the working tree: the checked-out branch may be anything.
- Every B* row lists its source files with blob hashes from the facts file.
- Stored procedures, DB config, batch jobs and master data are always `[suy luận]` and go under
  "Chưa đọc được", even if you can read their text.
- Read at most **40 files** per run (merge-base and develop together). List the rest under
  "Chưa đọc được" with the reason "vượt giới hạn đọc".
- Never write about behavior you did not read. Missing coverage is reported, not filled in.

## Steps

### 1. Scope

Write the anchors to `<output_dir>/<ticket>-anchors.json` as `{"anchors": [...]}` and run:

```bash
<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py" scout-facts --repo "<repo>" --anchors-file "<output_dir>/<ticket>-anchors.json" --out "<output_dir>/<ticket>-scout-facts.json" [--master-ref <ref>] [--develop-ref <ref>] [--fetch]
```

If it exits with code 2, show the tester its message (for example a missing branch) and stop.

From the facts file:
- `anchors[].merge_base` hits are the Production entry files.
- `anchors[].status == "new_in_phase"` means the anchor exists only on develop: note it for section 2.
- `anchors[].status == "not_found"` goes to "Grep không ra".

### 2. Master brief (merge-base)

Starting from the entry files, read code at `refs.merge_base` with `git show`. Follow callers and
shared logic (services, repositories, validators), and include migrations and config the grep hits.
Collect the paths you read and the symbol names that matter (classes, methods, tables, SP names).

Write B* rows in screen terms (rules §3). Each row's source files come from the paths you read.

### 3. Develop diff (always fresh)

Add `"paths"` (every path you read, folders allowed with a trailing `/`) and `"symbols"` to the anchors
file and run `scout-facts` again with the same arguments. Now:

- `blob_hashes_at_merge_base` has the hashes for every B* source file.
- `changed_files.kept` are the changed files that touch the scope (by path or by a term in the diff
  hunks). Read their diff with `git -C <repo> diff <merge_base>..<develop_head> -- <path>` and, where
  needed, the file at develop with `git show <develop_head>:<path>`.
- `commits_by_ticket` groups the phase's commits; `unlinked` holds commits without a ticket ID.

Describe each ticket's change in screen terms and link it to the B* rows it changes.

### 4. Coverage

Fill section 3 of the brief from what you actually read, the `unreadable` list in the facts file,
anchors not found, files over the read cap, and the dropped diff files.

### 5. Hand back

Save the brief as `<output_dir>/<ticket>-scout-brief.md` and return its path and the facts file path
to the caller. Do not write the survey report; that is `spec-qa`'s job.
