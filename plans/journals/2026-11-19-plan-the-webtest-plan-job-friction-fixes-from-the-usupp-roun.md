---
title: Plan the webtest plan-job friction fixes from the USUPP round
date: 2026-11-19
summary: "Three plan jobs for one Figma table led to a six-phase plan: import copy, one-call table read, tab-age notice, review refusals, export fixes, update docs"
---

# Plan the webtest plan-job friction fixes from the USUPP round

## What happened

The first real `webtest-plan` round (USUPP change table `6647:118139`, 45 rows, symbolic base URL)
needed three plan jobs before the review table was confirmed and the workbook exported.

- Job 1 failed: the tester's console tab was minted at 22:03:55, after the job was queued at
  21:53:13, so five answers came back `403 session-too-new`. The agent's held `console ask` never
  learned about it; the tester said so in the chat.
- Job 2 failed: the first staging pass had no captures (Python `urllib` got empty bodies from the
  Figma asset URLs; `curl` worked), and staging again silently ignored `--capture` because
  `webtest-stage` returned `again: true` before writing it. Fixed in `d08e4cd` (PR #5).
- Job 3 succeeded with run `W20261119-2215-usuppu-6647-118139` (45 rows, 45 captures).
- One `get_design_context` on the whole table returned every row's text and capture URL, where the
  skill prescribes two calls per row (90 calls).

## Decision

Plan `plans/261119-1612-webtest-plan-job-friction/` in six phases: `webtest-new --from-run`,
a `webtest-table` helper for the one-call read, a tab-age notice plus `refused_tab` for the agent
(auto re-queue), refusals for a not-web runner and a pc method at UI/server/`webtest-plan`, export
placeholders and relative capture links (no Pillow), README update section and version 0.5.1.

## Next steps

Implement with `/ak-cook plans/261119-1612-webtest-plan-job-friction/plan.md`; chains {1,2},
{3,4} and 5 can run in parallel.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
