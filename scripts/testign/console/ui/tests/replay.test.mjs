import assert from 'node:assert/strict';
import { test } from 'node:test';

import { render as renderRun } from '../views/run.mjs';
import { recipeSection, recipeState, render as renderScenarios } from '../views/scenarios.mjs';
import { stepText } from '../views/spec-steps.mjs';
import { render as renderSuite } from '../views/suite.mjs';
import { installFakeDocument } from './fake-dom.mjs';
import { byData, DICTS, fakeContext, translator } from './web-helpers.mjs';

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

const STEPS = [
  { action: 'goto', value: '/mypage' },
  { action: 'expect_text', locator: { role: 'banner' }, value: '予約履歴' },
];

test('a step reads as action, locator and value', () => {
  assert.equal(stepText(STEPS[0]), 'goto → /mypage');
  assert.equal(stepText({ action: 'click', locator: { role: 'button', name: 'Sign in' } }), 'click role="button" name="Sign in"');
  assert.equal(stepText({ action: 'fill', locator: { label: 'Password' }, value: '{{password}}' }), 'fill label="Password" → {{password}}');
});

const RECIPE = { exists: true, profile: 'member01', placeholders: ['password', 'username'], profile_set: true, missing_values: [],
  fingerprint: 'f1', steps: [{ action: 'fill', locator: { label: 'Password' }, value: '{{password}}' }],
  test: { ok: true, at: '2026-11-26T10:00:00+09:00' }, tested: true, approved: false, usable: false };

test('a recipe is usable only after its values, a passing test and the approval', () => {
  assert.equal(recipeState(null), 'none');
  assert.equal(recipeState({ ...RECIPE, profile_set: false }), 'values');
  assert.equal(recipeState({ ...RECIPE, missing_values: ['password'] }), 'values');
  assert.equal(recipeState({ ...RECIPE, tested: false }), 'test');
  assert.equal(recipeState(RECIPE), 'approve');
  assert.equal(recipeState({ ...RECIPE, approved: true }), 'usable');
  installFakeDocument();
  const t = translator('en');
  const shown = recipeSection(t, { ...RECIPE, profile_set: false, missing_values: ['password', 'username'] });
  assert.ok(shown.textContent.includes('profile-set --project <project> --profile member01'));
  assert.ok(shown.textContent.includes('{{password}}'));
});

test('approving a recipe sends the fingerprint the tester saw', async () => {
  const sent = [];
  const scenarios = { scenarios: [{ name: 'member', label: 'Member', approved: true, hash: 'h1', steps: [], recipe: RECIPE }] };
  const api = { projects: async () => ({ projects: [{ name: 'demo', hosts: ['dev.example.test'] }] }), scenarios: async () => scenarios,
    approveRecipe: async (...args) => { sent.push(args); return { ...RECIPE, approved: true }; } };
  const { ctx, view, ready } = fakeContext(api);
  renderScenarios(ctx);
  await ready;
  const row = byData(view, 'scenario').find((el) => el.tagName === 'TR' && el.dataset.scenario === 'member');
  row.listeners.click[0]({ target: row });
  const body = globalThis.document.body;
  assert.equal(byData(body, 'recipeState')[0].dataset.recipeState, 'approve');
  const [approve] = byData(body, 'approveRecipe');
  approve.listeners.click[0]();
  await tick();
  assert.deepEqual(sent, [['demo', 'member', 'f1']]);
});

function runOf(replay) {
  const cases = [{ row: 'r01', content: 'Header label', state: 'queued', class: 'sure', scenario: 'none', screen: { url: '/', name: '', confidence: 'high' },
    attempt: 0, evidence: [], capture: null, question: null }];
  return { id: 'W20261126-1000-demo', name: 'Round 2', project: 'demo', hosts: ['dev.example.test'], template: 'web', confirmed: true,
    signed_in: null, closed: null, exports: [], counts: { queued: 1 }, open: 1, cases, jobs: [], finish: null, waiting_on_tester: 0, replay };
}

