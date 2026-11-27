"""A suite's spec: the Playwright steps of each eligible case, recorded once and replayed by later runs.

The spec lives next to the suite, ``<suite folder>/spec.json``::

    {"testign_spec": 1, "suite": "<suite id>", "project": "<project>",
     "cases": {"c3": {"digest": "<case digest>", "scenario": "member", "steps": [...]}},
     "saved_at", "by", "check": {...} | null, "reviewed": {...} | null}

Only a case the agent may run without touching data goes in a spec: ``class: sure``, ``runner:
agent``, ``viewport: pc`` and kind ``label``, ``element`` or ``behaviour``. Triage puts every case
that writes data in ``choice``, so a replay never submits anything twice.

A step never holds a URL with a host (``goto`` takes a path, joined with the run's base URL), a
placeholder or an account value: signed-in cases sign in with their scenario's Login Recipe.

Each case is bound to its digest (content, kind, steps, expected, scenario): a case edited in the
suite after recording is left out of replays until it is recorded again. Before the tester can
mark the spec reviewed (on the console), every case must have replayed (the first run, or
``webtest-spec-check``) with no spec error on the current content; any later edit needs a new
check and a new review.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import fsutil
from .login_recipe import RecipeError, check_locator, check_timeout
from .webtest import NO_SCENARIO, WebtestError, now_iso

FILE = "spec.json"
VERSION = 1
# State checks compare an attribute of the element (disabled, checked, read-only), not its text.
STATE_CHECKS = ("expect_enabled", "expect_disabled", "expect_checked", "expect_unchecked",
                "expect_editable", "expect_readonly")
ACTIONS = ("goto", "fill", "click", "dblclick", "press", "select", "check", "wait_visible",
           "expect_visible", "expect_hidden", "expect_text", "expect_value", "expect_url") + STATE_CHECKS + ("click_blocked",)
NEEDS_LOCATOR = ("fill", "click", "dblclick", "press", "select", "check", "wait_visible",
                 "expect_visible", "expect_hidden", "expect_text", "expect_value") + STATE_CHECKS + ("click_blocked",)
NEEDS_VALUE = ("goto", "fill", "press", "select", "expect_text", "expect_value", "expect_url")
# click_blocked presses the element anyway and fails when anything happens; its optional value is a
# text that must not appear (the design's success message, say).
OPTIONAL_VALUE = ("click_blocked",)
ELIGIBLE_KINDS = ("label", "element", "behaviour")
MAX_STEPS = 60
MAX_VALUE = 2000
DIGEST_KEYS = ("content", "kind", "steps", "expected", "scenario")


class SpecError(WebtestError):
    """The spec cannot be saved or used; ``problems`` lists every reason."""

    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or [message]


def spec_digest(case: dict) -> str:
    """The fields a recording depends on, the same for a suite case and a run row."""
    items = [case.get(k) or "" for k in DIGEST_KEYS]
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def why_not_eligible(case: dict) -> str | None:
    """None when the case may go in a spec, else the reason."""
    if case.get("class") != "sure":
        return "only a sure case is replayed: a choice case may change data"
    if case.get("runner") != "agent":
        return "only a case the agent runs is replayed"
    if (case.get("viewport") or "pc") != "pc":
        return "phone-width cases are not replayed"
    if case.get("kind") not in ELIGIBLE_KINDS:
        return f"only {', '.join(ELIGIBLE_KINDS)} cases are replayed"
    return None


def check_step(raw: Any, where: str, problems: list[str]) -> dict:
    if not isinstance(raw, dict):
        problems.append(f"{where}: must be an object")
        return {}
    action = raw.get("action")
    if action not in ACTIONS:
        problems.append(f"{where}: action must be one of {', '.join(ACTIONS)}")
        return {}
    step: dict = {"action": action}
    if action in NEEDS_LOCATOR:
        step["locator"] = check_locator(raw.get("locator"), where, problems)
    elif raw.get("locator") is not None:
        problems.append(f"{where}: {action} takes no locator")
    value = raw.get("value")
    if action in NEEDS_VALUE:
        if not isinstance(value, str) or len(value) > MAX_VALUE or (action != "fill" and not value.strip()):
            problems.append(f"{where}: {action} needs a text value of up to {MAX_VALUE} characters")
        elif "{{" in value:
            problems.append(f"{where}: a spec holds no placeholder; a signed-in case signs in with its scenario's recipe")
        elif action == "goto" and (value.startswith(("http:", "https:", "//")) or "://" in value):
            problems.append(f"{where}: goto takes a path such as /mypage; the run's base URL gives the host")
        step["value"] = value
    elif action in OPTIONAL_VALUE and value is not None:
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_VALUE:
            problems.append(f"{where}: {action} value must be a text that must not appear")
        elif "{{" in value:
            problems.append(f"{where}: a spec holds no placeholder; a signed-in case signs in with its scenario's recipe")
        else:
            step["value"] = value
    elif value is not None:
        problems.append(f"{where}: {action} takes no value")
    check_timeout(raw, step, where, problems)
    unknown = set(raw) - {"action", "locator", "value", "timeout_ms"}
    if unknown:
        problems.append(f"{where}: unknown keys {sorted(unknown)}")
    return step


def is_check(action: str) -> bool:
    """A step that checks the app's answer: when it fails, the case is a fail (not a wrong spec)."""
    return action.startswith("expect_") or action == "click_blocked"


