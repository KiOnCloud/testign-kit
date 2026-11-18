---
title: Plan the testign console and harden it through red team
date: 2026-11-18
summary: "Kestrel mockup in vi/en/ja, six-phase console plan, 15 red-team findings applied, validation decisions recorded."
---

# Plan the testign console and harden it through red team

## What happened
- Compared 22 design systems for a dense local QA console; picked Kestrel (dense tables, shape-coded status, split view). Inter and JetBrains Mono carry Vietnamese; Japanese falls back to system faces. BIZ UDPGothic has no vietnamese subset, which ruled out Fukidashi as-is.
- Built a six-screen mockup on a Design canvas (Report, Tickets, Trace, Templates, Jobs, Close review) with a vi/en/ja switcher. Kestrel publishes no tokens.css, so it was regenerated from tokens.json with a Japanese font stack.
- Wrote plans/261118-1431-testign-console: stage 1 server, read API, templates and UI; stage 2 job bridge, Jobs and Close review, console skill.

## Red team (15 accepted of 34 raw)
- Critical: held `wait` calls of 9 minutes ignore Claude Code's 2-minute default Bash timeout; a killed client keeps its held call, so jobs went to dead connections. Fixed with offered/claim states, call replacement and a 100 s default.
- One token for agent and browser let injected text answer the tester's own approval asks. Split into an agent token (/agent only) and a browser session from a one-time launch code.
- Close review was weaker than qa-close's gates; the diff is now the tool's preview output and `wiki-update --job` checks the confirmed approval hash.
- Others: trace needs an explicit template, jobs carry base_revision (revision-moved), preview() stays untouched, non-ASCII upload names, Windows DETACHED_PROCESS opens a console per git call.

## Decisions
- UI chrome follows ui_lang; report content follows report lang; agent questions follow ui_lang.
- Tickets shows question count, not "open questions"; tester name lives in Settings; e2e Playwright job on macOS CI; no native review of ja strings before release.

## Next steps
- Mock up Scout cache and Settings before phase 3.
- Phase 1 spike on the user's attached Windows and macOS machines, then implement with /ak-cook.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
