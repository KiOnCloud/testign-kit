"""Single entry point the skills call: <python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py" <subcommand>."""

import sys

if sys.version_info < (3, 10):
    sys.stderr.write(
        "testign needs Python 3.10 or newer, found %d.%d. See the README for setup.\n" % sys.version_info[:2]
    )
    sys.exit(3)

import os  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from testign.cli import main  # noqa: E402

sys.exit(main())
