---
phase: 1
title: "Console server and lifecycle"
status: pending
priority: P1
effort: "2.5d"
dependencies: []
---

# Phase 1: Console server and lifecycle

## Goal

A per-user HTTP server on 127.0.0.1 that is started, reused, found stale and stopped safely
by `testign console start|open|status|stop`, keeps the agent's credential apart from the
browser's, and refuses every request that is not from the console.

## Context

- Model: Zukai Labs phase 2 (`/home/user/kioncloud/zukai-kobo/plans/261118-0518-zukai-labs-console/phase-02-labs-server-and-read-api.md`), adapted to Python and to per-user state.
- Entry point: `scripts/run.py` → `testign.cli.main`; every subcommand prints JSON on stdout; errors go to stderr with exit 2 (`cli.py` `main`).
- Config: `config.py` merges nested objects key by key, so a new `console` object keeps old files working. `config.load()` creates the file when missing (`config.py:66-70`).

## Gate: Windows and macOS spike (before any other work of this plan)
<!-- Red team 2026-11-18: survival check must run inside Claude Code, not only CI -->

A half-day spike with a throwaway `serve` (bind, `/health`, idle exit) started from a real
Claude Code session's Bash tool on Windows and on macOS. Record in `reports/`:

- whether the detached child survives the end of the Bash call, with `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB` and, if breakaway is denied, without the breakaway flag;
- whether a `git` call from the child opens a visible window;
- whether `webbrowser.open` from the child's parent CLI opens the default browser.

If the child does not survive on a platform, use the fallback below on that platform and
continue; if neither mode works, stop and replan. <!-- Updated: Validation Session 1 - spike runs on the user's attached machines --> The user attaches their
Windows and macOS machines to the session through Remote Control; Claude runs the spike there
and writes the report.

**Result so far:** Windows passed in detached mode on 2026-11-18 (`reports/spike-windows-2026-11-18.md`): breakaway allowed, no git window, browser opened. macOS still to run.

**Fallback mode (designed now):** `console serve --foreground` run through the harness's
background mode. It is still one server per user (same `server.json`, same reuse rule); it
ends with the harness's two-hour cap, which fails open jobs as `server-stopped` exactly like
an idle end; `console start` reports `mode: "foreground"` and the README says to start it again
after the cap.

## Requirements

- [ ] Binds `127.0.0.1` only, whatever the options; sends no `Access-Control-*` header.
- [ ] Two credentials. <!-- Red team 2026-11-18: agent must not hold the browser credential -->
  - **Agent token**: in `server.json`; accepted on `/agent/*` only; used by the agent CLI after the `/health` proof.
  - **Browser session**: `POST /api/session {code}` exchanges a one-time launch code for a session token held in server memory only; the code is burned on first use and expires after 10 minutes. `/api/*` accepts only a browser session token (`X-Testign-Session`) and refuses the agent token.
  - Launch codes are minted by `POST /agent/launch-code` (agent token) and handed straight to `webbrowser.open("http://127.0.0.1:<port>/#c=<code>")` by `console start` and `console open`; they are never printed when the browser opens. If no browser can be opened, the URL with the code is printed once, marked single-use.
  - Every new browser session is announced in already open tabs (via `/api/state` in phase 4; a banner in stage 1 on next load).
