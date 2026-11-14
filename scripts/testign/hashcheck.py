"""Check that a survey report's pinned refs still describe the code before test cases are written.

Two refs can move: develop HEAD (new commits in the phase) and the merge-base (a master hotfix merged
into develop changes Production behavior). Both are compared with the repo now.
"""

from __future__ import annotations

from . import gitscope, report


def _changed_paths(repo: str, old: str, new: str) -> list[str]:
    out = gitscope._git(repo, "diff", "--name-only", "-z", old, new)
    return [p for p in out.split("\0") if p]


def _commits(repo: str, old: str, new: str) -> list[dict]:
    out = gitscope._git(repo, "log", "--format=%H%x1f%s%x1e", f"{old}..{new}")
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if record:
            sha, subject = (record.split("\x1f") + [""])[:2]
            commits.append({"sha": sha, "subject": subject})
    return commits


def check(report_path: str, repo: str | None = None) -> dict:
    """Return ``status``: ``same``, ``moved_no_impact`` (warn, continue) or ``stale`` (stop and ask)."""
    meta, body = report.load(report_path)
    for key in ("master_ref", "develop_ref", "merge_base", "develop_head"):
        if not meta.get(key):
            raise report.ReportError(f"report frontmatter has no '{key}'")
    repo = repo or meta.get("repo")
    if not repo:
        raise report.ReportError("report frontmatter has no 'repo'; pass --repo")

    refs = gitscope.resolve_refs(repo, meta["master_ref"], meta["develop_ref"])
    now_base = gitscope.merge_base(repo, refs["master"], refs["develop"])
    old_head = gitscope.resolve_ref(repo, meta["develop_head"])
    old_base = gitscope.resolve_ref(repo, meta["merge_base"])

    moves = []
    if refs["develop"] != old_head:
        moves.append(("develop_head", old_head, refs["develop"]))
    if now_base != old_base:
        moves.append(("merge_base", old_base, now_base))

    result = {
        "report": str(report_path),
        "pinned": {"develop_head": old_head, "merge_base": old_base},
        "current": {"develop_head": refs["develop"], "merge_base": now_base},
        "moves": [],
        "stale_rows": [],
        "stale_files": [],
    }
    if not moves:
        return {**result, "status": "same"}

    sources = report.source_files(body)
    stale_files, stale_rows = set(), []
    for which, old, new in moves:
        changed = _changed_paths(repo, old, new)
        hit = sorted(p for p in changed if p in sources)
        stale_files.update(hit)
        for path in hit:
            stale_rows.extend(i for i in sources[path] if i not in stale_rows)
        result["moves"].append(
            {"ref": which, "from": old, "to": new, "commits": _commits(repo, old, new), "changed_files": changed}
        )
    result["stale_files"] = sorted(stale_files)
    result["stale_rows"] = stale_rows
    result["status"] = "stale" if stale_files else "moved_no_impact"
    return result
