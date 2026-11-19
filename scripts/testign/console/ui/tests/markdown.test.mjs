import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import { askBody, markdownBlocks, pipeCells, prose } from '../markdown.mjs';
import { installFakeDocument } from './fake-dom.mjs';

beforeEach(() => installFakeDocument());

const tags = (nodes) => nodes.map((n) => n.tagName.toLowerCase());
const find = (el, tag) => {
  if (el.tagName === tag.toUpperCase()) return [el];
  return (el.childNodes || []).flatMap((c) => (c.nodeType === 1 ? find(c, tag) : []));
};

test('pipe cells: outer pipes dropped, escaped pipes kept, cells trimmed', () => {
  assert.deepEqual(pipeCells('| a | b \\| c |  |'), ['a', 'b | c', '']);
  assert.deepEqual(pipeCells('x|y'), ['x', 'y']);
  assert.deepEqual(pipeCells('| ends with \\|'), ['ends with |']);
});

test('a template preview renders as heading, paragraphs and real tables', () => {
  const text = [
    '### Template preview: Sample (sample.xlsx)',
    '',
    '**Header row:** 4',
    '',
    '| Role | Column | Header |',
    '|---|---|---|',
    '| item | B | 確認項目 |',
    '| trace | H | 備考 |',
    '',
    '**Sheet!A1:B2**',
    '',
    '| # | A | B |',
    '|---|:---:|---|',
    '| 1 | テストケース一覧 |  |',
  ].join('\n');
  const nodes = markdownBlocks(text, 'en');
  assert.deepEqual(tags(nodes), ['h3', 'p', 'div', 'p', 'div']);
  const [first, second] = [find(nodes[2], 'table')[0], find(nodes[4], 'table')[0]];
  assert.deepEqual(find(first, 'th').map((th) => th.textContent), ['Role', 'Column', 'Header']);
  assert.deepEqual(find(first, 'tr').slice(1).map((tr) => find(tr, 'td').map((td) => td.textContent)),
    [['item', 'B', '確認項目'], ['trace', 'H', '備考']]);
  assert.deepEqual(find(second, 'td').map((td) => td.textContent), ['1', 'テストケース一覧', '']);
  assert.equal(find(nodes[1], 'strong')[0].textContent, 'Header row:');
});

test('markup in an ask body stays text', () => {
  const body = askBody('<img src=x onerror=alert(1)>\n| <b>x</b> |\n|---|\n| <script>y</script> |', 'vi');
  assert.equal(body.getAttribute('class'), 'ask-body');
  assert.equal(body.getAttribute('lang'), 'vi');
  assert.equal(find(body, 'img').length + find(body, 'b').length + find(body, 'script').length, 0);
  assert.match(body.textContent, /<img src=x onerror=alert\(1\)>/);
  assert.match(body.textContent, /<script>y<\/script>/);
});

test('one-line bodies stay one paragraph; lists group consecutive items', () => {
  assert.deepEqual(tags(markdownBlocks('Backlog MCP is not available.', 'en')), ['p']);
  assert.deepEqual(tags(markdownBlocks('Open:\n- Q1\n- Q2\n1. a\n2. b', 'en')), ['p', 'ul', 'ol']);
});

test('report prose skips table lines, as before', () => {
  const nodes = prose(['Intro', '| a | b |', '|---|---|', '| 1 | 2 |', '- item'], 'vi');
  assert.deepEqual(tags(nodes), ['p', 'ul']);
});
