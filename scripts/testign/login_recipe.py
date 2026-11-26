"""Login Recipes: the sign-in steps of a login scenario, filled from a profile the tester typed.

A recipe lets a replay sign in without the tester. It sits next to its scenario and the tester's
values sit apart from it, all under ``~/.testign-kit/webtest/`` (owner-only)::

    login/<project>/<scenario>/recipe.json      steps with {{placeholders}}, the profile it uses
    login/<project>/<scenario>/recipe-test.json the last test: {fingerprint, ok, at, error, failed_step}
    login/<project>/<scenario>/recipe-approval.json  {fingerprint, approved_at, by}: the tester approved it
    profiles/<project>/<profile>.json           {"values": {key: text}, "staging_test_account": true, ...} (0600)
    sessions/<project>/<scenario>.json          the signed-in storage state a replay opens with (0600)

Who writes what: the agent drafts a recipe (``login-recipe-save``) and may test it
(``login-recipe-test``): the engine fills the values in memory and scrubs them from every error it
returns, so the agent never sees one. Only the tester writes a profile, in their own terminal
(``profile-set`` prompts without echo and refuses piped input), and only the tester approves a
recipe, on the console. A recipe is usable while its approval and a passing test both hold the
fingerprint of the current recipe and profile keys.

Decided by the team (2026-11-26): profile values are plain text protected by file permissions, and
only dedicated staging test accounts go in a profile. ``hooks/secret_guard.py`` keeps Claude away
from the profiles and sessions folders. That is a guardrail, not a security boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import fsutil
from .login_scenarios import NotFound, _child, _read, _scenario_folder, _write, check_name, get_project, now_iso, store_dir
from .webtest import WebtestError, url_on_hosts

ACTIONS = ("goto", "fill", "click", "press", "wait_url", "wait_visible")
SUCCESS_CHECKS = ("wait_url", "wait_visible")
LOCATOR_KINDS = ("role", "label", "placeholder", "text", "test_id", "css")
PLACEHOLDER_RE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,39})\s*\}\}$")
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
MAX_STEPS = 30
MAX_TIMEOUT_MS = 120_000
MAX_VALUE = 500
RECIPE = "recipe.json"
TEST = "recipe-test.json"
APPROVAL = "recipe-approval.json"


class RecipeError(WebtestError):
    """The recipe or profile cannot be used; the message is one line and never holds a value."""


# locators and steps (shared with the spec) ----------------------------------------------------
def check_locator(raw: Any, where: str, problems: list[str]) -> dict | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: locator must be an object")
        return None
    kinds = [k for k in LOCATOR_KINDS if k in raw]
    if len(kinds) != 1:
        problems.append(f"{where}: locator needs exactly one of {', '.join(LOCATOR_KINDS)}")
        return None
    kind = kinds[0]
    value = raw[kind]
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        problems.append(f"{where}: locator.{kind} must be text of 1 to 300 characters")
        return None
    out: dict = {kind: value}
    if kind == "role" and raw.get("name") is not None:
        if not isinstance(raw["name"], str) or len(raw["name"]) > 300:
            problems.append(f"{where}: locator.name must be text of up to 300 characters")
        elif raw["name"]:
            out["name"] = raw["name"]
    if "exact" in raw:
        if not isinstance(raw["exact"], bool):
            problems.append(f"{where}: locator.exact must be true or false")
        elif kind in ("role", "label", "placeholder", "text"):
            out["exact"] = raw["exact"]
    if "nth" in raw:
        nth = raw["nth"]
        if not isinstance(nth, int) or isinstance(nth, bool) or not 0 <= nth <= 99:
            problems.append(f"{where}: locator.nth must be an integer from 0 to 99")
        else:
            out["nth"] = nth
    unknown = set(raw) - set(LOCATOR_KINDS) - {"name", "exact", "nth"}
    if unknown:
        problems.append(f"{where}: unknown locator keys {sorted(unknown)}")
    return out


def check_timeout(raw: dict, step: dict, where: str, problems: list[str]) -> None:
    if "timeout_ms" in raw:
        t = raw["timeout_ms"]
        if not isinstance(t, int) or isinstance(t, bool) or not 0 < t <= MAX_TIMEOUT_MS:
            problems.append(f"{where}: timeout_ms must be an integer from 1 to {MAX_TIMEOUT_MS}")
        else:
            step["timeout_ms"] = t


def placeholder_key(value: Any) -> str | None:
    match = PLACEHOLDER_RE.match(value) if isinstance(value, str) else None
    return match.group(1) if match else None


def glob_to_regex(glob: str) -> re.Pattern:
    """``**`` matches anything, ``*`` anything but '/', everything else is literal."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def url_matcher(value: str):
    """``<glob>`` matches; ``!<glob>`` matches once the URL no longer does."""
    negate = value.startswith("!")
    pattern = glob_to_regex(value[1:] if negate else value)
    return (lambda url: not pattern.match(url)) if negate else (lambda url: bool(pattern.match(url)))


