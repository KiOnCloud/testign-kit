"""Turn one saved ``get_design_context`` output of a Figma change table into staged rows.

The Figma MCP output is not a published contract, so this module reads only the shape seen in
real tables and refuses anything else with a short reason; the caller then falls back to reading
the table row by row. The shape it accepts::

    const assetPathPrefix = "https://www.figma.com/api/mcp/asset/<id>";
    const imgCaptureX = `${assetPathPrefix}/<file>.png`;
    export default function Table() {
      return (
        <div data-node-id="<table>" data-name="...">
          <div data-node-id="..." data-name="Header"> <div data-name="No">…</div> … </div>
          <div data-node-id="<row>" data-name="<label> · <target id>">
            <div data-name="No"><p>1</p></div>
            <div data-name="Capture"><div …><img src={imgCaptureX} /></div></div>
            <div data-name="Content"><p>…</p></div> …

Rows come from ``get_metadata`` of the same table (one frame per row named ``<label> · <target
id>``) and are cross-checked against the design context. Asset constants are read only above
``export default`` and attributes only in tag position, so text a designer typed into a cell can
never add a row, a cell or a capture URL. Stdlib only.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urlsplit

ASSET_HOSTS = ("www.figma.com",)
ASSET_PATH = "/api/mcp/asset/"
ASSET_PATH_RE = re.compile(r"[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*")
MAX_DEPTH = 100  # deeper JSX is refused instead of hitting the recursion limit
REQUIRED = ("No", "Content")
TARGET_RE = re.compile(r"^I?\d+:\d+(?:;\d+:\d+)*$")
NODE_RE = re.compile(r"^\d+:\d+$")
BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "section", "h1", "h2", "h3", "h4", "h5", "h6"}
MAX_TEXT = 4_000_000
INVISIBLE = " \t\r\n\xa0\u200b\u200c\u200d\u2060\ufeff"  # trimmed from each line's ends


class TableError(ValueError):
    """The output does not have the known table shape; the message is one short line."""


def load_tool_result(text: str) -> str:
    """The text of a saved tool result: a JSON list of ``{type: text, text}`` blocks, or raw text."""
    if len(text) > MAX_TEXT:
        raise TableError("the saved result is too large")
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            blocks = json.loads(stripped)
        except ValueError:
            raise TableError("the saved result is not a list of text blocks") from None
        if not isinstance(blocks, list) or not all(isinstance(b, dict) and isinstance(b.get("text"), str)
                                                   for b in blocks):
            raise TableError("the saved result is not a list of text blocks")
        return "\n".join(b["text"] for b in blocks)
    return text


# capture URLs ---------------------------------------------------------------------------------
def check_asset_url(url: Any) -> str:
    """An https URL on a Figma asset host under ``/api/mcp/asset/``; anything else is refused."""
    if not isinstance(url, str) or not url or len(url) > 500:
        raise TableError("a capture URL is missing or too long")
    if "\\" in url or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise TableError("a capture URL has characters a browser reads differently")
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        raise TableError("a capture URL cannot be read") from None
    # Only plain path characters: the URL goes into a quoted shell argument of `curl`.
    if (parts.scheme != "https" or host not in ASSET_HOSTS or parts.port is not None
            or "@" in parts.netloc or "%" in parts.netloc or parts.query or parts.fragment or "?" in url
            or "#" in url or not parts.path.startswith(ASSET_PATH) or ".." in parts.path
            or not ASSET_PATH_RE.fullmatch(parts.path[len(ASSET_PATH):])):
        raise TableError("a capture URL is not a Figma asset URL")
    return url


def _assets(prelude: str) -> dict[str, str]:
    """``const`` asset declarations above ``export default``, one per line at column 0."""
    prefix_name, prefix = None, None
    out: dict[str, str] = {}
    for line in prelude.splitlines():
        m = re.fullmatch(r'const ([A-Za-z_]\w*) = (?:"([^"\\`$]*)"|`\$\{([A-Za-z_]\w*)\}(/[^`\\$]*)`);', line)
        if not m:
            if line.startswith("const "):
                raise TableError("an asset constant has an unknown form")
            continue
        name, plain, ref, tail = m.groups()
        if name in out or name == prefix_name:
            raise TableError(f"the asset {name} is declared twice")
        if plain is not None and prefix_name is None and not out and name.lower().endswith("prefix"):
            prefix_name, prefix = name, plain
            continue
        if ref is not None:
            if ref != prefix_name or prefix is None:
                raise TableError(f"the asset {name} uses an unknown prefix")
            out[name] = prefix + tail
        else:
            out[name] = plain
    return out


# JSX ------------------------------------------------------------------------------------------
class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag, self.attrs, self.children = tag, attrs, []

    def elements(self) -> list["_Node"]:
        return [c for c in self.children if isinstance(c, _Node)]


_NAME = re.compile(r"[A-Za-z][\w.:-]*")
_ATTR = re.compile(r"[A-Za-z_][\w:-]*")


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def _literal(s: str, i: int) -> tuple[str, int]:
    """A string or template literal starting at ``s[i]`` (no ``${…}``); returns (value, end)."""
    quote = s[i]
    out, i = [], i + 1
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            out.append({"n": "\n", "t": "\t"}.get(s[i + 1], s[i + 1]))
            i += 2
            continue
        if ch == quote:
            return "".join(out), i + 1
        if quote == "`" and s.startswith("${", i):
            raise TableError("a text expression has an unknown form")
        out.append(ch)
        i += 1
    raise TableError("a text expression is not closed")


def _expression(s: str, i: int) -> tuple[str, str, int]:
    """``{"…"}``, ``{`…`}`` or ``{name}`` at ``s[i]``; returns (kind, value, end)."""
    j = _skip_ws(s, i + 1)
    if j < len(s) and s[j] in "\"'`":
        value, j = _literal(s, j)
        kind = "text"
    else:
        m = re.compile(r"[A-Za-z_]\w*").match(s, j)
        if not m:
            raise TableError("a JSX expression has an unknown form")
        value, j, kind = m.group(), m.end(), "name"
    j = _skip_ws(s, j)
    if j >= len(s) or s[j] != "}":
        raise TableError("a JSX expression has an unknown form")
    return kind, value, j + 1


def _jsx_text(raw: str) -> str:
    """JSX text rules: lines trimmed, blank lines dropped, the rest joined by one space."""
    lines = [line.strip() for line in raw.splitlines()]
    if len(lines) > 1:
        text = " ".join(line for line in lines if line)
    else:
        text = raw
    return html.unescape(text)


def _parse_jsx(s: str, i: int) -> _Node:
    """The element starting at ``s[i]`` and everything inside it."""
    stack: list[_Node] = []
    root: _Node | None = None
    while i < len(s):
        if s[i] == "<":
            if s.startswith("</", i):
                m = _NAME.match(s, i + 2)
                end = _skip_ws(s, m.end()) if m else i
                if not m or end >= len(s) or s[end] != ">" or not stack or stack[-1].tag != m.group():
                    raise TableError("the JSX has an unbalanced closing tag")
                stack.pop()
                i = end + 1
                if not stack:
                    return root  # type: ignore[return-value]
                continue
            m = _NAME.match(s, i + 1)
            if not m:
                raise TableError("the JSX has a tag of unknown form")
            node, i = _Node(m.group(), {}), m.end()
            while True:
                i = _skip_ws(s, i)
                if s.startswith("/>", i) or s.startswith(">", i):
                    break
                a = _ATTR.match(s, i)
                if not a:
                    raise TableError("the JSX has an attribute of unknown form")
                name, i = a.group(), a.end()
                if name in node.attrs:
                    raise TableError(f"a tag repeats the attribute {name}")
                if s.startswith("=", i):
                    if s.startswith('="', i):
                        end = s.find('"', i + 2)
                        if end < 0:
                            raise TableError("an attribute is not closed")
                        node.attrs[name] = html.unescape(s[i + 2:end])  # JSX decodes entities too
                        i = end + 1
                    elif s.startswith("={", i):
                        kind, value, i = _expression(s, i + 1)
                        node.attrs[name] = value if kind == "name" else ""
                        if kind == "name":
                            node.attrs[f"{name}:ref"] = value
                    else:
                        raise TableError("the JSX has an attribute of unknown form")
                else:
                    node.attrs[name] = ""
            if stack:
                stack[-1].children.append(node)
            else:
                root = node
            if s.startswith("/>", i):
                i += 2
                if not stack:
                    return node
            else:
                stack.append(node)
                if len(stack) > MAX_DEPTH:
                    raise TableError("the JSX is nested too deeply")
                i += 1
        elif s[i] == "{":
            if not stack:
                raise TableError("the JSX has no root element")
            kind, value, i = _expression(s, i)
            if kind != "text":
                raise TableError("a cell holds a JSX expression of unknown form")
            stack[-1].children.append(value)
        else:
            j = i
            while j < len(s) and s[j] not in "<{":
                j += 1
            if stack:
                text = _jsx_text(s[i:j])
                if text:
                    stack[-1].children.append(text)
            elif s[i:j].strip():
                raise TableError("the JSX has text outside its root element")
            i = j
    raise TableError("the JSX is not closed")


def _lines(node: _Node) -> list[str]:
    """A cell's text: a block element starts a line, ``<br>`` breaks one, links keep their address."""
    lines: list[str] = [""]

    def walk(n: _Node) -> None:
        for child in n.children:
            if isinstance(child, str):
                lines[-1] += child
            elif child.tag == "br":
                lines.append("")
            elif child.tag in BLOCK_TAGS:
                lines.append("")
                walk(child)
                lines.append("")
            elif child.tag == "a":
                label = " ".join(_lines(child))
                href = child.attrs.get("href", "")
                linked = href.startswith(("http://", "https://")) and href != label
                lines[-1] += f"[{label}]({href})" if linked else label
            elif child.tag == "img":
                continue
            else:
                walk(child)

    walk(node)
    cleaned = (line.strip(INVISIBLE) for line in lines)
    return [line for line in cleaned if line]