test('the Run screen offers Record and Replay only when rows can take them, and queues the mode', async () => {
  const quiet = runOf({ spec: 'missing', recordable: 0, replayable: 0 });
  const a = fakeContext({ run: async () => quiet }, { route: { params: { run: quiet.id }, query: {} } });
  renderRun(a.ctx);
  await a.ready;
  assert.deepEqual(byData(a.view, 'runAction').map((el) => el.dataset.runAction), ['columns', 'export', 'run']);

  const run = runOf({ spec: 'reviewed', recordable: 1, replayable: 1 });
  const queued = [];
  const b = fakeContext({ run: async () => run, createJob: async (body) => { queued.push(body); return { id: 'j1', kind: 'webtest-run' }; } }, { route: { params: { run: run.id }, query: {} } });
  renderRun(b.ctx);
  await b.ready;
  const actions = byData(b.view, 'runAction');
  assert.deepEqual(actions.map((el) => el.dataset.runAction), ['columns', 'export', 'record', 'replay', 'run']);
  assert.ok(actions[3].textContent.includes('Replay 1'));
  actions[3].listeners.click[0]();
  for (let i = 0; i < 5 && !queued.length; i += 1) await tick();
  assert.equal(queued.length, 1);
  assert.equal(queued[0].mode, 'replay');
  assert.equal(queued[0].run, run.id);
});

function suiteWithSpec(spec) {
  const c = { case: 'c1', trace: ['B1'], source: {}, content: 'Header label', preconditions: '', steps: '', expected: 'Reads 予約履歴',
    screen: { url: '/mypage', name: 'My Page', confidence: 'high' }, viewport: 'pc', mobile_method: null, class: 'sure',
    runner: 'agent', scenario: 'none', creator: 'agent' };
  return { id: 'S20261126-1000-spec', name: 'Booking header', project: 'demo', kind: 'manual', state: 'ready', case_lang: 'ja',
    source: { kind: 'manual' }, created_at: '2026-11-26T10:00:00+09:00', cases: [c], coverage: null, runs: [], generate: null,
    suite_digest: 'd1', spec };
}

test('the suite spec tab lists the steps and reviews the hash it shows once the check passed', async () => {
  const spec = { exists: true, hash: 'abc', status: 'draft', check: { status: 'passed' }, recorded: 1, eligible: 1, reviewed: null,
    cases: [{ case: 'c1', content: 'Header label', expected: 'Reads 予約履歴', scenario: 'none', steps: STEPS, changed: false,
      not_eligible: null, check: { result: 'ok' }, warnings: [{ step: null, kind: 'no_value_check' }] }] };
  const sent = [];
  const suite = suiteWithSpec(spec);
  const { ctx, view, ready } = fakeContext({ suite: async () => suite, scenarios: async () => ({ scenarios: [] }),
    reviewSpec: async (...args) => { sent.push(args); return { ...spec, status: 'reviewed' }; } },
  { route: { params: { suite: suite.id }, query: { tab: 'spec' } } });
  renderSuite(ctx);
  await ready;
  assert.equal(byData(view, 'specStatus')[0].dataset.specStatus, 'draft');
  assert.deepEqual(byData(view, 'specCase').map((el) => el.dataset.specCase), ['c1']);
  assert.ok(view.textContent.includes('expect_text role="banner" → 予約履歴'));
  assert.ok(view.textContent.includes(DICTS.en.spec_warn_no_value_check));
  const [review] = byData(view, 'specAction');
  assert.notEqual(review.disabled, true);
  review.listeners.click[0]();
  await tick();
  assert.deepEqual(sent, [[suite.id, 'abc']]);
});

test('the review waits for a passing check', async () => {
  const spec = { exists: true, hash: 'abc', status: 'draft', check: { status: 'stale' }, recorded: 1, eligible: 1, reviewed: null, cases: [] };
  const suite = suiteWithSpec(spec);
  const { ctx, view, ready } = fakeContext({ suite: async () => suite, scenarios: async () => ({ scenarios: [] }) },
    { route: { params: { suite: suite.id }, query: { tab: 'spec' } } });
  renderSuite(ctx);
  await ready;
  const [review] = byData(view, 'specAction');
  assert.equal(review.disabled, true);
  assert.equal(review.getAttribute('title'), DICTS.en.spec_review_needs_check);
});
