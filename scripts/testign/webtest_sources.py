"""Where the cases of a web test suite come from: one registry entry per source kind.

Every caller (the suite store, a run made from a suite, the export, the console API and the new
suite wizard) reads this registry instead of naming kinds, so a new source adds one entry here::

    mode         extract   one source row gives one case (figma, excel)
                 generate  the agent writes several cases per source row (backlog)
                 none      the tester writes every case (manual)
    check        validate the wizard input and return the ``source`` dict a suite stores
    ref          the identity of a source, compared when two suites or runs hold the same one
    rows         the source rows a case can trace to (only ``generate`` sources have rows apart
                 from their cases)
    trace_label  the export header of the ``trace`` field, or None when the kind has nothing to show
    trace_value  the text of that field for one case's source block
    needs_agent  the suite is born ``generating`` and a ``suite-generate`` job fills it
    extract      for ``extract`` sources read without the agent: the cases of the stored input

A source dict holds text or numbers only, at most 500 characters each, because a run copies it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import config, report

SOURCE_VALUE_CAP = 500
TRACE_ID_RE = re.compile(r"\b([BR]\d+)\b")
_FIGMA = re.compile(r"^https://(?:www\.)?figma\.com/(?:design|file|proto)/([A-Za-z0-9]{10,64})(?:/[^?#]*)?\?([^#]*)")

UPLOAD_CAP = 10 * 1024 * 1024  # as the template upload of the console
EXCEL_SUFFIXES = (".xlsx", ".xlsm")
EXCEL_MAX_ROWS = 2000


class SourceError(ValueError):
    """The wizard input does not name a usable source; ``code`` is the console's error code."""

    def __init__(self, message: str, code: str = "bad-source") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Env:
    """What a source needs from outside the suite: the output folder and the templates' home."""

    output_dir: Path
    home: Path | None = None
    ticket_regex: str = config.DEFAULT_TICKET_ID_REGEX

    @classmethod
    def from_config(cls, cfg: dict, home: Path | None = None) -> "Env":
        return cls(Path(str(cfg["output_dir"])).expanduser(), home,
                   str(cfg.get("ticket_id_regex") or config.DEFAULT_TICKET_ID_REGEX))


@dataclass(frozen=True)
class Source:
    kind: str
    mode: str
    needs_agent: bool
    trace_label: str | None
    check: Callable[[dict, Env], dict]
    ref: Callable[[dict], tuple]
    rows: Callable[[dict, Env, Path | None], list[dict]] = field(default=lambda _s, _e, _f: [])
    trace_value: Callable[[dict], str] = field(default=lambda _c: "")
    extract: Callable[[dict, Env, Path], list[dict]] | None = None


def _value(value: Any, what: str, cap: int = SOURCE_VALUE_CAP) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceError(f"{what} is required")
    value = value.strip()
    if len(value) > cap or any(ord(ch) < 32 for ch in value):
        raise SourceError(f"{what} is too long or has control characters")
    return value


# figma ----------------------------------------------------------------------------------------
def figma_source(url: Any) -> dict:
    """A Figma design URL with a node id → {kind, url, file, node}."""
    if not isinstance(url, str) or len(url) > 2000:
        raise SourceError("source must be a Figma design URL")
    m = _FIGMA.match(url.strip())
    node = None
    if m:
        for pair in m.group(2).split("&"):
            key, _, value = pair.partition("=")
            if key == "node-id" and re.fullmatch(r"\d+[-:]\d+", value):
                node = value.replace("-", ":")
    if not m or node is None:
        raise SourceError("source must be a Figma design URL with a node-id")
    if len(url.strip()) > SOURCE_VALUE_CAP:
        raise SourceError("the Figma URL is too long")
    return {"kind": "figma", "url": url.strip(), "file": m.group(1), "node": node}


def _check_figma(payload: dict, _env: Env) -> dict:
    return figma_source(payload.get("figma_url"))


# backlog --------------------------------------------------------------------------------------
def _is_link(path: Path) -> bool:
    from .webtest import _is_link as is_link  # noqa: PLC0415 - webtest imports this module

    return is_link(path)


def report_file(env: Env, ticket: str, name: str) -> Path:
    """The survey report file of a backlog source, refused when it or its folder is a link."""
    folder = report.ticket_dir(env.output_dir, ticket)
    path = folder / name
    if not report.is_revision_file(path) or _is_link(folder) or _is_link(path) or not path.is_file():
        raise SourceError(f"the survey report {name} of {ticket} cannot be read", "no-report")
    return path


