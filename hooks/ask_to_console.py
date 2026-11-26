#!/usr/bin/env python3
"""PreToolUse hook for AskUserQuestion: while this Claude Code session works on a console job, the
question belongs in the console, where the tester who queued the job is looking.

The hook asks the running console which open job this session claimed (``console claim`` records the
Claude Code session id). When there is one, it writes the questions as a ready ask file and denies
the terminal prompt with the exact ``console ask`` command. With no console, no job, or any error,
it does nothing and the question is asked in the terminal: a broken console never blocks a question.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))


def ask_file(questions: list) -> dict:
    """The console ask for AskUserQuestion's questions (same fields; the id follows the content)."""
    clean = [{"question": q.get("question"), "header": q.get("header") or "", "options": [
        {"label": o.get("label"), "description": o.get("description") or ""} for o in q.get("options") or []
        if isinstance(o, dict)], "multiSelect": bool(q.get("multiSelect"))} for q in questions if isinstance(q, dict)]
    digest = hashlib.sha256(json.dumps(clean, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {"type": "questions", "id": f"q-{digest[:16]}", "questions": clean}


def decide(payload: dict, home: Path | None = None) -> dict | None:
    """The hook output that sends the question to the console, or None to let it through."""
    from testign.console import client, lifecycle  # noqa: PLC0415 - only when there is a question

    session = str(payload.get("session_id") or "")
    questions = (payload.get("tool_input") or {}).get("questions")
    if not session or not isinstance(questions, list) or not questions:
        return None
    if lifecycle.read_server_json(home) is None:
        return None
    found = client.claimed(session, home=home)
    if not found.get("job"):
        return None
    ask = ask_file(questions)
    folder = lifecycle.ensure_state_dirs(home) / "asks"
    folder.mkdir(exist_ok=True)
    path = folder / f"{found['job']}-{ask['id']}.json"
    lifecycle.write_secure(path, json.dumps(ask, ensure_ascii=False, indent=2))
    command = (f'"{sys.executable}" "{PLUGIN_ROOT / "scripts" / "run.py"}" console ask {found["job"]} '
               f'--session {found["session"]} --question "{path}"')
    reason = (f"You are working on the testign console job {found['job']}, so ask the tester in the console, "
              f"not in the terminal. The questions are saved as a console ask: run `{command}` (a held call; "
              "see references/console-bridge.md \"Held calls\"), and go on with the job with the answers. "
              f"Write the question text in the job's ui_lang ({found.get('ui_lang') or 'en'}). Next time use "
              "`console ask` directly.")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def main() -> int:
    try:
        out = decide(json.loads(sys.stdin.read() or "{}"))
    except Exception:  # noqa: BLE001 - fail open: the question is asked in the terminal
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
