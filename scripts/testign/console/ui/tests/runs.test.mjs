import assert from 'node:assert/strict';
import { test } from 'node:test';

import { hostOf } from '../hosts.mjs';
import { canRequeue, requeueBody } from '../views/job-actions.mjs';
import { checkNewRun, defaultTemplate, neededScenarios, openNewRun, templateChoices } from '../views/new-run.mjs';
import {
  checkParkAnswer, currentEvidence, fileName, filterCases, parkAnswerBody, progressOf, render as renderRun,
} from '../views/run.mjs';
import {
  activeJob, countGroups, fromChat, needsYou, resultIcons, rowStateIcon, runState, sourceLabel,
} from '../views/runs.mjs';
import { installFakeDocument } from './fake-dom.mjs';
import { byData, DICTS, fakeContext, translator, walk } from './web-helpers.mjs';

const PROJECTS = [{ name: 'demo', hosts: ['dev.example.test'], signin_hosts: [] }];
const SUITES = [{ id: 'S20261125-1000-login', name: 'Login', state: 'ready', cases: 4, project: 'demo' },
  { id: 'S20261125-1100-draft', name: 'Draft', state: 'review', cases: 2 }];

test('the new run dialog needs a ready suite, a project host, the tester and a template', () => {
  const ok = { suite: SUITES[0].id, project: 'demo', base_url: 'https://dev.example.test/app', name: '', tester: 'An', template: 'web' };
  assert.deepEqual(checkNewRun(ok, PROJECTS, SUITES), {});
  assert.equal(checkNewRun({ ...ok, suite: SUITES[1].id }, PROJECTS, SUITES).suite, 'nr_err_suite');
  assert.equal(checkNewRun({ ...ok, base_url: 'https://evil.test/' }, PROJECTS, SUITES).base_url, 'runform_err_off_host');
  assert.equal(checkNewRun({ ...ok, base_url: 'dev.example.test' }, PROJECTS, SUITES).base_url, 'runform_err_base');
  assert.equal(checkNewRun({ ...ok, base_url: 'https://evil.example\\@dev.example.test/' }, PROJECTS, SUITES).base_url, 'runform_err_base');
  assert.equal(checkNewRun({ ...ok, project: 'nope' }, PROJECTS, SUITES).project, 'runform_err_project');
  assert.equal(checkNewRun({ ...ok, name: 'x'.repeat(81) }, PROJECTS, SUITES).name, 'runform_err_name');
  assert.equal(checkNewRun({ ...ok, tester: '  ' }, PROJECTS, SUITES).tester, 'nr_err_tester');
  assert.equal(checkNewRun({ ...ok, template: '' }, PROJECTS, SUITES).template, 'runform_err_template');
});

test('the scenarios a suite needs, and the ones the project has not approved', () => {
  const cases = [{ scenario: 'client' }, { scenario: 'none' }, { scenario: null }, { scenario: 'staff' }, { scenario: 'client' }];
  assert.deepEqual(neededScenarios(cases, [{ name: 'client', approved: true }, { name: 'staff', approved: false }]),
    { names: ['client', 'staff'], missing: ['staff'] });
  assert.deepEqual(neededScenarios([], []), { names: [], missing: [] });
});

