"""Parse and append to the decisions log page (format: references/decisions-log-format.md).

Pure string functions. Appending keeps every existing line byte for byte, including its own line
terminator, except the ``Status`` line of an entry that a new decision supersedes.
"""

from __future__ import annotations

import re

FIELDS = ["Date", "Question", "Decision", "Quote", "Source", "Decided by", "Approved by", "Report", "Status"]
ROW_KEYS = {
    "date": "Date",
    "question": "Question",
    "decision": "Decision",
    "quote": "Quote",
    "source": "Source",
    "decided_by": "Decided by",
    "approved_by": "Approved by",
    "report": "Report",
}
_FIELD_RE = re.compile(r"^- (" + "|".join(re.escape(f) for f in FIELDS) + r"):\s*(.*)$")
_ENTRY_RE = re.compile(r"^### (D-(.+)-(\d{3})) · (Q\d+)\s*$")
_LINE_RE = re.compile(r"([^\r\n]*)(\r\n|\n|\r|$)")


class DecisionsError(Exception):
    """The page or the rows cannot be processed. The message is meant for the tester."""


def check_text_format(text_format: str) -> None:
    if (text_format or "markdown").lower() != "markdown":
        raise DecisionsError(
            "the Backlog project uses Backlog notation, which the decisions log does not support yet. "
            "Switch the project's text formatting to Markdown, or record decisions by hand."
        )


def split_lines(text: str) -> list[tuple[str, str]]:
    """Split on CRLF, LF or CR only, keeping each line's own terminator (``""`` for the last line)."""
    out = []
    for m in _LINE_RE.finditer(text):
        if m.group(0) == "" and m.start() == len(text):
            break
        out.append((m.group(1), m.group(2)))
    return out


def ticket_pattern(ticket_regex: str) -> str:
    """The configured ticket regex made safe to embed: no anchors or word boundaries, groups neutralised."""
    rx = ticket_regex.replace("\\b", "").replace("^", "").replace("$", "")
    rx = re.sub(r"\((?!\?)", "(?:", rx)
    return f"(?:{rx})"


def _section_re(ticket_regex: str) -> re.Pattern:
    return re.compile(rf"^## (?P<ticket>{ticket_pattern(ticket_regex)})(?: · (?P<title>.*))?\s*$")


def parse(page: str, ticket_regex: str) -> dict:
    """Return ``{"tickets": {ticket: {"title", "line", "entries": [...]}}, "unparsed": [...]}``.

    Each entry has ``id``, ``ticket``, ``q``, ``line`` (1-based), ``fields``, ``status_lines`` and
    ``active``. Lines inside a ticket section that do not fit the format go to ``unparsed``.
    """
    section_re = _section_re(ticket_regex)
    tickets: dict[str, dict] = {}
    unparsed: list[dict] = []
    current_ticket, entry, last_field = None, None, None
    for no, (raw, _eol) in enumerate(split_lines(page), start=1):
        line = raw.rstrip()
        m = section_re.match(line)
        if m:
            current_ticket, entry, last_field = m.group("ticket"), None, None
            tickets.setdefault(current_ticket, {"title": (m.group("title") or "").strip(), "line": no, "entries": []})
            continue
        if line.startswith("## ") or line.startswith("# "):
            current_ticket, entry, last_field = None, None, None
            continue
        if current_ticket is None:
            continue
        m = _ENTRY_RE.match(line)
        if m and m.group(2) == current_ticket:
            entry = {"id": m.group(1), "ticket": m.group(2), "q": m.group(4), "line": no, "fields": {},
                     "status_lines": []}
            tickets[current_ticket]["entries"].append(entry)
            last_field = None
            continue
        if line.startswith("### "):
            entry, last_field = None, None
            unparsed.append({"line": no, "text": line})
            continue
        if not line.strip():
            continue
        if entry is not None:
            fm = _FIELD_RE.match(line)
            if fm:
                last_field = fm.group(1)
                entry["fields"][last_field] = fm.group(2).strip()
                if last_field == "Status":
                    entry["status_lines"].append(no)
                continue
            if last_field == "Quote" and re.match(r"^\s{2,}>", raw):
                quote_line = re.sub(r"^\s*>\s?", "", raw)
                prev = entry["fields"].get("Quote", "")
                entry["fields"]["Quote"] = f"{prev}\n{quote_line}" if prev else quote_line
                continue
        unparsed.append({"line": no, "text": line})
    for t in tickets.values():
        for e in t["entries"]:
            e["active"] = e["fields"].get("Status", "active").strip() == "active"
    return {"tickets": tickets, "unparsed": unparsed}


