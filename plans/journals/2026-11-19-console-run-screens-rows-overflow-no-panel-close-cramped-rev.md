---
title: "Console run screens: rows overflow, no panel close, cramped review table"
date: 2026-11-19
summary: "Kestrel nowrap outranked .wrap-cell; added row panel close, one-line count strip, wider review-table selects"
---

# Console run screens: rows overflow, no panel close, cramped review table

## What happened
Four UI defects on the web test run screens. Run rows with long URLs spilled into the next columns.
Cause: Kestrel's `.k-table td { white-space: nowrap }` (specificity 0,1,1) outranked `.wrap-cell` (0,1,0).
At the same time `overflow-wrap: anywhere` shrank the cell's min-content, so the column stayed narrow
and the text that would not wrap overflowed into the neighbouring cells. The row panel had no close
control. The stacked count badges wrapped into a column. Review-table selects were `width: 100%`,
which let the Scenario column shrink to 128px and cut off "Public pages, no sign-in".

## Changes
- `app.css`: `.k-table td.wrap-cell`, vertical padding on run and review tables, `.page-wide`,
  `width: auto` selects (128–320px), `.count-strip`.
- `views/run.mjs`: a close button in the row panel head, plus Esc through `pushEscape`.
- `views/runs.mjs`: `countStrip` replaces `countBadges`, with an icon, a number, and the state name as tooltip and sr-only text.
- `views/review-table.mjs`: the viewport `td` no longer uses `display: flex`.

## Verification
Before/after Playwright run on a scratch server. Old code: 1 overflowing cell, no close button, scenario select 128px.
New code: 0 overflowing cells, close button and Esc work, select 174px. 93 UI unit tests and 524 pytest pass.

## Next steps
None required. The run table scrolls sideways when the panel is open on narrow widths (accepted by the request).

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