test('the new run dialog creates the run, queues it and opens it', async () => {
  const calls = [];
  const api = {
    suites: async () => ({ suites: SUITES }), projects: async () => ({ projects: PROJECTS }),
    templates: async () => ({ default: 'tc', templates: [{ name: 'tc', purpose: 'testcase' }, { name: 'web', purpose: 'webtest' }] }),
    suite: async () => ({ id: SUITES[0].id, cases: [{ scenario: 'client' }] }),
    scenarios: async () => ({ scenarios: [{ name: 'client', approved: true }] }),
    createRun: async (body) => { calls.push(['run', body]); return { run: 'W20261125-1200-login', hosts: ['dev.example.test'] }; },
    createJob: async (body) => { calls.push(['job', body]); return { id: 'j1', kind: 'webtest-run', run: body.run, state: 'queued' }; },
  };
  const { ctx, calls: seen } = fakeContext(api);
  const document = globalThis.document;
  const opened = openNewRun(ctx, { suite: SUITES[0].id });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const dialog = walk(document.body).find((el) => el.dataset && el.dataset.newRun !== undefined);
  assert.ok(dialog, 'the dialog opens');
  assert.ok(dialog.textContent.includes(DICTS.en.nr_safety_t), 'the safety note is visible');
  const [submit] = byData(document.body, 'newRunSubmit');
  submit.listeners.click[0]();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(calls, [], 'an empty base URL is refused before sending');
  const base = walk(document.body).find((el) => el.getAttribute && el.getAttribute('id') === 'nr-base_url');
  base.value = 'https://dev.example.test/';
  base.listeners.input[0]({ target: base });
  submit.listeners.click[0]();
  const made = await opened;
  assert.equal(made.run, 'W20261125-1200-login');
  assert.deepEqual(calls[0], ['run', { suite: SUITES[0].id, project: 'demo', base_url: 'https://dev.example.test/', template: 'web',
    name: undefined, tester: 'Tester' }]);
  assert.deepEqual(calls[1], ['job', { kind: 'webtest-run', ui_lang: 'en', run: 'W20261125-1200-login', tester: 'Tester', mode: 'run' }]);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(seen.navigated, ['#/runs/W20261125-1200-login']);
});

test('hostOf reads the host in lower case and ignores the port', () => {
  assert.equal(hostOf('https://Dev.Example.TEST:8443/x?y'), 'dev.example.test');
  assert.equal(hostOf('ftp://dev.example.test/'), null);
  assert.equal(hostOf('/relative'), null);
});

test('hostOf refuses URLs a browser reads with another host', () => {
  for (const url of ['https://evil.example\\@dev.example.test/login', 'https://evil.example@dev.example.test/',
    'https://dev.example.test%2F@evil.example/', 'https://dev.example.test/a b', 'https://dev.example.test/\u0000']) {
    assert.equal(hostOf(url), null, url);
  }
});

test('web test templates come first in the template list and start selected', () => {
  const listing = { default: 'tc', templates: [{ name: 'tc', purpose: 'testcase' }, { name: 'web', purpose: 'webtest' }] };
  assert.deepEqual(templateChoices(listing).map((x) => x.name), ['web', 'tc']);
  assert.equal(defaultTemplate(listing), 'web');
  assert.equal(defaultTemplate({ default: 'b', templates: [{ name: 'a' }, { name: 'b' }] }), 'b');
  assert.equal(defaultTemplate({ templates: [] }), '');
});

test('count groups fold the tester\'s verdicts into Pass and Fail', () => {
  const counts = { pass: 2, fail: 1, 'self-run': 3, parked: 1, 'awaiting-tester': 1, manual: 1, 'not-applicable': 1, 'not-run': 2 };
  const cases = [{ state: 'self-run', result: { verdict: 'pass' } }, { state: 'self-run', result: { verdict: 'fail' } },
    { state: 'self-run', result: null }];
  const groups = Object.fromEntries(countGroups(counts, cases).map((g) => [g.key, g.n]));
  assert.deepEqual(groups, { pass: 3, fail: 2, tester: 1, manual: 2, needs_you: 2, not_run: 2 });
});

test('results are status icons whose tooltip and accessible name are the state and its count', () => {
  installFakeDocument();
  const line = resultIcons(translator('en'), { pass: 4, fail: 3, 'self-run': 1, manual: 8, parked: 1, queued: 2, 'not-run': 30 });
  const items = byData(line, 'count');
  assert.deepEqual(items.map((el) => el.dataset.count), ['pass', 'fail', 'tester', 'manual', 'needs_you', 'queued', 'not_run']);
  const icons = walk(line).filter((el) => el.getAttribute && el.getAttribute('role') === 'img');
  const expect = [['st--ok', 'pass', 4], ['st--bad', 'fail', 3], ['st--busy', 'tester', 1], ['st--busy', 'manual', 8],
    ['st--warn', 'needs_you', 1], ['st--busy', 'queued', 2], ['st--busy', 'not_run', 30]];
  assert.equal(icons.length, expect.length);
  icons.forEach((el, i) => {
    const [cls, key, n] = expect[i];
    assert.match(el.getAttribute('class'), new RegExp(cls));
    assert.equal(el.getAttribute('aria-label'), `${DICTS.en[`wt_count_${key}`]} ${n}`);
    assert.equal(el.getAttribute('tabindex'), '0');
    assert.ok(walk(el).some((c) => c.getAttribute && c.getAttribute('role') === 'tooltip' && c.textContent === `${DICTS.en[`wt_count_${key}`]} ${n}`));
  });
  const fail = rowStateIcon(translator('ja'), 'fail');
  assert.equal(fail.getAttribute('aria-label'), DICTS.ja.wt_state_fail);
});

