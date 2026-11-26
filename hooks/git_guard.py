#!/usr/bin/env python3
"""PreToolUse hook: block source-control changes in customer repositories on the guard list.

The policy is ``scripts/testign/git_guard.py``. With an empty guard list the hook returns at once.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from testign import git_guard  # noqa: E402

if __name__ == "__main__":
    sys.exit(git_guard.main())
