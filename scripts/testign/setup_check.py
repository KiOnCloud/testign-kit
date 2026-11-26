"""``setup``: check what testign needs on this computer, install what can be installed without admin
rights, and print the commands that need them.

Checked: Python 3.10+, openpyxl (test case workbooks), and for web test replay Playwright for Python
and each browser it can start. ``--install`` runs ``pip install --user`` for missing packages and
``playwright install <browser>`` for missing Playwright browsers; Microsoft Edge is never installed
here (it is the system's Edge), and Linux system libraries need ``playwright install-deps`` as root.
"""

from __future__ import annotations

import importlib.util
import site
import subprocess
import sys
from typing import Any

MIN_PYTHON = (3, 10)
PIP_NAMES = {"openpyxl": "openpyxl", "playwright": "playwright"}


def _python() -> str:
    return sys.executable or "python3"


def _pip_install(py: str, package: str) -> dict:
    """``pip install`` into the user site, or into the virtual environment this Python runs in."""
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    done = _run([py, "-m", "pip", "install", *([] if in_venv else ["--user"]), package])
    # A user site made by this install is not on sys.path yet.
    if not in_venv:
        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            site.addsitedir(user_site)
    importlib.invalidate_caches()
    return done


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _version(module: str) -> str | None:
    try:
        from importlib.metadata import version  # noqa: PLC0415

        return version(PIP_NAMES.get(module, module))
    except Exception:  # noqa: BLE001 - not installed, or installed without metadata
        return None


def _browser(name: str) -> dict:
    from . import webtest_live  # noqa: PLC0415

    try:
        with webtest_live.playwright() as p:
            webtest_live.launch(p, browser=name).close()
        return {"ok": True}
    except webtest_live.EngineUnavailable as exc:
        return {"ok": False, "error": str(exc)[:300]}


def _run(cmd: list[str]) -> dict:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": " ".join(cmd), "ok": False, "error": str(exc)[:300]}
    tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
    return {"command": " ".join(cmd), "ok": done.returncode == 0, **({} if done.returncode == 0 else {"error": "\n".join(tail)})}


def check(webtest: bool = False, browsers: list[str] | None = None, install: bool = False) -> dict[str, Any]:
    """Every check with ``ok``; ``installed`` lists what ``install`` ran; ``todo`` the commands left
    for the tester (admin rights, or a browser this command does not install)."""
    py = _python()
    checks: list[dict] = [{"name": "python", "ok": sys.version_info[:2] >= MIN_PYTHON,
                           "version": ".".join(map(str, sys.version_info[:3]))}]
    installed: list[dict] = []
    todo: list[str] = []
    modules = ["openpyxl", *(["playwright"] if webtest else [])]
    for module in modules:
        if not _has(module) and install:
            installed.append(_pip_install(py, PIP_NAMES[module]))
        ok = _has(module)
        checks.append({"name": module, "ok": ok, "version": _version(module) if ok else None})
        if not ok:
            todo.append(f"{py} -m pip install --user {PIP_NAMES[module]}")
    if webtest and _has("playwright"):
        for name in browsers or ["chromium"]:
            result = _browser(name)
            if not result["ok"] and install and name != "msedge":
                installed.append(_run([py, "-m", "playwright", "install", name]))
                result = _browser(name)
            checks.append({"name": f"browser:{name}", **result})
            if not result["ok"]:
                if name == "msedge":
                    todo.append("install Microsoft Edge (or, with admin rights: "
                                f"{py} -m playwright install msedge)")
                else:
                    todo.append(f"{py} -m playwright install {name}")
                    if sys.platform.startswith("linux"):
                        todo.append(f"sudo {py} -m playwright install-deps {name}")
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "installed": installed,
            "todo": list(dict.fromkeys(todo))}