_ANY_URL = ("http://a.invalid", "https://b.invalid/", "https://c.invalid/x/y.html?q=1#h")


def matches_every_url(value: str) -> bool:
    return not value.startswith("!") and all(glob_to_regex(value).match(u) for u in _ANY_URL)


def _step(raw: Any, index: int, allowed_hosts: list[str], problems: list[str]) -> dict:
    where = f"step {index}"
    if not isinstance(raw, dict):
        problems.append(f"{where}: must be an object")
        return {}
    action = raw.get("action")
    if action not in ACTIONS:
        problems.append(f"{where}: action must be one of {', '.join(ACTIONS)}")
        return {}
    step: dict = {"action": action}
    if action in ("fill", "click", "press", "wait_visible"):
        step["locator"] = check_locator(raw.get("locator"), where, problems)
    elif raw.get("locator") is not None:
        problems.append(f"{where}: {action} takes no locator")
    value = raw.get("value")
    if action == "goto":
        if not isinstance(value, str) or not url_on_hosts(value, allowed_hosts):
            problems.append(f"{where}: goto needs a URL on the project's hosts or sign-in hosts")
        step["value"] = value
    elif action == "fill":
        if placeholder_key(value) is None:
            # A literal is refused so that a real account value never lands in a recipe.
            problems.append(f"{where}: fill takes a placeholder such as {{{{password}}}}, never the value itself")
        step["value"] = value
    elif action == "press":
        if not isinstance(value, str) or not value.strip() or len(value) > 40:
            problems.append(f"{where}: press takes a key name such as Enter")
        step["value"] = value
    elif action == "wait_url":
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            problems.append(f"{where}: wait_url takes a URL glob")
        elif matches_every_url(value):
            problems.append(f"{where}: wait_url {value!r} matches every page, the sign-in page too")
        step["value"] = value
    elif value is not None:
        problems.append(f"{where}: {action} takes no value")
    check_timeout(raw, step, where, problems)
    unknown = set(raw) - {"action", "locator", "value", "timeout_ms"}
    if unknown:
        problems.append(f"{where}: unknown keys {sorted(unknown)}")
    return step


def check_recipe(data: Any, project: dict) -> dict:
    """An agent's draft: a profile name, the sign-in page and the steps, ending in a success check."""
    if not isinstance(data, dict):
        raise RecipeError("the recipe must be a JSON object")
    problems: list[str] = []
    unknown = set(data) - {"profile", "login_url", "steps"}
    if unknown:
        problems.append(f"unknown recipe keys {sorted(unknown)}")
    try:
        profile = check_name(data.get("profile"), "profile")
    except WebtestError as exc:
        problems.append(str(exc))
        profile = None
    allowed = project["hosts"] + project["signin_hosts"]
    login_url = data.get("login_url")
    if not isinstance(login_url, str) or not url_on_hosts(login_url, allowed):
        problems.append("login_url must be a URL on the project's hosts or sign-in hosts")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps or len(raw_steps) > MAX_STEPS:
        problems.append(f"steps must be a list of 1 to {MAX_STEPS} steps")
        raw_steps = []
    steps = [_step(s, i, allowed, problems) for i, s in enumerate(raw_steps, start=1)]
    if steps and steps[-1].get("action") not in SUCCESS_CHECKS:
        problems.append("the last step must prove the sign-in worked: wait_url or wait_visible")
    if steps and not placeholders(steps):
        problems.append("a recipe fills at least one placeholder")
    if problems:
        raise RecipeError("; ".join(problems[:12]))
    return {"profile": profile, "login_url": login_url, "steps": steps}


