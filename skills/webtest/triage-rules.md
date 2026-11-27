# Triage rules

How the `webtest` skill drafts each case of a suite in a generate job, before the tester reviews
the suite on its Cases tab. Stage the result with `suite-stage` items that name `case`, with the
fields `kind`, `class`, `reason`, `viewport`, `steps`, `expected`, `screen`, `scenario`, `runner`;
leave out a field you have no value for.

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
- A `choice` case runs only when the tester delegates it on the Cases tab, with preconditions.
  Leave `runner` out: the tester picks the agent (delegate), themselves, or nobody. Never write
  `preconditions` for the tester.
- At confirmation a `not-web` row becomes `manual` (`motion`) or `not-applicable` (`design-only`).

## Viewport

`viewport` is `pc` or `mobile`. A row about the phone layout (a Mobile frame in the page index, or
a row marked for phones) gets `viewport: mobile`, `mobile_method: device` and `runner: tester`:
the tester checks it on a real phone and enters the result on the run screen. Keep its kind and
class. The tester may switch the case to `mobile_method: emulation` on the Cases tab and give it
to the agent, which then checks it in a 390 px phone frame of the tester's Chrome (see the worker
brief). Never propose `runner: agent` for a `device` case; the suite refuses it.

## Steps and expected

Write both in the suite's case language; keep Japanese UI labels verbatim (「予約履歴」).

- `steps`: numbered lines that start from the screen ("1. Open My Page"). Name every click. A step
  that writes data appears only on a `choice` row.
- `expected`: what the page shows when the change is in, checkable on the page ("The header link
  reads 予約履歴; 予約確認 is gone"). For a `visual` row: "matches the capture" plus the element.
- Never put an account value, a password or a one-time code in steps, expected or preconditions.

## Screen and scenario

- `screen`: `{url, name, confidence}`. `url` is a path that a run joins to its base URL (`/news`). `confidence` is `high` for a target placed through the page index, `low` for a
  proposal from the row's text and capture, `none` with an empty `url` when no screen was found.
- `scenario`: `none` for public pages; else a scenario name that `login-scenario-list` shows for the
  project (a draft counts). The tester checks it on the Cases tab, and a suite is not confirmed while
  a case the agent runs has no screen or scenario.

## Test depth

A suite has a test depth (`depth` in `suite-show`: smoke, standard or thorough; the tester picks it
when making the suite and can change it on the Checks tab). The depth decides which kit checks the
cases must cover for each control the change touches, whatever the source says.
`<run> coverage-rules` prints every rule: its id, group, the depth it is required from, and the
case it asks for.

1. **List the controls first.** Before staging cases, stage the screen's controls the change
   touches as one object, `{"controls": [...], "roles": [...]}` (roles only when the source names
   more than one role that uses the screen):

   ```json
   {"controls": [
     {"about": "Cart edit/Cart lines/[Update]", "type": "button", "action": true,
      "needs": ["Cart edit/Cart lines/[Quantity]"], "goes_to": "Checkout"},
     {"about": "Cart edit/Cart lines/[Quantity]", "type": "textbox", "required": true,
      "format": "integer", "range": {"min": 1, "max": 99}}]}
   ```

   `about` is `Screen/Area/[Control]` with the UI label verbatim. `action: true` for a button that
   does something (submit, save, search); `needs` lists the inputs it depends on. Write only what
   the source or the code states: a `format`, `range` or `length` nobody wrote down is left out,
   never guessed.
2. **Tag each case** with the check it covers: `"rule": "state.empty", "about": "<control path>"`.
   One case that also covers another check lists it in `covers`
   (`[{"rule": "action.normal", "about": "..."}]`). A rule that asks for several cases
   (`state.missing_one`: one per needed input; `validation.boundary`: the limit and the value just
   past it, per limit) needs that many tagged cases.
3. **Class of a check case.** A state check that only looks at the button (disabled, a message, no
   request) is `kind: behaviour`, `class: sure`. A check that submits data (`action.normal` of a save
   button, `robustness.double`) is `choice`, as any case that writes data. Expected results of state
   checks name the state ("[Update] is disabled"), so a replay checks it with `expect_disabled` and
   `click_blocked`.
4. **What the source does not say.** When the source does not say what the button does with empty
   or wrong input (disabled, a message, or it works), still write the case with the steps, and put
   the open question in `expected` as "Disabled, or shows a message (not stated in the source)":
   the tester decides on review. Never invent a message text.
5. **Skip on purpose.** A required check that cannot apply (the button is hidden until a line
   exists) is staged in `skips` with a one-line reason: `{"skips": [{"rule", "about", "reason"}]}`.
6. `<run> suite-coverage --suite <S>` lists every required check with its status. Before
   `suite-generated`, every one is `covered` or `skipped`; a suite with a missing check cannot be
   confirmed.

A suite made before test depth has no depth and no checks; nothing changes for it until the tester
sets one.

### Extend job

A `suite-generate` job with `params.extend: true` comes from a deeper test depth on a suite that
already has cases. Run `<run> suite-coverage --suite <S>` and add a case (or a skip with a reason)
only for each `missing` check. Do not change, re-stage or remove the cases already there, and do
not re-read the whole source unless a new case needs a detail from it.
