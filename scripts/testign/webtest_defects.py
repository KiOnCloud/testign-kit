"""Defect drafts for the failed rows of a web test run.

Every row that failed (the agent's ``fail`` or the tester's own ``self-run`` fail) has a defect. Until
the tester saves it, it is a draft built from the row: title from the case content, steps, expected,
the actual result, the page URL and the evidence files. The tester edits it and then marks it

* ``sent`` with the tracker key it was filed under (testign posts nothing anywhere: the tester files it
  in Backlog or any tracker by hand and records the key here), or
* ``not-a-defect`` with the reason (the case or its expected result is wrong, the data was not set up …).

Saved defects live next to the tester's answers, in ``~/.testign-kit/webtest/runs/<run-id>/defects.json``
(owner-only), written only by the console server::

    {"<row>": {"status", "title", "steps", "expected", "actual", "url", "evidence", "tracker", "reason",
               "attempt", "at", "by"}}

A saved defect stays when the row later passes (a re-run of the row); ``stale`` says the row's current
result is no longer the failure it was written for.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import config, fsutil
from .webtest_history import verdict

STATUSES = ("draft", "sent", "not-a-defect")
FIELDS = {"title": 200, "steps": 4000, "expected": 4000, "actual": 4000, "tracker": 100, "reason": 2000}
FILE = "defects.json"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DefectError(ValueError):
    """The defect cannot be saved; the message is one line for the tester."""


def failed(case: dict) -> bool:
    return verdict(case) == "fail"


def draft_of(case: dict) -> dict:
    """A draft built from the row; nothing is stored until the tester saves it."""
    result = case.get("result") or {}
    title = " ".join(str(case.get("content") or case["row"]).split())[:FIELDS["title"]]
    return {"status": "draft", "title": title, "steps": case.get("steps") or "", "expected": case.get("expected") or "",
            "actual": result.get("actual") or "", "url": result.get("url") or "",
            "evidence": list(result.get("evidence") or []), "tracker": "", "reason": "",
            "attempt": int(case.get("attempt") or 0), "saved": False}


def store_folder(home: Path | None, run_id: str) -> Path | None:
    """``~/.testign-kit/webtest/runs/<run-id>`` found by listing (None when the console saved nothing)."""
    root = config.config_dir(home) / "webtest" / "runs"
    try:
        return next((p for p in root.iterdir() if p.is_dir() and p.name == run_id), None)
    except OSError:
        return None


def read(folder: Path | None) -> dict:
    if folder is None:
        return {}
    try:
        data = json.loads((folder / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def write(folder: Path, data: dict) -> None:
    fsutil.atomic_write_bytes(folder / FILE, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                              mode=0o600)


def for_run(run: dict, saved: dict) -> dict[str, dict]:
    """{row: defect} for every failed row and every row with a saved defect."""
    out: dict[str, dict] = {}
    for case in run["cases"]:
        row = case["row"]
        if row in saved:
            entry = {**saved[row], "saved": True}
            entry["stale"] = not failed(case) or int(case.get("attempt") or 0) != int(entry.get("attempt") or 0)
            out[row] = entry
        elif failed(case):
            out[row] = draft_of(case)
    return out


def _text(body: dict, key: str) -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DefectError(f"{key} must be text")
    value = _CONTROL.sub("", value).strip()
    if len(value) > FIELDS[key]:
        raise DefectError(f"{key} must be at most {FIELDS[key]} characters")
    return value


def check(body: Any) -> dict:
    """The tester's edit: status and fields, with what each status needs."""
    if not isinstance(body, dict):
        raise DefectError("the defect must be an object")
    status = body.get("status")
    if status not in STATUSES:
        raise DefectError("status must be draft, sent or not-a-defect")
    clean = {"status": status, **{k: _text(body, k) for k in FIELDS}}
    if not clean["title"]:
        raise DefectError("a defect needs a title")
    if status == "sent" and not clean["tracker"]:
        raise DefectError("a sent defect needs the tracker key it was filed under")
    if status == "not-a-defect" and not clean["reason"]:
        raise DefectError("not a defect needs the reason")
    if status != "sent":
        clean["tracker"] = clean["tracker"] if status == "draft" else ""
    if status != "not-a-defect":
        clean["reason"] = ""
    return clean


def save(folder: Path, run: dict, row: Any, body: Any, *, at: str, by: str | None) -> dict:
    case = next((c for c in run["cases"] if c["row"] == row), None)
    if case is None:
        raise DefectError("no such row")
    data = read(folder)
    if row not in data and not failed(case):
        raise DefectError("only a failed row gets a defect")
    clean = check(body)
    base = data.get(row) or draft_of(case)
    entry = {**{k: base.get(k) for k in ("url", "evidence", "attempt")}, **clean, "at": at, "by": by}
    if row not in data or clean["status"] == "draft":
        # A draft follows the row's latest failure: its page URL, evidence and attempt.
        fresh = draft_of(case) if failed(case) else base
        entry.update({"url": fresh.get("url") or "", "evidence": list(fresh.get("evidence") or []),
                      "attempt": int(fresh.get("attempt") or 0)})
    data[row] = entry
    write(folder, data)
    return {**entry, "saved": True, "stale": not failed(case) or int(case.get("attempt") or 0) != entry["attempt"]}


def counts(defects: dict[str, dict]) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for d in defects.values():
        out[d.get("status") if d.get("status") in STATUSES else "draft"] += 1
    return out