def placeholders(steps: list[dict]) -> list[str]:
    return sorted({k for k in (placeholder_key(s.get("value")) for s in steps if s.get("action") == "fill") if k})


def fingerprint(recipe: dict) -> str:
    material = {k: recipe.get(k) for k in ("profile", "login_url", "steps")}
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# recipes ---------------------------------------------------------------------------------------
def save(home: Path | None, project: Any, scenario: Any, data: Any) -> dict:
    project = check_name(project, "project")
    recipe = check_recipe(data, get_project(home, project))
    folder = _scenario_folder(home, project, check_name(scenario, "scenario"))
    _write(folder / RECIPE, {**recipe, "saved_at": now_iso()})
    for stale in (TEST, APPROVAL):
        (folder / stale).unlink(missing_ok=True)
    return view(home, project, scenario)


def load(home: Path | None, project: str, scenario: str) -> dict | None:
    try:
        folder = _scenario_folder(home, project, scenario)
    except NotFound:
        return None
    data = _read(folder / RECIPE)
    return data if isinstance(data, dict) else None


def view(home: Path | None, project: str, scenario: str) -> dict:
    """What the console and the agent see: steps, placeholders, test and approval. Never a value."""
    folder = _scenario_folder(home, project, scenario)
    recipe = _read(folder / RECIPE)
    if not isinstance(recipe, dict):
        return {"exists": False, "usable": False}
    fp = fingerprint(recipe)
    test = _read(folder / TEST) or {}
    approval = _read(folder / APPROVAL) or {}
    keys = profile_keys(home, project, recipe.get("profile"))
    missing = [k for k in placeholders(recipe.get("steps") or []) if k not in (keys or [])]
    tested = test.get("fingerprint") == fp and bool(test.get("ok"))
    approved = approval.get("fingerprint") == fp
    return {"exists": True, "profile": recipe.get("profile"), "login_url": recipe.get("login_url"),
            "steps": recipe.get("steps"), "placeholders": placeholders(recipe.get("steps") or []),
            "profile_set": keys is not None, "missing_values": missing, "fingerprint": fp,
            "test": {k: test.get(k) for k in ("ok", "at", "error", "failed_step")} if test.get("fingerprint") == fp else None,
            "tested": tested, "approved": approved, "approved_by": approval.get("by") if approved else None,
            "usable": tested and approved and not missing and keys is not None}


def approve(home: Path | None, project: str, scenario: str, fp: Any, by: str | None) -> dict:
    """The tester approves the recipe they looked at; it needs a passing test of that fingerprint."""
    folder = _scenario_folder(home, project, scenario)
    current = view(home, project, scenario)
    if not current["exists"] or fp != current["fingerprint"]:
        raise RecipeError("the recipe changed since you opened it; reload and check it again")
    if not current["tested"]:
        raise RecipeError("test the recipe first: it has not signed in with the current steps")
    _write(folder / APPROVAL, {"fingerprint": fp, "approved_at": now_iso(), "by": by})
    return view(home, project, scenario)


def store_test(home: Path | None, project: str, scenario: str, fp: str, result: dict) -> None:
    folder = _scenario_folder(home, project, scenario)
    _write(folder / TEST, {"fingerprint": fp, "at": now_iso(), "ok": bool(result.get("ok")),
                           "error": result.get("error"), "failed_step": result.get("failed_step")})


def usable(home: Path | None, project: str, scenario: str) -> bool:
    try:
        return bool(view(home, project, scenario)["usable"])
    except WebtestError:
        return False


# profiles ---------------------------------------------------------------------------------------
def profiles_dir(home: Path | None) -> Path:
    return store_dir(home) / "profiles"


def sessions_dir(home: Path | None) -> Path:
    return store_dir(home) / "sessions"


def _profile_path(home: Path | None, project: str, profile: str, create: bool = False) -> Path | None:
    root = profiles_dir(home)
    folder = _child(root, project) if root.is_dir() else None
    if folder is None:
        if not create:
            return None
        fsutil.owner_only_dirs(root, root / project)
        folder = root / project
    return folder / f"{profile}.json"


