import assert from 'node:assert/strict';
import { test } from 'node:test';

import { requeueBody } from '../views/job-actions.mjs';
import { checkRunForm, hostOf, templateChoices } from '../views/run-form.mjs';
import {
  checkParkAnswer, currentEvidence, fileName, filterCases, parkAnswerBody, progressOf, render as renderRun,
} from '../views/run.mjs';
import { activeJob, countGroups, fromChat, reviewJob, sourceLabel } from '../views/runs.mjs';
import { byData, DICTS, fakeContext, translator } from './web-helpers.mjs';

const PROJECTS = [{ name: 'demo', hosts: ['dev.example.test'], signin_hosts: [] }];
const FIGMA = 'https://www.figma.com/design/AbCdEfGhIjKl/Change-table?node-id=12-34';

test('the new-run form accepts a Figma link with a node id on a project host', () => {
  const ok = { figma_url: FIGMA, project: 'demo', base_url: 'https://dev.example.test/app', name: 'Update 11', template: 'web' };
  assert.deepEqual(checkRunForm(ok, PROJECTS), {});
  assert.equal(checkRunForm({ ...ok, figma_url: 'https://www.figma.com/design/AbCdEfGhIjKl/x' }, PROJECTS).figma_url, 'runform_err_figma');
  assert.equal(checkRunForm({ ...ok, base_url: 'https://evil.test/' }, PROJECTS).base_url, 'runform_err_off_host');
  assert.equal(checkRunForm({ ...ok, base_url: 'dev.example.test' }, PROJECTS).base_url, 'runform_err_base');
  assert.equal(checkRunForm({ ...ok, project: 'nope' }, PROJECTS).project, 'runform_err_project');
  assert.equal(checkRunForm({ ...ok, name: 'x'.repeat(81) }, PROJECTS).name, 'runform_err_name');
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
  assert.equal(checkRunForm({ figma_url: FIGMA, project: 'demo', base_url: 'https://evil.example\\@dev.example.test/',
    name: 'U', template: 'web' }, PROJECTS).base_url, 'runform_err_base');
});

test('web test templates come first in the template list', () => {
  const listing = { default: 'tc', templates: [{ name: 'tc', purpose: 'testcase' }, { name: 'web', purpose: 'webtest' }] };
  assert.deepEqual(templateChoices(listing).map((x) => x.name), ['web', 'tc']);
});

test('count groups fold the tester\'s verdicts into Pass and Fail', () => {
  const counts = { pass: 2, fail: 1, 'self-run': 3, parked: 1, 'awaiting-tester': 1, manual: 1, 'not-applicable': 1, 'not-run': 2 };
  const cases = [{ state: 'self-run', result: { verdict: 'pass' } }, { state: 'self-run', result: { verdict: 'fail' } },
    { state: 'self-run', result: null }];
  const groups = Object.fromEntries(countGroups(counts, cases).map((g) => [g.key, g.n]));
  assert.deepEqual(groups, { pass: 3, fail: 2, tester: 1, manual: 2, needs_you: 2, not_run: 2 });
});

test('job helpers find the open job, the review table and jobs queued from the chat', () => {
  const jobs = [{ id: 'a', state: 'done' }, { id: 'b', state: 'needs-input', ask: { type: 'review-table' } }];
  assert.equal(activeJob(jobs).id, 'b');
  assert.equal(reviewJob(jobs).id, 'b');
  assert.equal(reviewJob([{ state: 'needs-input', ask: { type: 'sign-in' } }]), null);
  assert.equal(fromChat({ queued_by: 'agent', opened: false }), true);
  assert.equal(fromChat({ queued_by: 'agent', opened: true }), false);
  assert.equal(fromChat({ queued_by: 'tester', opened: false }), false);
  assert.equal(sourceLabel({ kind: 'figma', node: '12:34' }), 'Figma · 12:34');
});

test('queueing a web test run again keeps the same run', () => {
  const run = { kind: 'webtest-run', run: 'W20261119-1000-demo', params: { run: 'W20261119-1000-demo', tester: 'An', mode: 'run' } };
  assert.deepEqual(requeueBody(run, 'Other'), { kind: 'webtest-run', run: 'W20261119-1000-demo', tester: 'An', mode: 'run' });
  const plan = { kind: 'webtest-plan', report_lang: 'ja', params: { name: 'U', source: { kind: 'figma', url: FIGMA, node: '12:34' },
    base_url: 'https://dev.example.test/', project: 'demo', template: 'web', hosts: ['dev.example.test'] } };
  assert.deepEqual(requeueBody(plan, 'An'), { kind: 'webtest-plan', name: 'U', figma_url: FIGMA, base_url: 'https://dev.example.test/',
    project: 'demo', template: 'web', report_lang: 'ja' });
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

test('the not-confirmed failure label and every row state read in all three languages', () => {
  const keys = ['job_reason_not_confirmed', 'job_reason_not_confirmed_body', 'job_kind_webtest_plan', 'job_kind_webtest_run'];
  for (const s of ['draft', 'queued', 'running', 'parked', 'awaiting-tester', 'pass', 'fail', 'manual', 'not-applicable', 'self-run', 'not-run']) {
    keys.push(`wt_state_${s.replace(/-/g, '_')}`);
  }
  for (const lang of ['vi', 'en', 'ja']) {
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
  assert.deepEqual(actions, ['run', 'export']);
});

test('the Run screen shows the review table link while the plan job waits on it', async () => {
  const run = { ...runWith(3), confirmed: false, jobs: [{ id: 'j1', kind: 'webtest-plan', state: 'needs-input', run: 'W20261119-1000-demo',
    ask: { id: 'review-W', type: 'review-table' }, queued_by: 'agent', opened: false, created_at: '2026-11-19T10:00:00+09:00' }] };
  const { ctx, view, ready } = fakeContext({ run: async () => run }, { route: { params: { run: run.id }, query: {} } });
  renderRun(ctx);
  await ready;
  assert.equal(byData(view, 'openReviewTable').length, 1);
  assert.deepEqual(byData(view, 'runAction'), []);
});

test('web job kinds read as words, not as their ids', async () => {
  const { kindLabel } = await import('../views/job-actions.mjs');
  const t = translator('en');
  assert.equal(kindLabel(t, 'webtest-run'), DICTS.en.job_kind_webtest_run);
  assert.equal(kindLabel(t, 'webtest-plan'), DICTS.en.job_kind_webtest_plan);
  assert.equal(kindLabel(t, 'close'), DICTS.en.job_kind_close);
});
