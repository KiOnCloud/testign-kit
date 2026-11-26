import assert from 'node:assert/strict';
import test from 'node:test';

import { checkDefect, defectText, filterDefects } from '../views/defects.mjs';
import { defectBody } from '../views/run.mjs';
import { cellView } from '../views/suite.mjs';

const t = (key) => key;

test('checkDefect names what each status still needs', () => {
  assert.equal(checkDefect({ status: 'draft', title: ' ' }), 'defect_err_title');
  assert.equal(checkDefect({ status: 'sent', title: 'x', tracker: '' }), 'defect_err_tracker');
  assert.equal(checkDefect({ status: 'not-a-defect', title: 'x', reason: '' }), 'defect_err_reason');
  assert.equal(checkDefect({ status: 'sent', title: 'x', tracker: 'PROJ-1' }), null);
});

test('defectBody keeps the tracker or the reason by status', () => {
  const f = { title: ' T ', steps: '1', expected: 'e', actual: 'a', tracker: 'P-1', reason: 'r' };
  assert.deepEqual(defectBody('sent', f), { status: 'sent', title: 'T', steps: '1', expected: 'e', actual: 'a', tracker: 'P-1', reason: '' });
  assert.equal(defectBody('not-a-defect', f).tracker, '');
  assert.equal(defectBody('not-a-defect', f).reason, 'r');
});

test('filterDefects filters by status and words', () => {
  const list = [{ status: 'draft', title: 'Header link', run: 'W1', row: 'r01' },
    { status: 'sent', title: 'Footer', tracker: 'PROJ-9', run: 'W2', row: 'r02' }];
  assert.deepEqual(filterDefects(list, 'draft', '').map((d) => d.row), ['r01']);
  assert.deepEqual(filterDefects(list, 'all', 'proj-9').map((d) => d.row), ['r02']);
});

test('defectText writes labelled sections that have content', () => {
  const text = defectText(t, { title: 'Header', steps: '1. Open', expected: '', actual: 'old label', evidence: ['evidence/r01-a1-1.png'],
    url: 'https://dev.example.test/mypage', row: 'r01' }, { id: 'W1', name: 'round 1', base_url: 'https://dev.example.test' });
  assert.match(text, /^Header\n\ndefect_env:\nhttps:\/\/dev\.example\.test\nhttps:\/\/dev\.example\.test\/mypage/);
  assert.ok(text.includes('run_steps:\n1. Open') && !text.includes('run_expected:'));
  assert.ok(text.endsWith('defect_source:\nround 1 · r01'));
});

test('cellView shows Fixed for a pass after a fail', () => {
  assert.deepEqual(cellView({ verdict: 'pass', fixed: true }), { key: 'run_fixed', kind: 'success' });
  assert.deepEqual(cellView({ verdict: 'fail' }), { key: 'wt_verdict_fail', kind: 'danger' });
  assert.deepEqual(cellView({ verdict: 'not-run' }), { key: 'wt_state_not_run', kind: 'outline' });
  assert.equal(cellView(undefined), null);
});
