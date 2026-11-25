---
phase: 5
title: "Yohaku, English and Japanese"
status: completed
priority: P1
effort: "1.25d"
dependencies: []
---

# Phase 5: Yohaku, English and Japanese

<!-- Updated: Validation Session 1 - font pipeline and asset-test lines, no inline styles from the mockup, LOCK source, --font-mono, statusIcon on top of statusGlyph, every vi consumer listed, theme control kept in Preferences as an explicit addition, THIRD_PARTY_NOTICES, Japanese fallback note -->

## Goal

The console loads Yohaku instead of Kestrel, offers English (default) and Japanese only, and the
shared table, tooltip and status-icon styles from the mockup exist for phases 6–7.

## Context

- `ui/index.html:9-11` links `/vendor/kestrel/tokens.css`, `/vendor/kestrel/bundle.css`, `/app.css`;
  `index.html:2` says `lang="vi"`. `app.css` declares Inter and JetBrains Mono, including Vietnamese
  subsets, under `ui/fonts/`.
- `tests/test_console_ui_assets.py`: `KESTREL` path (line 15), languages (16), key equality and
  placeholders against vi (35, 46, 53), no `style=` in any `.mjs` or `.html` and no `.style.` in
  modules (61-72), no `<style>` in `index.html` (78), the vendored CSS `LOCK.json` with a `source`
  that must start with `https://claude.ai/artifact/` (89-97, 91), fonts keyed by family to
  `OFL-Inter.txt` / `OFL-JetBrainsMono.txt` with absolute `url("/fonts/…")` and one `unicode-range`
  per file (107-119), the static manifest including `/fonts/inter-latin-wght-normal.woff2`,
  `/fonts/OFL-Inter.txt` and `/i18n/vi.json` (130-131). Static manifest: `server.py:156`.
- Languages: `FALLBACK = 'vi'` (`i18n.mjs:6`), `LANGS = ['vi','en','ja']` (`prefs.mjs:4`),
  `defaultLang` ends in vi (`prefs.mjs:36-45`), `lang: 'vi'` (`main.mjs:38`), `LANG_NAMES.vi`
  (`shell.mjs:9`), language radio (`shell.mjs:96-101`), three 840-key JSON files. The bridge accepts
  `ui_lang: "vi"` on jobs (`console/jobs.py:34, 891-893`), and old job records carrying it are shown
  by `jobs.mjs:162, 242, 269` and `review-table.mjs:284`. Tests naming vi: `i18n.test.mjs:8, 25-29,
  40, 51, 54`, `prefs.test.mjs:21-28`, `web-helpers.mjs:9`, `runs.test.mjs:117`.
- `dom.mjs` already has `icon()` (line 129) and `statusGlyph(shape, extra)` (line 170, used by
  `job-actions.mjs:105`).
- The mockup has 17 `style="` attributes (some inside JS templates) and a `<style>` block; it has no
  theme control, while the console today saves `testign.theme`.
- `THIRD_PARTY_NOTICES.md:7-32` names Kestrel, Inter and JetBrains Mono with their `ui/fonts/OFL-*`
  paths.

## Tasks & Steps

1. Vendor Yohaku CSS: copy `tokens.css` and `bundle.css` from `mockup/ds/yohaku/` into
   `ui/vendor/yohaku/`, write its `LOCK.json` with the real origin (qingyi-test-kit
   `qingyi/lab/static/`, with the commit it came from) and sha256 values, and change the asset test's
   `KESTREL` path and `source` rule (line 91) to accept that origin. Remove `ui/vendor/kestrel/`.
2. Fonts: copy the four Noto Sans woff2 files into `ui/fonts/` and `OFL.txt` as `OFL-NotoSans.txt`;
   write four `@font-face` rules with absolute `/fonts/` URLs and one `unicode-range` each in
   `app.css` (Yohaku's own `fonts.css` with relative URLs is not used); extend the licence map in the
   asset test (line 109) with `noto-sans`; remove every Inter and JetBrains Mono file and licence;
   update the manifest expectations (lines 130-131). Define `--font-mono` in `app.css` as the system
   `ui-monospace` stack. Japanese uses Yohaku's system fallbacks (Noto Sans JP, Hiragino, Yu Gothic,
   Meiryo; `tokens.css:34-35`), present on macOS and Windows; a Linux machine without a Japanese font
   shows missing glyphs, which is accepted and noted in the README.
3. Rewrite `app.css` on Yohaku tokens: the lab shell (top bar, 248 px sidebar with collapsible groups
   and an inset bar on the active row, one scroll container), `.tbl-box` (sideways scroll, `min-width`
   960 px, `white-space: nowrap`, 64 px rows), status icons (`.st--ok|warn|busy|bad`) and the tooltip
   rule (`.yh-tip` hidden until `:hover` or `:focus-visible` of its anchor, wrapping text). Port these
   from the mockup's `<style>` block into `app.css`. Every mockup `style="…"` becomes a named class
   (one-off widths become a few utility classes); nothing is set through `.style.` in modules.
4. Add `statusIcon(kind, iconName, tip)` to `dom.mjs`, built on `icon()` and sharing one class map
   with `statusGlyph`; it renders a focusable anchor whose `aria-label` is the tip, so the meaning is
   reachable without a mouse.
5. Languages: `LANGS = ['en','ja']`, `FALLBACK = 'en'`, `defaultLang` falls back to `en`, `main.mjs`
   starts in `en`, `index.html` says `lang="en"`, `LANG_NAMES` loses `vi`; a saved
   `testign.uiLang = "vi"` falls back to the browser list, then `en`. Delete `i18n/vi.json`. Replace
   the language radio with a select in the top bar. The bridge accepts `ui_lang` `en` or `ja` for new
   jobs; an old job record with `vi` is displayed in English.
6. Theme: the mockup has no theme control, but the console has one today; keep it as an explicit
   addition to the mockup, a light/dark segmented control in Preferences (phase 7) that drives Yohaku's
   `[data-theme="dark"]` through the existing `testign.theme` key. No top-bar toggle.
7. Update `THIRD_PARTY_NOTICES.md`: remove Kestrel, Inter and JetBrains Mono; add Yohaku and Noto Sans
   (OFL) with their paths.
8. Update every test listed above to the two-language set, with key equality and placeholders
   checked against `en`.

## Files to Create / Modify

- Create: `ui/vendor/yohaku/{tokens.css,bundle.css,LOCK.json}`, `ui/fonts/noto-sans-*.woff2`,
  `ui/fonts/OFL-NotoSans.txt`
- Delete: `ui/vendor/kestrel/`, `ui/fonts/inter-*`, `ui/fonts/jetbrains-mono-*`,
  `ui/fonts/OFL-Inter.txt`, `ui/fonts/OFL-JetBrainsMono.txt`, `ui/i18n/vi.json`
- Modify: `ui/index.html`, `ui/app.css`, `ui/dom.mjs`, `ui/i18n.mjs`, `ui/prefs.mjs`, `ui/main.mjs`,
  `ui/views/shell.mjs` (language select only), `console/server.py` (static manifest),
  `console/jobs.py` (`LANGS`), `THIRD_PARTY_NOTICES.md`, the tests listed above

## Verification

- `python -m pytest tests/test_console_ui_assets.py`
- `node --test "scripts/testign/console/ui/tests/*.test.mjs"`
- `rg -n "vi\.json|'vi'|\"vi\"" scripts/testign/console/ui` returns nothing.
- `rg -n 'style="' scripts/testign/console/ui` returns nothing.