def _check_backlog(payload: dict, env: Env) -> dict:
    ticket = payload.get("ticket")
    if not isinstance(ticket, str) or not re.fullmatch(env.ticket_regex, ticket) or len(ticket) > 64 \
            or not re.fullmatch(r"[A-Za-z0-9_-]+", ticket):
        raise SourceError("ticket does not match ticket_id_regex", "bad-ticket")
    folder = report.ticket_dir(env.output_dir, ticket)
    revision = payload.get("revision")
    try:
        if revision in (None, ""):
            path = report.latest_revision(folder, ticket)
        else:
            if isinstance(revision, bool) or not str(revision).isdigit():
                raise SourceError("revision must be a number")
            path = folder / report.revision_name(ticket, int(revision))
    except report.ReportError:
        raise SourceError(f"{ticket} has no survey report; survey the ticket first", "no-report") from None
    path = report_file(env, ticket, path.name)
    try:
        meta, body = report.load(path)
    except (report.ReportError, OSError, UnicodeDecodeError):
        raise SourceError(f"the survey report {path.name} cannot be read", "no-report") from None
    if not report.behavior_rows(body) and not report.regression_rows(body):
        raise SourceError(f"the survey report {path.name} has no B* or R* rows", "no-report")
    revision_no = int(path.stem.rsplit("-r", 1)[1])
    out = {"kind": "backlog", "ticket": ticket, "report": path.name, "revision": revision_no}
    for key in ("develop_head", "merge_base"):
        value = meta.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{7,40}", value):
            out[key] = value
    return out


def _backlog_rows(source: dict, env: Env, _folder: Path | None) -> list[dict]:
    path = report_file(env, str(source.get("ticket") or ""), str(source.get("report") or ""))
    try:
        _meta, body = report.load(path)
    except (report.ReportError, OSError, UnicodeDecodeError):
        raise SourceError(f"the survey report {path.name} cannot be read", "no-report") from None
    return ([{"id": r["id"], "label": r["behavior"]} for r in report.behavior_rows(body)]
            + [{"id": r["id"], "label": r["area"]} for r in report.regression_rows(body)])


# excel ----------------------------------------------------------------------------------------
def safe_file_name(name: Any) -> str:
    """The name a workbook is stored under in a suite: a short ASCII slug with its own suffix."""
    if not isinstance(name, str) or not name.strip():
        raise SourceError("the Excel file has no name")
    base = Path(name.replace("\\", "/")).name
    suffix = Path(base).suffix.lower()
    if suffix not in EXCEL_SUFFIXES:
        raise SourceError("the Excel file must be .xlsx or .xlsm", "bad-file")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(base).stem).strip("-._")[:60] or "cases"
    return stem + suffix


def _check_excel(payload: dict, env: Env) -> dict:
    from . import templates  # noqa: PLC0415

    name = safe_file_name(payload.get("file_name"))
    template = _value(payload.get("template"), "template", 100)
    try:
        entry = templates.resolve(template, env.home)
    except templates.TemplateError:
        raise SourceError("template is not registered", "unknown-template") from None
    sheet = payload.get("sheet")
    out = {"kind": "excel", "file": name, "template": entry["name"]}
    if sheet not in (None, ""):
        out["sheet"] = _value(sheet, "sheet", 100)
    return out


def check_workbook_file(path: Path) -> None:
    """An uploaded workbook within the caps: 10 MB on disk and 5 MB unzipped, not a link."""
    from . import templates  # noqa: PLC0415

    try:
        if _is_link(path) or not path.is_file():
            raise OSError
        size = path.stat().st_size
    except OSError:
        raise SourceError("the Excel file cannot be read", "bad-file") from None
    if size > UPLOAD_CAP:
        raise SourceError("the Excel file is larger than 10 MB", "too-large")
    unzipped = templates._unzipped_size(path)
    if unzipped <= 0:
        raise SourceError("the file is not an Excel workbook", "bad-file")
    if unzipped > templates.FULL_LOAD_CAP:
        raise SourceError("the Excel file is larger than 5 MB unzipped", "too-large")