def check_steps(case_id: str, raw: Any, problems: list[str]) -> list[dict]:
    if not isinstance(raw, list) or not raw or len(raw) > MAX_STEPS:
        problems.append(f"{case_id}: steps must be a list of 1 to {MAX_STEPS} steps")
        return []
    steps = [check_step(s, f"{case_id} step {i}", problems) for i, s in enumerate(raw, start=1)]
    if not any(is_check(s.get("action", "")) for s in steps):
        problems.append(f"{case_id}: the steps need at least one check of the expected result (expect_ or click_blocked)")
    return steps


def path(folder: Path) -> Path:
    return folder / FILE


def load(folder: Path) -> dict | None:
    try:
        data = json.loads(path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("testign_spec") != VERSION or not isinstance(data.get("cases"), dict):
        return None
    return data


def write(folder: Path, spec: dict) -> None:
    fsutil.atomic_write_bytes(path(folder), (json.dumps(spec, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def content_hash(spec: dict) -> str:
    material = {"suite": spec.get("suite"), "project": spec.get("project"), "cases": spec.get("cases")}
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def normalise(suite: dict, raw_cases: Any) -> dict:
    """{case id: {"steps"}} checked against the suite: eligible cases only, every step valid."""
    if not isinstance(raw_cases, dict) or not raw_cases:
        raise SpecError("cases must map case ids to their steps")
    by_id = {c["case"]: c for c in suite["cases"]}
    problems: list[str] = []
    out = {}
    for case_id, body in raw_cases.items():
        case = by_id.get(case_id)
        if case is None:
            problems.append(f"{case_id}: no such case in the suite")
            continue
        reason = why_not_eligible(case)
        if reason:
            problems.append(f"{case_id}: {reason}")
            continue
        steps = check_steps(case_id, (body or {}).get("steps") if isinstance(body, dict) else None, problems)
        out[case_id] = {"digest": spec_digest(case), "scenario": case.get("scenario") or NO_SCENARIO, "steps": steps}
    if problems:
        raise SpecError("; ".join(problems[:12]), problems)
    return out


def save(folder: Path, suite: dict, raw_cases: Any, by: str = "agent", check: dict | None = None) -> dict:
    """Write the spec (replacing the cases it names, keeping the others). Clears the review."""
    cases = normalise(suite, raw_cases)
    current = load(folder) or {}
    merged = {k: v for k, v in (current.get("cases") or {}).items() if k not in cases}
    merged.update(cases)
    spec = {"testign_spec": VERSION, "suite": suite["id"], "project": suite.get("project"), "cases": merged,
            "saved_at": now_iso(), "by": (by or "agent")[:100], "check": None, "reviewed": None}
    if check is not None:
        # Results of the cases kept from before still count when they were checked on that content.
        old_check = current.get("check") or {}
        old = (old_check.get("cases") or {}) if current and old_check.get("hash") == content_hash(current) else {}
        results = {k: v for k, v in old.items() if k in merged and k not in cases}
        results.update(check)
        spec["check"] = {"at": now_iso(), "by": "first run", "hash": content_hash(spec), "cases": results}
    write(folder, spec)
    return spec


def store_check(folder: Path, results: dict, by: str, spec_hash: str) -> dict:
    spec = load(folder)
    if spec is None:
        raise SpecError("the suite has no spec yet")
    if content_hash(spec) != spec_hash:
        raise SpecError("the spec changed while it was checked; check it again")
    spec["check"] = {"at": now_iso(), "by": by, "hash": spec_hash, "cases": results}
    write(folder, spec)
    return spec["check"]


def check_state(spec: dict | None) -> dict:
    """{"status": "missing" | "stale" | "spec_errors" | "passed", "spec_errors": [...], "fail": [...]}."""
    check = (spec or {}).get("check")
    if not check:
        return {"status": "missing", "spec_errors": [], "fail": []}
    cases = {k: v for k, v in (check.get("cases") or {}).items() if k in spec["cases"]}
    errors = sorted(k for k, v in cases.items() if v.get("result") not in ("ok", "fail"))
    fail = sorted(k for k, v in cases.items() if v.get("result") == "fail")
    unchecked = sorted(k for k in spec["cases"] if k not in cases)
    if check.get("hash") != content_hash(spec) or unchecked:
        status = "stale"
    else:
        status = "spec_errors" if errors else "passed"
    return {"status": status, "at": check.get("at"), "by": check.get("by"), "spec_errors": errors, "fail": fail,
            "unchecked": unchecked}


def is_reviewed(spec: dict | None) -> bool:
    return bool(spec and spec.get("reviewed") and spec["reviewed"].get("hash") == content_hash(spec))


def review(folder: Path, spec_hash: Any, by: str | None) -> dict:
    """The tester marks the spec they looked at reviewed; it needs a passing check on that content."""
    spec = load(folder)
    if spec is None:
        raise SpecError("the suite has no spec yet")
    if spec_hash != content_hash(spec):
        raise SpecError("the spec changed since you opened it; reload and look at it again")
    state = check_state(spec)
    if state["status"] in ("missing", "stale"):
        raise SpecError("replay the spec first (a first run or a spec check): it has not replayed since the last change")
    if state["status"] == "spec_errors":
        raise SpecError(f"{len(state['spec_errors'])} cases have a step that finds nothing: "
                        f"{', '.join(state['spec_errors'][:10])}; record them again or remove them first")
    spec["reviewed"] = {"at": now_iso(), "by": (by or "")[:100] or None, "hash": spec_hash}
    write(folder, spec)
    return spec


def remove_cases(folder: Path, case_ids: Any) -> dict:
    """Drop cases from the spec (the tester, on the console). Clears the review."""
    spec = load(folder)
    if spec is None:
        raise SpecError("the suite has no spec yet")
    if not isinstance(case_ids, list) or not all(isinstance(c, str) for c in case_ids):
        raise SpecError("cases must be a list of case ids")
    spec["cases"] = {k: v for k, v in spec["cases"].items() if k not in case_ids}
    spec["reviewed"] = None
    write(folder, spec)
    return spec


def replayable(spec: dict | None, case: dict, row_case_id: str) -> dict | None:
    """The spec case a run row replays: the spec is reviewed and the row's case is unchanged."""
    if not is_reviewed(spec):
        return None
    body = spec["cases"].get(row_case_id)
    if body is None or body.get("digest") != spec_digest(case) or why_not_eligible(case):
        return None
    return body


def row_case_id(row: str) -> str:
    """Run rows ``r03`` come from suite cases ``c3``."""
    return f"c{int(row[1:])}"


def view(folder: Path, suite: dict) -> dict:
    """The spec beside each case's design, for the console's spec card."""
    from . import webtest_live  # noqa: PLC0415 - the warnings are plain text checks; no browser

    spec = load(folder)
    check = (spec or {}).get("check") or {}
    cases = []
    for case in suite["cases"]:
        body = (spec or {}).get("cases", {}).get(case["case"])
        reason = why_not_eligible(case)
        if body is None and reason:
            continue
        steps = (body or {}).get("steps")
        cases.append({"case": case["case"], "content": case.get("content") or "", "expected": case.get("expected") or "",
                      "scenario": case.get("scenario") or NO_SCENARIO, "steps": steps,
                      "changed": bool(body) and body.get("digest") != spec_digest(case),
                      "not_eligible": reason if body else None,
                      "check": (check.get("cases") or {}).get(case["case"]),
                      "warnings": webtest_live.assertion_warnings(steps, case.get("expected") or "") if steps else []})
    return {"exists": spec is not None, "hash": content_hash(spec) if spec else None,
            "status": "missing" if spec is None else ("reviewed" if is_reviewed(spec) else "draft"),
            "saved_at": (spec or {}).get("saved_at"), "reviewed": (spec or {}).get("reviewed") if is_reviewed(spec) else None,
            "check": check_state(spec) if spec else None, "cases": cases,
            "recorded": len((spec or {}).get("cases") or {}),
            "eligible": sum(1 for c in suite["cases"] if not why_not_eligible(c))}


__all__ = ["RecipeError", "SpecError", "load", "save", "view", "review", "check_state", "replayable", "row_case_id"]