def _read_profile(home: Path | None, project: str, profile: Any) -> dict | None:
    if not isinstance(profile, str):
        return None
    try:
        check_name(profile, "profile")
        check_name(project, "project")
    except WebtestError:
        return None
    path = _profile_path(home, project, profile)
    data = _read(path) if path is not None and path.is_file() else None
    if not isinstance(data, dict) or not isinstance(data.get("values"), dict):
        return None
    return data


def profile_keys(home: Path | None, project: str, profile: Any) -> list[str] | None:
    """The profile's keys (never its values), or None when there is no such profile."""
    data = _read_profile(home, project, profile)
    return sorted(data["values"]) if data else None


def profile_values(home: Path | None, project: str, profile: Any) -> dict[str, str]:
    """For the engine only: never print, log or return these."""
    data = _read_profile(home, project, profile)
    if data is None:
        raise RecipeError(f"profile {profile} is not set; the tester sets it with profile-set in their own terminal")
    return {k: v for k, v in data["values"].items() if isinstance(v, str)}


def set_profile(home: Path | None, project: Any, profile: Any, values: dict[str, str]) -> dict:
    """Called by ``profile-set`` with the values the tester typed. Writes 0600; returns keys only."""
    project = check_name(project, "project")
    get_project(home, project)
    profile = check_name(profile, "profile")
    if not values:
        raise RecipeError("a profile needs at least one value")
    clean = {}
    for key, value in values.items():
        if not KEY_RE.match(key):
            raise RecipeError(f"profile key {key!r} must be letters, digits or underscores")
        if not isinstance(value, str) or not value or len(value) > MAX_VALUE or "\n" in value or "\r" in value:
            raise RecipeError(f"the value for {key} must be one line of 1 to {MAX_VALUE} characters")
        clean[key] = value
    path = _profile_path(home, project, profile, create=True)
    _write(path, {"values": clean, "staging_test_account": True, "set_at": now_iso()})
    return {"project": project, "profile": profile, "keys": sorted(clean)}


def remove_profile(home: Path | None, project: Any, profile: Any) -> dict:
    project = check_name(project, "project")
    profile = check_name(profile, "profile")
    path = _profile_path(home, project, profile)
    if path is None or not path.is_file():
        raise NotFound("no such profile")
    path.unlink()
    return {"removed": profile}


def list_profiles(home: Path | None, project: Any) -> list[dict]:
    project = check_name(project, "project")
    root = profiles_dir(home)
    folder = _child(root, project) if root.is_dir() else None
    out = []
    for path in sorted(folder.glob("*.json")) if folder else []:
        keys = profile_keys(home, project, path.stem)
        if keys is not None:
            out.append({"profile": path.stem, "keys": keys})
    return out


def session_path(home: Path | None, project: str, scenario: str, create: bool = False) -> Path | None:
    root = sessions_dir(home)
    folder = _child(root, project) if root.is_dir() else None
    if folder is None:
        if not create:
            return None
        fsutil.owner_only_dirs(root, root / project)
        folder = root / project
    return folder / f"{scenario}.json"


def save_session(home: Path | None, project: str, scenario: str, state: dict) -> Path:
    path = session_path(home, project, scenario, create=True)
    _write(path, state)
    return path


def drop_session(home: Path | None, project: str, scenario: str) -> None:
    path = session_path(home, project, scenario)
    if path is not None:
        path.unlink(missing_ok=True)


def redact(text: str, values: list[str] | dict) -> str:
    """One line of ``text`` with every profile value replaced."""
    items = values.values() if isinstance(values, dict) else values
    for secret in sorted((v for v in items if isinstance(v, str) and v), key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    first = text.strip().splitlines()[0] if text.strip() else "error"
    return first[:400]


def same_page(url: str, login_url: str) -> bool:
    """True when ``url`` is the sign-in page (same host and path, any query)."""
    a, b = urlsplit(url or ""), urlsplit(login_url or "")
    return bool(a.hostname) and a.hostname == b.hostname and (a.path.rstrip("/") or "/") == (b.path.rstrip("/") or "/")
