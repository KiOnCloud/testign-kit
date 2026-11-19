---
phase: 6
title: "Plugin update docs and verification"
status: in-progress
priority: P2
effort: "0.5d"
dependencies: [1, 2, 3, 4, 5]
---

# Phase 6: Plugin update docs and verification

<!-- Updated: Validation Session 1 - bump to 0.5.1 -->
<!-- Updated: Red Team Session 1 - restart the console on update, README version pin -->

## Goal

Testers can update the installed plugin from the README without mixing versions, and the whole
change set is verified.

## Context

- During the USUPP round the installed plugin was 0.1.0 (cache dated 2026-11-14, no console) while
  the repo was 0.5.0. README "Install the plugin" (`README.md:50-65`) only links to the official
  docs for updates.
- Version lives in `pyproject.toml:3`, `.claude-plugin/plugin.json:3`,
  `scripts/testign/__init__.py:3`, and README pins it at `README.md:8`. `console start` only notes
  a version difference when reusing a server (`console/lifecycle.py:265-277`); `console stop`
  refuses while a job is open (`server.py:572-573`).

## Files to Create / Modify

- Modify: `README.md` (version, Update the plugin, web test helpers and export links)
- Modify: `pyproject.toml`, `.claude-plugin/plugin.json`, `scripts/testign/__init__.py`

## Tasks & Steps

- [x] Bump to 0.5.1 in the three version files and `README.md:8`; `grep -rn "0\.5\.0"` outside
      plans/ finds nothing else.
- [x] Look up the current Claude Code plugin update commands in the official docs; write "Update
      the plugin": finish or close open console jobs, `console stop`, update the marketplace and
      the plugin, `console start`, check `<run> --version`.
- [x] README web test section: `webtest-new --from-run`, `webtest-table --urls/--captures`, the
      `no-older-tab` behaviour, capture links on `No` cells and the cover placeholders.
- [ ] Full verification: Python tests, UI unit tests, e2e console tests.
- [ ] Re-run the USUPP flow with the console: plan job (one-call table read, or `--from-run`),
      a deliberately too-new tab (claim fails, re-queue), review table with a mobile→pc and a
      sure→not-web edit, export; check acceptance criteria 1–5 on real output.

## Verification

- `python -m pytest tests -q --ignore=tests/e2e`
- `python -m pytest tests/e2e -q`
- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`
