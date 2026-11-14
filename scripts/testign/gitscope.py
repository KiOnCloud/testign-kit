"""Read-only git queries used by the scout skill.

Every call goes through ``_git`` which runs ``git --no-pager -C <repo> -c core.quotepath=off``.
Nothing here changes the working tree, the index or any ref: only rev-parse, merge-base, rev-list,
grep at a ref, diff between refs, log and ls-tree are used.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import PurePosixPath
from typing import Iterable

UNLINKED = "unlinked"


class GitError(Exception):
    """A git command failed or a ref could not be resolved. The message is meant for the tester."""


def _git(repo: str, *args: str, ok_codes: tuple[int, ...] = (0,)) -> str:
    cmd = ["git", "--no-pager", "-C", str(repo), "-c", "core.quotepath=off", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not on PATH") from exc
    if proc.returncode not in ok_codes:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise GitError(f"git {args[0]} failed in {repo}: {detail}")
    return proc.stdout


def resolve_ref(repo: str, ref: str) -> str:
    """Return the full commit SHA for a branch name, tag or (abbreviated) SHA."""
    out = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", ok_codes=(0, 1, 128))
    sha = out.strip()
    if not sha:
        raise GitError(f"ref '{ref}' not found in {repo}")
    return sha


def resolve_refs(repo: str, master: str, develop: str) -> dict[str, str]:
    return {"master": resolve_ref(repo, master), "develop": resolve_ref(repo, develop)}


def merge_base(repo: str, master: str, develop: str) -> str:
    out = _git(repo, "merge-base", master, develop, ok_codes=(0, 1)).strip()
    if not out:
        raise GitError(f"'{master}' and '{develop}' have no common ancestor in {repo}")
    return out


def root_commit(repo: str, ref: str) -> str:
    """The oldest root commit reachable from ``ref``; identifies the repository for the cache."""
    roots = _git(repo, "rev-list", "--max-parents=0", ref).split()
    return sorted(roots)[0]


def _grep(repo: str, ref: str, anchor: str) -> list[dict]:
    out = _git(repo, "grep", "-z", "-n", "-I", "-F", "-e", anchor, ref, "--", ok_codes=(0, 1))
    hits = []
    prefix = f"{ref}:"
    for line in out.splitlines():
        parts = line.split("\0")
        if len(parts) < 3:
            continue
        where, lineno, text = parts[0], parts[1], "\0".join(parts[2:])
        path = where[len(prefix):] if where.startswith(prefix) else where
        hits.append({"path": path, "line": int(lineno), "text": text.strip()})
    return hits


def grep_anchors(repo: str, base: str, develop: str, anchors: Iterable[str]) -> list[dict]:
    """Grep each anchor at the merge-base and at develop HEAD.

    status is ``production`` when the anchor exists at the merge-base, ``new_in_phase`` when it is
    only on develop, and ``not_found`` when neither has it. ``removed_in_phase`` marks an anchor that
    exists at the merge-base but no longer on develop.
    """
    results = []
    for anchor in anchors:
        at_base = _grep(repo, base, anchor)
        at_dev = _grep(repo, develop, anchor)
        if at_base and at_dev:
            status = "production"
        elif at_base:
            status = "removed_in_phase"
        elif at_dev:
            status = "new_in_phase"
        else:
            status = "not_found"
        results.append({"anchor": anchor, "status": status, "merge_base": at_base, "develop": at_dev})
    return results


def _in_scope(path: str, scoped: Iterable[str]) -> bool:
    for entry in scoped:
        entry = entry.rstrip("/")
        if path == entry or path.startswith(entry + "/"):
            return True
    return False


def _name_status(repo: str, spec: str) -> list[dict]:
    out = _git(repo, "diff", "--name-status", "-z", "--find-renames", spec)
    fields = out.split("\0")
    entries, i = [], 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status[0] in "RC":
            entries.append({"status": status[0], "old_path": fields[i + 1], "path": fields[i + 2]})
            i += 3
        else:
            entries.append({"status": status[0], "old_path": None, "path": fields[i + 1]})
            i += 2
    return entries


def _hunk_terms(repo: str, spec: str, entry: dict, terms: list[str]) -> list[str]:
    paths = [entry["path"]] + ([entry["old_path"]] if entry["old_path"] else [])
    out = _git(repo, "diff", "-U0", "--find-renames", spec, "--", *paths)
    changed = [
        line[1:]
        for line in out.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    body = "\n".join(changed)
    return [t for t in terms if t and t in body]


def diff_name_status(repo: str, master: str, develop: str, three_dot: bool = True) -> list[dict]:
    """Changed files between refs. Three-dot (merge-base) by default; two-dot only for contrast."""
    return _name_status(repo, f"{master}...{develop}" if three_dot else f"{master}..{develop}")


def changed_files(
    repo: str, master: str, develop: str, paths: Iterable[str], terms: Iterable[str]
) -> dict[str, list[dict]]:
    """Files changed by ``git diff master...develop`` split into kept and dropped.

    A file is kept when it (or its pre-rename path) is inside the scoped paths, or when its changed
    lines contain one of the terms (anchors and symbol names). Everything else is dropped and
    returned so the brief can list it in coverage.
    """
    scoped = list(paths)
    term_list = [t for t in dict.fromkeys(terms) if t]
    spec = f"{master}...{develop}"
    kept, dropped = [], []
    for entry in _name_status(repo, spec):
        if _in_scope(entry["path"], scoped) or (entry["old_path"] and _in_scope(entry["old_path"], scoped)):
            kept.append({**entry, "reason": "scoped_path", "matched_terms": []})
            continue
        matched = _hunk_terms(repo, spec, entry, term_list)
        if matched:
            kept.append({**entry, "reason": "term", "matched_terms": matched})
        else:
            dropped.append(entry)
    return {"kept": kept, "dropped": dropped}


def commits_by_ticket(repo: str, base: str, develop: str, ticket_regex: str) -> dict[str, list[dict]]:
    """Commits in ``base..develop`` (oldest first) grouped by ticket IDs found in the message."""
    rx = re.compile(ticket_regex)
    out = _git(repo, "log", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"{base}..{develop}")
    groups: dict[str, list[dict]] = {}
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, subject, body = (record.split("\x1f") + ["", ""])[:3]
        commit = {"sha": sha, "subject": subject}
        tickets = list(dict.fromkeys(rx.findall(f"{subject}\n{body}")))
        for ticket in tickets or [UNLINKED]:
            groups.setdefault(ticket, []).append(commit)
    return groups


def blob_hashes(repo: str, ref: str, paths: Iterable[str]) -> dict[str, str | None]:
    """Blob SHA of each path at ``ref``; ``None`` when the path does not exist there."""
    wanted = list(dict.fromkeys(paths))
    result: dict[str, str | None] = {p: None for p in wanted}
    if not wanted:
        return result
    out = _git(repo, "ls-tree", "-z", "--full-tree", ref, "--", *wanted)
    for record in out.split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        _mode, kind, sha = meta.split()
        if kind == "blob" and path in result:
            result[path] = sha
    return result


SQL_EXTS = {".sql", ".prc", ".pks", ".pkb", ".proc", ".fnc", ".trg"}
CONFIG_EXTS = {".config", ".ini", ".properties", ".env", ".cfg", ".conf", ".toml", ".yml", ".yaml"}
BATCH_EXTS = {".bat", ".cmd", ".ps1", ".sh", ".job", ".cron"}
DATA_EXTS = {".csv", ".tsv"}
SQL_DIRS = {"storedprocedures", "stored_procedures", "procedures", "sp", "sql"}
CONFIG_DIRS = {"config", "configs", "conf", "settings"}
BATCH_DIRS = {"batch", "batches", "jobs", "cron", "scheduler"}
DATA_DIRS = {"masterdata", "master_data", "seed", "seeds", "seeddata"}


def classify_unreadable(paths: Iterable[str]) -> list[dict]:
    """Flag paths whose behavior the agent cannot confirm by reading source.

    kind is one of ``stored_procedure``, ``config``, ``batch``, ``master_data``. Conclusions that
    depend on them stay ``[suy luận]``.
    """
    flagged = []
    for path in dict.fromkeys(paths):
        p = PurePosixPath(path)
        ext = p.suffix.lower()
        name = p.name.lower()
        dirs = {d.lower() for d in p.parts[:-1]}
        if ext in SQL_EXTS or dirs & SQL_DIRS:
            kind = "stored_procedure"
        elif ext in BATCH_EXTS or dirs & BATCH_DIRS:
            kind = "batch"
        elif ext in DATA_EXTS or dirs & DATA_DIRS:
            kind = "master_data"
        elif (
            ext in CONFIG_EXTS
            or dirs & CONFIG_DIRS
            or name.startswith("appsettings")
            or name in {"web.config", "app.config", ".env"}
        ):
            kind = "config"
        else:
            continue
        flagged.append({"path": path, "kind": kind})
    return flagged


def fetch(repo: str) -> None:
    """Update remote-tracking refs. Only called when the tester passes --fetch."""
    _git(repo, "fetch", "--quiet")