def render_entry(entry_id: str, row: dict) -> list[str]:
    missing = [k for k in ROW_KEYS if not str(row.get(k, "")).strip()]
    if missing:
        raise DecisionsError(f"row for {row.get('ticket')} {row.get('q')} is missing: {', '.join(missing)}")
    multiline = [k for k in ROW_KEYS if k != "quote" and re.search(r"[\r\n]", str(row[k]))]
    if multiline:
        raise DecisionsError(
            f"row for {row['ticket']} {row['q']} has line breaks in: {', '.join(multiline)}; only 'quote' may span lines"
        )
    lines = [f"### {entry_id} · {row['q']}"]
    for key, field in ROW_KEYS.items():
        if key == "quote":
            lines.append("- Quote:")
            lines.extend(f"  > {q}" if q else "  >" for q in str(row["quote"]).splitlines())
        else:
            lines.append(f"- {field}: {str(row[key]).strip()}")
    lines.append("- Status: active")
    return lines


def _check_page(parsed: dict) -> None:
    broken = [u for u in parsed["unparsed"] if u["text"].startswith("### ")]
    if broken:
        where = ", ".join(f"line {u['line']}: {u['text']}" for u in broken[:5])
        raise DecisionsError(
            "the decisions log has entry headings that do not follow the format (" + where + "). "
            "Fix them on the wiki first so entry IDs are not reused."
        )
    for ticket in parsed["tickets"].values():
        for e in ticket["entries"]:
            if not e["status_lines"]:
                raise DecisionsError(f"entry {e['id']} has no '- Status:' line; add one on the wiki first")


INDEX_HEADER = "| ID | Page | Ticket | Q | Anchors | Date | Status |"
INDEX_RULE = "|---|---|---|---|---|---|---|"
_INDEX_ROW_RE = re.compile(r"^\|\s*(D-[^|\s]+-\d{3})\s*\|")
COMMON = "common"
INDEX = "index"


class _PageEdit:
    """Pending edits of one page: replaced lines, blocks inserted after a line, new ticket sections."""

    def __init__(self, name: str, content: str, ticket_regex: str, heading: str):
        self.name = name
        self.original = content
        self.heading = heading
        self.lines = split_lines(content)
        terms = [t for _, t in self.lines if t]
        self.eol = max(set(terms), key=terms.count) if terms else "\n"
        self.parsed = parse(content, ticket_regex)
        _check_page(self.parsed)
        self.replace: dict[int, str] = {}
        self.inserts: dict[int, list[str]] = {}
        self.sections: dict[str, list[str]] = {}
        self.titles: dict[str, str] = {}

    def target_for(self, ticket: str, title: str) -> list[str]:
        section = self.parsed["tickets"].get(ticket)
        if section:
            return self.inserts.setdefault(_section_end(self.lines, section["line"]), [])
        if title:
            self.titles.setdefault(ticket, title)
        return self.sections.setdefault(ticket, [])

    def render(self) -> str:
        out: list[str] = []
        for idx, (text, eol) in enumerate(self.lines):
            text = self.replace.get(idx, text)
            extra = self.inserts.get(idx)
            if extra is None:
                out.append(text + eol)
                continue
            out.append(text + (eol or self.eol))
            next_is_heading = idx + 1 < len(self.lines) and self.lines[idx + 1][0].startswith("#")
            block = extra + ([""] if next_is_heading else [])
            for j, new_line in enumerate(block):
                last = j == len(block) - 1
                out.append(new_line + ("" if last and not eol else (eol or self.eol)))
        text = "".join(out)
        if not text.strip() and self.sections:
            text = self.heading + self.eol
        for ticket, block in self.sections.items():
            title = self.titles.get(ticket, "")
            heading = f"## {ticket} · {title}" if title else f"## {ticket}"
            if text and not text.endswith(("\n", "\r")):
                text += self.eol
            if text.strip() and not text.endswith(self.eol * 2):
                text += self.eol
            text += self.eol.join([heading, *block]) + self.eol
        return text

    @property
    def changed(self) -> bool:
        return bool(self.replace or self.inserts or self.sections)


def parse_index(page: str) -> list[dict]:
    """Rows of the decisions index table: id, page, ticket, q, anchors (list), date, status, line (0-based)."""
    rows = []
    for idx, (raw, _eol) in enumerate(split_lines(page)):
        if not _INDEX_ROW_RE.match(raw.strip()):
            continue
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", raw.strip().strip("|"))]
        if len(cells) < 7:
            continue
        rows.append({
            "id": cells[0], "page": cells[1], "ticket": cells[2], "q": cells[3],
            "anchors": [a.strip() for a in cells[4].split(";") if a.strip()],
            "date": cells[5], "status": cells[6], "line": idx,
        })
    return rows


