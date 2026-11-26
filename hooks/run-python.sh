#!/bin/sh
# Run a testign hook script with the first working Python 3.10+.
#
# The python.org installer on Windows creates python.exe and py.exe but no python3, and python3 there
# is often the Microsoft Store stub, which is on PATH but does not run. So each candidate is started
# once, not only looked up.
#
# Usage: sh run-python.sh <fail-closed|fail-open> <hook script>  (the hook payload stays on stdin)
#
# With no working Python, a fail-closed hook (the git guard) exits 2 while a guard list exists, so
# Claude Code blocks the tool call and shows the message instead of skipping the guard silently.
# Without a guard list, and for fail-open hooks, it exits 0 and the tool call goes ahead.

mode="$1"
shift
for candidate in python3 python "py -3"; do
  # Word splitting of "py -3" is intended. The probe must not consume stdin.
  if $candidate -c 'import sys; sys.exit(sys.version_info < (3, 10))' </dev/null >/dev/null 2>&1; then
    exec $candidate "$@"
  fi
done

list="$HOME/.testign-kit/guarded_repos.json"
if [ "$mode" = "fail-closed" ] && [ -s "$list" ]; then
  echo "testign: no working Python 3.10+ found (tried python3, python, py -3), so the git guard for your customer repositories cannot run and this tool call is blocked. Install Python 3.10+ (python.org), open a new terminal and start Claude Code again." >&2
  exit 2
fi
exit 0
