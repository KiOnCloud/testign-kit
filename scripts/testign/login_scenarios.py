"""Projects and login scenarios for web test runs, stored in ``~/.testign-kit/webtest/`` (owner-only).

::

    projects.json                         {"<project>": {"hosts": [...], "signin_hosts": [...]}}
    login/<project>/<scenario>/
      scenario.json                       the checklist the agent drafted
      approval.json                       {"hash", "approved_at", "by"}: the tester approved that hash
      rejection.json                      {"note", "rejected_at", "by"}: what the tester wants changed

Who writes what: project hosts only through the console (the tester); a scenario draft through
``login-scenario-save`` (the agent), checked against the tester's hosts; an approval or a rejection
only through the console. A scenario is usable while ``approval.json`` holds the hash of the
current ``scenario.json``; saving a draft clears the approval.

A scenario is a checklist for the tester, who signs in by hand. It has no field for an account
name, password, code or selector, and nothing in the plugin types into a sign-in form.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, fsutil
from .webtest import NAME_RE, NO_SCENARIO, WebtestError, check_host, url_on_hosts

RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
SCENARIO_KEYS = {"name", "label", "login_url", "signout_url", "steps", "signed_in_check", "account_hint",
                 "created_at"}
MAX_HOSTS = 20
MAX_STEPS = 20


class NotFound(WebtestError):
    """No such project or scenario."""


class Conflict(WebtestError):
    """The scenario changed since the tester looked at it."""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def store_dir(home: Path | None = None) -> Path:
    return config.config_dir(home) / "webtest"


def ensure_store(home: Path | None = None) -> Path:
    root = store_dir(home)
    fsutil.owner_only_dirs(root, root / "login", root / "runs")
    return root


def check_name(name: Any, what: str) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name) or name.upper() in RESERVED:
        raise WebtestError(f"{what} must be 1 to 40 lowercase letters, digits or dashes")
    return name


def _write(path: Path, data: Any) -> None:
    fsutil.atomic_write_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                              mode=0o600)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _child(folder: Path, name: str) -> Path | None:
    """A subfolder found by listing, never by joining a requested name."""
    try:
        return next((p for p in folder.iterdir() if p.is_dir() and p.name == name), None)
    except OSError:
        return None


# projects -------------------------------------------------------------------------------------
def load_projects(home: Path | None = None) -> dict[str, dict]:
    data = _read(store_dir(home) / "projects.json")
    if not isinstance(data, dict):
        return {}
    out = {}
    for name, entry in data.items():
        if isinstance(name, str) and NAME_RE.match(name) and isinstance(entry, dict):
            out[name] = {"hosts": [h for h in entry.get("hosts") or [] if isinstance(h, str)],
                         "signin_hosts": [h for h in entry.get("signin_hosts") or [] if isinstance(h, str)]}
    return out


def get_project(home: Path | None, name: Any) -> dict:
    projects = load_projects(home)
    if not isinstance(name, str) or name not in projects:
        raise NotFound("no such project")
    return projects[name]


def _hosts(value: Any, what: str, *, required: bool) -> list[str]:
    if value is None:
        value = []
    if not isinstance(value, list) or len(value) > MAX_HOSTS:
        raise WebtestError(f"{what} must be a list of up to {MAX_HOSTS} host names")
    hosts = list(dict.fromkeys(check_host(h) for h in value))
    if required and not hosts:
        raise WebtestError(f"{what} needs at least one host")
    return hosts


# The console handles requests on several threads; two saves must not read the same old file.
_PROJECTS_LOCK = threading.Lock()


def save_project(home: Path | None, name: Any, hosts: Any, signin_hosts: Any = None) -> dict:
    """Create or edit a project's hosts. Called by the console only: no CLI command writes hosts."""
    name = check_name(name, "project")
    entry = {"hosts": _hosts(hosts, "hosts", required=True),
             "signin_hosts": _hosts(signin_hosts, "signin_hosts", required=False)}
    root = ensure_store(home)
    with _PROJECTS_LOCK:
        data = _read(root / "projects.json")
        data = data if isinstance(data, dict) else {}
        data[name] = entry
        _write(root / "projects.json", data)
    return {"name": name, **entry}