def _index_line(row: dict) -> str:
    def cell(value: str) -> str:
        return str(value).replace("|", "\\|")

    anchors = "; ".join(cell(a) for a in row["anchors"])
    return f"| {row['id']} | {row['page']} | {row['ticket']} | {row['q']} | {anchors} | {row['date']} | {row['status']} |"


def _norm_anchor(text: str) -> str:
    return re.sub(r"[\s「」『』【】\"'`]+", "", text).casefold()


def _anchors_match(a: str, b: str) -> bool:
    x, y = _norm_anchor(a), _norm_anchor(b)
    if len(x) < 2 or len(y) < 2:
        return x == y and bool(x)
    return x in y or y in x


def lookup(index_page: str, anchors: list[str], ticket: str | None = None, feature: str | None = None) -> dict:
    """Index rows relevant to a survey and the pages to open.

    A row matches when it belongs to the ticket or one of its anchors overlaps a survey anchor. The pages
    to open are the pages of every matching row, plus ``common`` and the survey's own feature page, so a
    decision filed under another feature is still found.
    """
    rows = parse_index(index_page)
    matched = [
        r for r in rows
        if r["ticket"] == ticket or any(_anchors_match(a, b) for a in anchors for b in r["anchors"])
    ]
    pages = list(dict.fromkeys([*(r["page"] for r in matched), COMMON, *([feature] if feature else [])]))
    return {"matched": [{k: v for k, v in r.items() if k != "line"} for r in matched], "pages": pages}


def page_slug(feature: str) -> str:
    """Feature page slug; the same slug as the scout cache key."""
    from .cache import slug as cache_slug

    try:
        slug = cache_slug(str(feature))
    except ValueError:
        raise DecisionsError("row has an empty 'feature'; use the feature slug or 'common'") from None
    if slug == INDEX:
        raise DecisionsError("'index' is reserved for the decisions index page")
    return slug


def pages_needed(rows: list[dict], index_page: str) -> list[str]:
    """Pages the append must load: the rows' target pages, plus pages holding entries for the same
    ticket and Q (they may be superseded or already contain the same decision)."""
    keys = {(r["ticket"], r["q"]) for r in rows}
    targets = [page_slug(r.get("feature", "")) for r in rows]
    related = [r["page"] for r in parse_index(index_page) if (r["ticket"], r["q"]) in keys]
    return list(dict.fromkeys([*targets, *related]))


