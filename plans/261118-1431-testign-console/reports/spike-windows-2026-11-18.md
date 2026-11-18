# Spike report: detached console server on Windows

Date: 2026-11-18, 22:15–22:17 (Asia/Saigon)
Gate: phase 1, "Gate: Windows and macOS spike"
Script: `plans/261118-1431-testign-console/spike/console_spike.py`

## Outcome

Windows passes the gate in **detached mode**. The server, started with
`CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB`, outlived the Bash
call that started it and kept answering across five later Bash calls. Breakaway was not denied,
so the `--no-breakaway` retry was not needed. The fallback mode is not needed on Windows.
`git` from the server opened no window, and `webbrowser.open` opened the default browser.

macOS is still pending, so the gate as a whole is not closed yet.

## Environment

- Machine: the user's Windows 11 Home Single Language 10.0.26200 machine.
- Runtime: Claude Code in the Claude desktop app (Code tab). Each step ran as a separate call of
  the Bash tool, which is Git Bash here.
- `python` on PATH: a venv launcher at `…\hermes-agent\venv\Scripts\python.exe`. It starts the
  real interpreter, uv's CPython 3.11.15
  (`…\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe`), as a child process.
- Git: 2.53.0.windows.3.

## Steps and outputs

### start (22:15:04)

```json
{
  "child_pid": 15396,
  "flags": ["CREATE_NO_WINDOW", "CREATE_NEW_PROCESS_GROUP", "CREATE_BREAKAWAY_FROM_JOB"],
  "breakaway_denied": false,
  "platform": "win32",
  "python": "3.11.15",
  "answering": true
}
```

### check right after start (22:15:09)

```json
{"alive": true, "health": {"pid": 17616, "uptime_s": 5.9}, "checked_at": "2026-11-18T22:15:09"}
```

### check after about 60 seconds (22:16:22)

```json
{"alive": true, "health": {"pid": 17616, "uptime_s": 79.2}, "checked_at": "2026-11-18T22:16:22"}
```

### git

```json
{
  "git_without_flag": {"creationflags": 0, "returncode": 0, "stdout": "git version 2.53.0.windows.3", "ms": 19},
  "git_with_CREATE_NO_WINDOW": {"creationflags": 134217728, "returncode": 0, "stdout": "git version 2.53.0.windows.3", "ms": 32}
}
```

The user watched the screen and saw no console window for either call.

### browser

```json
{"webbrowser_open_returned": true}
```

The user confirmed that a tab opened in the default browser and showed the pid and uptime JSON.

### stop (22:17:28)

```json
{"stopped": true, "still_answering": false}
```

Afterwards nothing was listening on port 4799 (only `TIME_WAIT` entries from the closed
connections), and neither process 15396 nor 17616 was running. `serve.log` recorded
`serve pid=17616 port=4799` at 22:15:03 and `shutdown requested` at 22:17:28.

## Findings for phase 1

1. **The pid from `Popen` may not be the server's pid.** When `python` is a venv launcher,
   `Popen.pid` (15396) belongs to the launcher, and the real server (17616) is its child. The
   launcher exits when the server exits. `server.json` must therefore record the pid the server
   reports for itself (`os.getpid()` inside `serve`, as `/health` already returns it), and
   `console stop` and stale-server checks must use that pid or `/shutdown`, never `Popen.pid`.
2. **No `git` window, with or without `CREATE_NO_WINDOW` on the call.** The server itself was
   created with `CREATE_NO_WINDOW`, so it has a hidden console that child console programs
   inherit. Keeping `CREATE_NO_WINDOW` on the server is what matters. Passing it on each
   `subprocess` call as well is harmless and guards against a future change of the server's
   flags. The difference in timing (19 ms against 32 ms) is noise.
3. **Breakaway from the job object was allowed** in the desktop app's Bash tool. The code should
   still keep the fallback to starting without `CREATE_BREAKAWAY_FROM_JOB` when `Popen` raises,
   as the spike does, because other hosts may forbid breakaway.

## Not covered

- `start --no-breakaway`: not needed, because breakaway was allowed.
- `start --detached` (adding `DETACHED_PROCESS` to confirm the git-window problem the plan cites
  for rejecting that flag): optional and not run.
- Claude Code as a CLI in a terminal window, rather than the desktop app: its Bash tool may run
  under a different job object. Not tested.
- Survival beyond about 2.5 minutes, survival after the Claude Code session ends, and the
  10-minute idle exit: none of these are part of the gate, and none were run.
- macOS: still to do on a macOS machine. Which machine is not settled.

## Decision

Phase 1 uses detached mode on Windows with the flags above and the breakaway fallback. The
fallback mode (`console serve --foreground` under the harness's background mode) stays designed
for any platform where the macOS run or a later host fails.
