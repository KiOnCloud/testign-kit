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
    if meta.get("revision") is not None and str(meta["revision"]).isdigit():
        meta["revision"] = int(meta["revision"])
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
    meta = {**meta, **(meta_updates or {})}
    meta["revision"] = int(target.stem.rsplit("-r", 1)[1])
    meta["previous"] = read_path.name
    meta["generated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    write_new(target, join(meta, body))
    return target


def write_new(target: Path, text: str) -> None:
    """Create ``target`` exclusively; an existing file (even one created a moment ago) is never replaced."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except FileExistsError:
        raise ReportError(f"{target} already exists; refusing to overwrite") from None


def is_revision_file(path: Path) -> bool:
    return re.search(r"-survey-r\d+\.md$", Path(path).name) is not None


SOURCE_LABELS = ("[code]", "[khách chốt]", "[wiki]", "[observed]", "[suy luận]")
REQUIRED_SECTIONS = (1, 2, 3, 6)
_PLACEHOLDER = re.compile(r"<(?!/?(?:details|summary|br|b|i|code|sub|sup)\b)[^<>\n]{1,60}>")


def ticket_dir(output_dir: Path, ticket: str) -> Path:
    """Reports and test case files of a ticket live in ``<output_dir>/<TICKET>/``."""
    return Path(output_dir).expanduser() / ticket


def new_report_path(output_dir: Path, ticket: str) -> Path:
    """Path for the next revision of ``ticket`` (``r1`` when none exists). Never an existing file."""
    folder = ticket_dir(output_dir, ticket)
    found = _revisions(folder, ticket) if folder.exists() else []
    return folder / revision_name(ticket, (found[-1][0] if found else 0) + 1)


def _q_blocks(body: str) -> dict[str, str]:
    text = section(body, 4)
    blocks = {}
    for m in re.finditer(r"^### (Q\d+)\b(.*?)(?=^### |\Z)", text, flags=re.S | re.M):
        blocks[m.group(1)] = m.group(0)
    return blocks


def validate(path: Path) -> dict:
    """Check a report file against the template contract."""
    path = Path(path)
    if not path.exists():
        return {"ok": False, "errors": [f"report not found: {path}"], "warnings": []}
    return validate_text(path.read_text(encoding="utf-8"))


def validate_text(text: str) -> dict:
    """Check report text against the template contract. ``errors`` must be empty; ``warnings`` are advisory."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        meta, body = split(text)
    except ReportError as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": []}

    for key in FRONTMATTER_KEYS:
        if key not in meta:
            errors.append(f"frontmatter is missing '{key}'")
    if "revision" in meta and not isinstance(meta["revision"], int):
        errors.append(f"frontmatter 'revision' must be a number, got {meta['revision']!r}")
    for key in ("merge_base", "develop_head"):
        if meta.get(key) and not re.fullmatch(r"[0-9a-f]{40}", str(meta[key])):
            errors.append(f"frontmatter '{key}' must be a full 40-character SHA")

    numbers = [int(n) for n in re.findall(r"^## (\d+)\.", body, flags=re.M)]
    for n in REQUIRED_SECTIONS:
        if n not in numbers:
            errors.append(f"section {n} is missing")
    if numbers != sorted(numbers):
        errors.append(f"sections are out of order: {numbers}")

    for cells in table_rows(section(body, 3)):
        if cells and re.fullmatch(r"B\d+", cells[0]) and not any(l in " ".join(cells) for l in SOURCE_LABELS):
            errors.append(f"{cells[0]} has no source label")

    blocks = _q_blocks(body)
    for q in question_rows(body):
        block = blocks.get(q["id"])
        if block is None:
            errors.append(f"{q['id']} is in section 2 but has no detail block in section 4")
            continue
        heading = block.splitlines()[0]
        if not re.search(r"\b(fact|intent)\b", heading):
            errors.append(f"{q['id']} heading has no fact/intent label")
        if not any(l in block for l in SOURCE_LABELS):
            errors.append(f"{q['id']} has no source label")
        if "brse" in q["qa"].lower() and "(ja" not in block:
            errors.append(f"{q['id']} is routed to BrSE/khách but has no ja draft question")

    if not section(body, 6).strip():
        errors.append("section 6 (coverage) is empty")

    visible = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    leftovers = sorted(set(_PLACEHOLDER.findall(visible)))
    if leftovers:
        warnings.append("unfilled placeholders: " + ", ".join(leftovers[:10]))
    return {"ok": not errors, "errors": errors, "warnings": warnings}
