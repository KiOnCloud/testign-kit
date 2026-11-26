import assert from 'node:assert/strict';
import { test } from 'node:test';

import { bootstrap } from '../api.mjs';
import { HOME, href, legacyReviewTarget, parseRoute, redirectOf, SCREENS, sectionOf } from '../router.mjs';

test('the screens of the three menu groups parse from the hash; the home is Test suites', () => {
  assert.equal(HOME, 'suites');
  assert.deepEqual(parseRoute(''), { name: 'suites', params: {}, query: {} });
  assert.deepEqual(parseRoute('#/'), { name: 'suites', params: {}, query: {} });
  for (const name of SCREENS) assert.deepEqual(parseRoute(`#/${name}`), { name, params: {}, query: {} });
  assert.deepEqual(SCREENS, ['suites', 'survey', 'runs', 'defects', 'agent', 'projects', 'scenarios', 'templates', 'cache', 'settings']);
});

test('detail routes carry their id', () => {
  assert.deepEqual(parseRoute('#/suites/new?kind=backlog&ticket=DEMO-1'), { name: 'suiteNew', params: {}, query: { kind: 'backlog', ticket: 'DEMO-1' } });
  assert.deepEqual(parseRoute('#/suites/S20261125-1000-x'), { name: 'suite', params: { suite: 'S20261125-1000-x' }, query: {} });
  assert.deepEqual(parseRoute('#/survey/DEMO-1'), { name: 'report', params: { ticket: 'DEMO-1' }, query: {} });
  assert.deepEqual(parseRoute('#/survey/DEMO-1/trace'), { name: 'trace', params: { ticket: 'DEMO-1' }, query: {} });
  assert.deepEqual(parseRoute('#/runs/W1'), { name: 'run', params: { run: 'W1' }, query: {} });
  assert.deepEqual(parseRoute('#/agent/j-123'), { name: 'agent', params: { job: 'j-123' }, query: {} });
});

test('queries and encoded segments are decoded', () => {
  const r = parseRoute('#/survey/DEMO-1/trace?workbook=DEMO-1%20tc.xlsx&template=m%E1%BA%ABu');
  assert.deepEqual(r.query, { workbook: 'DEMO-1 tc.xlsx', template: 'mẫu' });
  assert.equal(parseRoute('#/survey/A%2FB').params.ticket, 'A/B');
  assert.deepEqual(parseRoute('#/survey/DEMO-1?rev=a&rev=b').query, { rev: 'a' });
});

test('unknown or malformed routes are notfound', () => {
  for (const hash of ['#/nope', '#/settings/extra', '#/survey/DEMO-1/other', '#/survey/%E0%A4%A', '#c=launchcode',
    '#/suites/S1/cases', '#/runs/W1/x', '#/agent/j-1/review', '#/tickets', '#/jobs', '#/login']) {
    assert.equal(parseRoute(hash).name, 'notfound', hash);
  }
});

test('href encodes segments and drops empty query values', () => {
  assert.equal(href(['survey', 'DEMO-1', 'trace'], { workbook: 'a b.xlsx', template: undefined }), '#/survey/DEMO-1/trace?workbook=a%20b.xlsx');
  assert.equal(href(['survey', 'A/B']), '#/survey/A%2FB');
  assert.equal(parseRoute(href(['survey', 'DEMO-1', 'trace'], { workbook: 'x&y=z.xlsx' })).query.workbook, 'x&y=z.xlsx');
});

test('detail routes light their menu row', () => {
  assert.equal(sectionOf(parseRoute('#/suites/new')), 'suites');
  assert.equal(sectionOf(parseRoute('#/suites/S1')), 'suites');
  assert.equal(sectionOf(parseRoute('#/survey/DEMO-1')), 'survey');
  assert.equal(sectionOf(parseRoute('#/survey/DEMO-1/trace')), 'survey');
  assert.equal(sectionOf(parseRoute('#/runs/W1')), 'runs');
  assert.equal(sectionOf(parseRoute('#/agent/j-1')), 'agent');
  assert.equal(sectionOf(parseRoute('#/cache')), 'cache');
});

test('the redirect table sends every link written before the redesign to its new screen', () => {
  const table = [
    ['', '#/suites'],
    ['#/', '#/suites'],
    ['#/tickets', '#/survey'],
    ['#/tickets/DEMO-1', '#/survey/DEMO-1'],
    ['#/tickets/DEMO-1/trace?workbook=a%20b.xlsx', '#/survey/DEMO-1/trace?workbook=a%20b.xlsx'],
    ['#/tickets/A%2FB', '#/survey/A%2FB'],
    ['#/jobs', '#/agent'],
    ['#/jobs/j-123', '#/agent/j-123'],
    ['#/login', '#/scenarios'],
    ['#/login?project=demo', '#/scenarios?project=demo'],
  ];
  for (const [from, to] of table) {
    assert.deepEqual(redirectOf(from), { to }, from);
    assert.notEqual(parseRoute(to).name, 'notfound', to);
  }
  assert.deepEqual(redirectOf('#/jobs/j-123/review'), { job: 'j-123' });
  assert.deepEqual(redirectOf('#/jobs/j-123/review-table'), { job: 'j-123' });
});

test('current and launch-code hashes are not redirected', () => {
  for (const hash of ['#/suites', '#/suites/S1', '#/survey/DEMO-1', '#/runs', '#/agent/j-1', '#c=abc', '#/tickets/%E0%A4%A']) {
    assert.equal(redirectOf(hash), null, hash);
  }
});

test('an old review link opens the job\'s run, else the job itself', () => {
  assert.equal(legacyReviewTarget({ id: 'j-1', run: 'W20261119-1000-demo' }, 'j-1'), '#/runs/W20261119-1000-demo');
  assert.equal(legacyReviewTarget({ id: 'j-1', run: null }, 'j-1'), '#/agent/j-1');
  assert.equal(legacyReviewTarget(null, 'j-2'), '#/agent/j-2');
});

test('a launch link lands on Test suites once its code is read', async () => {
  const replaced = [];
  const loc = { hash: '#c=abc123', pathname: '/', search: '' };
  const hist = { replaceState: (...args) => replaced.push(args[2]) };
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ session: 's-1', version: '1.0.0' }) });
  try {
    assert.equal(await bootstrap(loc, hist), true);
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.deepEqual(replaced, ['/#/suites']);
  const kept = [];
  await bootstrap({ hash: '#/runs', pathname: '/', search: '' }, { replaceState: (...a) => kept.push(a) });
  assert.deepEqual(kept, []);
});
