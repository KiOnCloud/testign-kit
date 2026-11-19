# Triage rules

How the `webtest` skill drafts each case before the review table. Write the result with
`webtest-triage` as `{"<row>": {kind, class, reason, viewport, steps, expected, screen, scenario,
runner, preconditions}}`; leave out a field you have no value for.

## Kind, class and runner

| `kind` | Signals in the row | `class` | `runner` |
|---|---|---|---|
| `label` | text or label replaced | `sure` | `agent` |
| `element` | something added or removed on a page | `sure` | `agent` |
| `visual` | logo, image, colour, layout compared with the capture | `sure` | `agent` |
| `behaviour` | navigation, new tab, sort order, shown or hidden by viewport | `sure` when no data is written, else `choice` | `agent` when `sure`; leave out when `choice` |
| `data-rule` | a rule that depends on a record's status, or needs creating, changing or cancelling data | `choice` | leave out |
| `motion` | animation, parallax, marquee | `not-web` | `none` |
| `design-only` | a component variant for which the screen method finds no page | `not-web` | `none` |

- When two kinds fit, the one lower in the table wins.
- `reason` is one line the tester can check ("text change on a visible link").
- A `choice` row runs only when the tester delegates it in the review table, with preconditions.
  Leave `runner` out: the tester picks the agent (delegate), themselves, or nobody. Never write
  `preconditions` for the tester.
- At confirmation a `not-web` row becomes `manual` (`motion`) or `not-applicable` (`design-only`).

## Viewport

`viewport` is `pc` or `mobile`. A row about the phone layout (a Mobile frame in the page index, or
a row marked for phones) gets `viewport: mobile`, `mobile_method: device` and `runner: tester`:
the tester checks it on a real phone and enters the result on the run screen. Keep its kind and
class. The tester may switch the row to `mobile_method: emulation` in the review table and give it
to the agent, which then checks it in a 390 px phone frame of the tester's Chrome (see the worker
brief). Never propose `runner: agent` for a `device` row; the review table refuses it.

## Steps and expected

Write both in the run's report language; keep Japanese UI labels verbatim (「予約履歴」).

- `steps`: numbered lines that start from the screen ("1. Open My Page"). Name every click. A step
  that writes data appears only on a `choice` row.
- `expected`: what the page shows when the change is in, checkable on the page ("The header link
  reads 予約履歴; 予約確認 is gone"). For a `visual` row: "matches the capture" plus the element.
- Never put an account value, a password or a one-time code in steps, expected or preconditions.

## Screen and scenario

- `screen`: `{url, name, confidence}`. `url` is a path on the base URL (`/news`) or an absolute URL
  on a run host. `confidence` is `high` for a target placed through the page index, `low` for a
  proposal from the row's text and capture, `none` with an empty `url` when no screen was found.
- `scenario`: `none` for public pages; else a scenario name that `login-scenario-list` shows for the
  project (a draft counts). The review table refuses any other name.
