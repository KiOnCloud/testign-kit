import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  addColumn, colIndex, colLetter, columnsAnswer, freeFields, initialDraft, moveColumn, openColumnsEditor, removeColumn, setColumn,
  sheetOrder,
} from '../views/columns.mjs';
import { byData, fakeContext } from './web-helpers.mjs';

const INFO = {
  plan: {
    template: 'web', sheet: 'Sheet1', header_row: 1, verdict_labels: { pass: 'OK', fail: 'NG' },
    columns: [{ field: 'no', letter: 'A' }, { field: 'content', letter: 'B' }, { field: 'verdict', letter: 'C' },
      { field: 'actual', letter: 'D', new: true, header: '実際の結果' }],
  },
  headers: { A: 'No', B: '確認項目', C: '結果' }, last_column: 'C',
  fields: ['no', 'content', 'screen', 'expected'], templates: ['web', 'other'],
};

test('the run\'s first guess saves as it is', () => {
  const result = columnsAnswer(INFO, initialDraft(INFO));
  assert.equal(result.ok, true, JSON.stringify(result.errors));
  assert.deepEqual(result.body, {
    columns: [{ field: 'no', letter: 'A' }, { field: 'content', letter: 'B' }, { field: 'verdict', letter: 'C' },
      { field: 'actual', letter: 'D', new: true, header: '実際の結果' }],
    verdict_labels: { pass: 'OK', fail: 'NG' },
  });
});

test('removing the verdict or content column is refused', () => {
  assert.deepEqual(columnsAnswer(INFO, removeColumn(initialDraft(INFO), 3)).body.columns.map((c) => c.letter), ['A', 'B', 'C']);
  assert.ok(columnsAnswer(INFO, removeColumn(initialDraft(INFO), 2)).errors.some((e) => e.key === 'rt_err_need_verdict'));
  assert.ok(columnsAnswer(INFO, removeColumn(initialDraft(INFO), 1)).errors.some((e) => e.key === 'rt_err_need_content'));
});

test('a new column goes right of every used letter and needs a header', () => {
  let draft = addColumn(initialDraft(INFO), INFO, 'executed_at');
  assert.equal(draft.columns[4].letter, 'E');
  assert.ok(columnsAnswer(INFO, draft).errors.some((e) => e.key === 'rt_err_header'));
  draft = setColumn(draft, 4, { header: '実施日' });
  assert.equal(columnsAnswer(INFO, draft).ok, true);
  const left = setColumn(draft, 4, { letter: 'B' });
  const keys = columnsAnswer(INFO, left).errors.map((e) => e.key);
  assert.ok(keys.includes('rt_err_new_left') && keys.includes('rt_err_letter_twice'));
  assert.equal(colLetter(colIndex('AZ') + 1), 'BA');
});

test('moving a column swaps fields; letters stay in place', () => {
  const draft = moveColumn(initialDraft(INFO), 1, 2);
  assert.deepEqual(draft.columns.slice(0, 3).map((c) => [c.letter, c.field]), [['A', 'no'], ['B', 'verdict'], ['C', 'content']]);
  assert.equal(moveColumn(draft, 0, -1), draft);
  assert.deepEqual(sheetOrder(setColumn(draft, 0, { letter: 'Z' })).map((c) => c.letter), ['B', 'C', 'D', 'Z']);
});

test('labels need Pass and Fail; another template is sent and its headers left to the server', () => {
  const noFail = { ...initialDraft(INFO), labels: { pass: 'OK', fail: '' } };
  assert.ok(columnsAnswer(INFO, noFail).errors.some((e) => e.key === 'rt_err_labels'));
  const other = { ...initialDraft(INFO), template: 'other' };
  const out = columnsAnswer(INFO, setColumn(other, 3, { letter: 'B', new: undefined }));
  assert.equal(out.body.template, 'other');
  assert.ok(!out.errors.some((e) => e.key === 'rt_err_no_header'));
  assert.deepEqual(freeFields(initialDraft(INFO), INFO), ['screen', 'expected', 'evidence', 'executed_at', 'by',
    'flaky', 'verdict_chromium', 'verdict_msedge', 'verdict_firefox', 'verdict_webkit']);
});

test('the editor saves the plan and reports a busy run', async () => {
  const sent = [];
  let busy = true;
  const api = {
    runColumns: async () => INFO,
    putRunColumns: async (run, body) => {
      sent.push([run, body]);
      if (busy) { busy = false; const e = new Error('busy'); e.code = 'run-busy'; e.status = 409; throw e; }
      return { ok: true };
    },
  };
  const { ctx, calls } = fakeContext(api);
  let saved = 0;
  openColumnsEditor(ctx, { id: 'W1', name: 'Update 11' }, () => { saved += 1; });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const [save] = byData(globalThis.document.body, 'saveColumns');
  assert.ok(save, 'the dialog has a save button');
  save.listeners.click[0]();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(saved, 0);
  assert.ok(globalThis.document.body.textContent.includes(ctx.t('cols_err_busy')));
  save.listeners.click[0]();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(saved, 1);
  assert.equal(sent.length, 2);
  assert.equal(sent[1][0], 'W1');
  assert.deepEqual(calls.toasts.at(-1), [ctx.t('cols_saved'), undefined]);
});
