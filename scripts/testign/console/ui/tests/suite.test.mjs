import assert from 'node:assert/strict';
import { test } from 'node:test';

import { bulkBody, caseToForm, filterCases, formToBody, render as renderSuite, ruleErrors, splitTrace } from '../views/suite.mjs';
import { byData, DICTS, fakeContext, walk } from './web-helpers.mjs';

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const byId = (root, id) => walk(root).find((el) => el.getAttribute && el.getAttribute('id') === id);
function type(el, value, event = 'input') {
  el.value = value;
  for (const fn of el.listeners[event] || []) fn({ target: el });
}

function caseOf(n, extra) {
  return { case: `c${n}`, trace: [`B${n}`], source: {}, content: `Case ${n}`, preconditions: '', steps: '', expected: '',
    screen: { url: `/page/${n}`, name: 'Page', confidence: 'high' }, viewport: 'pc', mobile_method: null, class: 'sure',
    runner: 'agent', scenario: 'none', creator: 'agent', ...extra };
}

function suiteOf(id, extra) {
  return { id, name: 'Booking header', project: 'demo', kind: 'backlog', state: 'review', case_lang: 'ja',
    source: { kind: 'backlog', ticket: 'DEMO-1', revision: 2 }, created_at: '2026-11-25T10:00:00+09:00',
    cases: [caseOf(1), caseOf(2, { class: 'choice', runner: 'tester' }), caseOf(3, { class: 'not-web', runner: 'none', screen: null })],
    coverage: { mode: 'generate', rows: [{ id: 'B1', label: 'Row 1', cases: ['c1'] }, { id: 'B9', label: 'Row 9', cases: [] }], uncovered: ['B9'], orphans: [] },
    runs: [], generate: null, suite_digest: 'd1', ...extra };
}

test('a case form keeps its screen record when the path is unchanged and follows the run rules', () => {
  const c = caseOf(1);
  const f = caseToForm(c);
  assert.equal(f.screen, '/page/1');
  assert.equal(f.trace, 'B1');
  const body = formToBody({ ...f, content: 'Header shows 予約' }, c);
  assert.deepEqual(body.screen, c.screen, 'an unchanged path keeps its name and confidence');
  assert.equal(body.content, 'Header shows 予約');
  assert.equal(formToBody({ ...f, screen: '/other' }, c).screen, '/other');
  assert.equal(formToBody({ ...f, screen: '' }, c).screen, null);
  assert.equal(formToBody({ ...f, class: 'not-web', runner: 'agent' }, c).runner, 'none');
  assert.equal(formToBody({ ...f, viewport: 'mobile', mobile_method: '' }, c).mobile_method, 'device');
  assert.equal(formToBody({ ...f, viewport: 'pc', mobile_method: 'emulation' }, c).mobile_method, null);
  assert.deepEqual(splitTrace('B1, R2 B1、R3'), ['B1', 'R2', 'R3']);
});

test('only a refusal about the case\'s own fields becomes field errors; bulk edits change three fields', () => {
  const err = { code: 'case-rules', details: { case: 'c2', errors: { runner: 'a real device is run by the tester' } } };
  assert.deepEqual(ruleErrors(err, 'c2'), { runner: 'a real device is run by the tester' });
  assert.deepEqual(ruleErrors(err, 'c1'), {});
  assert.deepEqual(ruleErrors({ code: 'conflict', message: 'x' }, 'c2'), {});
  assert.deepEqual(bulkBody(new Set(['c1', 'c2']), 'runner', 'tester'), { cases: ['c1', 'c2'], fields: { runner: 'tester' } });
  assert.deepEqual(bulkBody(['c1'], 'scenario', ''), { cases: ['c1'], fields: { scenario: null } });
  assert.throws(() => bulkBody(['c1'], 'content', 'x'), RangeError);
  const cases = suiteOf('x').cases;
  assert.deepEqual(filterCases(cases, '', 'choice').map((c) => c.case), ['c2']);
  assert.deepEqual(filterCases(cases, '', 'not-web').map((c) => c.case), ['c3']);
  assert.deepEqual(filterCases(cases, 'b2', 'all').map((c) => c.case), ['c2']);
  assert.deepEqual(filterCases(cases, '', 'problems', { c3: { content: 'x' } }).map((c) => c.case), ['c3']);
});