test('a run needs the tester while rows wait on them or a job asks', () => {
  const run = { counts: { parked: 1, 'awaiting-tester': 2, pass: 3 } };
  assert.equal(needsYou(run, []), 3);
  assert.equal(needsYou({ counts: {} }, [{ state: 'needs-input' }]), 1);
  assert.equal(needsYou({ ...run, closed: '2026-11-25T10:00:00+09:00' }, []), 0);
  assert.equal(runState(run, []), 'needs');
  assert.equal(runState({ counts: {} }, [{ state: 'running' }]), 'running');
  assert.equal(runState({ counts: {}, closed: 'x' }, []), 'done');
  assert.equal(runState({ counts: {} }, []), 'open');
});

test('job helpers find the open job and jobs queued from the chat', () => {
  const jobs = [{ id: 'a', state: 'done' }, { id: 'b', state: 'needs-input', ask: { type: 'sign-in' } }];
  assert.equal(activeJob(jobs).id, 'b');
  assert.equal(fromChat({ queued_by: 'agent', opened: false }), true);
  assert.equal(fromChat({ queued_by: 'agent', opened: true }), false);
  assert.equal(fromChat({ queued_by: 'tester', opened: false }), false);
  assert.equal(sourceLabel({ kind: 'figma', node: '12:34' }), 'Figma · 12:34');
});

test('queueing a web test run again keeps the same run', () => {
  const run = { kind: 'webtest-run', run: 'W20261119-1000-demo', params: { run: 'W20261119-1000-demo', tester: 'An', mode: 'run' } };
  assert.deepEqual(requeueBody(run, 'Other'), { kind: 'webtest-run', run: 'W20261119-1000-demo', tester: 'An', mode: 'run' });
  assert.equal(canRequeue(run), true);
  assert.equal(canRequeue({ kind: 'webtest-plan', state: 'failed' }), false, 'a legacy kind is shown read-only');
  assert.equal(canRequeue({ kind: 'suite-generate', state: 'failed' }), false);
});

test('a parked row answer needs an action, and preconditions when delegating', () => {
  assert.equal(checkParkAnswer({}), 'run_err_pick_action');
  assert.equal(checkParkAnswer({ action: 'delegate', preconditions: '  ' }), 'run_err_preconditions');
  assert.equal(checkParkAnswer({ action: 'delegate', preconditions: 'booking #1042' }), null);
  assert.equal(checkParkAnswer({ action: 'skip' }), null);
  assert.deepEqual(parkAnswerBody({ action: 'delegate', preconditions: ' booking #1042 ' }), { action: 'delegate', preconditions: 'booking #1042' });
  assert.deepEqual(parkAnswerBody({ action: 'self-run', preconditions: 'ignored' }), { action: 'self-run' });
});

test('row filters, progress and the evidence of the current attempt', () => {
  const cases = [
    { row: 'r01', state: 'pass' }, { row: 'r02', state: 'fail' }, { row: 'r03', state: 'parked' },
    { row: 'r04', state: 'parked', answer: { action: 'skip' } }, { row: 'r05', state: 'awaiting-tester' },
    { row: 'r06', state: 'self-run', result: { verdict: 'fail' } }, { row: 'r07', state: 'queued' },
  ];
  assert.deepEqual(filterCases(cases, 'needs').map((c) => c.row), ['r03', 'r05']);
  assert.deepEqual(filterCases(cases, 'fail').map((c) => c.row), ['r02', 'r06']);
  assert.equal(filterCases(cases, 'all').length, 7);
  assert.deepEqual(progressOf(cases), { done: 3, total: 7 });
  const c = { attempt: 2, evidence: [{ file: 'evidence/r02-a1-1.png', attempt: 1 }, { file: 'evidence/r02-a2-1.png', attempt: 2 }] };
  assert.deepEqual(currentEvidence(c), ['r02-a2-1.png']);
  assert.equal(fileName('source/r01.png'), 'r01.png');
});