def apply_changes(pages: dict[str, str], index_page: str, rows: list[dict], ticket_regex: str,
                  titles: dict[str, str] | None = None, project: str = "") -> tuple[dict[str, str], str, dict]:
    """Append approved rows across feature/common pages and the index.

    ``pages`` maps page slug to current content ("" for a page that does not exist yet) and must hold
    every page from ``pages_needed``. Returns (changed pages, new index content, result). Existing lines
    are kept byte for byte except superseded ``Status`` lines (on pages) and status cells (in the index).
    A row whose decision is already on a page is skipped; if the index lacks its row (an earlier run
    stopped between the page and the index write), the index row is added.
    """
    titles = titles or {}
    ticket_re = re.compile(ticket_pattern(ticket_regex))
    rows = [dict(r) for r in rows]
    for row in rows:
        if not re.fullmatch(r"Q\d+", str(row.get("q", ""))):
            raise DecisionsError(f"row has an invalid Q ID: {row.get('q')!r}")
        if not ticket_re.fullmatch(str(row.get("ticket", ""))):
            raise DecisionsError(f"row has an invalid ticket ID: {row.get('ticket')!r}")
        anchors = row.get("anchors")
        if not isinstance(anchors, list) or not [a for a in anchors if str(a).strip()]:
            raise DecisionsError(f"row for {row['ticket']} {row['q']} needs a non-empty 'anchors' list")
        row["_page"] = page_slug(row.get("feature", ""))
    missing = [p for p in pages_needed(rows, index_page) if p not in pages]
    if missing:
        raise DecisionsError(f"pages not loaded: {', '.join(missing)}")

    editors = {
        name: _PageEdit(name, content, ticket_regex,
                        f"# Decisions — {project + ' / ' if project else ''}{name}")
        for name, content in pages.items()
    }
    index_lines = split_lines(index_page)
    index_terms = [t for _, t in index_lines if t]
    index_eol = max(set(index_terms), key=index_terms.count) if index_terms else "\n"
    index_rows = parse_index(index_page)
    index_ids = {r["id"] for r in index_rows}
    index_replace: dict[int, str] = {}
    index_new: list[dict] = []

    everything = index_page + "".join(pages.values())
    counters: dict[str, int] = {}
    seen: dict[tuple[str, str, str], tuple[str, str]] = {}
    active: dict[tuple[str, str], tuple] = {}
    for name, ed in editors.items():
        for t, d in ed.parsed["tickets"].items():
            for e in d["entries"]:
                seen[(t, e["q"], e["fields"].get("Source", "").strip())] = (e["id"], name)
                if e["active"]:
                    active[(t, e["q"])] = ("page", name, e["status_lines"][-1] - 1, e["id"])

    result = {"added": [], "skipped": [], "superseded": [], "index_repaired": [], "pages": []}
    for row in rows:
        ticket, q, source, page = row["ticket"], row["q"], str(row["source"]).strip(), row["_page"]
        anchors = [str(a).strip() for a in row["anchors"] if str(a).strip()]
        if (ticket, q, source) in seen:
            entry_id, where = seen[(ticket, q, source)]
            result["skipped"].append({"ticket": ticket, "q": q, "source": source, "id": entry_id, "page": where})
            if entry_id not in index_ids:
                index_new.append({"id": entry_id, "page": where, "ticket": ticket, "q": q, "anchors": anchors,
                                  "date": row.get("date", ""), "status": "active"})
                index_ids.add(entry_id)
                result["index_repaired"].append(entry_id)
            continue
        if ticket not in counters:
            counters[ticket] = max([int(x) for x in re.findall(rf"\bD-{re.escape(ticket)}-(\d{{3}})\b", everything)] or [0])
        counters[ticket] += 1
        entry_id = f"D-{ticket}-{counters[ticket]:03d}"
        block = ["", *render_entry(entry_id, row)]
        seen[(ticket, q, source)] = (entry_id, page)
        result["added"].append(entry_id)

        previous = active.get((ticket, q))
        if previous:
            superseded = f"- Status: superseded by {entry_id}"
            if previous[0] == "page":
                editors[previous[1]].replace[previous[2]] = superseded
            else:
                previous[1][previous[2]] = superseded
            prev_id = previous[-1]
            result["superseded"].append(prev_id)
            for r in index_rows:
                if r["id"] == prev_id:
                    index_replace[r["line"]] = _index_line({**r, "status": f"superseded by {entry_id}"})
            for r in index_new:
                if r["id"] == prev_id:
                    r["status"] = f"superseded by {entry_id}"

        target = editors[page].target_for(ticket, titles.get(ticket, row.get("ticket_title", "")))
        target.extend(block)
        active[(ticket, q)] = ("new", target, len(target) - 1, entry_id)
        index_new.append({"id": entry_id, "page": page, "ticket": ticket, "q": q, "anchors": anchors,
                          "date": row["date"], "status": "active"})
        index_ids.add(entry_id)

    changed = {name: ed.render() for name, ed in editors.items() if ed.changed}
    result["pages"] = sorted(changed)
    new_index = _render_index(index_lines, index_eol, index_replace, index_new, index_rows, project)
    return changed, new_index, result


def _render_index(lines, eol, replace, new_rows, rows, project) -> str:
    out = [replace.get(i, text) + term for i, (text, term) in enumerate(lines)]
    if not new_rows:
        return "".join(out)
    added = [_index_line(r) for r in new_rows]
    if rows:
        last = rows[-1]["line"]
        text, term = lines[last]
        out[last] = replace.get(last, text) + (term or eol)
        block = [a + eol for a in added]
        if not term:
            block[-1] = added[-1]
        out[last + 1:last + 1] = block
        return "".join(out)
    text = "".join(out)
    if not text.strip():
        title = f"# Decisions index — {project}" if project else "# Decisions index"
        text = (title + eol + eol + "> Managed by testign `/testign:close`. One row per decision; keep the columns."
                + eol + eol)
    elif not text.endswith(("\n", "\r")):
        text += eol + eol
    elif not text.endswith(eol * 2):
        text += eol
    return text + eol.join([INDEX_HEADER, INDEX_RULE, *added]) + eol


def append(page: str, rows: list[dict], ticket_regex: str, titles: dict[str, str] | None = None) -> tuple[str, dict]:
    """Single-page append (all rows on one page, no index). Kept for parsing/formatting checks."""
    rows = [{"feature": "page", "anchors": ["-"], **r} for r in rows]
    changed, _index, result = apply_changes({"page": page}, "", rows, ticket_regex, titles)
    return changed.get("page", page), {k: result[k] for k in ("added", "skipped", "superseded")}


def _section_end(lines: list[tuple[str, str]], heading_line: int) -> int:
    """0-based index of the last non-blank line of the section that starts at ``heading_line`` (1-based)."""
    last = heading_line - 1
    for idx in range(heading_line, len(lines)):
        text = lines[idx][0]
        if text.startswith("## ") or text.startswith("# "):
            break
        if text.strip():
            last = idx
    return last
