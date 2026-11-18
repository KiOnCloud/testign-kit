"""Read-only projections for the console: tickets, report revisions, hash checks, trace, cache, config.

Every path segment a request names (ticket, revision, workbook, template, cache entry) is looked up
in a listing built from the file system at request time; none is joined into a path. Nothing here
writes: config is read with ``create=False`` and reports are only read.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any

from .. import cache, config, decisions, gitscope, hashcheck, report, templates, trace
from .server import ApiError, ConsoleState, Request

HASH_TTL = 60.0
HASH_SLOTS = threading.BoundedSemaphore(2)
WORKBOOK_SUFFIXES = (".xlsx", ".xlsm")
_REV_RE = re.compile(r"^(?P<ticket>.+)-survey-r(?P<n>\d+)\.md$")
_SEVERITY = (("blocking", ("🔴", "blocking")), ("major", ("🟠", "major")), ("minor", ("🟡", "minor")))


# config ---------------------------------------------------------------------------------------
def load_config(state: ConsoleState) -> dict:
    try:
        return config.load(state.home, create=False)
    except config.ConfigError:
        raise ApiError(500, "config-invalid", "config.json cannot be read") from None


def config_view(cfg: dict) -> dict:
    backlog = cfg.get("backlog") if isinstance(cfg.get("backlog"), dict) else {}
    return {
        "output_dir": cfg.get("output_dir"),
        "lang": cfg.get("lang"),
        "master_ref": cfg.get("master_ref"),
        "develop_ref": cfg.get("develop_ref"),
        "backlog": {
            "space": backlog.get("space"),
            "project_key": backlog.get("project_key"),
            "decisions_log_prefix": backlog.get("decisions_log_prefix"),
        },
    }


def ticket_rx(cfg: dict) -> re.Pattern:
    return re.compile(decisions.ticket_pattern(str(cfg.get("ticket_id_regex") or config.DEFAULT_TICKET_ID_REGEX)))


# listings -------------------------------------------------------------------------------------
def ticket_folders(cfg: dict) -> dict[str, Path]:
    """Folders under ``output_dir`` whose whole name matches the ticket regex."""
    root = Path(str(cfg.get("output_dir") or "")).expanduser()
    rx = ticket_rx(cfg)
    found: dict[str, Path] = {}
    try:
        children = list(root.iterdir())
    except OSError:
        return found
    for child in children:
        try:
            if child.is_dir() and rx.fullmatch(child.name):
                found[child.name] = child
        except OSError:
            continue
    return found


def revision_files(folder: Path, ticket: str) -> list[dict]:
    """Revision files of a ticket, numbered, each with its consistency state.

    ``ok``: frontmatter ``ticket`` is the folder name and ``revision`` the number in the file name.
    ``inconsistent``: readable but naming another ticket or number. ``unreadable``: cannot be parsed.
    """
    out = []
    try:
        names = [p for p in folder.iterdir() if p.is_file()]
    except OSError:
        return out
    for path in names:
        m = _REV_RE.match(path.name)
        if not m or m.group("ticket") != ticket:
            continue
        n = int(m.group("n"))
        entry: dict[str, Any] = {"name": path.name, "revision": n, "path": path, "generated_at": None}
        try:
            meta, _ = report.load(path)
        except (OSError, UnicodeDecodeError, report.ReportError):
            entry["state"] = "unreadable"
        else:
            entry["generated_at"] = meta.get("generated_at")
            entry["state"] = "ok" if meta.get("ticket") == ticket and meta.get("revision") == n else "inconsistent"
        out.append(entry)
    return sorted(out, key=lambda e: e["revision"])


def latest_of(revisions: list[dict]) -> dict | None:
    """The highest revision that is consistent or unreadable; inconsistent files never count."""
    candidates = [r for r in revisions if r["state"] != "inconsistent"]
    return candidates[-1] if candidates else None


def workbooks(folder: Path) -> dict[str, Path]:
    found = {}
    try:
        for path in folder.iterdir():
            if path.is_file() and path.suffix.lower() in WORKBOOK_SUFFIXES and not path.name.startswith("~$"):
                found[path.name] = path
    except OSError:
        pass
    return found


def _ticket(cfg: dict, ticket: str) -> tuple[Path, list[dict]]:
    folders = ticket_folders(cfg)
    if ticket not in folders:
        raise ApiError(404, "not-found", "no such ticket")
    revisions = revision_files(folders[ticket], ticket)
    if not revisions:
        raise ApiError(404, "not-found", "no such ticket")
    return folders[ticket], revisions


def _latest_ok(revisions: list[dict]) -> dict:
    latest = latest_of(revisions)
    if latest is None:
        raise ApiError(409, "inconsistent", "no consistent revision")
    if latest["state"] == "unreadable":
        raise ApiError(422, "unreadable", "the latest revision cannot be read")
    return latest


# report projections ---------------------------------------------------------------------------
def _severity(level: str) -> str | None:
    text = level.lower()
    for name, marks in _SEVERITY:
        if any(mark in text for mark in marks):
            return name
    return None


def finding_counts(body: str) -> dict:
    questions = report.question_rows(body)
    severity = {"blocking": 0, "major": 0, "minor": 0}
    block = {"block": 0, "partial": 0, "no": 0}
    for q in questions:
        level = _severity(q["level"])
        if level:
            severity[level] += 1
        blocks = q["blocks"].strip().lower()
        if blocks in block:
            block[blocks] += 1
    return {"questions": len(questions), "block_count": block["block"], "severity": severity, "blocks": block}


def coverage(body: str) -> dict | None:
    """Section 7 summary when it was filled by ``trace --write-revision``; None while it is a placeholder."""
    text = report.section(body, 7)
    total = None
    rows_with_case = rows_total = None
    for cells in report.table_rows(text):
        if len(cells) < 2:
            continue
        value = cells[1].strip()
        if total is None and re.fullmatch(r"\d+", value):
            total = int(value)
        m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", value)
        if m and rows_total is None:
            rows_with_case, rows_total = int(m.group(1)), int(m.group(2))
    if total is None:
        return None
    gaps: list[str] = []
    orphans_line = waiting_line = ""
    for line in text.splitlines():
        if "**Gaps**" in line:
            gaps = re.findall(r"\b[BR]\d+\b", line.split(":", 1)[-1])
        elif "**Orphans**" in line:
            orphans_line = line.split(":", 1)[-1].strip()
        elif "**Chờ QA**" in line or "**Waiting**" in line:
            waiting_line = line.split(":", 1)[-1].strip()
    source = re.search(r"`([^`]+\.xls[xm])`", text)
    return {
        "total_cases": total,
        "rows_with_case": rows_with_case,
        "rows_total": rows_total,
        "gaps": gaps,
        "orphans": orphans_line,
        "waiting": waiting_line,
        "workbook": source.group(1) if source else None,
    }


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _tables(text: str) -> list[dict]:
    tables, current = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            current = None
            continue
        cells = [c.strip().replace("\\|", "|") for c in report._PIPE.split(stripped.strip("|"))]
        if current is None:
            current = {"header": cells, "rows": []}
            tables.append(current)
        elif all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        else:
            current["rows"].append(cells)
    return tables


def _sections(body: str) -> list[dict]:
    out = []
    for m in re.finditer(r"^## (\d+)\.\s*([^\n]*)\n(.*?)(?=^## |\Z)", body, flags=re.S | re.M):
        text = _strip_comments(m.group(3))
        lines = [line.rstrip() for line in text.splitlines()]
        while lines and not lines[-1].strip() or lines and lines[-1].strip() == "---":
            lines.pop()
        while lines and not lines[0].strip():
            lines.pop(0)
        out.append({"number": int(m.group(1)), "heading": m.group(2).strip(), "lines": lines, "tables": _tables(text)})
    return out


def _findings(body: str) -> dict[str, dict]:
    out = {}
    for qid, block in report._q_blocks(body).items():
        lines = _strip_comments(block).splitlines()
        heading = lines[0].lstrip("#").strip() if lines else qid
        rest = [line.rstrip() for line in lines[1:]]
        while rest and (not rest[-1].strip() or rest[-1].strip() == "---"):
            rest.pop()
        out[qid] = {"heading": heading, "lines": rest}
    return out


def _behaviors(body: str) -> list[dict]:
    keys = ("id", "behavior", "production", "develop", "spec", "deviation")
    flags = {r["id"]: r["needs_case"] for r in report.behavior_rows(body)}
    rows = []
    for cells in report.table_rows(report.section(body, 3)):
        if cells and re.fullmatch(r"B\d+", cells[0]):
            row = {k: (cells[i] if i < len(cells) else "") for i, k in enumerate(keys)}
            row["needs_case"] = flags.get(cells[0], False)
            rows.append(row)
    return rows


def _regressions(body: str) -> list[dict]:
    keys = ("id", "area", "reason", "level", "source")
    return [
        {k: (cells[i] if i < len(cells) else "") for i, k in enumerate(keys)}
        for cells in report.table_rows(report.section(body, 5))
        if cells and re.fullmatch(r"R\d+", cells[0])
    ]


def revision_view(path: Path) -> dict:
    meta, body = report.load(path)
    return {
        "name": path.name,
        "frontmatter": {k: v for k, v in meta.items()},
        "title": report.title(body),
        "conclusion": report.conclusion(body),
        "counts": finding_counts(body),
        "sections": _sections(body),
        "questions": report.question_rows(body),
        "behaviors": _behaviors(body),
        "regressions": _regressions(body),
        "findings": _findings(body),
        "coverage": coverage(body),
    }


def ticket_summary(ticket: str, folder: Path) -> dict | None:
    revisions = revision_files(folder, ticket)
    if not revisions:
        return None
    inconsistent = [r["name"] for r in revisions if r["state"] == "inconsistent"]
    books = sorted(
        ({"name": n, "mtime": _mtime(p)} for n, p in workbooks(folder).items()),
        key=lambda b: b["mtime"] or 0,
        reverse=True,
    )
    out: dict[str, Any] = {"id": ticket, "workbooks": books, "inconsistent": inconsistent,
                           "revisions": len(revisions)}
    latest = latest_of(revisions)
    if latest is None:
        out["error"] = "inconsistent"
        return out
    out.update({"latest": latest["name"], "revision": latest["revision"]})
    if latest["state"] == "unreadable":
        out["error"] = "unreadable"
        return out
    try:
        meta, body = report.load(latest["path"])
        counts = finding_counts(body)
        out.update({
            "title": report.title(body),
            "lang": meta.get("lang"),
            "generated_at": meta.get("generated_at"),
            "conclusion": report.conclusion(body),
            "severity": counts["severity"],
            "blocks": counts["blocks"],
            "questions": counts["questions"],
            "block_count": counts["block_count"],
            "coverage": coverage(body),
        })
    except Exception:  # noqa: BLE001 - one bad file never fails the listing
        out["error"] = "unreadable"
    return out


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


# hash checks ----------------------------------------------------------------------------------
class HashCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, dict]] = {}

    def get(self, key: str) -> dict | None:
        with self._lock:
            item = self._items.get(key)
            if item and time.monotonic() - item[0] < HASH_TTL:
                return item[1]
            return None

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._items[key] = (time.monotonic(), value)


def usable_repo(repo: Any) -> Path | None:
    """An absolute existing folder inside a git work tree (worktrees and submodules included)."""
    if not isinstance(repo, str) or not repo.strip():
        return None
    path = Path(repo)
    if not path.is_absolute() or not path.is_dir():
        return None
    try:
        gitscope._git(str(path), "rev-parse", "--git-dir")
    except gitscope.GitError:
        return None
    return path


def hash_status(path: Path, cache_: HashCache) -> dict:
    key = f"{path}|{_mtime(path)}"
    cached = cache_.get(key)
    if cached is not None:
        return cached
    if not HASH_SLOTS.acquire(timeout=30):
        return {"status": "unknown", "reason": "busy"}
    try:
        try:
            meta, _ = report.load(path)
        except (OSError, UnicodeDecodeError, report.ReportError):
            result = {"status": "unknown", "reason": "report-unreadable"}
        else:
            repo = usable_repo(meta.get("repo"))
            if repo is None:
                result = {"status": "unknown", "reason": "repo-not-found"}
            else:
                try:
                    result = hashcheck.check(str(path), str(repo))
                except report.ReportError:
                    result = {"status": "unknown", "reason": "report-incomplete"}
                except gitscope.GitError:
                    result = {"status": "unknown", "reason": "git-error"}
                except Exception:  # noqa: BLE001
                    result = {"status": "unknown", "reason": "error"}
        result.pop("report", None)
        cache_.put(key, result)
        return result
    finally:
        HASH_SLOTS.release()


# trace ----------------------------------------------------------------------------------------
def trace_view(cfg: dict, ticket: str, workbook: str | None, template_name: str | None, home: Path | None) -> dict:
    folder, revisions = _ticket(cfg, ticket)
    latest = _latest_ok(revisions)
    books = workbooks(folder)
    if not workbook or workbook not in books:
        raise ApiError(404, "not-found", "no such workbook")
    listing = templates.list_templates(home)
    if not listing["templates"]:
        return {"state": "no-template"}
    names = {t["name"] for t in listing["templates"]}
    name = template_name or listing["default"]
    if name not in names:
        raise ApiError(404, "not-found", "no such template")
    entry = templates.resolve(name, home)
    found = trace.trace_for(latest["path"], books[workbook], entry)
    sheet = found["sheet"]
    template_headers = templates.headers_at(Path(entry["path"]), entry["sheet"], entry["header_row"])
    workbook_headers = templates.headers_at(books[workbook], sheet, entry["header_row"])
    return {
        "state": "ok",
        "report": latest["name"],
        "workbook": workbook,
        "template": name,
        "sheet": sheet,
        "header_match": template_headers == workbook_headers,
        "template_headers": template_headers,
        "workbook_headers": workbook_headers,
        **found["summary"],
        "cases": [
            {"row": c["row"], "no": c["id"], "item": c["item"], "trace": c["trace"], "questions": c["questions"]}
            for c in found["cases"]
        ],
    }


# scout cache ----------------------------------------------------------------------------------
def cache_view(home: Path | None) -> dict:
    root = config.config_dir(home) / "cache"
    entries = []
    try:
        roots = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        roots = []
    for commit_dir in roots:
        try:
            features = sorted(p for p in commit_dir.iterdir() if p.is_dir())
        except OSError:
            continue
        for folder in features:
            manifest, problem = cache.load(folder)
            if manifest is None:
                entries.append({"root_commit": commit_dir.name, "feature": folder.name, "error": problem})
                continue
            entries.append({
                "root_commit": manifest.get("root_commit") or commit_dir.name,
                "feature": manifest.get("feature") or folder.name,
                "merge_base": manifest.get("merge_base"),
                "files": len(manifest.get("files", {})),
                "rows": sorted(manifest.get("rows", {})),
                "anchors": manifest.get("anchors", []),
                "unread": manifest.get("unread", []),
                "scout_model": manifest.get("scout_model"),
                "plugin_version": manifest.get("plugin_version"),
                "saved_at": manifest.get("created_at"),
                "reviewed_by": manifest.get("reviewed_by"),
            })
    return {"entries": entries}


# routes ---------------------------------------------------------------------------------------
def install(state: ConsoleState) -> None:
    hashes = HashCache()

    def get_config(req: Request) -> dict:
        return config_view(load_config(req.state))

    def get_tickets(req: Request) -> dict:
        cfg = load_config(req.state)
        tickets = []
        for name, folder in sorted(ticket_folders(cfg).items()):
            summary = ticket_summary(name, folder)
            if summary is not None:
                tickets.append(summary)
        return {"tickets": tickets, "output_dir": cfg.get("output_dir")}

    def get_ticket(req: Request) -> dict:
        cfg = load_config(req.state)
        ticket = req.params["ticket"]
        folder, revisions = _ticket(cfg, ticket)
        latest = latest_of(revisions)
        view = None
        error = None
        if latest is None:
            error = "inconsistent"
        elif latest["state"] == "unreadable":
            error = "unreadable"
        else:
            try:
                view = revision_view(latest["path"])
            except Exception:  # noqa: BLE001
                error = "unreadable"
        return {
            "id": ticket,
            "revisions": [{k: r[k] for k in ("name", "revision", "generated_at", "state")} for r in revisions],
            "latest": view,
            "workbooks": sorted(workbooks(folder)),
            **({"error": error} if error else {}),
        }

    def get_revision(req: Request) -> dict:
        cfg = load_config(req.state)
        _, revisions = _ticket(cfg, req.params["ticket"])
        match = next((r for r in revisions if r["name"] == req.params["rev"]), None)
        if match is None:
            raise ApiError(404, "not-found", "no such revision")
        if match["state"] == "unreadable":
            raise ApiError(422, "unreadable", "this revision cannot be read")
        try:
            view = revision_view(match["path"])
        except Exception:  # noqa: BLE001
            raise ApiError(422, "unreadable", "this revision cannot be read") from None
        return {**view, "state": match["state"]}

    def get_hash(req: Request) -> dict:
        cfg = load_config(req.state)
        _, revisions = _ticket(cfg, req.params["ticket"])
        latest = _latest_ok(revisions)
        return {"revision": latest["name"], **hash_status(latest["path"], hashes)}

    def get_trace(req: Request) -> dict:
        cfg = load_config(req.state)
        try:
            return trace_view(cfg, req.params["ticket"], req.arg("workbook"), req.arg("template"), req.state.home)
        except templates.TemplateError:
            raise ApiError(400, "template-error", "the workbook does not fit the template") from None
        except report.ReportError:
            raise ApiError(422, "unreadable", "the latest revision cannot be read") from None
        except ApiError:
            raise
        except Exception:  # noqa: BLE001 - openpyxl and zipfile raise many types for a broken file
            raise ApiError(400, "workbook-unreadable", "the workbook cannot be read") from None

    def get_cache(req: Request) -> dict:
        return cache_view(req.state.home)

    r = state.router
    r.add("GET", "/api/config", "browser", get_config)
    r.add("GET", "/api/tickets", "browser", get_tickets)
    r.add("GET", "/api/tickets/:ticket", "browser", get_ticket)
    r.add("GET", "/api/tickets/:ticket/revisions/:rev", "browser", get_revision)
    r.add("GET", "/api/tickets/:ticket/hash", "browser", get_hash)
    r.add("GET", "/api/tickets/:ticket/trace", "browser", get_trace)
    r.add("GET", "/api/cache", "browser", get_cache)
