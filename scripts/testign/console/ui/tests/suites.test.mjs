import assert from 'node:assert/strict';
import { test } from 'node:test';

import { freshnessIcon, surveyAction, surveyingTickets } from '../views/survey.mjs';
import { checkStep, createBody, finishKey, offeredSources, render as renderWizard } from '../views/suite-new.mjs';
import { filterSuites, sourceRef, suiteCounts, suiteFilter, suiteStateBadge } from '../views/suites.mjs';
import { statusIcon } from '../dom.mjs';
import { installFakeDocument } from './fake-dom.mjs';
import { byData, DICTS, fakeContext, translator, walk } from './web-helpers.mjs';

const t = translator('en');
const SUITES = [
  { id: 'S1', name: 'Booking header', kind: 'figma', source: { kind: 'figma', node: '12:34' }, state: 'review', project: 'demo', cases: 9 },
  { id: 'S2', name: 'DEMO-1 login', kind: 'backlog', source: { kind: 'backlog', ticket: 'DEMO-1', revision: 2 }, state: 'generating', cases: 0 },
  { id: 'S3', name: 'Regression', kind: 'excel', source: { kind: 'excel', file: 'regression.xlsx' }, state: 'ready', cases: 40 },
  { id: 'S4', readable: false },
];

test('suites fall under one filter each and the counts add up', () => {
  assert.deepEqual(SUITES.slice(0, 3).map(suiteFilter), ['needs', 'generating', 'ready']);
  assert.deepEqual(suiteCounts(SUITES), { all: 4, needs: 1, generating: 1, ready: 1 });
  assert.deepEqual(filterSuites(t, SUITES, '', 'ready').map((s) => s.id), ['S3']);
  assert.deepEqual(filterSuites(t, SUITES, 'demo-1', 'all').map((s) => s.id), ['S2']);
  assert.deepEqual(filterSuites(t, SUITES, '12:34', 'all').map((s) => s.id), ['S1']);
  assert.deepEqual(filterSuites(t, SUITES, '', 'all').length, 4);
  assert.equal(sourceRef(t, SUITES[1].source), 'DEMO-1 · survey r2');
  assert.equal(sourceRef(t, SUITES[0].source), 'node 12:34');
  assert.equal(sourceRef(t, SUITES[2].source), 'regression.xlsx');
  installFakeDocument();
  assert.equal(suiteStateBadge(translator('ja'), 'review').textContent, DICTS.ja.suite_state_review);
});

test('report freshness maps to four status icons whose tooltip is the meaning', () => {
  installFakeDocument();
  const expect = [
    [freshnessIcon(t, { status: 'same' }), 'ok', 'check', DICTS.en.fr_same],
    [freshnessIcon(t, { status: 'moved_no_impact' }), 'ok', 'check', DICTS.en.fr_moved],
    [freshnessIcon(t, { status: 'stale' }), 'warn', 'warning', DICTS.en.fr_stale],
    [freshnessIcon(t, { status: 'same' }, true), 'busy', 'clock', DICTS.en.fr_surveying],
    [freshnessIcon(t, { status: 'unknown', reason: 'busy' }), 'busy', 'clock', DICTS.en.fr_checking],
  ];
  for (const [got, kind, icon, tip] of expect) {
    assert.deepEqual(got, { kind, icon, tip });
    const el = statusIcon(got.kind, got.icon, got.tip);
    assert.equal(el.getAttribute('aria-label'), tip);
    assert.equal(el.getAttribute('role'), 'img');
    assert.equal(el.getAttribute('tabindex'), '0');
    assert.ok(walk(el).some((c) => c.getAttribute && c.getAttribute('role') === 'tooltip' && c.textContent === tip));
  }
  const unknown = freshnessIcon(t, { status: 'unknown', reason: 'no-repo' });
  assert.equal(unknown.kind, 'busy');
  assert.equal(unknown.icon, 'dash');
  assert.ok(unknown.tip);
});

