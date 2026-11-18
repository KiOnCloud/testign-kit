# Third-party notices

The testign console UI (`scripts/testign/console/ui/`) ships the following third-party material.

## Kestrel design system

- Files: `scripts/testign/console/ui/vendor/kestrel/tokens.css`, `scripts/testign/console/ui/vendor/kestrel/bundle.css`
- Source: https://claude.ai/artifact/8zVwRX2YRdzPjEyPSVaB8i, version `1795001967-49ce`
- Licence: the artifact states no licence. It describes itself as modelled on the visual grammar of
  Linear "without carrying any of Linear's brand assets", and names Inter and JetBrains Mono (both
  SIL OFL) as its faces. It is vendored for this project by the project owner's decision of
  2026-11-18.
- Changes: the Google Fonts `@import` at the top of `bundle.css` is removed; the fonts below are
  self-hosted instead. Source, version, checksums and the change are recorded in
  `scripts/testign/console/ui/vendor/kestrel/LOCK.json`.

## Inter

- Files: `scripts/testign/console/ui/fonts/inter-*.woff2` (variable weight; latin, latin-ext and
  vietnamese subsets)
- Source: `@fontsource-variable/inter@5.1.0`
- Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter)
- Licence: SIL Open Font License 1.1, full text in `scripts/testign/console/ui/fonts/OFL-Inter.txt`

## JetBrains Mono

- Files: `scripts/testign/console/ui/fonts/jetbrains-mono-*.woff2` (weights 400 and 500; latin,
  latin-ext and vietnamese subsets)
- Source: `@fontsource/jetbrains-mono@5.1.0`
- Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)
- Licence: SIL Open Font License 1.1, full text in
  `scripts/testign/console/ui/fonts/OFL-JetBrainsMono.txt`
