---
name: scout
user-invocable: false
description: Internal skill of the testign plugin, invoked by spec-qa and not by the tester directly. Given anchors from a spec and a local repo, it surveys Production behavior at the merge-base of master and develop, the current phase's changes from git diff master...develop grouped by ticket ID, and writes a brief with an honest coverage section. Reuses a cached master brief when its source files are unchanged.
argument-hint: <TICKET-ID> --repo <path> --anchors-file <path> --spec-file <path> [--master-ref <ref>] [--develop-ref <ref>] [--fetch] [--feature <name>]
context: fork
agent: general-purpose
background: false
model: sonnet
effort: medium
---

# scout

Produce a scout brief for one ticket. You run in your own subagent context: you do not see the
conversation that called you, only these arguments from `spec-qa`:

```text
$ARGUMENTS
```

- First argument: `ticket`, the ticket ID.
- `--repo`: path to the tester's local clone of the customer repo.
- `--anchors-file`: the anchors file `spec-qa` wrote, `{"anchors": [...]}` with screen names, JP UI
  labels (verbatim), API names and business terms from the spec. Its folder is the work folder.
- `--spec-file`: the ticket text as `spec-qa` read it. Use it only to know which behaviors to
  describe: for every rule the spec states (formulas, rounding, limits, validation, who sees what),
  write what the code does today, including "the code does not do this" when that is what you read.
  The spec is never a source for a B* row and you do not judge it; `spec-qa` compares.
- optional `--master-ref`, `--develop-ref` (branch names or SHAs), `--fetch` (only if the tester
  passed it), `--feature` (cache entry name; default the first screen name among the anchors).

If `--repo`, `--anchors-file` or `--spec-file` is missing, stop and reply `SCOUT_FAILED: <what is missing>`.

Flow: `scope → cache check → master brief (reuse, partial re-read, or full) → develop diff (always
fresh) → coverage → cache save`.

## Before you start

1. Read `${CLAUDE_PLUGIN_ROOT}/references/rules.md` and follow it. Pay attention to §2 (git is
   read-only) and §10 (how to call Python). Below, `<run>` means
   `<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py"`.
2. Read `${CLAUDE_PLUGIN_ROOT}/skills/scout/brief-format.md`. The brief must follow it.
   Read the spec file.
3. Work folder `<work>`: the folder of the anchors file (`<output_dir>/<TICKET>/`).

## Hard rules

- **Never** run `git checkout`, `switch`, `reset`, `stash`, `pull`, `commit`, `merge`, `rebase`, or
  anything that writes to the customer repo's working tree, index or refs. Read files only with
  `git -C <repo> show <sha>:<path>`; search only with `git -C <repo> grep <sha>`. Do not open files
  from the working tree: the checked-out branch may be anything.
- Every B* row lists its source files with blob hashes from the facts file.
- Stored procedures, DB config, batch jobs and master data are always `[suy luận]` and go under
  "Chưa đọc được", even if you can read their text. The cache never promotes them.
- Read at most **40 files** per run (merge-base and develop together). List the rest under
  "Chưa đọc được" with the reason "vượt giới hạn đọc".
- Never write about behavior you did not read. Missing coverage is reported, not filled in.

## Steps

### 1. Scope (always runs)

Run, with the anchors file you were given:

```bash
<run> scout-facts --repo "<repo>" --anchors-file "<work>/<ticket>-anchors.json" --out "<work>/<ticket>-scout-facts.json" [--master-ref <ref>] [--develop-ref <ref>] [--fetch]
```

If it exits with code 2, stop and reply `SCOUT_FAILED: <its message>` (for example a missing branch).

From the facts file:
- `anchors[].merge_base` hits are the Production entry files.
- `anchors[].status == "new_in_phase"` means the anchor exists only on develop: note it for section 2.
- `anchors[].status == "not_found"` goes to "Grep không ra".

### 2. Cache check

```bash
<run> cache-check --repo "<repo>" --feature "<feature>" --anchors-file "<work>/<ticket>-anchors.json" [--master-ref <ref>] [--develop-ref <ref>]
```

- `hit` → copy section 1 (B* rows) of the cached `brief` as is; skip step 3.
- `partial` → copy section 1, then re-read only the rows in `stale_rows` (their source files changed)
  and whatever the `new_anchors` touch, in step 3. Keep the other rows unchanged.
- `miss` → do the full step 3.

A cached brief was written for an earlier ticket. On `hit` or `partial`, if the spec states a rule
that no cached row covers, read the code for that rule in step 3 too, add rows for it, and report the
result as `partial` with those rows listed as re-read.

Remember `result`, `cache_root`, `cache_feature`, `scout_model` and the re-read rows: they go into the brief
frontmatter and the report's coverage section.

### 3. Master brief (merge-base)

Starting from the entry files, read code at `refs.merge_base` with `git show`. Follow callers and
shared logic (services, repositories, validators), and include migrations and config the grep hits.
Collect the paths you read and the symbol names that matter (classes, methods, tables, SP names).

Write B* rows in screen terms (rules §3). Each row's source files are the paths you read for it. For
rows reused from the cache, keep their source files.

### 4. Develop diff (always fresh)

Add `"paths"` (every source path of every B* row, plus other paths you read; folders allowed with a
trailing `/`) and `"symbols"` to the anchors file and run `scout-facts` again with the same arguments.
Now:

- `blob_hashes_at_merge_base` has the hashes for every B* source file.
- `changed_files.kept` are the changed files that touch the scope (by path or by a term in the diff
  hunks). Read their diff with `git -C <repo> diff <merge_base>..<develop_head> -- <path>` and, where
  needed, the file at develop with `git show <develop_head>:<path>`.
- `commits_by_ticket` groups the phase's commits; `unlinked` holds commits without a ticket ID.

Describe each ticket's change in screen terms and link it to the B* rows it changes.

### 5. Coverage

Fill section 3 of the brief from what you actually read, the `unreadable` list in the facts file,
anchors not found, files over the read cap, the dropped diff files, and the cache result.

### 6. Save and hand back

Save the brief as `<work>/<ticket>-scout-brief.md`, then store its master section in the cache
(skip on `hit`, since nothing changed):

```bash
<run> cache-save --feature "<feature>" --brief "<work>/<ticket>-scout-brief.md" --facts "<work>/<ticket>-scout-facts.json"
```

If `cache-save` refuses (for example a B* row without source files), fix the brief rather than
skipping the cache: a row without sources is a brief error. Do not write the survey report; that is
`spec-qa`'s job.

Your final reply goes back into the caller's context, so keep it to this block and nothing else. Do
not repeat the brief or any code you read; `spec-qa` reads the brief file itself.

```text
SCOUT_DONE
brief: <work>/<ticket>-scout-brief.md
facts: <work>/<ticket>-scout-facts.json
cache_result: <hit | partial | miss>
cache_root: <cache_root>
cache_feature: <cache_feature>
files_read: <number of files read>
```
