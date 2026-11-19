# Spike report: detached console server on macOS

Date: 2026-11-19, 09:41–09:46 (Asia/Tokyo)
Gate: phase 1, "Gate: Windows and macOS spike"
Script: `plans/261118-1431-testign-console/spike/console_spike.py`

## Outcome

macOS passes the gate in **detached mode**. The spike server, started with
`start_new_session=True`, outlived the Bash call that started it and kept answering across
separate Bash calls for 95.8 seconds, until it was stopped on purpose. The real console server
(`testign console start`) behaved the same way. The fallback mode is not needed on macOS. With
the Windows result from 2026-11-18, the gate is closed for both platforms.

## Environment

- Machine: the user's Mac, macOS 26.7.1 (build 25G241).
- Runtime: Claude Code in the Claude desktop app (Code tab), working in a git worktree. Each
  step ran as a separate call of the Bash tool (zsh).
- `python3`: CPython 3.14.4 from python.org (`/Library/Frameworks/Python.framework`). No venv
  launcher, so `Popen.pid` and the server's own pid are the same here.
- Git: 2.50.1 (Apple Git-155).

## Steps and outputs

### First run (stopped after 45 s, too early for the 60 s check)

`start` at 09:41:54 → child pid 96749, flags `["start_new_session"]`, `answering: true`.
`check` at 09:42:02 and 09:42:22 → `alive: true`. `ps` showed the child with parent pid 1
(re-parented to launchd) in its own process group. Stopped at 09:42:39 with 44.5 s uptime.

### Second run (survival past 60 s)

`start` at 09:42:50 → child pid 700. A later Bash call, run in the background so it could wait,
checked at 09:44:26:

```json
{"alive": true, "health": {"pid": 700, "uptime_s": 95.8}, "checked_at": "2026-11-19T09:44:26"}
```

then `stop` → `{"stopped": true, "still_answering": false}`. Afterwards nothing listened on
port 4799 and pid 700 was gone.

### git

```json
{
  "git_without_flag": {"creationflags": 0, "returncode": 0, "stdout": "git version 2.50.1 (Apple Git-155)", "ms": 23},
  "git_with_CREATE_NO_WINDOW": {"creationflags": 0, "returncode": 0, "stdout": "git version 2.50.1 (Apple Git-155)", "ms": 20}
}
```

Creation flags do not exist on POSIX; macOS opens no terminal window for a child process.

### browser

`{"webbrowser_open_returned": true}`. The user was not watching the screen at the time, so
nobody confirmed that the tab appeared. The real console was opened in the Claude desktop app's
browser pane instead (`console start --no-browser`, then `console open --print`).

### Real console server

With an isolated `HOME` (scratch folder) and `console.port` 4795:

- `console start --no-browser` → `{reused: false, mode: "detached", version: "0.3.0"}`; the
  server's parent pid was 1 and it answered `console status` from the next Bash call.
- A second `console start` → `reused: true`; still one `console serve` process.
- `console/` is mode 0700; `server.json` and `server.log` are 0600.
- The server stayed up for about 17 minutes across many separate Bash calls during the manual
  round, then `console stop` ended it cleanly.

## Decision

Phase 1 uses detached mode on macOS with `start_new_session=True`, as already implemented. No
change to the code is needed.

## Not covered

- Visual confirmation that `webbrowser.open` showed a tab in the default browser.
- Claude Code as a CLI in Terminal.app rather than the desktop app.
- Survival after the Claude Code session ends, and the 30-minute idle exit.
