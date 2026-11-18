import assert from 'node:assert/strict';
import { test } from 'node:test';

import { confirmAnswer, pasteAnswer, questionsAnswer, reviewAnswer, splitAnchors } from '../views/ask-form.mjs';
import { requeueBody, revOf } from '../views/job-actions.mjs';
import { checkSurvey, looksAbsolute, prefillFromReport } from '../views/survey-form.mjs';

const QUESTIONS = {
  type: 'questions', id: 'q-1', questions: [
    { question: 'Which comment?', options: [{ label: 'A' }, { label: 'B' }], multiSelect: false, other: 'line' },
    { question: 'Which rows?', options: [{ label: 'B1' }, { label: 'B2' }, { label: 'B3' }], multiSelect: true, other: 'multiline' },
  ],
};

const ROWS = {
  type: 'review-rows', id: 'rows-1', rows: [
    { row: 'q1-a', q: 'Q1', decision: '割引は請求書にも適用', anchors: ['確定'], page: 'QA/Decisions/order' },
    { row: 'q1-b', q: 'Q1', decision: '切り捨て', anchors: [], page: 'QA/Decisions/order' },
    { row: 'q2-a', q: 'Q2', decision: '切り上げ', anchors: [], page: 'QA/Decisions/common' },
  ],
};

test('questions: one answer per question, single choice trimmed, Other on its own counts', () => {
  const ok = questionsAnswer(QUESTIONS, [{ selected: ['A', 'B'] }, { selected: ['B1', 'B3'], other: 'line 1\nline 2' }]);
  assert.deepEqual(ok, { ok: true, answer: [{ selected: ['A'] }, { selected: ['B1', 'B3'], other: 'line 1\nline 2' }] });
  const otherOnly = questionsAnswer(QUESTIONS, [{ selected: [], other: 'BrSE said\nin chat' }, { selected: ['B2'] }]);
  assert.deepEqual(otherOnly.answer[0], { selected: [], other: 'BrSE said in chat' });
});

test('questions: unanswered questions and unknown labels are refused', () => {
  assert.deepEqual(questionsAnswer(QUESTIONS, [{ selected: [] }, { selected: ['B1'] }]), { ok: false, missing: [0] });
  assert.deepEqual(questionsAnswer(QUESTIONS, [{ selected: ['Z'] }, { other: '   ' }]), { ok: false, missing: [0, 1] });
  assert.deepEqual(questionsAnswer(QUESTIONS, []), { ok: false, missing: [0, 1] });
});

test('review-rows: every row needs a choice; edits carry only what changed', () => {
  const answer = reviewAnswer(ROWS, {
    'q1-a': { action: 'edit', decision: '割引は請求書と領収書に適用', anchors: ['確定', '領収書'], page: 'QA/Decisions/order' },
    'q1-b': { action: 'skip' },
    'q2-a': { action: 'write' },
  });
  assert.deepEqual(answer, {
    ok: true,
    answer: { rows: {
      'q1-a': { action: 'edit', decision: '割引は請求書と領収書に適用', anchors: ['確定', '領収書'] },
      'q1-b': { action: 'skip' },
      'q2-a': { action: 'write' },
    } },
  });
});

test('review-rows: an incomplete answer is refused', () => {
  const missing = reviewAnswer(ROWS, { 'q1-a': { action: 'write' } });
  assert.deepEqual(missing, { ok: false, missing: ['q1-b', 'q2-a'], badEdits: [] });
  const unchanged = reviewAnswer(ROWS, {
    'q1-a': { action: 'edit', decision: '割引は請求書にも適用', anchors: ['確定'] },
    'q1-b': { action: 'write' }, 'q2-a': { action: 'bogus' },
  });
  assert.deepEqual(unchanged, { ok: false, missing: ['q2-a'], badEdits: ['q1-a'] });
  assert.equal(reviewAnswer(ROWS, null).ok, false);
});

test('review-rows: a page-only edit is enough', () => {
  const r = reviewAnswer({ rows: [ROWS.rows[2]] }, { 'q2-a': { action: 'edit', page: 'QA/Decisions/order' } });
  assert.deepEqual(r.answer.rows['q2-a'], { action: 'edit', page: 'QA/Decisions/order' });
});

test('confirm-diff and paste-pages answers', () => {
  assert.deepEqual(confirmAnswer(true), { confirm: true });
  assert.deepEqual(confirmAnswer('yes'), { confirm: false });
  assert.deepEqual(pasteAnswer(), { done: true });
});

test('anchors split on commas, semicolons and Japanese separators', () => {
  assert.deepEqual(splitAnchors('確定, 合計；割引、領収書;  '), ['確定', '合計；割引', '領収書']);
  assert.deepEqual(splitAnchors(''), []);
});

test('survey checks mirror the server and prefill prefers the remembered repo', () => {
  assert.equal(looksAbsolute('C:\\work\\app'), true);
  assert.equal(looksAbsolute('/home/a/app'), true);
  assert.equal(looksAbsolute('\\\\server\\share'), true);
  assert.equal(looksAbsolute('work/app'), false);
  assert.deepEqual(checkSurvey({ ticket: 'DEMO-1', repo: 'C:\\app', master_ref: 'master', develop_ref: 'release/1.2', feature: '注文確定', report_lang: 'ja' }), {});
  assert.deepEqual(Object.keys(checkSurvey({ ticket: '', repo: 'app', master_ref: 'a b', feature: 'x y', report_lang: 'fr' })).sort(),
    ['feature', 'master_ref', 'repo', 'report_lang', 'ticket']);
  const fm = { ticket: 'DEMO-2', repo: '/old/clone', master_ref: 'master', develop_ref: 'develop', lang: 'ja', cache_feature: 'order' };
  assert.deepEqual(prefillFromReport(fm, 'D:\\repos\\app', 'vi'),
    { ticket: 'DEMO-2', repo: 'D:\\repos\\app', master_ref: 'master', develop_ref: 'develop', feature: 'order', report_lang: 'ja', fetch: false });
  assert.equal(prefillFromReport(fm, '', 'vi').repo, '/old/clone');
  assert.equal(prefillFromReport({ repo: 'relative' }, '', 'en').repo, '');
  assert.equal(prefillFromReport({}, '', 'en').report_lang, 'en');
});

test('queue again keeps the job parameters; the server pins the latest revision', () => {
  assert.equal(revOf('DEMO-1-survey-r12.md'), 'r12');
  assert.equal(revOf(null), '');
  assert.deepEqual(requeueBody({ kind: 'close', ticket: 'DEMO-1', params: { tester: 'A' } }, 'B'), { kind: 'close', ticket: 'DEMO-1', tester: 'A' });
  assert.deepEqual(requeueBody({ kind: 'testcase', ticket: 'DEMO-1', params: { mode: 'write', template: 't', workbook: 'w.xlsx', focus: ['R3'] } }),
    { kind: 'testcase', ticket: 'DEMO-1', mode: 'write', template: 't', workbook: 'w.xlsx', focus: ['R3'] });
  assert.deepEqual(requeueBody({ kind: 'survey', ticket: 'DEMO-1', report_lang: 'ja', params: { repo: '/r', fetch: true, develop_ref: 'dev' } }),
    { kind: 'survey', ticket: 'DEMO-1', repo: '/r', fetch: true, develop_ref: 'dev', report_lang: 'ja' });
});