def _cell_text(node: _Node) -> str:
    return "\n".join(_lines(node))


def _images(node: _Node) -> list[str]:
    found = []
    for child in node.elements():
        if child.tag == "img":
            if "src:ref" not in child.attrs:
                raise TableError("a capture image has no asset reference")
            found.append(child.attrs["src:ref"])
        found.extend(_images(child))
    return found


# metadata -------------------------------------------------------------------------------------
_TAG = re.compile(r'<(/?)([a-z][a-z0-9-]*)((?:\s+[a-z-]+="[^"]*")*)\s*(/?)>')
_XML_ATTR = re.compile(r'([a-z-]+)="([^"]*)"')


def _metadata_rows(metadata: str, table_id: str, source_node: str) -> list[dict]:
    """The direct child frames of ``table_id``: ``[{id, name, y}]`` in document order.

    The table must be ``source_node`` (the run's Figma node) or lie inside it, so a saved result
    of another table is never staged under this run's source.
    """
    depth, table_depth, rows = 0, None, []
    ancestors: list[str] = []
    for m in _TAG.finditer(metadata):
        closing, _tag, attrs_text, self_closing = m.groups()
        if closing:
            depth -= 1
            if ancestors:
                ancestors.pop()
            if table_depth is not None and depth < table_depth:
                return rows
            continue
        attrs = {k: html.unescape(v) for k, v in _XML_ATTR.findall(attrs_text)}
        if table_depth is None and attrs.get("id") == table_id:
            if source_node != table_id and source_node not in ancestors:
                raise TableError("the table is not the run's Figma node or inside it")
            table_depth = depth + 1
        elif table_depth is not None and depth == table_depth:
            try:
                y = float(attrs.get("y", ""))
            except ValueError:
                raise TableError("a row layer has no position") from None
            rows.append({"id": attrs.get("id", ""), "name": attrs.get("name", ""), "y": y})
        if not self_closing:
            depth += 1
            ancestors.append(attrs.get("id", ""))
    if table_depth is None:
        raise TableError("the metadata does not hold the table of the design context")
    raise TableError("the metadata is not closed")


