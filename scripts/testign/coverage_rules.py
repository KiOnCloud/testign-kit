"""Test depth: the checks a case list must cover for each control, whatever the source or template.

A source (Figma table, survey report, Excel) says what changed; these rules say which cases a test
of that change cannot leave out. The case list (a web test suite, or a ``testcase`` cases file) lists
the controls in scope::

    {"about": "Cart edit/Cart lines/[Update]", "type": "button", "action": true,
     "needs": ["Cart edit/Cart lines/[Quantity]"], "goes_to": "Checkout"}
    {"about": "Cart edit/Cart lines/[Quantity]", "type": "textbox", "required": true, "format": "integer",
     "range": {"min": 1, "max": 99}, "length": {"min": 1, "max": 20}, "chars": "digits", "default": "1"}
    {"about": "Cart edit/Cart lines", "type": "area"}

and the roles that use them (``roles``). Each rule applies to some controls, asks for a number of
cases, and is required from a test depth on (``depth``: smoke, standard or thorough). A case covers
a check when its ``rule`` and ``about`` match, or through ``covers`` (one case that is also, say, the
valid-input run of the button). A required check that is not covered is skipped on purpose with a
reason (``skips``: ``{"rule", "about", "reason"}``); anything else is missing, and a suite with a
missing check cannot be confirmed.

A list without ``depth`` (made before depth existed) tracks no coverage.
"""

from __future__ import annotations

from typing import Any

DEPTHS = ("smoke", "standard", "thorough")
DEFAULT_DEPTH = "standard"
GROUPS = ("display", "action", "state", "validation", "combination", "role", "robustness")
CONTROL_TYPES = ("button", "link", "textbox", "textarea", "number", "select", "checkbox", "radio", "date",
                 "file", "toggle", "area", "screen", "popup", "label", "table")
_NOT_INPUT = {"button", "link", "area", "screen", "popup", "label", "table"}
MAX_CONTROLS = 300
MAX_ROLES = 20
MAX_SKIPS = 500
MAX_COVERS = 10
ABOUT_CAP = 200
REASON_CAP = 500


class CoverageError(ValueError):
    """Controls, roles, skips or a case's rule fields break the shape."""


def path(about: Any) -> str:
    if isinstance(about, (list, tuple)):
        about = "/".join(str(a) for a in about)
    return "/".join(p.strip() for p in str(about or "").split("/"))


def _needs(c: dict) -> list[str]:
    return [path(n) for n in c.get("needs") or [] if isinstance(n, str) and n.strip()]


def _action(c: dict) -> bool:
    return bool(c.get("action"))


def _gated(c: dict) -> bool:
    """An action button that depends on inputs."""
    return _action(c) and bool(_needs(c))


def _input(c: dict) -> bool:
    return str(c.get("type") or "").lower() not in _NOT_INPUT


def _bounds(c: dict, key: str) -> int:
    b = c.get(key)
    return sum(1 for k in ("min", "max") if isinstance(b, dict) and b.get(k) not in (None, ""))


def _has(c: dict, key: str) -> bool:
    return str(c.get(key) or "").strip() != ""


def _formatted(c: dict, by: dict) -> list[str]:
    return [n for n in _needs(c) if _has(by.get(n) or {}, "format")]


def _roles(listing: dict) -> list[str]:
    return [r for r in listing.get("roles") or [] if str(r).strip()]


