"""Projects and login scenarios in the console: the tester edits hosts and approves checklists.

Hosts are written here only; no CLI command writes them. A scenario draft comes from the agent
(``login-scenario-save``) and is usable once the tester approves the hash they saw. Project and
scenario names from a request are matched against a pattern and resolved by listing.
"""

from __future__ import annotations

from typing import Any, Callable

from .. import login_recipe
from .. import login_scenarios as ls
from ..webtest import WebtestError
from .server import ApiError


def _call(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except ls.NotFound as exc:
        raise ApiError(404, "not-found", str(exc)) from None
    except ls.Conflict as exc:
        raise ApiError(409, "scenario-changed", str(exc)) from None
    except WebtestError as exc:
        raise ApiError(400, "bad-request", str(exc)) from None


def _by(session: str | None) -> str | None:
    from .jobs import fingerprint  # noqa: PLC0415

    return fingerprint(session)


def projects_view(home) -> dict:
    projects = ls.load_projects(home)
    out = []
    for name, entry in sorted(projects.items()):
        scenarios = _call(lambda n=name: ls.list_scenarios(home, n))
        out.append({"name": name, **entry, "scenarios": len(scenarios),
                    "approved": sum(1 for s in scenarios if s.get("approved"))})
    return {"projects": out}


def save_project(home, name: Any, body: Any) -> dict:
    body = body if isinstance(body, dict) else {}
    return _call(lambda: ls.save_project(home, name, body.get("hosts"), body.get("signin_hosts")))


def scenarios_view(home, project: Any) -> dict:
    entry = _call(lambda: ls.get_project(home, project))
    scenarios = _call(lambda: ls.list_scenarios(home, project))
    for scenario in scenarios:
        scenario["recipe"] = _call(lambda s=scenario: login_recipe.view(home, project, s["name"]))
    return {"project": project, **entry, "scenarios": scenarios,
            "profiles": _call(lambda: login_recipe.list_profiles(home, project))}


def approve_recipe(home, project: Any, scenario: Any, body: Any, session: str | None) -> dict:
    """The tester approves the recipe steps they looked at (its fingerprint); never a value."""
    fp = body.get("fingerprint") if isinstance(body, dict) else None
    try:
        return login_recipe.approve(home, project, scenario, fp, _by(session))
    except ls.NotFound as exc:
        raise ApiError(404, "not-found", str(exc)) from None
    except login_recipe.RecipeError as exc:
        raise ApiError(409, "recipe-not-ready", str(exc)) from None


def install(state) -> None:
    home = state.home
    r = state.router
    r.add("GET", "/api/webtest/projects", "browser", lambda q: projects_view(home))
    r.add("PUT", "/api/webtest/projects/:project", "browser",
          lambda q: save_project(home, q.params["project"], q.body))
    r.add("GET", "/api/webtest/login/:project", "browser", lambda q: scenarios_view(home, q.params["project"]))
    r.add("POST", "/api/webtest/login/:project/:scenario/approve", "browser",
          lambda q: _call(lambda: ls.approve(home, q.params["project"], q.params["scenario"],
                                             (q.body or {}).get("hash") if isinstance(q.body, dict) else None,
                                             _by(q.session))))
    r.add("POST", "/api/webtest/login/:project/:scenario/reject", "browser",
          lambda q: _call(lambda: ls.reject(home, q.params["project"], q.params["scenario"],
                                            (q.body or {}).get("note") if isinstance(q.body, dict) else None,
                                            _by(q.session))))
    r.add("POST", "/api/webtest/login/:project/:scenario/recipe/approve", "browser",
          lambda q: approve_recipe(home, q.params["project"], q.params["scenario"], q.body, q.session))
    r.add("DELETE", "/api/webtest/login/:project/:scenario", "browser",
          lambda q: _call(lambda: ls.remove(home, q.params["project"], q.params["scenario"])))
