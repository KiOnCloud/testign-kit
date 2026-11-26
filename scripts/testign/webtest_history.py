"""Results of a suite's cases across the runs made from it, and the Fixed mark.

Runs copy a suite, so the same case appears as the same row (``c3`` → ``r03``) in every run made
from it. A row's result is comparable with an earlier run's only when the case is unchanged (same
content, kind, steps and expected) and both runs are on the same project: the same suite run on
another project's hosts tests another site.

* ``verdict(case)``: ``pass`` or ``fail`` for a row with a result (the agent's or the tester's own),
  else None. Manual, not-applicable and not-run rows have no verdict.
* ``previous(root, run)``: per row, the newest earlier run of the same suite and project where the
  unchanged row has a verdict, and that verdict.
* A row is **Fixed** when that previous verdict is ``fail`` and the row passes now.
* ``suite_results(root, suite_id)``: a case-by-run matrix for the suite's Runs tab.

Read only: nothing here writes a run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import webtest
from .webtest import DIGEST_KEYS, WebtestError

MATRIX_RUNS = 8


def verdict(case: dict) -> str | None:
    if case.get("state") == "pass":
        return "pass"
    if case.get("state") == "fail":
        return "fail"
    if case.get("state") == "self-run":
        value = (case.get("result") or {}).get("verdict")
        return value if value in ("pass", "fail") else None
    return None


def case_digest(case: dict) -> str:
    items = [case.get(k) or "" for k in DIGEST_KEYS]
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _suite_runs(root: Path, suite_id: str) -> list[dict]:
    """Runs made from the suite, oldest first (run ids start with their creation minute)."""
    out = []
    for run_id, folder in sorted(webtest.list_runs(root).items()):
        try:
            run = webtest.load(folder)
        except WebtestError:
            continue
        if (run.get("suite") or {}).get("id") == suite_id:
            out.append(run)
    return out


def _order(run: dict) -> tuple:
    return (str(run.get("created_at") or ""), run["id"])


def previous(root: Path, run: dict) -> dict[str, dict]:
    """{row: {run, name, verdict}} from the newest earlier run of the same suite and project."""
    suite_id = (run.get("suite") or {}).get("id")
    if not suite_id:
        return {}
    earlier = [r for r in _suite_runs(root, suite_id)
               if r["id"] != run["id"] and r.get("project") == run.get("project") and _order(r) < _order(run)]
    earlier.sort(key=_order, reverse=True)
    out: dict[str, dict] = {}
    for case in run["cases"]:
        digest = case_digest(case)
        for other in earlier:
            match = next((c for c in other["cases"] if c["row"] == case["row"]), None)
            if match is None or case_digest(match) != digest:
                continue
            got = verdict(match)
            if got is None:
                continue
            out[case["row"]] = {"run": other["id"], "name": other.get("name") or other["id"], "verdict": got}
            break
    return out


def fixed(case: dict, prev: dict | None) -> bool:
    return bool(prev) and prev.get("verdict") == "fail" and verdict(case) == "pass"


def run_marks(root: Path, run: dict) -> dict[str, dict]:
    """{row: {"previous": {...}, "fixed": bool}} for the rows that have an earlier verdict."""
    prev = previous(root, run)
    by_row = {c["row"]: c for c in run["cases"]}
    return {row: {"previous": p, "fixed": fixed(by_row[row], p)} for row, p in prev.items()}


def suite_results(root: Path, suite_id: Any, cases: list[dict]) -> dict:
    """The newest runs of a suite (at most ``MATRIX_RUNS``) and each suite case's verdict in them.

    ``cases`` are the suite's cases (``case`` ids such as ``c3``). A cell is ``pass``, ``fail``, a
    row state without a verdict (``manual``, ``not-run`` …), or missing when the run has no such row.
    ``changed`` marks a cell whose run held another version of the case than the suite has now;
    ``fixed`` marks a pass after a fail of the unchanged case in the previous run of the same project.
    """
    runs = _suite_runs(root, str(suite_id))[-MATRIX_RUNS:]
    marks = {r["id"]: run_marks(root, r) for r in runs}
    rows = []
    for item in cases:
        row = f"r{int(str(item['case'])[1:]):02d}"
        digest = case_digest(item)
        cells = {}
        for r in runs:
            case = next((c for c in r["cases"] if c["row"] == row), None)
            if case is None:
                continue
            cells[r["id"]] = {"verdict": verdict(case) or case.get("state"),
                              "fixed": bool(marks[r["id"]].get(row, {}).get("fixed")),
                              "changed": case_digest(case) != digest}
        rows.append({"case": item["case"], "row": row, "content": item.get("content") or "", "cells": cells})
    return {"runs": [{"id": r["id"], "name": r.get("name"), "created_at": r.get("created_at"),
                      "project": r.get("project"), "base_url": r.get("base_url")} for r in reversed(runs)],
            "cases": rows}