function suiteApi(suite, log, overrides = {}) {
  return {
    suite: async () => suite,
    scenarios: async () => ({ scenarios: [{ name: 'client', approved: true }] }),
    tickets: async () => ({ tickets: [{ id: 'DEMO-1', revision: 2, freshness: { status: 'same' } }] }),
    updateCase: async (id, caseId, body) => { log.push(['update', id, caseId, body]); return { case: { ...caseOf(1), ...body, case: caseId } }; },
    addCase: async (id, body) => { log.push(['add', id, body]); return { case: { ...body, case: 'c4' } }; },
    bulkCases: async (id, body) => { log.push(['bulk', id, body]); return { changed: body.cases }; },
    ...overrides,
  };
}

test('editing a case saves it through the run rules and shows a refused field under that field', async () => {
  const log = [];
  let refuse = true;
  const suite = suiteOf('S20261125-1000-form');
  const api = suiteApi(suite, log, {
    updateCase: async (id, caseId, body) => {
      log.push(['update', id, caseId, body]);
      if (refuse) {
        refuse = false;
        const e = new Error('case c2: runner: a choice case run by the agent needs preconditions');
        Object.assign(e, { status: 400, code: 'case-rules', details: { case: caseId, errors: { preconditions: 'a choice case run by the agent needs preconditions' } } });
        throw e;
      }
      return { case: { ...caseOf(2), ...body } };
    },
  });
  const { ctx, view, calls, ready } = fakeContext(api, { route: { params: { suite: suite.id }, query: {} } });
  renderSuite(ctx);
  await ready;
  assert.equal(byData(view, 'case').filter((el) => el.tagName === 'TR').length, 3);
  const row = byData(view, 'case').find((el) => el.tagName === 'TR' && el.dataset.case === 'c2');
  row.listeners.click[0]({ target: row });
  const [form] = byData(view, 'caseForm');
  assert.equal(form.dataset.caseForm, 'c2');
  type(byId(view, 'case-runner'), 'agent', 'change');
  const [save] = byData(view, 'caseSave');
  save.listeners.click[0]();
  await tick();
  assert.equal(log.length, 1);
  assert.equal(log[0][3].runner, 'agent');
  assert.ok(view.textContent.includes('a choice case run by the agent needs preconditions'), 'the server message shows');
  type(byId(view, 'case-preconditions'), 'booking #1042 is confirmed');
  save.listeners.click[0]();
  await tick();
  assert.equal(log.length, 2);
  assert.equal(log[1][3].preconditions, 'booking #1042 is confirmed');
  assert.ok(calls.toasts.some(([text]) => text === ctx.t('case_saved', { id: 'c2' })));
});

test('adding a case posts a new one', async () => {
  const log = [];
  const suite = suiteOf('S20261125-1000-add');
  const { ctx, view, ready } = fakeContext(suiteApi(suite, log), { route: { params: { suite: suite.id }, query: {} } });
  renderSuite(ctx);
  await ready;
  byData(view, 'addCase')[0].listeners.click[0]();
  assert.equal(byData(view, 'caseForm')[0].dataset.caseForm, 'new');
  type(byId(view, 'case-content'), 'Footer shows the address');
  type(byId(view, 'case-class'), 'sure', 'change');
  byData(view, 'caseSave')[0].listeners.click[0]();
  await tick();
  assert.equal(log[0][0], 'add');
  assert.equal(log[0][2].content, 'Footer shows the address');
  assert.equal(log[0][2].class, 'sure');
});

