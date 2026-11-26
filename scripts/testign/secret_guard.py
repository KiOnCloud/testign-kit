#!/usr/bin/env python3
"""Secret guard: keep Claude away from Login Recipe profiles and saved sessions.

The PreToolUse hook ``hooks/secret_guard.py`` blocks, in every project with the plugin enabled:

* file tools (Read, Write, Edit, MultiEdit, NotebookEdit, Grep, Glob) on
  ``~/.testign-kit/webtest/profiles/`` (staging test account values) and
  ``~/.testign-kit/webtest/sessions/`` (signed-in cookies);
* Bash commands that name either folder, and the commands only the tester runs: ``profile-set``,
  ``profile-remove``;
* Bash commands that call the console's recipe approval or redeem a console link
  (``/recipe/approve``, ``/launch?code=``): the tester approves on the console.

The engine reads a profile in memory when it signs in, and Claude only runs the commands that do
that (``login-recipe-test``, ``webtest-record-*``, ``webtest-replay``); their output never holds a
value. Like the git guard this is a guardrail, not a security boundary: a profile is plain text
under file permissions, and a command that builds a path at run time can get past a text match.

Protocol (Claude Code hooks): the tool call arrives as JSON on stdin. Exit 0 allows it; exit 2
blocks it and the message on stderr is shown to Claude.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from . import login_recipe

FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit"}
SEARCH_TOOLS = {"Grep", "Glob"}
_TESTER_ONLY = re.compile(r"\bprofile-(set|remove)\b")
_CONSOLE = re.compile(r"/recipe/approve\b|/launch\?code=", re.IGNORECASE)
_DIR_TEXT = re.compile(r"\.testign-kit[/\\]+webtest[/\\]+(?:profiles|sessions)\b", re.IGNORECASE)


def protected(home: Path | None = None) -> list[Path]:
    return [login_recipe.profiles_dir(home), login_recipe.sessions_dir(home)]


def _resolve(path: str, cwd: str) -> Path:
    p = Path(os.path.expandvars(path)).expanduser()
    if not p.is_absolute():
        p = Path(cwd) / p
    return Path(os.path.normpath(str(p)))


def _norm(p: Path) -> str:
    try:
        p = p.resolve()
    except OSError:
        pass
    return os.path.normcase(str(p))


def inside(path: Path, roots: list[Path]) -> bool:
    target = _norm(path)
    for root in roots:
        base = _norm(root)
        if target == base or target.startswith(base.rstrip("\\/") + os.sep):
            return True
    return False


def _names_dir(command: str, roots: list[Path]) -> bool:
    if _DIR_TEXT.search(command):
        return True
    home = str(Path.home())
    for folder in roots:
        forms = {str(folder)}
        if str(folder).startswith(home):
            tail = str(folder)[len(home):]
            forms |= {"~" + tail, "$HOME" + tail, "${HOME}" + tail, "%USERPROFILE%" + tail}
        if any(f in command for f in forms):
            return True
    return False


def evaluate(payload: dict, home: Path | None = None) -> str | None:
    tool = payload.get("tool_name", "")
    data = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    roots = protected(home)
    if tool in FILE_TOOLS | SEARCH_TOOLS:
        target = data.get("file_path") or data.get("notebook_path") or data.get("path")
        if tool in SEARCH_TOOLS and not target:
            target = cwd
        resolved = _resolve(str(target), cwd) if target else None
        # A search over a parent folder (the home folder, ~/.testign-kit) would walk into them too.
        covers = tool in SEARCH_TOOLS and resolved is not None and any(inside(r, [resolved]) for r in roots)
        if resolved is not None and (inside(resolved, roots) or covers):
            return (f"Blocked by testign: {tool} on the Login Recipe profiles or saved sessions. They hold staging "
                    "test account values and signed-in cookies; only the engine reads them.")
        pattern = str(data.get("pattern", "")) if tool == "Glob" else ""
        if _DIR_TEXT.search(pattern) or re.search(r"webtest[/\\]+(profiles|sessions)", pattern):
            return "Blocked by testign: globbing the Login Recipe profiles or saved sessions."
    elif tool == "Bash":
        command = str(data.get("command", ""))
        if _TESTER_ONLY.search(command):
            return ("Blocked by testign: only the tester sets or removes a profile, in their own terminal. Ask them to "
                    "run the profile-set command themselves.")
        if _CONSOLE.search(command):
            return ("Blocked by testign: the tester approves recipes and opens console links in their browser; Claude "
                    "does not call those.")
        if _names_dir(command, roots):
            return ("Blocked by testign: commands that touch the Login Recipe profiles or saved sessions. Use "
                    "login-recipe-test, webtest-record-* or webtest-replay; they sign in without showing a value.")
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, UnicodeDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    message = evaluate(payload)
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0
