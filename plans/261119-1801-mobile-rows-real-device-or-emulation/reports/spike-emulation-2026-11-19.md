# Spike: phone-width emulation for the agent (2026-11-19)

Site: `https://dev.u-supp-u.devkarte.jp` (phone layout under 600 px). Machine: macOS, Google
Chrome 157.0.8103.79 with Claude in Chrome, Claude desktop app. Pages: `/about-us` (public) and
`/reservation` (needs the `client` sign-in; the tester was not signed in during the spike).

## Results

| # | Backend | Width seen by the page | Phone layout | Read text | Click / scroll | Evidence on disk | Sign-in reuse | Debug connection | Result |
|---|---|---|---|---|---|---|---|---|---|
| B | Claude in Chrome `resize_window` 390×844 | 1680 (unchanged) | no | — | — | — | — | no | **Fail** (same as item G) |
| D | Claude in Chrome, same-origin `<iframe>` 390×844 replacing the tab's own document | 390 | yes (`max-width: 599px` matches, menu button) | only through the frame's `contentDocument` (page script); `read_page`, `find`, `get_page_text` see nothing inside the frame | yes (menu opened, wheel scroll moved the frame to `scrollY` 1000) | yes (`zoom` with `save_to_disk` on the frame region) | expected (same origin, first-party cookies); not verified signed in | no | **Pass, with limits** |
| C | Built-in browser pane of the desktop app, `resize_window` preset `mobile` | 375 | yes | yes (`read_page` lists 「メニューを開く」) | not tried beyond reading | screenshot only inline; the harness keeps a copy under `tool-results/` | no (own cookie jar; the tester signs in inside the pane) | no | **Pass, with limits** |
| A | Chrome DevTools MCP attached to the tester's Chrome | — | — | — | — | — | yes | yes | **Not tried**: not configured; needs `claude mcp add` of `chrome-devtools-mcp`, a session restart and remote debugging turned on in Chrome |

## Limits

- **D:** needs two page scripts: one that replaces the run-host page's document with a 390-px
  frame of the screen URL, one that reads the frame's text. The worker brief forbids page scripts
  today, so it needs a narrow, written exception. The user agent stays desktop and there is no
  touch emulation, so a site that switches on user agent rather than width would differ. Links
  with `target="_blank"` open full width outside the frame. A site that sends
  `X-Frame-Options: DENY`, a `frame-ancestors` CSP or frame-busting script cannot be framed; the
  worker must detect that (frame width or `contentDocument` missing) and return `blocked-env`.
  Browser autofill can fill the sign-in form inside the frame; the worker must never read it.
- **C:** only inside the Claude desktop app; the emulated size is cleared when the turn ends or
  the pane's width changes, so it is set again for every row; it is not known whether a worker
  subagent gets the pane's tools; the tester must sign in again inside the pane, which splits the
  sign-in flow from the tester's Chrome.
- **A:** the only full emulation (UA, touch, DPR) in the tester's own Chrome, at the cost of a
  debug connection, which the web test plan excluded.

## Recommendation

Use **D** as the emulation backend: it works in the tester's own Chrome with the existing worker
tools, keeps the tester's sign-in, needs no setup and no debug connection. Record the emulated
width and "desktop user agent" in `actual`. Keep A as a later option if a site needs a real
mobile user agent. C is not used: its separate sign-in and per-turn reset do not fit the run job.

Phase 4 changes accordingly: the worker frames the screen itself (no new tools), the brief gets a
scoped page-script exception for the frame and for reading its text, and a framing failure is
`blocked-env`, which the capability fallback hands to the tester.

## Open

- Sign-in reuse inside the frame on `/reservation` while signed in as `client` (to verify in
  phase 4's dry run).
- The tester accepts the page-script exception for D.