# Each rule: group, the depth it is required from, a label, the case it asks for, and
# rows(control, controls by about, listing) -> cases needed (0 = does not apply to this control).
RULES: dict[str, dict] = {
    "display.initial": {"group": "display", "depth": "smoke", "label": "Initial value",
                        "case": "Open the screen and check the value each input shows first.",
                        "rows": lambda c, by, d: 1 if _input(c) else 0},
    "display.layout": {"group": "display", "depth": "smoke", "label": "Layout",
                       "case": "Check the layout of each area or popup against the design.",
                       "rows": lambda c, by, d: 1 if str(c.get("type") or "").lower() in ("area", "popup", "screen") else 0},
    "action.normal": {"group": "action", "depth": "smoke", "label": "Works with valid input",
                      "case": "Press each action button with every input valid and check what it does.",
                      "rows": lambda c, by, d: 1 if _action(c) else 0},
    "action.navigate": {"group": "action", "depth": "smoke", "label": "Goes to the right screen",
                        "case": "Press a button that moves on and check the screen it opens.",
                        "rows": lambda c, by, d: 1 if _has(c, "goes_to") else 0},
    "state.empty": {"group": "state", "depth": "standard", "label": "Inputs empty",
                    "case": "Leave every input the button needs empty, then check the button (disabled, a message, or it works).",
                    "rows": lambda c, by, d: 1 if _gated(c) else 0},
    "state.missing_one": {"group": "state", "depth": "standard", "label": "One required input missing at a time",
                          "case": "Fill every input but one, once per input the button needs.",
                          "rows": lambda c, by, d: len(_needs(c)) if _gated(c) and len(_needs(c)) > 1 else 0},
    "state.invalid": {"group": "state", "depth": "standard", "label": "Input in a wrong format",
                      "case": "Put a value in the wrong format into each input with a format, the others valid.",
                      "rows": lambda c, by, d: len(_formatted(c, by)) if _gated(c) else 0},
    "state.refill": {"group": "state", "depth": "thorough", "label": "Filled, then one cleared",
                     "case": "Fill every input, clear one again, then check the button is blocked again.",
                     "rows": lambda c, by, d: 1 if _gated(c) else 0},
    "validation.boundary": {"group": "validation", "depth": "standard", "label": "Limits and the values next to them",
                            "case": "For each limit of range or length, the value on the limit and the one just past it.",
                            "rows": lambda c, by, d: 2 * (_bounds(c, "range") + _bounds(c, "length")) if _input(c) else 0},
    "validation.message": {"group": "validation", "depth": "standard", "label": "Message text word for word",
                           "case": "Each message an input shows (refused value, wrong format), checked word for word.",
                           "rows": lambda c, by, d: 1 if _input(c) and (_bounds(c, "range") or _bounds(c, "length") or _has(c, "format")) else 0},
    "validation.chars": {"group": "validation", "depth": "thorough", "label": "Character types",
                         "case": "Each character type the input refuses (full-width, symbols, letters in a number).",
                         "rows": lambda c, by, d: 1 if _input(c) and _has(c, "chars") else 0},
    "validation.length": {"group": "validation", "depth": "thorough", "label": "Length",
                          "case": "The longest value accepted and one character more.",
                          "rows": lambda c, by, d: 1 if _input(c) and _bounds(c, "length") else 0},
    "combination.pairs": {"group": "combination", "depth": "thorough", "label": "Every pair of input values",
                          "case": "Cases where every pair of input values appears at least once (pairwise, not every combination).",
                          "rows": lambda c, by, d: 1 if _gated(c) and len(_needs(c)) > 1 else 0},
    "role.each": {"group": "role", "depth": "standard", "label": "Each role",
                  "case": "Each role that uses the screen presses the button once (allowed, hidden or refused).",
                  "rows": lambda c, by, d: len(_roles(d)) if _action(c) and len(_roles(d)) > 1 else 0},
    "robustness.double": {"group": "robustness", "depth": "thorough", "label": "Pressed twice quickly",
                          "case": "Press the action button twice quickly and check it runs once.",
                          "rows": lambda c, by, d: 1 if _action(c) else 0},
    "robustness.leave": {"group": "robustness", "depth": "thorough", "label": "Leave with unsaved input",
                         "case": "Type into the inputs, leave the screen without saving, and check what happens.",
                         "rows": lambda c, by, d: 1 if _gated(c) else 0},
}


# shapes -----------------------------------------------------------------------------------------
def check_depth(value: Any, allow_none: bool = False) -> str | None:
    if value in (None, "") and allow_none:
        return None
    if value not in DEPTHS:
        raise CoverageError(f"depth must be one of {', '.join(DEPTHS)}")
    return value


