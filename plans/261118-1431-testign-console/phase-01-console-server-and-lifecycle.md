---
phase: 1
title: "Console server and lifecycle"
status: pending
priority: P1
effort: "2d"
dependencies: []
---

# Phase 1: Console server and lifecycle

## Goal

A per-user HTTP server on 127.0.0.1 that is started, reused, found stale and stopped safely
by `testign console start|status|stop`, and refuses every request that is not from the console.

## Context

- Model: Zukai Labs phase 2 (`/home/user/kioncloud/zukai-kobo/plans/261118-0518-zukai-labs-console/phase-02-labs-server-and-read-api.md`), adapted to Python and to per-user state.
- Entry point: `scripts/run.py` → `testign.cli.main`; every subcommand prints JSON on stdout; errors go to stderr with exit 2 (`cli.py` `main`).
- Config: `config.py` merges nested objects key by key, so a new `console` object keeps old files working.

## Requirements

- [ ] Binds `127.0.0.1` only, whatever the options; sends no `Access-Control-*` header.
- [ ] Every `/api` and `/agent` route needs `X-Testign-Token`; compared with `hmac.compare_digest`.
- [ ] Request checks, in this order, before any body is read: method known for the route (`OPTIONS` → 403); `Host` is `127.0.0.1:<port>` or `localhost:<port>`; `Origin`, when present, equals `http://<Host>`; `Sec-Fetch-Site: cross-site` → 403; token; body size (1 MB JSON; uploads have their own cap in phase 2).
- [ ] Every response carries `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, plus `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`; API responses add `Cache-Control: no-store`.
- [ ] `GET /health?nonce=<n>` needs no token and answers `{version, job_open, proof: HMAC-SHA256(token, nonce)}`.
- [ ] One server per user. The port is `console.port` (default 4791); a busy port is never answered by taking the next one.
- [ ] Windows: `allow_reuse_address = False` and `SO_EXCLUSIVEADDRUSE`, so another process cannot bind the same port beside the server.
- [ ] Token: `secrets.token_urlsafe(32)`, made in the child after the bind succeeds; never on a command line or in the environment.
- [ ] State folder `~/.testign-kit/console/`: `server.json` (pid, port, instance, version, started_at, token; written to a temporary sibling then `os.replace`; mode 0600 on POSIX), `server.log` (capped at 1 MB, one rotation).
- [ ] `start`: in a cloud session (`CLAUDE_CODE_REMOTE=true`) exit 2 unless `--skip-cloud-check`; under SSH (`SSH_CONNECTION`) start and say the port must be forwarded. Read `server.json`; on connection refused, delete it only if it still names the same instance; on a live server, reuse it when its proof matches; on a version mismatch with no job open, ask it to stop and start a new one; on no answer or a wrong proof, exit 2 naming the port, `lsof -i :<port>` / `netstat -ano`, and `console.port`.
- [ ] The child is started detached with stdio discarded: POSIX `start_new_session=True`; Windows `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`. `start` waits up to five seconds for a `server.json` whose server proves itself.
- [ ] `start` and `status` print `{url: "http://127.0.0.1:<port>/#t=<token>", reused, version, port}`. The URL is printed only to stdout.
- [ ] Idle end after `console.idle_minutes` (default 30) with no token request and no agent call; a `busy()` hook (filled in phase 4) keeps it alive while a job is open.
- [ ] `stop` proves the server, then `POST /agent/shutdown`; it waits for the port to close. With a job open it needs `--force`.
- [ ] The log holds method, route pattern, status, duration and an error code; never a body, query string, token or path.

## Files to Create / Modify

- Create: `scripts/testign/console/__init__.py`
- Create: `scripts/testign/console/server.py` (handler, check chain, route table, JSON helpers, static file serving from a manifest, log)
- Create: `scripts/testign/console/lifecycle.py` (paths, port, `server.json`, proof, start, status, stop, serve, idle timer)
- Modify: `scripts/testign/cli.py` (`console start|status|stop|serve`; `serve` is what `start` runs and is hidden from help)
- Modify: `scripts/testign/config.py` (defaults: `"console": {"port": 4791, "idle_minutes": 30}`)
- Create: `tests/test_console_server.py`, `tests/test_console_lifecycle.py`

## Tasks & Steps

1. `server.py`: subclass `ThreadingHTTPServer` with `daemon_threads = True`; on Windows set `allow_reuse_address = False` and the exclusive-address socket option in `server_bind`.
2. Route table: `(method, pattern) → handler`; patterns use named segments that handlers resolve through listings (phase 2), never by joining them into paths.
3. The check chain as listed above, written once and applied before routing. Errors are `{error: {code, message}}` JSON with stable codes (`forbidden`, `not-found`, `too-large`, `bad-request`, `conflict`).
4. Static serving: at start, walk `console/ui/` and build `{url path → (file, content type)}`; anything else is 404. `index.html` gets `Cache-Control: no-store`.
5. `lifecycle.py`: start, status, stop, serve, the proof exchange and the stale-file rule exactly as the requirements say. Serve installs a 60-second timer that checks idle.
6. CLI wiring under one `console` subparser with its own subcommands; output through the existing `_emit`.

## Verification

- `python -m pytest tests/test_console_server.py tests/test_console_lifecycle.py -v`
- Tests cover: 403 without token, with a wrong token, with a foreign `Host`, with a foreign `Origin`, with `Sec-Fetch-Site: cross-site`, for `OPTIONS`; headers present on 200 and 403; a body over the cap gets 413 before it is read; `/health` proof matches; a second `start` returns `reused: true` and the same pid; a stale `server.json` with a dead pid is replaced; a foreign socket on the port makes `start` exit 2 without touching `server.json`; idle end with a short `idle_minutes`; `stop` closes the port; the log contains no token.
- On Windows CI: after `console start` returns, `GET /health` still answers (detached child survives).

## Success Criteria

Acceptance criteria 1 and 2 of the plan pass in CI on Windows and macOS.

## Risk Assessment

- Detached child killed with the parent on Windows. Signal: the Windows survival test fails. Response: document running `console serve` in the harness's background mode (two-hour cap) and keep `start` for macOS; adjust within the plan.
- Another local user on a shared machine owns port 4791. Signal: the proof fails. Response: the error names `console.port`; no automatic port change.

## Security Considerations

- Same-machine processes can read `server.json` only with the user's rights (0600 on POSIX, the profile's ACL on Windows).
- DNS rebinding is blocked by the `Host` check; CSRF by the token header, which a cross-origin page cannot set without CORS.