test('the not-confirmed failure label and every row state read in both languages', () => {
  const keys = ['job_reason_not_confirmed', 'job_reason_not_confirmed_body', 'job_kind_webtest_plan', 'job_kind_webtest_run'];
  for (const s of ['draft', 'queued', 'running', 'parked', 'awaiting-tester', 'pass', 'fail', 'manual', 'not-applicable', 'self-run', 'not-run']) {
    keys.push(`wt_state_${s.replace(/-/g, '_')}`);
  }
  for (const lang of ['en', 'ja']) {
    for (const key of keys) assert.ok(DICTS[lang][key], `${lang} ${key}`);
  }
  assert.notEqual(translator('ja')('job_reason_not_confirmed'), translator('en')('job_reason_not_confirmed'));
});

function runWith(n) {
  const cases = [];
  for (let i = 1; i <= n; i += 1) {
    const row = `r${String(i).padStart(2, '0')}`;
    cases.push({ row, content: `Change ${i}`, state: i % 5 === 0 ? 'parked' : 'pass', class: 'sure', scenario: 'none',
      screen: { url: `/page/${i}`, name: '', confidence: 'high' }, attempt: 1, evidence: [], capture: `source/${row}.png`,
      question: i % 5 === 0 ? { id: `${row}-a1`, body: 'Which booking?', asked_at: '2026-11-19T10:00:00+09:00' } : null });
  }
  return { id: 'W20261119-1000-demo', name: 'Update 11', project: 'demo', hosts: ['dev.example.test'], template: 'web',
    confirmed: true, signed_in: null, closed: null, exports: [], counts: { pass: n - Math.floor(n / 5), parked: Math.floor(n / 5) },
    open: Math.floor(n / 5), cases, jobs: [], finish: null, waiting_on_tester: Math.floor(n / 5) };
}

test('the Run screen renders all 45 rows and offers Run when no job is open', async () => {
  const run = runWith(45);
  const { ctx, view, ready } = fakeContext({ run: async () => run }, { route: { params: { run: run.id }, query: {} } });
  renderRun(ctx);
  await ready;
  assert.equal(byData(view, 'row').filter((el) => el.tagName === 'TR').length, 45);
  const actions = byData(view, 'runAction').map((el) => el.dataset.runAction);
  assert.deepEqual(actions, ['columns', 'export', 'run']);
});

test('the Run screen has no action while it is not confirmed', async () => {
  const run = { ...runWith(3), confirmed: false };
  const { ctx, view, ready } = fakeContext({ run: async () => run }, { route: { params: { run: run.id }, query: {} } });
  renderRun(ctx);
  await ready;
  assert.deepEqual(byData(view, 'runAction'), []);
  assert.ok(view.textContent.includes(DICTS.en.run_not_confirmed));
});

test('web job kinds read as words, not as their ids', async () => {
  const { kindLabel } = await import('../views/job-actions.mjs');
  const t = translator('en');
  assert.equal(kindLabel(t, 'webtest-run'), DICTS.en.job_kind_webtest_run);
  assert.equal(kindLabel(t, 'webtest-plan'), DICTS.en.job_kind_webtest_plan);
  assert.equal(kindLabel(t, 'close'), DICTS.en.job_kind_close);
});

test('the row panel closes from its close button', async () => {
  const run = runWith(3);
  const row = run.cases[0].row;
  const { ctx, view, ready } = fakeContext({ run: async () => run, runImage: async () => 'data:image/png;base64,' }, { route: { params: { run: run.id }, query: { row } } });
  renderRun(ctx);
  await ready;
  const [close] = byData(view, 'closeRow');
  assert.ok(close, 'the open row panel has a close button');
  assert.equal(close.getAttribute('aria-label'), DICTS.en.report_close_detail);
  close.listeners.click[0]();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(byData(view, 'closeRow'), []);
  assert.equal(walk(view).filter((el) => /run-panel/.test(el.getAttribute('class') || '')).length, 0);
});