def _split_label(name: str) -> tuple[str, str] | None:
    label, sep, target = name.rpartition(" · ")
    if not sep or not label.strip() or not TARGET_RE.match(target):
        return None
    return label, target


# the table ------------------------------------------------------------------------------------
def parse(context_text: str, metadata_text: str, *, file_key: str, table_node: str) -> list[dict]:
    """``[{row, source, type, content, creator, capture_url, numbered_by}]``.

    Rows are numbered by the ``No`` cell; when that column is not a set of distinct numbers they are
    numbered top to bottom on the canvas, and ``numbered_by`` says ``canvas`` instead of ``no``.
    """
    try:
        return _parse(context_text, metadata_text, file_key, table_node)
    except RecursionError:
        raise TableError("the output is nested too deeply") from None


def _parse(context_text: str, metadata_text: str, file_key: str, table_node: str) -> list[dict]:
    context = load_tool_result(context_text)
    metadata = load_tool_result(metadata_text)
    start = context.find("\nexport default function ")
    if start < 0:
        raise TableError("the design context has no component; it may be metadata only")
    assets = _assets(context[:start])
    body = context.find("<", start)
    if body < 0:
        raise TableError("the design context has no JSX")
    root = _parse_jsx(context, body)
    table_id = root.attrs.get("data-node-id", "")
    if not NODE_RE.match(table_id):
        raise TableError("the table has no node id")
    children = root.elements()
    headers = [c for c in children if c.attrs.get("data-name") == "Header"]
    if len(headers) != 1:
        raise TableError("the table has no single Header row")
    columns = [c.attrs.get("data-name", "") for c in headers[0].elements()]
    if len(set(columns)) != len(columns) or any(name not in columns for name in REQUIRED):
        raise TableError(f"the header must name each of {', '.join(REQUIRED)} once")
    meta = {r["id"]: r for r in _metadata_rows(metadata, table_id, table_node) if r["name"] != "Header"}
    found = []
    for row in children:
        if row is headers[0]:
            continue
        node_id, name = row.attrs.get("data-node-id", ""), row.attrs.get("data-name", "")
        split = _split_label(name)
        if not NODE_RE.match(node_id) or split is None:
            raise TableError(f"the row {node_id or '?'} is not named <label> · <target id>")
        if node_id not in meta or meta[node_id]["name"] != name:
            raise TableError(f"the row {node_id} is not in the metadata of the table")
        cells: dict[str, _Node] = {}
        for cell in row.elements():
            key = cell.attrs.get("data-name", "")
            if key in cells:
                raise TableError(f"the row {node_id} has two {key} cells")
            cells[key] = cell
        if "Content" not in cells or "No" not in cells:
            raise TableError(f"the row {node_id} has no Content or No cell")
        content = _cell_text(cells["Content"])
        if not content:
            raise TableError(f"the row {node_id} has empty content")
        images = _images(cells["Capture"]) if "Capture" in cells else []
        if len(images) > 1:
            raise TableError(f"the row {node_id} has more than one capture")
        url = None
        if images:
            if images[0] not in assets:
                raise TableError(f"the capture of row {node_id} names an unknown asset")
            url = check_asset_url(assets[images[0]])
        found.append({"node": node_id, "target": split[1], "y": meta[node_id]["y"],
                      "no": _cell_text(cells["No"]), "content": content,
                      "type": _cell_text(cells["Type"]) if "Type" in cells else "",
                      "creator": _cell_text(cells["Creator"]) if "Creator" in cells else "", "capture_url": url})
    if not found:
        raise TableError("the table has no rows")
    if set(meta) != {r["node"] for r in found}:
        raise TableError("the metadata and the design context list other rows")
    numbers = [int(r["no"]) if re.fullmatch(r"\d{1,4}", r["no"]) else None for r in found]
    if None not in numbers and len(set(numbers)) == len(numbers) and 0 not in numbers:
        ordered, by = sorted(zip(numbers, found), key=lambda pair: pair[0]), "no"
    else:  # no usable No column: the order on the canvas, top to bottom
        ordered, by = list(enumerate(sorted(found, key=lambda r: r["y"]), start=1)), "canvas"
    return [{"row": f"r{n:02d}",
             "source": {"kind": "figma", "file": file_key, "table_node": table_node, "row_node": r["node"],
                        "target_node": r["target"], "no": r["no"]},
             "type": r["type"], "content": r["content"], "creator": r["creator"], "capture_url": r["capture_url"],
             "numbered_by": by}
            for n, r in ordered]