test('a surveyed ticket offers one action', () => {
  assert.equal(surveyAction({ freshness: { status: 'stale' }, open_questions: 2 }, false), 'resurvey');
  assert.equal(surveyAction({ freshness: { status: 'same' }, open_questions: 2 }, false), 'answer');
  assert.equal(surveyAction({ freshness: { status: 'same' }, open_questions: 0 }, false), 'suite');
  assert.equal(surveyAction({ freshness: { status: 'same' } }, true), null);
  assert.deepEqual([...surveyingTickets([{ kind: 'survey', state: 'running', ticket: 'DEMO-1' }, { kind: 'survey', state: 'done', ticket: 'DEMO-2' }])],
    ['DEMO-1']);
});

const SOURCES = [{ kind: 'figma', mode: 'extract', needs_agent: true }, { kind: 'backlog', mode: 'generate', needs_agent: true },
  { kind: 'excel', mode: 'extract', needs_agent: false }, { kind: 'manual', mode: 'none', needs_agent: false }, { kind: 'jira', needs_agent: true }];
const FIGMA = 'https://www.figma.com/design/AbCdEfGhIjKl/Change-table?node-id=12-34';

test('each source checks its own input; the other steps are shared', () => {
  assert.deepEqual(offeredSources(SOURCES).map((s) => s.kind), ['figma', 'backlog', 'excel', 'manual']);
  assert.deepEqual(checkStep(1, { kind: null }), { kind: 'wiz_err_kind' });
  assert.deepEqual(checkStep(2, { kind: 'figma', figma_url: 'https://www.figma.com/design/x' }), { figma_url: 'wiz_err_figma' });
  assert.deepEqual(checkStep(2, { kind: 'figma', figma_url: FIGMA }), {});
  assert.deepEqual(checkStep(2, { kind: 'backlog', ticket: '' }), { ticket: 'wiz_err_ticket' });
  assert.deepEqual(checkStep(2, { kind: 'excel', file: { name: 'a.csv', size: 1 }, template: 'tc' }), { file: 'wiz_err_file_type' });
  assert.deepEqual(checkStep(2, { kind: 'excel', file: { name: 'a.xlsx', size: 11 * 1024 * 1024 }, template: '' }),
    { file: 'wiz_err_file_size', template: 'wiz_err_template' });
  assert.deepEqual(checkStep(2, { kind: 'manual' }), {});
  assert.deepEqual(checkStep(3, { name: ' ' }), { name: 'wiz_err_name' });
  assert.deepEqual(checkStep(3, { name: 'x'.repeat(121) }), { name: 'wiz_err_name' });
  assert.equal(finishKey(SOURCES[0]), 'wiz_queue_gen');
  assert.equal(finishKey(SOURCES[2]), 'wiz_create');
  assert.deepEqual(createBody({ kind: 'backlog', ticket: 'DEMO-1', name: ' Login ', project: 'demo', case_lang: 'ja' }, 'en'),
    { kind: 'backlog', name: 'Login', ui_lang: 'en', ticket: 'DEMO-1', project: 'demo', case_lang: 'ja' });
});

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const byId = (root, id) => walk(root).find((el) => el.getAttribute && el.getAttribute('id') === id);
const wizButton = (view, name) => byData(view, 'wiz').find((el) => el.dataset.wiz === name);
function type(el, value, event = 'input') {
  el.value = value;
  for (const fn of el.listeners[event] || []) fn({ target: el });
}