def _about(value: Any, where: str) -> str:
    text = path(value)
    if not text or len(text) > ABOUT_CAP:
        raise CoverageError(f"{where}: about must be a control path of up to {ABOUT_CAP} characters")
    return text


def _bound(value: Any, where: str) -> dict | None:
    if value in (None, {}):
        return None
    if not isinstance(value, dict) or set(value) - {"min", "max"}:
        raise CoverageError(f"{where} must be {{\"min\", \"max\"}}")
    out = {}
    for k in ("min", "max"):
        v = value.get(k)
        if v in (None, ""):
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float, str)) or len(str(v)) > 40:
            raise CoverageError(f"{where}.{k} must be a number or a short text")
        out[k] = v
    return out or None


_CONTROL_KEYS = {"about", "type", "action", "needs", "goes_to", "required", "format", "range", "length",
                 "chars", "default"}


def check_controls(raw: Any) -> list[dict]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_CONTROLS:
        raise CoverageError(f"controls must be a list of up to {MAX_CONTROLS} controls")
    out, seen = [], set()
    for n, c in enumerate(raw, start=1):
        where = f"control {n}"
        if not isinstance(c, dict):
            raise CoverageError(f"{where} must be an object")
        extra = set(c) - _CONTROL_KEYS
        if extra:
            raise CoverageError(f"{where}: unknown keys {sorted(extra)}")
        about = _about(c.get("about"), where)
        if about in seen:
            raise CoverageError(f"{where}: {about} is listed twice")
        seen.add(about)
        ctype = str(c.get("type") or "").lower()
        if ctype not in CONTROL_TYPES:
            raise CoverageError(f"{where}: type must be one of {', '.join(CONTROL_TYPES)}")
        item: dict = {"about": about, "type": ctype}
        if c.get("action"):
            item["action"] = True
        if c.get("required"):
            item["required"] = True
        needs = c.get("needs")
        if needs not in (None, []):
            if not isinstance(needs, list) or len(needs) > 50:
                raise CoverageError(f"{where}: needs must be a list of control paths")
            item["needs"] = [_about(x, f"{where} needs") for x in needs]
        for key in ("goes_to", "format", "chars", "default"):
            v = c.get(key)
            if v not in (None, ""):
                if not isinstance(v, (str, int, float)) or isinstance(v, bool) or len(str(v)) > ABOUT_CAP:
                    raise CoverageError(f"{where}: {key} must be a short text")
                item[key] = str(v)
        for key in ("range", "length"):
            b = _bound(c.get(key), f"{where} {key}")
            if b:
                item[key] = b
        out.append(item)
    return out


def check_roles(raw: Any) -> list[str]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ROLES or not all(isinstance(r, str) and 0 < len(r.strip()) <= 60 for r in raw):
        raise CoverageError(f"roles must be a list of up to {MAX_ROLES} short names")
    return list(dict.fromkeys(r.strip() for r in raw))


def check_skips(raw: Any) -> list[dict]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_SKIPS:
        raise CoverageError(f"skips must be a list of up to {MAX_SKIPS} items")
    out = {}
    for n, s in enumerate(raw, start=1):
        if not isinstance(s, dict) or set(s) - {"rule", "about", "reason", "by"}:
            raise CoverageError(f"skip {n} must be {{\"rule\", \"about\", \"reason\"}}")
        if s.get("rule") not in RULES:
            raise CoverageError(f"skip {n}: rule must be a kit rule")
        reason = str(s.get("reason") or "").strip()
        if not reason or len(reason) > REASON_CAP:
            raise CoverageError(f"skip {n}: say why the check is left out (up to {REASON_CAP} characters)")
        item = {"rule": s["rule"], "about": _about(s.get("about"), f"skip {n}"), "reason": reason}
        if isinstance(s.get("by"), str) and s["by"].strip():
            item["by"] = s["by"].strip()[:100]
        out[(item["rule"], item["about"])] = item
    return list(out.values())


