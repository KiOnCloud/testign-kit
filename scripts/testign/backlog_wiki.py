"""Minimal Backlog REST client for the decisions log wiki page (stdlib only).

Uses the same ``BACKLOG_DOMAIN`` and ``BACKLOG_API_KEY`` environment variables as the Backlog MCP
server. The API key is sent as the ``apiKey`` query parameter, as the Backlog API requires, and is
removed from every error message. Writes replace the whole page, so ``update`` re-reads the page and
refuses to write when it changed since the tester saw the diff.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30


class BacklogError(Exception):
    """A Backlog API call failed. The message never contains the API key."""


class ConflictError(BacklogError):
    """The page changed between the read the tester approved and the write."""


def _settings() -> tuple[str, str]:
    domain = os.environ.get("BACKLOG_DOMAIN", "").strip()
    key = os.environ.get("BACKLOG_API_KEY", "").strip()
    if not domain or not key:
        raise BacklogError(
            "BACKLOG_DOMAIN and BACKLOG_API_KEY are not set in this shell. Set them as environment "
            "variables (the same values as the Backlog MCP server) or paste the decisions by hand."
        )
    base = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    host = urllib.parse.urlsplit(base).hostname or ""
    if base.startswith("http://") and host not in ("127.0.0.1", "localhost", "::1"):
        raise BacklogError("BACKLOG_DOMAIN must use https; the API key would be sent in clear text")
    return base.rstrip("/"), key


def _redact(text: str, key: str) -> str:
    if not key:
        return text
    for form in {key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key)}:
        text = text.replace(form, "[redacted]")
    return text


def wiki_id_of(value: int | str) -> str:
    """A wiki page ID is a positive integer; anything else is refused before it reaches a URL."""
    text = str(value).strip()
    if not re.fullmatch(r"\d+", text):
        raise BacklogError(f"wiki page ID must be a number, got {str(value)[:40]!r}")
    return text


def _call(method: str, path: str, query: dict | None = None, form: dict | None = None) -> object:
    base, key = _settings()
    params = {**(query or {}), "apiKey": key}
    url = f"{base}/api/v2{path}?{urllib.parse.urlencode(params)}"
    data = urllib.parse.urlencode(form).encode("utf-8") if form is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = "; ".join(e.get("message", "") for e in json.loads(body).get("errors", []))
        except (ValueError, AttributeError):
            detail = body[:200]
        raise BacklogError(_redact(f"Backlog API {method} {path} returned {exc.code}: {detail}", key)) from None
    except urllib.error.URLError as exc:
        raise BacklogError(_redact(f"cannot reach Backlog at {base}: {exc.reason}", key)) from None
    except Exception as exc:  # noqa: BLE001 - anything else may carry the URL, and with it the key
        raise BacklogError(_redact(f"Backlog API {method} {path} failed: {type(exc).__name__}: {exc}", key)) from None


def get(wiki_id: int | str) -> dict:
    page = _call("GET", f"/wikis/{wiki_id_of(wiki_id)}")
    return {"id": page["id"], "name": page["name"], "content": page.get("content") or "", "updated": page.get("updated")}


def list_pages(project_key: str, prefix: str = "") -> dict[str, dict]:
    """Wiki pages of a project whose name starts with ``prefix``: name -> {id, updated}. Metadata only."""
    pages = _call("GET", "/wikis", {"projectIdOrKey": project_key, **({"keyword": prefix} if prefix else {})})
    return {
        p["name"]: {"id": p["id"], "updated": p.get("updated")}
        for p in pages
        if str(p.get("name", "")).startswith(prefix)
    }


def find(project_key: str, name: str) -> int:
    """Wiki page ID by exact page name within a project."""
    page = list_pages(project_key, name).get(name)
    if not page:
        raise BacklogError(f"wiki page '{name}' not found in project {project_key}")
    return page["id"]


def create(project_key: str, name: str, content: str, mail_notify: bool = False) -> dict:
    """Create a page, refusing when a page with that name appeared since the tester saw the diff."""
    if name in list_pages(project_key, name):
        raise ConflictError(f"wiki page '{name}' was created by someone else meanwhile; show the tester a new diff")
    project = _call("GET", f"/projects/{urllib.parse.quote(project_key, safe='')}")
    page = _call("POST", "/wikis", form={"projectId": str(project["id"]), "name": name, "content": content,
                                         "mailNotify": str(mail_notify).lower()})
    if _normalize(page.get("content") or "") != _normalize(content):
        raise BacklogError(f"Backlog saved different content than was sent to '{name}'; check the page by hand.")
    return {"id": page["id"], "name": page["name"], "updated": page.get("updated")}


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


def update(wiki_id: int | str, content: str, expected_updated: str, expected_content: str | None = None,
           mail_notify: bool = False) -> dict:
    """Replace the page content, but only if the page still matches what the tester approved."""
    current = get(wiki_id)
    if current["updated"] != expected_updated or (
        expected_content is not None and _normalize(current["content"]) != _normalize(expected_content)
    ):
        raise ConflictError(
            f"the wiki page changed since it was read (updated {expected_updated} → {current['updated']}). "
            "Read it again and show the tester a new diff."
        )
    page = _call("PATCH", f"/wikis/{wiki_id_of(wiki_id)}", form={"content": content, "mailNotify": str(mail_notify).lower()})
    if _normalize(page.get("content") or "") != _normalize(content):
        raise BacklogError("Backlog saved different content than was sent; check the page by hand.")
    return {"id": page["id"], "name": page["name"], "updated": page.get("updated")}