function wizardApi(made) {
  return {
    sources: async () => ({ sources: SOURCES }),
    tickets: async () => ({ tickets: [{ id: 'DEMO-1', title: 'Login fix', revision: 2, latest: 'DEMO-1-survey-r2.md', open_questions: 0,
      freshness: { status: 'same' } }] }),
    templates: async () => ({ default: 'tc', templates: [{ name: 'tc', purpose: 'testcase' }, { name: 'web', purpose: 'webtest' }] }),
    projects: async () => ({ projects: [{ name: 'demo', hosts: ['dev.example.test'] }] }),
    config: async () => ({ lang: 'ja', report_langs: ['en', 'ja'] }),
    uploadSuiteFile: async (file) => { made.push(['upload', file.name]); return { upload: 'u-1' }; },
    createSuite: async (body) => { made.push(['create', body]); return { suite: 'S9', state: body.kind === 'excel' || body.kind === 'manual' ? 'review' : 'generating', job: body.kind === 'figma' || body.kind === 'backlog' ? { id: 'j1' } : null }; },
  };
}

async function runWizard(kind, fill, query = {}) {
  const made = [];
  const { ctx, view, calls, ready } = fakeContext(wizardApi(made), { route: { params: {}, query: { ...query, n: String(Math.random()) } } });
  renderWizard(ctx);
  await ready;
  if (!query.kind) {
    const pick = byData(view, 'src').find((el) => el.dataset.src === kind);
    assert.ok(pick, `${kind} is offered`);
    pick.listeners.click[0]();
    wizButton(view, 'next').listeners.click[0]();
  }
  // Step 2 refuses to go on until the source's own input is right.
  if (kind !== 'manual') {
    wizButton(view, 'next').listeners.click[0]();
    assert.ok(view.textContent.includes(DICTS.en.wiz_step_input));
    assert.ok(walk(view).some((el) => /k-field__error/.test(el.getAttribute('class') || '')), `${kind} shows its input error`);
  }
  fill(view);
  wizButton(view, 'next').listeners.click[0]();
  const name = byId(view, 'wiz-name');
  assert.ok(name, 'step 3 asks for the name');
  if (!name.value) type(name, `${kind} suite`);
  wizButton(view, 'next').listeners.click[0]();
  const done = wizButton(view, 'done');
  assert.ok(done, 'step 4 shows the finish button');
  done.listeners.click[0]();
  await tick();
  await tick();
  return { made, calls };
}

test('the wizard walks figma, backlog, excel and manual through the same four steps', async () => {
  const figma = await runWizard('figma', (view) => type(byId(view, 'wiz-figma'), FIGMA));
  assert.deepEqual(figma.made, [['create', { kind: 'figma', name: 'figma suite', ui_lang: 'en', figma_url: FIGMA, case_lang: 'ja', depth: 'standard' }]]);
  assert.deepEqual(figma.calls.navigated, ['#/suites/S9']);
  assert.equal(figma.calls.toasts[0][0], DICTS.en.wiz_queued);

  const backlog = await runWizard('backlog', (view) => type(byId(view, 'wiz-ticket'), 'DEMO-1', 'change'), { kind: 'backlog' });
  assert.equal(backlog.made[0][1].ticket, 'DEMO-1');
  assert.equal(backlog.made[0][1].name, 'DEMO-1 · Login fix', 'the name starts from the ticket');

  const file = { name: 'regression.xlsx', size: 2048, arrayBuffer: async () => new ArrayBuffer(2) };
  const excel = await runWizard('excel', (view) => {
    const input = byId(view, 'wiz-file');
    input.files = [file];
    input.listeners.change[0]({ target: input });
  });
  assert.deepEqual(excel.made[0], ['upload', 'regression.xlsx']);
  assert.deepEqual(excel.made[1], ['create', { kind: 'excel', name: 'regression', ui_lang: 'en', template: 'tc', case_lang: 'ja', depth: 'standard', upload: 'u-1' }]);
  assert.equal(excel.calls.toasts[0][0], DICTS.en.wiz_created);

  const manual = await runWizard('manual', (view) => type(byId(view, 'wiz-note'), 'Smoke checks'));
  assert.deepEqual(manual.made, [['create', { kind: 'manual', name: 'manual suite', ui_lang: 'en', note: 'Smoke checks', case_lang: 'ja', depth: 'standard' }]]);
});