def check_case_fields(data: dict) -> dict:
    """A case's ``rule``, ``about`` and ``covers``, checked; only the fields that are set."""
    out: dict = {}
    rule, about = data.get("rule"), data.get("about")
    if rule not in (None, ""):
        if rule not in RULES:
            raise CoverageError("rule must be a kit rule (see coverage-rules)")
        out["rule"] = rule
        out["about"] = _about(about, "case")
    elif about not in (None, ""):
        raise CoverageError("about needs a rule")
    covers = data.get("covers")
    if covers not in (None, []):
        if not isinstance(covers, list) or len(covers) > MAX_COVERS:
            raise CoverageError(f"covers must be a list of up to {MAX_COVERS} {{\"rule\", \"about\"}}")
        items = []
        for c in covers:
            if not isinstance(c, dict) or set(c) - {"rule", "about"} or c.get("rule") not in RULES:
                raise CoverageError("each covers item is {\"rule\", \"about\"} with a kit rule")
            items.append({"rule": c["rule"], "about": _about(c.get("about"), "covers")})
        out["covers"] = items
    return out


# coverage ---------------------------------------------------------------------------------------
def covered_by(case: dict) -> list[tuple[str, str]]:
    out = []
    if case.get("rule") and case.get("about"):
        out.append((case["rule"], path(case["about"])))
    for c in case.get("covers") or []:
        if isinstance(c, dict) and c.get("rule") and c.get("about"):
            out.append((c["rule"], path(c["about"])))
    return out


def depth_of(listing: dict) -> str | None:
    d = listing.get("depth")
    return d if d in DEPTHS else None


def is_required(rule_id: str, depth: str | None) -> bool:
    if depth is None:
        return False
    return DEPTHS.index(RULES[rule_id]["depth"]) <= DEPTHS.index(depth)


def catalogue() -> list[dict]:
    """The rules as the CLI prints them for the agent."""
    return [{"id": rid, "group": r["group"], "from": r["depth"], "label": r["label"], "case": r["case"]}
            for rid, r in RULES.items()]


def checks(listing: dict) -> list[dict]:
    """[{"rule", "about", "rows", "required"}] for every listed control a rule applies to."""
    controls = [c for c in listing.get("controls") or [] if isinstance(c, dict) and c.get("about")]
    by_about = {path(c["about"]): c for c in controls}
    depth = depth_of(listing)
    out = []
    for c in controls:
        for rid, rule in RULES.items():
            n = rule["rows"](c, by_about, listing)
            if n:
                out.append({"rule": rid, "about": path(c["about"]), "rows": n, "required": is_required(rid, depth)})
    return out


def required(listing: dict) -> list[dict]:
    return [c for c in checks(listing) if c["required"]]


def coverage(listing: dict, everything: bool = False) -> list[dict]:
    """Each check with its status: covered, skipped, partial or missing; ``optional`` for a check the
    depth does not require (listed only with ``everything``). ``cases`` are the case ids (or 1-based
    positions when a case has no id) that cover it."""
    rows: dict = {}
    for n, case in enumerate(listing.get("cases") or [], start=1):
        for key in covered_by(case):
            rows.setdefault(key, []).append(case.get("case") or n)
    skips = {(s.get("rule"), path(s.get("about"))): s for s in listing.get("skips") or [] if isinstance(s, dict)}
    out = []
    for chk in checks(listing):
        if not chk["required"] and not everything:
            continue
        key = (chk["rule"], chk["about"])
        got = rows.get(key, [])
        item = {"rule": chk["rule"], "about": chk["about"], "rows": chk["rows"], "cases": got}
        if len(got) >= chk["rows"]:
            item["status"] = "covered"
        elif not chk["required"]:
            item["status"] = "optional"
        elif key in skips:
            item["status"], item["reason"] = "skipped", skips[key]["reason"]
        else:
            item["status"] = "partial" if got else "missing"
        out.append(item)
    return out