# scenarios ------------------------------------------------------------------------------------
def scenario_hash(scenario: dict) -> str:
    return hashlib.sha256(json.dumps(scenario, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _line(value: Any, what: str, cap: int) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str) or len(value) > cap or "\n" in value or "\r" in value:
        raise WebtestError(f"{what} must be one line of up to {cap} characters")
    return value.strip()


def check_scenario(data: Any, project: dict) -> dict:
    """A draft from the agent: known keys only, every URL on the project's hosts or sign-in hosts."""
    if not isinstance(data, dict):
        raise WebtestError("the scenario must be a JSON object")
    extra = set(data) - SCENARIO_KEYS
    if extra:
        raise WebtestError(f"unknown scenario keys: {', '.join(sorted(extra))}")
    name = check_name(data.get("name"), "scenario name")
    if name == NO_SCENARIO:
        raise WebtestError("the scenario 'none' is built in")
    allowed = project["hosts"] + project["signin_hosts"]
    out: dict[str, Any] = {"name": name, "label": _line(data.get("label"), "label", 100) or name}
    for key in ("login_url", "signout_url"):
        url = _line(data.get(key), key, 2000)
        if url and not url_on_hosts(url, allowed):
            raise WebtestError(f"{key} is not on the project's hosts or sign-in hosts")
        out[key] = url
    steps = data.get("steps") or []
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise WebtestError(f"steps must be a list of up to {MAX_STEPS} lines")
    out["steps"] = [s for s in (_line(s, "a step", 300) for s in steps) if s]
    check = data.get("signed_in_check")
    if check is not None:
        if not isinstance(check, dict) or set(check) - {"url", "text"}:
            raise WebtestError("signed_in_check must be {url, text}")
        url = _line(check.get("url"), "signed_in_check.url", 2000)
        if url and not url_on_hosts(url, project["hosts"]):
            raise WebtestError("signed_in_check.url is not on the project's hosts")
        out["signed_in_check"] = {"url": url, "text": _line(check.get("text"), "signed_in_check.text", 200)}
    else:
        out["signed_in_check"] = {"url": "", "text": ""}
    out["account_hint"] = _line(data.get("account_hint"), "account_hint", 300)
    return out


def _project_folder(home: Path | None, project: str, create: bool = False) -> Path | None:
    login = store_dir(home) / "login"
    found = _child(login, project)
    if found is None and create:
        ensure_store(home)
        found = login / project
        fsutil.owner_only_dirs(found)
    return found


def _scenario_folder(home: Path | None, project: str, name: str) -> Path:
    folder = _project_folder(home, project)
    found = _child(folder, name) if folder else None
    if found is None:
        raise NotFound("no such scenario")
    return found


def _view(folder: Path) -> dict | None:
    scenario = _read(folder / "scenario.json")
    if not isinstance(scenario, dict):
        return None
    digest = scenario_hash(scenario)
    approval = _read(folder / "approval.json") or {}
    rejection = _read(folder / "rejection.json")
    return {**scenario, "hash": digest, "approved": approval.get("hash") == digest,
            "approved_at": approval.get("approved_at") if approval.get("hash") == digest else None,
            "rejection": rejection if isinstance(rejection, dict) else None}


def list_scenarios(home: Path | None, project: str) -> list[dict]:
    get_project(home, project)
    folder = _project_folder(home, project)
    out = []
    try:
        children = sorted(p for p in folder.iterdir() if p.is_dir()) if folder else []
    except OSError:
        children = []
    for child in children:
        if NAME_RE.match(child.name):
            view = _view(child)
            if view is not None:
                out.append(view)
    return out


def get_scenario(home: Path | None, project: str, name: Any) -> dict:
    get_project(home, project)
    if name == NO_SCENARIO:
        return {"name": NO_SCENARIO, "label": NO_SCENARIO, "steps": [], "approved": True, "builtin": True}
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise NotFound("no such scenario")
    view = _view(_scenario_folder(home, project, name))
    if view is None:
        raise NotFound("no such scenario")
    return view


def is_approved(home: Path | None, project: str, name: str) -> bool:
    try:
        return bool(get_scenario(home, project, name)["approved"])
    except WebtestError:
        return False


def save_draft(home: Path | None, project: Any, data: Any) -> dict:
    project = check_name(project, "project")
    scenario = check_scenario(data, get_project(home, project))
    scenario["created_at"] = now_iso()
    folder = _project_folder(home, project, create=True)
    target = _child(folder, scenario["name"])
    if target is None:
        target = folder / scenario["name"]
        fsutil.owner_only_dirs(target)
    _write(target / "scenario.json", scenario)
    for stale in ("approval.json", "rejection.json"):
        (target / stale).unlink(missing_ok=True)
    return _view(target)


def approve(home: Path | None, project: str, name: str, digest: Any, by: str | None) -> dict:
    folder = _scenario_folder(home, project, name)
    view = _view(folder)
    if view is None or digest != view["hash"]:
        raise Conflict("the scenario changed since you opened it; reload and check it again")
    _write(folder / "approval.json", {"hash": view["hash"], "approved_at": now_iso(), "by": by})
    (folder / "rejection.json").unlink(missing_ok=True)
    return _view(folder)


def reject(home: Path | None, project: str, name: str, note: Any, by: str | None) -> dict:
    folder = _scenario_folder(home, project, name)
    if not isinstance(note, str) or not note.strip() or len(note) > 2000:
        raise WebtestError("a rejection needs a note of up to 2000 characters")
    (folder / "approval.json").unlink(missing_ok=True)
    _write(folder / "rejection.json", {"note": note.strip(), "rejected_at": now_iso(), "by": by})
    return _view(folder)


def remove(home: Path | None, project: str, name: str) -> dict:
    folder = _scenario_folder(home, project, name)
    shutil.rmtree(folder)
    return {"removed": name}