- [ ] Request checks, in this order, before any body is read: method known for the route (`OPTIONS` → 403); `Host` name is `127.0.0.1` or `localhost`, any port (port forwarding); `Origin`, when present, equals `http://<Host>`; `Sec-Fetch-Site`, when present, is `same-origin` or `none`; credential for the route group; `Content-Type` is `application/json` on JSON bodies and `application/octet-stream` on the upload route (else 415); body size (1 MB JSON; uploads have their own cap in phase 2). <!-- Red team 2026-11-18: reference allowlist, 415, any port -->
- [ ] Every response carries `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, plus `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`; API responses add `Cache-Control: no-store`.
- [ ] `GET /health?nonce=<n>` needs no credential and answers `{version, busy, proof: HMAC-SHA256(agent token, nonce)}`.
- [ ] One server per user. The port is `console.port` (default 4791); a busy port is never answered by taking the next one.
- [ ] Windows: `allow_reuse_address = False` and `SO_EXCLUSIVEADDRUSE`, so another process cannot bind the same port beside the server.
- [ ] Tokens: `secrets.token_urlsafe(32)`, made in the child after the bind succeeds; never on a command line or in the environment; compared with `hmac.compare_digest`.
- [ ] State folder `~/.testign-kit/console/` created with mode 0700 (and its `jobs/`, `uploads/`); every state file created with `os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o600)` as a temporary sibling, then `os.replace`, retried briefly on `PermissionError` on Windows. <!-- Red team 2026-11-18: customer data at rest -->
- [ ] `server.json`: pid, port, instance, version, started_at, mode, agent token. `server.log`: capped at 1 MB, one rotation.
- [ ] The pid in `server.json` is the one the server reports for itself (`os.getpid()` inside `serve`, also returned by `/health`); `stop` and the stale-server check use that pid or `/agent/shutdown`, never `Popen.pid`, which belongs to a launcher when `python` is a venv shim. <!-- Updated: Windows spike 2026-11-18 - launcher pid differs from server pid -->
- [ ] `start`: in a cloud session (`CLAUDE_CODE_REMOTE=true`) exit 2 unless `--skip-cloud-check`; under SSH (`SSH_CONNECTION`) start and say the port must be forwarded and that `console open --print` gives a single-use URL. Read `server.json`; on connection refused, delete it only if it still names the same instance; on a live server whose proof matches, reuse it, also when its version differs (report both versions and say `console stop` replaces it when no job is open); on no answer or a wrong proof, exit 2 naming the port, `lsof -i :<port>` / `netstat -ano`, and `console.port`. `start` never stops a running server. <!-- Red team 2026-11-18: no implicit restart on version mismatch -->
- [ ] The child is started with stdio discarded: POSIX `start_new_session=True`; Windows `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB`, retried without breakaway when it is denied. `DETACHED_PROCESS` is not used: it would leave the child without a console, so every console program it runs (git) would open a window. <!-- Red team 2026-11-18: Windows git windows -->
- [ ] `start` waits up to five seconds for a `server.json` whose server proves itself, opens the browser with a fresh launch code, and prints `{reused, version, server_version, port, mode, browser_opened}` (no token, no code unless the browser could not be opened).
- [ ] `open` mints a launch code and opens the browser (for a lost tab or after a 403); `open --print` prints the single-use URL instead.
- [ ] `status` prints `{running, version, port, mode, busy}`; never a token or code.
- [ ] Idle end after `console.idle_minutes` (default 30) when there is no browser request, no agent call, no open held call and `busy()` is false; `busy()` (filled in phase 4) is true while any job is queued, offered, running or waiting for an answer. <!-- Red team 2026-11-18: queued jobs and held calls keep the server alive -->
- [ ] `stop` proves the server, then `POST /agent/shutdown`; it waits for the port to close. While `busy()` it needs `--force`.
- [ ] Logging: `log_message`, `log_error` and `handle_error` are overridden so nothing reaches stderr; `server.log` holds method, route pattern, status, duration and an error code; never a body, query string, token, code, path, header value or exception message. <!-- Red team 2026-11-18: stderr leaks -->
- [ ] The server reads config without creating it (`config.load(create=False)`; missing file → defaults in memory).

## Files to Create / Modify

- Create: `scripts/testign/console/__init__.py`
- Create: `scripts/testign/console/server.py` (handler, check chain, route groups and credentials, JSON helpers, static file serving from a manifest, scrubbed log)
- Create: `scripts/testign/console/lifecycle.py` (paths and modes, port, `server.json`, proof, start, open, status, stop, serve, launch codes, browser sessions, idle timer, secure file writes)
- Modify: `scripts/testign/cli.py` (`console start|open|status|stop|serve`; `serve` is hidden from help)
- Modify: `scripts/testign/config.py` (defaults: `"console": {"port": 4791, "idle_minutes": 30}`; `load(create=True)` keyword, default unchanged)
- Create: `tests/test_console_server.py`, `tests/test_console_lifecycle.py`

## Tasks & Steps

1. The spike gate above; record the result before step 2.
2. `server.py`: subclass `ThreadingHTTPServer` with `daemon_threads = True`; on Windows set `allow_reuse_address = False` and the exclusive-address socket option in `server_bind`; override the three log methods.
3. Route table: `(method, pattern, group) → handler`, groups `public` (static, `/health`, `/api/session`), `browser` (`/api/*`), `agent` (`/agent/*`); patterns use named segments that handlers resolve through listings (phase 2), never by joining them into paths.
4. The check chain as listed above, written once and applied before routing. Errors are `{error: {code, message}}` with stable codes (`forbidden`, `not-found`, `too-large`, `unsupported-media-type`, `bad-request`, `conflict`); messages hold no customer text.
5. Static serving: at start, walk `console/ui/` (excluding `tests/`) and build `{url path → (file, content type)}`; anything else is 404. `index.html` gets `Cache-Control: no-store`.
6. `lifecycle.py`: start, open, status, stop, serve, proof, launch codes and sessions, the stale-file rule and secure writes exactly as the requirements say. Serve installs a 60-second timer that checks idle.
7. CLI wiring under one `console` subparser; output through the existing `_emit`.

## Verification

- `python -m pytest tests/test_console_server.py tests/test_console_lifecycle.py -v`
- Tests cover: 403 without a credential, with a wrong one, with the agent token on `/api/*`, with a browser session on `/agent/*`, with a foreign `Host` name, with a foreign `Origin`, with `Sec-Fetch-Site: same-site` and `cross-site`, for `OPTIONS`; `Host` with another port is accepted; 415 for a wrong `Content-Type`; headers present on 200 and 403; a body over the cap gets 413 before it is read; `/health` proof matches; a launch code works once and not after 10 minutes; a second `start` returns `reused: true` and the same pid, also with a different version; a stale `server.json` with a dead pid is replaced; a foreign socket on the port makes `start` exit 2 without touching `server.json`; idle end with a short `idle_minutes` and no idle end while `busy()`; `stop` closes the port; `server.json` and the folder have modes 0600 and 0700 on POSIX; running `serve --foreground` prints nothing on stderr for normal and failing requests; `start` output never contains the agent token; `config.load(create=False)` does not create a file.
- On Windows CI: after `console start` returns, `GET /health` still answers; the child's creation flags do not include `DETACHED_PROCESS`.

## Success Criteria

Acceptance criteria 1 and 2 of the plan pass in CI on Windows and macOS, and the spike report says which mode each platform uses.

## Risk Assessment

- Detached child killed with the Bash call on a platform. Signal: the spike. Response: fallback mode on that platform (designed above); stop and replan only if neither mode works.
- No default browser can be opened (headless, SSH). Signal: `browser_opened: false`. Response: the single-use URL is printed once; the README explains it.
- Another local user on a shared machine owns port 4791. Signal: the proof fails. Response: the error names `console.port`; no automatic port change.

## Security Considerations

- The agent's credential reaches `/agent/*` only, so text injected into the agent cannot answer the tester's approval asks with a token it already sees.
- A same-user process that deliberately mints a launch code can still open a browser session; that is outside this design's reach (it could also read the browser's storage). Every new session is announced in open tabs so it is visible.
- DNS rebinding is blocked by the `Host` check; CSRF by the custom credential header, which a cross-origin page cannot send without CORS, plus the fetch-metadata and content-type checks.
