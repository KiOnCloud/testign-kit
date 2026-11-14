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


def append(page: str, rows: list[dict], ticket_regex: str, titles: dict[str, str] | None = None) -> tuple[str, dict]:
    """Append approved ``rows`` to ``page``. Returns the new page and what was added, skipped, superseded.

    A row is skipped when the ticket already has an entry with the same Q ID and Source link. A row with
    the same Q ID and a different Source becomes a new entry, and the previous active entry for that Q
    (on the page or earlier in the same batch) gets ``Status: superseded by <new ID>``.
    """
    titles = titles or {}
    ticket_re = re.compile(ticket_pattern(ticket_regex))
    for row in rows:
        if not re.fullmatch(r"Q\d+", str(row.get("q", ""))):
            raise DecisionsError(f"row has an invalid Q ID: {row.get('q')!r}")
        if not ticket_re.fullmatch(str(row.get("ticket", ""))):
            raise DecisionsError(f"row has an invalid ticket ID: {row.get('ticket')!r}")

    lines = split_lines(page)
    terms = [t for _, t in lines if t]
    default_eol = max(set(terms), key=terms.count) if terms else "\n"
    parsed = parse(page, ticket_regex)
    _check_page(parsed)

    result = {"added": [], "skipped": [], "superseded": []}
    status_updates: dict[int, str] = {}  # 0-based index of an existing line -> new text
    inserts: dict[int, list[str]] = {}  # new lines after an existing line index
    new_sections: dict[str, list[str]] = {}
    active: dict[tuple[str, str], tuple] = {}  # (ticket, q) -> ("page", line index, id) | ("new", list, pos, id)

    counters: dict[str, int] = {}
    for t, d in parsed["tickets"].items():
        ids = [int(x) for x in re.findall(rf"\bD-{re.escape(t)}-(\d{{3}})\b", page)]
        counters[t] = max(ids or [0])
        for e in d["entries"]:
            if e["active"]:
                active[(t, e["q"])] = ("page", e["status_lines"][-1] - 1, e["id"])
    seen = {
        (t, e["q"], e["fields"].get("Source", "").strip())
        for t, d in parsed["tickets"].items()
        for e in d["entries"]
    }

    for row in rows:
        ticket, q, source = row["ticket"], row["q"], str(row["source"]).strip()
        if (ticket, q, source) in seen:
            result["skipped"].append({"ticket": ticket, "q": q, "source": source})
            continue
        counters[ticket] = counters.get(ticket, 0) + 1
        entry_id = f"D-{ticket}-{counters[ticket]:03d}"
        block = ["", *render_entry(entry_id, row)]
        seen.add((ticket, q, source))
        result["added"].append(entry_id)

        previous = active.get((ticket, q))
        if previous:
            superseded = f"- Status: superseded by {entry_id}"
            if previous[0] == "page":
                status_updates[previous[1]] = superseded
            else:
                previous[1][previous[2]] = superseded
            result["superseded"].append(previous[-1])

        section = parsed["tickets"].get(ticket)
        if section:
            target = inserts.setdefault(_section_end(lines, section["line"]), [])
        else:
            target = new_sections.setdefault(ticket, [])
        target.extend(block)
        active[(ticket, q)] = ("new", target, len(target) - 1, entry_id)

    out: list[str] = []
    for idx, (text, eol) in enumerate(lines):
        text = status_updates.get(idx, text)
        extra = inserts.get(idx)
        if extra is None:
            out.append(text + eol)
            continue
        out.append(text + (eol or default_eol))
        next_is_heading = idx + 1 < len(lines) and lines[idx + 1][0].startswith("#")
        block = extra + ([""] if next_is_heading else [])
        for j, new_line in enumerate(block):
            last = j == len(block) - 1
            out.append(new_line + ("" if last and not eol else (eol or default_eol)))
    text = "".join(out)
    for ticket, block in new_sections.items():
        title = titles.get(ticket, "")
        heading = f"## {ticket} · {title}" if title else f"## {ticket}"
        if text and not text.endswith(("\n", "\r")):
            text += default_eol
        if text.strip() and not text.endswith(default_eol * 2):
            text += default_eol  # blank line before the new section
        text += default_eol.join([heading, *block]) + default_eol
    return text, result


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