def problems(listing: dict) -> list[str]:
    """References that point nowhere: a need, a case's rule or about, or a skip naming no listed check."""
    listed = {path(c.get("about")) for c in listing.get("controls") or [] if isinstance(c, dict)}
    out = []
    for c in listing.get("controls") or []:
        for n in _needs(c):
            if n not in listed:
                out.append(f"control {c.get('about')} needs '{n}', which is not in controls")
    for n, case in enumerate(listing.get("cases") or [], start=1):
        for rid, about in covered_by(case):
            if about not in listed:
                out.append(f"case {case.get('case') or n}: about '{about}' of {rid} is not in controls")
    real = {(c["rule"], c["about"]) for c in checks(listing)}
    for s in listing.get("skips") or []:
        if (s.get("rule"), path(s.get("about"))) not in real:
            out.append(f"the skip of {s.get('rule')} for '{s.get('about')}' names no check of the listed controls")
    return out


def missing(listing: dict) -> list[dict]:
    """Required checks neither covered nor skipped."""
    return [c for c in coverage(listing) if c["status"] in ("missing", "partial")]


def summary(listing: dict) -> dict | None:
    """Counts for a list with depth: required checks by status, and what is missing."""
    depth = depth_of(listing)
    if depth is None:
        return None
    items = coverage(listing)
    counts = {s: sum(1 for c in items if c["status"] == s) for s in ("covered", "skipped", "partial", "missing")}
    return {"depth": depth, "controls": len(listing.get("controls") or []), "required": len(items), **counts,
            "missing_checks": [{k: c[k] for k in ("rule", "about", "rows", "cases")} for c in items
                               if c["status"] in ("missing", "partial")],
            "problems": problems(listing)}


def view(listing: dict) -> dict | None:
    """The Coverage tab: {"depth", "rows", "problems", ...}, required checks first, grouped as the
    rules are; None for a list without depth."""
    depth = depth_of(listing)
    if depth is None:
        return None
    controls = {path(c.get("about")): c for c in listing.get("controls") or [] if isinstance(c, dict)}
    out = []
    for item in coverage(listing, everything=True):
        rule = RULES[item["rule"]]
        out.append({"group": rule["group"], "rule": item["rule"], "label": rule["label"], "case_hint": rule["case"],
                    "about": item["about"], "control": item["about"].split("/")[-1], "level": rule["depth"],
                    "status": "missing" if item["status"] == "partial" else item["status"],
                    "partial": item["status"] == "partial", "need": item["rows"],
                    "required": is_required(item["rule"], depth), "cases": item["cases"],
                    "inputs": [n.split("/")[-1] for n in _needs(controls.get(item["about"]) or {})],
                    "reason": item.get("reason")})
    order = {g: i for i, g in enumerate(GROUPS)}
    rule_order = list(RULES)
    out.sort(key=lambda r: (not r["required"], order[r["group"]], rule_order.index(r["rule"])))
    req = [r for r in out if r["required"]]
    return {"depth": depth, "depths": list(DEPTHS), "controls": len(controls), "rows": out,
            "required": len(req), "covered": sum(1 for r in req if r["status"] == "covered"),
            "skipped": sum(1 for r in req if r["status"] == "skipped"),
            "missing": sum(1 for r in req if r["status"] == "missing"), "problems": problems(listing)}


def adds_checks(listing: dict, depth: str) -> bool:
    """Whether moving the list to ``depth`` requires checks it does not require now."""
    before = {(c["rule"], c["about"]) for c in required(listing)}
    after = {(c["rule"], c["about"]) for c in required({**listing, "depth": depth})}
    return bool(after - before)


def sheet_rows(listing: dict) -> list[list] | None:
    """The Coverage sheet of an export: a title row, a header and one row per check."""
    v = view(listing)
    if v is None:
        return None
    rows: list[list] = [[f"Test depth: {v['depth']}"],
                        ["Group", "Check", "Control", "Required", "Status", "Cases", "Reason"]]
    for r in v["rows"]:
        rows.append([r["group"], r["label"], r["about"], "Yes" if r["required"] else f"From {r['level']}",
                     r["status"] + (" (partial)" if r["partial"] else ""), ", ".join(str(c) for c in r["cases"]),
                     r.get("reason") or ""])
    return rows
