import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  addColumn, bulkEdit, colIndex, colLetter, initialDraft, moveColumn, removeColumn, render, reviewTableAnswer, sampleGrid,
  screenOk, setEdit,
} from '../views/review-table.mjs';
import { byData, fakeContext } from './web-helpers.mjs';

function line(row, extra) {
  return { row, no: null, content: `Change ${row}`, screen: '/news', screen_name: null, confidence: 'high', class: 'sure', kind: 'label',
    reason: 'Text change', runner: 'agent', scenario: 'none', viewport: 'pc', preconditions: null, steps: null, expected: null,
    capture: null, ...extra };
}

function ask(lines) {
  return {
    type: 'review-table', id: 'review-W20261119-1000-demo', run: 'W20261119-1000-demo', template: 'web',
    headers: { A: 'No', B: '確認項目', C: '結果' }, last_column: 'C',
    columns: [{ field: 'no', letter: 'A' }, { field: 'content', letter: 'B' }, { field: 'verdict', letter: 'C' },
      { field: 'actual', letter: 'D', new: true, header: '実際の結果' }],
    verdict_labels: { pass: 'OK', fail: 'NG' }, verdict_options: ['OK', 'NG', '保留', '対象外'],
    samples: [{ row: 'r01', class: 'sure', cells: { A: '1', B: 'Label reads 予約履歴', C: '' } }],
    lines, digest: 'x', hosts: ['dev.example.test'],
    scenarios: [{ name: 'client', label: 'Client', approved: true }, { name: 'staff', label: 'Staff', approved: false }],
  };
}

const ASK = ask([line('r01'), line('r02', { class: 'choice', runner: 'tester', reason: 'Writes data' }),
  line('r03', { runner: 'tester' })]);

test('the agent\'s plan confirms as it is', () => {
  const result = reviewTableAnswer(ASK, initialDraft(ASK));
  assert.equal(result.ok, true, JSON.stringify(result.errors));
  assert.deepEqual(result.answer.verdict_labels, { pass: 'OK', fail: 'NG' });
  assert.deepEqual(result.answer.rows, {});
  assert.equal(result.answer.confirm, true);
  const r02 = ask([line('r01'), line('r02', { class: 'choice', preconditions: '' })]);
  assert.equal(reviewTableAnswer(r02, initialDraft(r02)).ok, false);
});

test('a phone-width row cannot go to the agent', () => {
  const a = ask([line('r01', { runner: 'tester', viewport: 'mobile' })]);
  const draft = setEdit(initialDraft(a), a.lines[0], 'runner', 'agent');
  assert.deepEqual(reviewTableAnswer(a, draft).errors.map((e) => [e.key, e.row]), [['rt_err_mobile_agent', 'r01']]);
  assert.equal(reviewTableAnswer(a, initialDraft(a)).ok, true);
});

test('confirm is refused while a delegated choice row has no preconditions', () => {
  const a = ask([line('r01'), line('r02', { class: 'choice', runner: 'tester' })]);
  let draft = initialDraft(a);
  draft = setEdit(draft, a.lines[1], 'runner', 'agent');
  const refused = reviewTableAnswer(a, draft);
  assert.equal(refused.ok, false);
  assert.deepEqual(refused.errors.map((e) => [e.key, e.row]), [['rt_err_preconditions', 'r02']]);
  draft = setEdit(draft, a.lines[1], 'preconditions', 'booking #1042, Confirmed');
  const ok = reviewTableAnswer(a, draft);
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.answer.rows, { r02: { runner: 'agent', preconditions: 'booking #1042, Confirmed' } });
});

test('removing a column drops it from the answer and from the sample grid', () => {
  const draft = removeColumn(initialDraft(ASK), 3);
  assert.deepEqual(sampleGrid(ASK, draft).map((c) => c.letter), ['A', 'B', 'C']);
  assert.deepEqual(reviewTableAnswer(ASK, draft).answer.columns.map((c) => c.letter), ['A', 'B', 'C']);
  const noVerdict = removeColumn(initialDraft(ASK), 2);
  assert.ok(reviewTableAnswer(ASK, noVerdict).errors.some((e) => e.key === 'rt_err_need_verdict'));
});

test('the sample grid follows sheet order and leaves result columns empty', () => {
  const grid = sampleGrid(ASK, initialDraft(ASK));
  assert.deepEqual(grid.map((c) => [c.letter, c.header]), [['A', 'No'], ['B', '確認項目'], ['C', '結果'], ['D', '実際の結果']]);
  assert.deepEqual(grid[1].cells, ['Label reads 予約履歴']);
  assert.deepEqual(grid[2].cells, [null]);
});

