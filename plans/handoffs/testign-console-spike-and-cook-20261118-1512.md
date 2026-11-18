---
handoff-version: 1
generated: 2026-11-18T15:12:00Z
generator: ak-handoff
focus: "Continue the testign console work from a new local Claude Code session on the user's Windows machine CloudKigo (D:\\Workspace\\testign-kit). Next step: run the phase 1 spike script, record the report, then implement with /ak-cook on plans/261118-1431-testign-console/plan.md."
workspace: KiOnCloud/testign-kit
branch: claude/relaxed-franklin-oikzoa
head: 82bd512 (before the commit that adds this file)
---

# HANDOFF: testign console — run the phase 1 spike, then implement

## Mission and current status

> Continue the testign console work from a new local Claude Code session on the user's Windows machine CloudKigo (D:\Workspace\testign-kit). Next step: run the phase 1 spike script, record the report, then implement with /ak-cook on plans/261118-1431-testign-console/plan.md.

Outcome: a local web console for the testign plugin (`/testign:console`) that browses tickets, survey reports, trace results and the scout cache, manages Excel templates, and queues survey / close / testcase jobs for the attached Claude Code session, with UI in vi, en and ja.

Done:
- Design system chosen (Kestrel) and an eight-screen mockup approved: Report, Tickets, Trace, Templates, Jobs, Close review, Scout cache, Settings, each switchable vi/en/ja.
- Six-phase plan written, red-teamed (15 findings applied), validated with the user. `ak plan validate` passes.
- Spike script written and checked on Linux (POSIX path only).

Remaining:
- Phase 1 spike on Windows (CloudKigo) and on a macOS machine, with a report.
- Phases 1–6 implementation (nothing implemented yet; no code outside `plans/` was changed).

Urgency: not stated.

## Scope and guardrails

- Workspace: `KiOnCloud/testign-kit`, branch `claude/relaxed-franklin-oikzoa`.
- In scope: everything in `plans/261118-1431-testign-console/plan.md` and its phase files, in order.
- Out of scope (plan non-goals): remote or multi-user hosting, editing or translating report content, editing Excel in the browser, any LLM call inside the server, resuming dead jobs, locking out CLI sessions outside the queue, editing config from the console.
- Constraints from the user:
  - Commits carry only the user's identity: `KiOnCloud <76955774+KiOnCloud@users.noreply.github.com>`. No `Co-Authored-By`, no session links, no AI references. Conventional commit format.
  - Do not open a pull request unless asked.
  - Repository is public: never commit customer code, specs or data; use made-up tickets (the DEMO fixtures).
  - Agent questions in console jobs follow the job's `ui_lang`; report content follows the report's `lang`.
- Safety boundaries: the console server writes only under `~/.testign-kit/console/` and `~/.testign-kit/templates/`; never commit secrets or `.env`; stop any server or watcher you start (one spike server on port 4799; the real console defaults to 4791).

## Current state

- Branch: `claude/relaxed-franklin-oikzoa` (pushed to origin).
- HEAD: `82bd512` before this handoff commit; this file and `plans/261118-1431-testign-console/mockup/` are added in the next commit by the same identity.
- Working tree: clean after that commit.
- Changed files vs `main` (`27dceec`): only under `plans/` — the plan, phase files, journal, spike script, mockup sources, this handoff.
- Untracked files: none expected.
- Intentional local modifications: no.
- Note: the branch's four earlier commits were re-authored to the user's identity and force-pushed with lease in the cloud session; if a local clone fetched the branch before that, run `git fetch origin && git reset --hard origin/claude/relaxed-franklin-oikzoa` (only on that branch, only if it has no local work).

## Decisions and rationale

| Decision | Rationale | Alternative rejected | Reference |
|---|---|---|---|
| Kestrel design system, light theme default | Densest product system with shape-coded status and split view | Yohaku (accent reserved for money), Fukidashi (BIZ UDPGothic lacks Vietnamese), Sienna (Latin-only sans, missing components) | plan.md Key decisions |
| Inter + JetBrains Mono self-hosted; Japanese from system fonts | Both have vietnamese subsets; Noto Sans JP is several MB | Ship Noto Sans JP | phase 3 |
| Python stdlib server, one per user, port 4791 | No new runtime dependency; state is per user | Port Zukai's Node server | phase 1 |
| Two credentials: agent token on `/agent/*` only; browser session via one-time launch code opened by `console start/open` | Injected text must not answer the tester's approval asks | One shared token | phase 1, red team #2 |
| Jobs are offered then claimed; held calls default 100 s | Claude Code Bash stops commands after 2 minutes by default | 9-minute held calls | phase 4, red team #1 |
| Close review: rows keyed by row id with edit; diff is the tool's preview; `wiki-update --job` checks the confirmed approval hash | As strong as qa-close's own gates | Agent-typed diff, Q-keyed rows | phase 4–6, red team #3 |
| `base_revision` on writing jobs, fail `revision-moved` | Prevents splitting report history | Pin revision only | phase 4 |
| Trace always needs a template; header mismatch warning | Workbooks do not record their template | Default template silently | phase 2 |
| Tickets shows question count, not "open questions" | Reports do not mark answered questions machine-readably | qa-close marker | user, 2026-11-18 |
| Tester name in Settings (browser) | Needed for `approved_by` | Ask on each close | user, 2026-11-18 |
| Playwright e2e in CI as a macOS-only job | Catch CSP/layout/i18n issues | Manual only | user, 2026-11-18 |
| No native review of ja strings before release | User choice | BrSE review | user, 2026-11-18 |

