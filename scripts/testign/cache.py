"""Local cache of scout master briefs: ~/.testign-kit/cache/<root-commit>/<feature>/.

Only the master brief (Production behavior at the merge-base) is cached; the develop diff always runs
fresh. An entry is reused only when every source file's blob hash at the new merge-base still matches.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import config

MANIFEST = "manifest.json"
BRIEF = "brief.md"
SCOUT_SKILL = Path(__file__).resolve().parents[2] / "skills" / "scout" / "SKILL.md"
_MODEL_RE = re.compile(r"^model:\s*(\S+)\s*$", flags=re.M)


def slug(feature: str) -> str:
    text = re.sub(r"[^\w\-]+", "-", feature.strip().lower(), flags=re.UNICODE).strip("-")
    if not text:
        raise ValueError("feature name is empty")
    return text


def entry_dir(root_commit: str, feature: str, home: Path | None = None) -> Path:
    return config.config_dir(home) / "cache" / root_commit / slug(feature)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load(folder: Path) -> tuple[dict | None, str | None]:
    """Return (manifest, problem). A missing or corrupt manifest gives (None, reason)."""
    path = Path(folder) / MANIFEST
    if not path.exists():
        return None, "no cache entry"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # ValueError covers JSON and UTF-8 decode errors
        return None, f"manifest unreadable: {exc}"
    problem = _shape_problem(data)
    if problem:
        return None, f"manifest malformed: {problem}"
    brief = Path(folder) / BRIEF
    if not brief.exists() or _sha(brief.read_bytes()) != data["brief_sha256"]:
        return None, "brief missing or does not match the manifest"
    return data, None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _shape_problem(data: object) -> str | None:
    if not isinstance(data, dict):
        return "not an object"
    files = data.get("files")
    if not isinstance(files, dict) or not files or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in files.items()
    ):
        return "'files' must be a non-empty map of path to blob hash"
    if not isinstance(data.get("anchors"), list):
        return "'anchors' must be a list"
    rows = data.get("rows")
    if not isinstance(rows, dict) or not all(isinstance(v, list) for v in rows.values()):
        return "'rows' must be a map of row ID to paths"
    if not isinstance(data.get("brief_sha256"), str):
        return "'brief_sha256' missing"
    return None


def scout_model(env: dict | None = None, skill: Path = SCOUT_SKILL) -> str:
    """The model the scout subagent is configured to run on, as recorded in a cache entry.

    ``CLAUDE_CODE_SUBAGENT_MODEL`` together with ``CLAUDE_CODE_SUBAGENT_MODEL_FORCE`` overrides the
    skill's ``model`` field; without the force flag, the skill's field wins. ``inherit`` means the
    tester's session model. This is the configured value, not one reported by the model itself.
    """
    env = os.environ if env is None else env
    forced = env.get("CLAUDE_CODE_SUBAGENT_MODEL", "").strip()
    if forced and env.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "").strip().lower() in {"1", "true", "yes"}:
        return f"{forced} (forced)"
    try:
        text = skill.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    head = text.split("\n---", 1)[0] if text.startswith("---") else ""
    m = _MODEL_RE.search(head)
    return m.group(1) if m else "inherit"


def _major(version: str) -> str:
    return str(version or "0").split(".")[0]


def decide(manifest: dict | None, anchors: list[str], current_hashes: dict[str, str | None],
           plugin_version: str, root_commit: str, problem: str | None = None) -> dict:
    """Classify reuse as ``hit``, ``partial`` (with stale rows and new anchors) or ``miss``.

    ``current_hashes`` are blob hashes at the current merge-base for the manifest's files.
    """
    if manifest is None:
        return {"result": "miss", "reason": problem or "no cache entry", "stale_rows": [], "new_anchors": anchors}
    if _major(manifest.get("plugin_version", "")) != _major(plugin_version):
        return {"result": "miss", "reason": "plugin major version changed", "stale_rows": [], "new_anchors": anchors}
    if manifest.get("root_commit") and manifest["root_commit"] != root_commit:
        return {"result": "miss", "reason": "different repository", "stale_rows": [], "new_anchors": anchors}

    files = manifest["files"]
    changed = sorted(p for p, h in files.items() if current_hashes.get(p) != h)
    new_anchors = [a for a in anchors if a not in set(manifest.get("anchors", []))]
    if files and len(changed) * 2 > len(files):
        return {"result": "miss", "reason": "most source files changed", "changed_files": changed,
                "stale_rows": [], "new_anchors": new_anchors}
    if not changed and not new_anchors:
        return {"result": "hit", "reason": "all source files unchanged", "changed_files": [],
                "stale_rows": [], "new_anchors": []}
    rows = manifest.get("rows", {})
    stale = [row for row, paths in rows.items() if any(p in changed for p in paths)]
    return {"result": "partial", "reason": "some source files changed or new anchors",
            "changed_files": changed, "stale_rows": stale, "new_anchors": new_anchors}


_ROW_RE = re.compile(r"^\|\s*(B\d+)\s*\|")
_SRC_RE = re.compile(r"`([^`@]+)@[0-9a-f]{4,40}`")


def brief_rows(brief: str) -> dict[str, list[str]]:
    """B* row → source paths, read from section 1 of a scout brief (``path@blob`` in backticks)."""
    m = re.search(r"^## 1\.[^\n]*\n(.*?)(?=^## |\Z)", brief, flags=re.S | re.M)
    rows: dict[str, list[str]] = {}
    for line in (m.group(1) if m else "").splitlines():
        rm = _ROW_RE.match(line.strip())
        if rm:
            rows[rm.group(1)] = list(dict.fromkeys(_SRC_RE.findall(line)))
    return rows


def save(folder: Path, brief: str, facts: dict, feature: str, model: str | None = None) -> dict:
    """Store the brief and a manifest built from the brief's source files and the scout facts."""
    rows = brief_rows(brief)
    if not rows:
        raise ValueError("the brief has no B* rows with `path@blob` source files; nothing to cache")
    empty = [r for r, paths in rows.items() if not paths]
    if empty:
        raise ValueError(f"B* rows without source files cannot be cached: {', '.join(empty)}")
    known = facts.get("blob_hashes_at_merge_base", {})
    paths = sorted({p for ps in rows.values() for p in ps})
    missing = [p for p in paths if not known.get(p)]
    if missing:
        raise ValueError(
            "source files have no blob hash at the merge-base in the facts file (rerun scout-facts with them "
            "in \"paths\"): " + ", ".join(missing)
        )
    old, _ = load(folder)
    manifest = {
        "feature": feature,
        "root_commit": facts["refs"]["root_commit"],
        "merge_base": facts["refs"]["merge_base"],
        "anchors": [a["anchor"] for a in facts.get("anchors", [])],
        "files": {p: known[p] for p in paths},
        "rows": rows,
        "unread": facts.get("unreadable", []),
        "plugin_version": facts.get("plugin_version"),
        "scout_model": model if model is not None else scout_model(),
        "brief_sha256": _sha(brief.encode("utf-8")),
        "reviewed_by": None,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    if old and old.get("files") == manifest["files"] and old.get("reviewed_by"):
        manifest["reviewed_by"] = old["reviewed_by"]
    folder = Path(folder)
    # The manifest carries the brief's hash, so a crash between the two writes leaves a pair that
    # load() rejects instead of a stale "hit".
    _atomic_write(folder / BRIEF, brief)
    _atomic_write(folder / MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def review(folder: Path, by: str, when: str | None = None) -> dict:
    """Set ``reviewed_by`` on an entry after a successful qa-close. Brief and hashes are untouched."""
    manifest, problem = load(folder)
    if manifest is None:
        raise ValueError(f"cannot mark review: {problem} at {folder}")
    manifest["reviewed_by"] = {"name": by, "date": when or datetime.now().date().isoformat()}
    _atomic_write(Path(folder) / MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest
