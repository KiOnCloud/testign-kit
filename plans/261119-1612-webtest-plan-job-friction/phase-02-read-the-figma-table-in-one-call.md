---
phase: 2
title: "Read the Figma table in one call"
status: completed
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Read the Figma table in one call

<!-- Updated: Red Team Session 1 - no Python download, validated capture URLs, two-step stage with captures, file handoff, order by No, skip staged rows, hostile fixtures -->

## Goal

Read a change table with one `get_design_context` call when it fits, and turn that output into
staged rows, each with its capture, with a CLI helper instead of an ad hoc script.

## Context

- Skill step 3 (`skills/webtest/SKILL.md:90-108`) reads per row: `get_design_context` for text and
  `get_screenshot` for the capture, 2 calls a row (90 for 45 rows). A View/Collab seat or a
  Starter plan has 20 calls a month (`SKILL.md:69-72`).
- In the USUPP round one `get_design_context` on the table frame returned ~204 KB of JSX with every
  row's text and an asset URL per capture. Claude Code did not inline it: it saved the result to a
  tool-results file and reported the path, which the agent then parsed. Row frames carry
  `data-node-id` = the row layer id from `get_metadata`; cells carry `data-name` = the header names.
- Capture URLs come from designer-controlled output and the rules forbid opening URLs outside the
  run's hosts (`references/rules.md:107-112`); `stage()` reads a capture fully before its size
  check (`webtest.py:522-525`).
- Case order after import comes from `source.no` (`webtest.py:386-389`, `:566`).

## Files to Create / Modify

- Create: `scripts/testign/figma_table.py` (parser and URL check; separate because it depends on
  an external, unpublished output shape)
- Modify: `scripts/testign/cli.py` (`webtest-table`)
- Modify: `skills/webtest/SKILL.md` step 3
- Create: `tests/test_figma_table.py` with synthetic fixtures (no customer text)

## Tasks & Steps

- [x] `figma_table.parse(context_text, metadata_xml)` (stdlib only): match `data-node-id` /
      `data-name` only in tag position and asset `const` declarations only at top level, never
      inside JSX text; refuse duplicate asset names and duplicate cells in a row; take rows from
      the metadata row layers (`<label> · <target id>`) and cross-check each id; number rows by
      the `No` cell (fallback: absolute `y`). Return `[{row, source, type, content, creator,
      capture_url}]`. An unknown shape, a row without `Content` or with empty content raises with
      a short reason (never a partial or skipped row).
- [x] Capture URL check: `https` only, host in a fixed Figma asset host list (`www.figma.com`
      `/api/mcp/asset/…` as seen in the round; extend only from evidence); anything else is
      refused before it is printed.
- [x] `webtest-table --run <r> --context <file> --metadata <file> --urls` prints
      `{rows: [{row, capture_url}]}` for rows not staged yet (rows whose `row_node` is already
      staged are skipped and listed). The agent downloads them with `curl -sSL --max-redirs 0
      --max-filesize 20M` into one folder.
- [x] `webtest-table … --captures <dir>` stages every not-yet-staged row once, with its capture
      from `<dir>/<row>.png|.jpg`, through `stage()`; a row whose capture is missing is refused,
      so no capture-less row is ever staged.
- [x] Skill step 3: call `get_design_context` on the table frame first; use the tool-results file
      path Claude Code reports as `--context` (never retype the output); when the result comes back
      inline, as metadata only, or the helper refuses the shape, fall back to the per-row reads.
      Save `get_metadata` of the table the same way for `--metadata`.
- [x] Tests: rows out of z-order numbered by `No`; multi-line content and a link inside content;
      hostile fixtures (a forged `data-name="Content"` and a second `const imgCapture…` inside a
      text node; a `file://`, `http://127.0.0.1` and foreign-host asset URL); refusal on missing
      or empty `Content`; `--urls` skips staged rows; `--captures` stages all rows with captures
      and refuses a missing one.

## Verification

- `python -m pytest tests/test_figma_table.py tests/test_webtest.py -q`
- Manual: the saved USUPP output (this session's tool-results file, not committed) parses to 45
  rows in the same order and text as run `W20261119-2215`.

## Risks

- The output shape changes with the Figma MCP version (signal: helper refusal; response: per-row
  fallback, then update the parser from the new sample).
- Another Claude Code version may inline large results instead of saving them (signal: no file
  path in the result; response: per-row fallback, the call is still counted).
- A table built with other header layer names is refused and takes the per-row path.