test('a new column goes right of every used letter and needs a header', () => {
  let draft = addColumn(initialDraft(ASK), ASK, 'executed_at');
  assert.equal(draft.columns[4].letter, 'E');
  assert.ok(reviewTableAnswer(ASK, draft).errors.some((e) => e.key === 'rt_err_header'));
  draft = { ...draft, columns: draft.columns.map((c, i) => (i === 4 ? { ...c, header: '実施日' } : c)) };
  assert.equal(reviewTableAnswer(ASK, draft).ok, true);
  const left = { ...draft, columns: draft.columns.map((c, i) => (i === 4 ? { ...c, letter: 'B' } : c)) };
  const keys = reviewTableAnswer(ASK, left).errors.map((e) => e.key);
  assert.ok(keys.includes('rt_err_new_left') && keys.includes('rt_err_letter_twice'));
  assert.equal(colLetter(colIndex('AZ') + 1), 'BA');
});

test('moving a column swaps fields; letters stay in place', () => {
  const draft = moveColumn(initialDraft(ASK), 1, 1);
  assert.deepEqual(draft.columns.slice(0, 3).map((c) => [c.letter, c.field]), [['A', 'no'], ['B', 'verdict'], ['C', 'content']]);
  assert.equal(moveColumn(draft, 0, -1), draft);
});

test('labels need Pass and Fail; screens must be paths or on a run host', () => {
  const draft = { ...initialDraft(ASK), labels: { pass: 'OK', fail: '' } };
  assert.ok(reviewTableAnswer(ASK, draft).errors.some((e) => e.key === 'rt_err_labels'));
  assert.equal(screenOk('', []), true);
  assert.equal(screenOk('/news?x=1', []), true);
  assert.equal(screenOk('//evil.test/x', ['dev.example.test']), false);
  assert.equal(screenOk('https://DEV.example.test:8443/x', ['dev.example.test']), true);
  assert.equal(screenOk('https://dev.example.test.evil.test/', ['dev.example.test']), false);
  assert.equal(screenOk('javascript:alert(1)', ['dev.example.test']), false);
  assert.equal(screenOk('https://evil.example\\@dev.example.test/x', ['dev.example.test']), false);
  assert.equal(screenOk('https://evil.example@dev.example.test/x', ['dev.example.test']), false);
  const bad = setEdit(initialDraft(ASK), ASK.lines[0], 'screen', 'https://evil.test/');
  assert.deepEqual(reviewTableAnswer(ASK, bad).errors.map((e) => e.key), ['rt_err_screen']);
});

test('an edit back to the agent\'s value is dropped; bulk edits touch the selected rows only', () => {
  let draft = setEdit(initialDraft(ASK), ASK.lines[0], 'viewport', 'mobile');
  assert.deepEqual(draft.rows, { r01: { viewport: 'mobile' } });
  draft = setEdit(draft, ASK.lines[0], 'viewport', 'pc');
  assert.deepEqual(draft.rows, {});
  const bulk = bulkEdit(initialDraft(ASK), ASK, new Set(['r01', 'r03']), 'scenario', 'client');
  assert.deepEqual(Object.keys(bulk.rows), ['r01', 'r03']);
});

test('an unapproved scenario or a missing screen warns without blocking', () => {
  let draft = setEdit(initialDraft(ASK), ASK.lines[0], 'scenario', 'staff');
  draft = setEdit(draft, ASK.lines[2], 'runner', 'agent');
  draft = setEdit(draft, ASK.lines[2], 'screen', '');
  const result = reviewTableAnswer(ASK, draft);
  assert.equal(result.ok, true);
  assert.deepEqual(result.warnings.map((w) => [w.key, w.row]), [['rt_warn_unapproved', 'r01'], ['rt_warn_no_screen', 'r03']]);
  const unknown = setEdit(initialDraft(ASK), ASK.lines[0], 'scenario', 'ghost');
  assert.deepEqual(reviewTableAnswer(ASK, unknown).errors.map((e) => e.key), ['rt_err_scenario']);
});

test('the review table renders 45 lines and keeps Confirm off while a row blocks it', async () => {
  const lines = [];
  for (let i = 1; i <= 45; i += 1) lines.push(line(`r${String(i).padStart(2, '0')}`, i === 7 ? { class: 'choice' } : {}));
  const a = ask(lines);
  const job = { id: 'j1', kind: 'webtest-plan', state: 'needs-input', ui_lang: 'en', run: a.run, ask: a };
  const sent = [];
  const { ctx, view, ready } = fakeContext({ job: async () => job, answer: async (...args) => { sent.push(args); return { ok: true }; } },
    { route: { params: { job: 'j1' }, query: {} } });
  render(ctx);
  await ready;
  assert.equal(byData(view, 'rtRow').length, 45);
  const confirm = byData(view, 'confirmTable')[0];
  assert.equal(confirm.disabled, true);
  assert.deepEqual(sent, []);
});