def read_case_rows(path: Path, layout: dict, sheet: str | None = None) -> list[dict]:
    """Test case rows of a workbook laid out as a registered template: no, item, steps, expected, trace.

    Read only and streamed; rows with no item are skipped; at most 2000 rows are read.
    """
    from . import templates  # noqa: PLC0415

    check_workbook_file(path)
    try:
        wb = templates._openpyxl().load_workbook(path, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - any parse failure of an uploaded file is the same refusal
        raise SourceError("the file is not an Excel workbook", "bad-file") from None
    try:
        name = sheet or layout.get("sheet")
        if name not in wb.sheetnames:
            raise SourceError("the template's sheet is not in the file; name the sheet to read", "bad-sheet")
        if not hasattr(wb[name], "iter_rows"):
            raise SourceError("the named sheet holds a chart, not cells; name the sheet to read", "bad-sheet")
        cols = {role: templates._col_index(letter) - 1 for role, letter in (layout.get("columns") or {}).items()}
        if "item" not in cols:
            raise SourceError("the template maps no item column", "bad-template")
        header_row = int(layout.get("header_row") or 1)
        out = []
        for number, values in enumerate(wb[name].iter_rows(min_row=header_row + 1, values_only=True),
                                        start=header_row + 1):
            def cell(role: str) -> str:
                index = cols.get(role)
                if index is None or index >= len(values) or values[index] is None:
                    return ""
                return str(values[index]).replace("\r", "").strip()
            item = cell("item")
            if not item:
                continue
            if len(out) >= EXCEL_MAX_ROWS:
                raise SourceError(f"the sheet has more than {EXCEL_MAX_ROWS} test cases", "too-large")
            no = cell("no") or str(number)
            out.append({"no": no[:SOURCE_VALUE_CAP], "row": number, "content": item, "steps": cell("steps"),
                        "expected": cell("expected"),
                        "trace": list(dict.fromkeys(TRACE_ID_RE.findall(cell("trace"))))})
        return out
    except (KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, SourceError):
            raise
        raise SourceError("the Excel file cannot be read with this template", "bad-file") from None
    finally:
        wb.close()


def _excel_extract(source: dict, env: Env, folder: Path) -> list[dict]:
    from . import templates  # noqa: PLC0415

    try:
        entry = templates.resolve(source.get("template"), env.home)
    except templates.TemplateError:
        raise SourceError("template is not registered", "unknown-template") from None
    rows = read_case_rows(folder / "source" / str(source["file"]), entry, source.get("sheet"))
    if not rows:
        raise SourceError("no test case rows were found under the template's header row", "no-cases")
    return [{"source": {"no": r["no"]}, "trace": r["trace"], "content": r["content"], "steps": r["steps"],
             "expected": r["expected"]} for r in rows]


# manual ---------------------------------------------------------------------------------------
def _check_manual(payload: dict, _env: Env) -> dict:
    note = payload.get("note")
    out = {"kind": "manual"}
    if note not in (None, ""):
        out["note"] = _value(note, "note")
    return out


# the registry ---------------------------------------------------------------------------------
REGISTRY: dict[str, Source] = {}


def register(source: Source) -> None:
    if source.mode not in ("extract", "generate", "none"):
        raise ValueError(f"unknown mode {source.mode}")
    REGISTRY[source.kind] = source


register(Source("figma", "extract", True, "Figma node", _check_figma,
                lambda s: ("figma", str(s.get("file") or ""), str(s.get("node") or "")),
                trace_value=lambda c: str(c.get("target_node") or "")))
register(Source("backlog", "generate", True, "Trace", _check_backlog,
                lambda s: ("backlog", str(s.get("ticket") or ""), str(s.get("report") or "")),
                rows=_backlog_rows, trace_value=lambda c: str(c.get("trace") or "")))
register(Source("excel", "extract", False, "Row", _check_excel,
                lambda s: ("excel", str(s.get("file") or ""), str(s.get("template") or "")),
                trace_value=lambda c: str(c.get("no") or ""), extract=_excel_extract))
register(Source("manual", "none", False, None, _check_manual, lambda _s: ("manual",)))


def kinds() -> tuple[str, ...]:
    return tuple(REGISTRY)


def get(kind: Any) -> Source:
    entry = REGISTRY.get(kind) if isinstance(kind, str) else None
    if entry is None:
        raise SourceError(f"source kind must be one of {', '.join(REGISTRY)}", "unknown-kind")
    return entry


def check(kind: Any, payload: Any, env: Env) -> dict:
    if not isinstance(payload, dict):
        raise SourceError("the source input must be an object")
    source = get(kind).check(payload, env)
    for key, value in source.items():
        if not re.fullmatch(r"[a-z_]{1,30}", key) or not isinstance(value, (str, int)) \
                or (isinstance(value, str) and len(value) > SOURCE_VALUE_CAP):
            raise SourceError(f"source.{key} is not short text or a number")
    return source


def ref(source: Any) -> tuple:
    """The identity of a source; an unknown kind compares on kind, file and node."""
    source = source if isinstance(source, dict) else {}
    entry = REGISTRY.get(source.get("kind"))
    if entry is None:
        return tuple(str(source.get(k) or "") for k in ("kind", "file", "node"))
    return entry.ref(source)


def listing() -> list[dict]:
    """What the wizard shows: kind, mode and whether the agent writes the cases."""
    return [{"kind": s.kind, "mode": s.mode, "needs_agent": s.needs_agent, "trace_label": s.trace_label}
            for s in REGISTRY.values()]
