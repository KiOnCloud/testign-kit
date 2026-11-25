# Third-party notices

The testign console UI (`scripts/testign/console/ui/`) ships the following third-party material.

## Yohaku design system

- Files: `scripts/testign/console/ui/vendor/yohaku/tokens.css`, `scripts/testign/console/ui/vendor/yohaku/bundle.css`
- Source: qingyi-test-kit (https://github.com/KiOnCloud/qingyi-test-kit), `qingyi/lab/static/yohaku/` at
  commit `78b044ba7f4caf77a7a33ec7232b095617d97a7a`
- Licence: the source repository states no licence. Yohaku is the design system of the qingyi lab
  console from the same organisation; it is vendored for this project by the project owner's
  decision of 2026-11-25.
- Changes: none. Yohaku's `fonts.css` is not vendored; `scripts/testign/console/ui/app.css`
  declares the same Noto Sans faces with absolute `/fonts/` URLs. Source, commit and checksums are
  recorded in `scripts/testign/console/ui/vendor/yohaku/LOCK.json`.

## Noto Sans

- Files: `scripts/testign/console/ui/fonts/noto-sans-*.woff2` (weights 400 and 700; latin and
  latin-ext subsets)
- Source: qingyi-test-kit `qingyi/lab/static/fonts/`, the files Yohaku ships
- Copyright 2022 The Noto Project Authors (https://github.com/notofonts/latin-greek-cyrillic)
- Licence: SIL Open Font License 1.1, full text in `scripts/testign/console/ui/fonts/OFL-NotoSans.txt`
- Japanese text uses the system's Japanese fonts (Noto Sans JP, Hiragino, Yu Gothic or Meiryo);
  no Japanese font is bundled.
