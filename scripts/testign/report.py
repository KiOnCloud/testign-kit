"""Survey report files: frontmatter, revisions and the tables the later steps read.

Reports are named ``<TICKET>-survey-r<N>.md``. A revision is never overwritten; changes always go to
``r<N+1>`` with ``previous`` pointing at the file that was read.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

FRONTMATTER_KEYS = [
    "ticket",
    "repo",
    "master_ref",
    "develop_ref",
    "merge_base",
    "develop_head",
    "revision",
    "previous",
    "plugin_version",
    "lang",
    "generated_at",
]
ID_RE = re.compile(r"\b([BRQ]\d+)\b")
_PIPE = re.compile(r"(?<!\\)\|")


class ReportError(Exception):
    """The report file is missing, malformed or would be overwritten."""


def revision_name(ticket: str, revision: int) -> str:
    return f"{ticket}-survey-r{revision}.md"


def _revisions(folder: Path, ticket: str) -> list[tuple[int, Path]]:
    rx = re.compile(rf"^{re.escape(ticket)}-survey-r(\d+)\.md$")
    found = []
    for path in folder.glob(f"{ticket}-survey-r*.md"):
        m = rx.match(path.name)
        if m:
            found.append((int(m.group(1)), path))
    return sorted(found)


def latest_revision(folder: Path, ticket: str) -> Path:
    found = _revisions(Path(folder), ticket)
    if not found:
        raise ReportError(f"no survey report for {ticket} in {folder}")
    return found[-1][1]


def next_revision_path(path: Path) -> Path:
    """Path for the revision after the highest one that exists next to ``path``."""
    path = Path(path)
    meta, _ = split(path.read_text(encoding="utf-8"))
    ticket = meta.get("ticket") or ""
    found = _revisions(path.parent, ticket)
    top = found[-1][0] if found else int(meta.get("revision") or 0)
    return path.parent / revision_name(ticket, top + 1)


def split(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body). Values are strings, ints for ``revision``, None for null."""
    if not text.startswith("---"):
        raise ReportError("report has no YAML frontmatter")
    lines = text.splitlines(keepends=True)
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ReportError("report frontmatter is not closed with ---")
    meta: dict = {}
    for line in lines[1:end]:
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        meta[key.strip()] = None if value in ("", "null", "~") else value
    if meta.get("revision") is not None:
        try:
            meta["revision"] = int(meta["revision"])
        except ValueError as exc:
            raise ReportError(f"revision must be a number, got {meta['revision']!r}") from exc
    return meta, "".join(lines[end + 1 :])


def join(meta: dict, body: str) -> str:
    keys = FRONTMATTER_KEYS + [k for k in meta if k not in FRONTMATTER_KEYS]
    lines = ["---"]
    for key in keys:
        if key in meta:
            value = meta[key]
            lines.append(f"{key}: {'null' if value is None else value}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def load(path: Path) -> tuple[dict, str]:
    path = Path(path)
    if not path.exists():
        raise ReportError(f"report not found: {path}")
    return split(path.read_text(encoding="utf-8"))


def section(body: str, number: int) -> str:
    """Text of section ``## <number>.`` up to the next ``## `` heading."""
    m = re.search(rf"^## {number}\.[^\n]*\n(.*?)(?=^## |\Z)", body, flags=re.S | re.M)
    return m.group(1) if m else ""


def table_rows(text: str) -> list[list[str]]:
    """Data rows of the Markdown tables in ``text`` (header and separator rows skipped)."""
    rows, header_seen = [], False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            header_seen = False
            continue
        cells = [c.strip().replace("\\|", "|") for c in _PIPE.split(line.strip("|"))]
        if not header_seen:
            header_seen = True
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def behavior_rows(body: str) -> list[dict]:
    """B* rows of section 3. ``needs_case`` is true when develop changed it or the spec deviates."""
    out = []
    for cells in table_rows(section(body, 3)):
        if not cells or not re.fullmatch(r"B\d+", cells[0]):
            continue
        develop = cells[3] if len(cells) > 3 else ""
        deviation = cells[5] if len(cells) > 5 else ""
        out.append(
            {
                "id": cells[0],
                "behavior": cells[1] if len(cells) > 1 else "",
                "needs_case": ("➖" not in develop) or ("⚠" in deviation),
            }
        )
    return out


def regression_rows(body: str) -> list[dict]:
    return [
        {"id": c[0], "area": c[1] if len(c) > 1 else "", "needs_case": True}
        for c in table_rows(section(body, 5))
        if c and re.fullmatch(r"R\d+", c[0])
    ]


def question_rows(body: str) -> list[dict]:
    return [
        {"id": c[0], "qa": c[1], "summary": c[2], "level": c[3], "blocks": c[4]}
        for c in table_rows(section(body, 2))
        if len(c) >= 5 and re.fullmatch(r"Q\d+", c[0])
    ]


def source_files(body: str) -> dict[str, list[str]]:
    """Map each code path in section 8 (appendix) to the report row IDs that cite it."""
    files: dict[str, list[str]] = {}
    for cells in table_rows(section(body, 8)):
        if len(cells) < 2:
            continue
        ids = ID_RE.findall(cells[0])
        for raw in re.findall(r"`([^`]+)`", cells[1]) or [cells[1]]:
            path = re.sub(r":\d+(-\d+)?$", "", raw.strip())
            if path:
                files.setdefault(path, [])
                files[path].extend(i for i in ids if i not in files[path])
    return files


def replace_section(body: str, number: int, new_text: str) -> str:
    """Replace the content of section ``number`` (heading kept) with ``new_text``."""
    pattern = re.compile(rf"(^## {number}\.[^\n]*\n)(.*?)(?=^## |\Z)", flags=re.S | re.M)
    if not pattern.search(body):
        raise ReportError(f"report has no section {number}")
    return pattern.sub(lambda m: m.group(1) + new_text, body, count=1)


def write_revision(read_path: Path, body: str, meta_updates: dict | None = None) -> Path:
    """Write ``body`` as the next revision of the report at ``read_path`` and return its path."""
    read_path = Path(read_path)
    meta, _ = load(read_path)
    target = next_revision_path(read_path)
    if target.exists():
        raise ReportError(f"{target} already exists; refusing to overwrite")
    meta = {**meta, **(meta_updates or {})}
    meta["revision"] = int(target.stem.rsplit("-r", 1)[1])
    meta["previous"] = read_path.name
    meta["generated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    target.write_text(join(meta, body), encoding="utf-8", newline="\n")
    return target