## Work performed

- Scouted the plugin (`skills/`, `commands/`, `scripts/testign/`, `templates/`, `tests/`) and the reference design `KiOnCloud/zukai-kobo` (`plans/261118-0518-zukai-labs-console/`, `skills/labs/SKILL.md`).
- Built the mockup on a claude.ai Design canvas (private): https://claude.ai/artifact/FbwXMaek4XshNT2nPdpkTB. Its sources are copied to `plans/261118-1431-testign-console/mockup/` (`*.dc.html`, `canvas.json`, `ds/kestrel/tokens.css` — the generated Kestrel tokens with the Japanese font stack, needed in phase 3).
- `ak plan create` + six `ak plan add-phase`; plan written; four red-team reviewers; validation interview; `ak plan validate` → OK.
- Spike script `plans/261118-1431-testign-console/spike/console_spike.py`: on Linux, `start` then a separate `check` → `alive: true`; `git` route returned `git version 2.43.0`; `stop` closed port 4799.
- Remote Control from the cloud session could not use `D:\Workspace` on CloudKigo (listed, `not_available`; folder not hidden, desktop app up to date) — cloud use of local folders is not available to this account yet. Hence this local handoff.
- Task list (session-scoped, not persisted): phases 1–6 pending; mockup task completed.

## Verification

- Run: `ak plan validate plans/261118-1431-testign-console` → valid; whole-plan consistency sweeps after red team and validation → 0 contradictions.
- Run: spike script on Linux (POSIX branch) → works as described above.
- Not run: anything on Windows or macOS (the spike exists for that); no product code exists yet, so no pytest/node tests for the console.
- Mockup: published but never rendered or screenshotted for layout checks.

## Open risks and blockers

- The spike decides phase 1's mode per platform: if the detached child dies when the Bash call ends, use the fallback mode designed in phase 1 (harness background mode, two-hour cap). If neither works, stop and replan.
- A macOS machine is needed for the second half of the spike; which machine is not settled (CCVS065's OS unknown).
- Load-bearing assumptions are listed in plan.md (browser reaches 127.0.0.1; held calls fit the runtime limit; the model treats ticket text as data).

## Exact next actions

> Update 2026-11-18 15:25 UTC: steps 2–3 are done for Windows (`plans/261118-1431-testign-console/reports/spike-windows-2026-11-18.md`, detached mode passes; phase 1 updated to record the server's own pid). macOS spike deferred to 2026-11-19 by the user. Continue at step 4 after step 1.

1. **First safe step**: on CloudKigo, in `D:\Workspace\testign-kit`, run `git fetch origin && git checkout claude/relaxed-franklin-oikzoa && git pull`, set `git config user.name "KiOnCloud"` and `git config user.email "76955774+KiOnCloud@users.noreply.github.com"`, then read `plans/261118-1431-testign-console/plan.md` and `phase-01-console-server-and-lifecycle.md` (section "Gate: Windows and macOS spike").
2. Run the spike, each command as a separate Bash call from the repo root: `python plans/261118-1431-testign-console/spike/console_spike.py start`, `check` (immediately and again after ~60 s), `git` (ask the user whether a console window flashed for the plain call and for the `CREATE_NO_WINDOW` call), `browser` (ask whether a tab opened), `stop`. If `check` says `alive: false`, retry with `start --no-breakaway`. Optionally `start --detached` to confirm the `DETACHED_PROCESS` git-window problem.
3. Write `plans/261118-1431-testign-console/reports/spike-windows-<date>.md` with the JSON outputs and observations; decide detached vs fallback for Windows; repeat on a macOS machine when available.
4. Implement with `/ak-cook plans/261118-1431-testign-console/plan.md`, phase by phase in dependency order (1 → 2 → 3; 4 can run beside 3; then 5; then 6). Run each phase's Verification commands before marking it done.
5. Commit with the user's identity only, conventional messages, push to `claude/relaxed-franklin-oikzoa`; no PR unless asked.

## Source pointers

- Plan index: `plans/261118-1431-testign-console/plan.md` (contract, key decisions, Red Team Review, Validation Log)
- Phase files: `plans/261118-1431-testign-console/phase-01-…` to `phase-06-…`
- Spike script: `plans/261118-1431-testign-console/spike/console_spike.py`
- Mockup sources: `plans/261118-1431-testign-console/mockup/` (canvas: https://claude.ai/artifact/FbwXMaek4XshNT2nPdpkTB, private to the user)
- Kestrel design system: https://claude.ai/artifact/8zVwRX2YRdzPjEyPSVaB8i (version `1795001967-49ce`)
- Journal: `plans/journals/2026-11-18-plan-the-testign-console-and-harden-it-through-red-team.md`
- Reference design: `KiOnCloud/zukai-kobo` → `plans/261118-0518-zukai-labs-console/`, `skills/labs/SKILL.md`
- Existing code the plan builds on: `scripts/testign/{cli,config,report,templates,trace,hashcheck,cache,gitscope,xlsx}.py`, `skills/{spec-qa,qa-close,testcase}/SKILL.md`, `.github/workflows/test.yml`