test('a bulk edit changes the checked cases only, and delete asks first', async () => {
  const log = [];
  const suite = suiteOf('S20261125-1000-bulk');
  const { ctx, view, ready } = fakeContext(suiteApi(suite, log), { route: { params: { suite: suite.id }, query: {} } });
  renderSuite(ctx);
  await ready;
  assert.ok(view.textContent.includes(DICTS.en.suite_bulk_hint));
  const boxes = walk(view).filter((el) => el.tagName === 'INPUT' && el.getAttribute('type') === 'checkbox');
  // The first box selects all; tick c1 and c3.
  for (const i of [1, 3]) { boxes[i].checked = true; boxes[i].listeners.change[0]({ target: boxes[i] }); }
  const field = byId(view, 'bulk-field');
  type(field, 'runner', 'change');
  const value = byId(view, 'bulk-value');
  value.value = 'tester';
  byData(view, 'bulkApply')[0].listeners.click[0]();
  await tick();
  assert.deepEqual(log[0], ['bulk', suite.id, { cases: ['c1', 'c3'], fields: { runner: 'tester' } }]);
  await tick();
  for (const i of [2]) {
    const again = walk(view).filter((el) => el.tagName === 'INPUT' && el.getAttribute('type') === 'checkbox');
    again[i].checked = true;
    again[i].listeners.change[0]({ target: again[i] });
  }
  byData(view, 'bulkDelete')[0].listeners.click[0]();
  assert.equal(log.length, 1, 'nothing is deleted before the tester confirms');
  byData(globalThis.document.body, 'confirmDelete')[0].listeners.click[0]();
  await tick();
  assert.deepEqual(log[1], ['bulk', suite.id, { cases: ['c2'], delete: true }]);
});

test('a generating suite is read-only and links its job; New run waits for a ready suite', async () => {
  const suite = suiteOf('S20261125-1000-gen', { state: 'generating', generate: { id: 'j-7', state: 'running', progress: [{ message: 'Reading B4' }] } });
  const { ctx, view, ready } = fakeContext(suiteApi(suite, []), { route: { params: { suite: suite.id }, query: {} } });
  renderSuite(ctx);
  await ready;
  assert.equal(byData(view, 'addCase').length, 0);
  assert.ok(walk(view).filter((el) => el.tagName === 'INPUT' && el.getAttribute('type') === 'checkbox').every((el) => el.disabled === true));
  assert.ok(view.textContent.includes('Reading B4'));
  assert.ok(walk(view).some((el) => el.tagName === 'A' && el.getAttribute('href') === '#/agent/j-7'));
  const run = byData(view, 'suiteAction').find((el) => el.dataset.suiteAction === 'new-run');
  assert.equal(run.disabled, true);
  assert.equal(run.getAttribute('title'), DICTS.en.suite_confirm_first);
});

test('confirming a suite with a broken case lists the problem and marks the row', async () => {
  const suite = suiteOf('S20261125-1000-confirm');
  const api = suiteApi(suite, [], {
    confirmSuite: async () => {
      const e = new Error('case c3');
      Object.assign(e, { status: 400, code: 'case-rules', details: { case: 'c3', errors: { content: 'is required' }, problems: { c3: { content: 'is required' } } } });
      throw e;
    },
  });
  const { ctx, view, ready } = fakeContext(api, { route: { params: { suite: suite.id }, query: {} } });
  renderSuite(ctx);
  await ready;
  byData(view, 'suiteAction').find((el) => el.dataset.suiteAction === 'confirm').listeners.click[0]();
  await tick();
  await tick();
  assert.ok(view.textContent.includes(ctx.t('suite_problems', { n: 1 })));
  assert.deepEqual(byData(view, 'case').filter((el) => el.tagName === 'TR').map((el) => el.dataset.case), ['c3']);
  assert.ok(walk(view).some((el) => el.getAttribute && el.getAttribute('aria-label') === `${DICTS.en.case_f_content}: is required`));
});
