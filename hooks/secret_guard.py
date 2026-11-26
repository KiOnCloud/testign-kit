#!/usr/bin/env python3
"""PreToolUse hook: keep Claude away from Login Recipe profiles and saved sessions.

The policy is ``scripts/testign/secret_guard.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from testign import secret_guard  # noqa: E402

if __name__ == "__main__":
    sys.exit(secret_guard.main())
