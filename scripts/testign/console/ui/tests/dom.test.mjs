import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import { h, icon, inline, mount, showBidi, STATUS_CLASSES, statusGlyph, statusIcon } from '../dom.mjs';
import { installFakeDocument } from './fake-dom.mjs';

beforeEach(() => installFakeDocument());

test('text goes in as text, never as markup', () => {
  const el = h('p.note', '<img src=x onerror=alert(1)>');
  assert.equal(el.textContent, '<img src=x onerror=alert(1)>');
  assert.equal(el.children.length, 0);
  assert.equal(el.getAttribute('class'), 'note');
});

test('mixed children become text nodes and elements', () => {
  const el = h('div', ['a <b>', h('span', 'c'), 3]);
  assert.equal(el.childNodes.length, 3);
  assert.equal(el.childNodes[0].nodeType, 3);
  assert.equal(el.textContent, 'a <b>c3');
});

test('style and on* attributes are refused', () => {
  assert.throws(() => h('div', { style: 'color:red' }), /not allowed/);
  assert.throws(() => h('div', { STYLE: 'x' }), /not allowed/);
  assert.throws(() => h('a', { onclick: 'alert(1)' }), /not allowed/);
  assert.throws(() => h('a', { onMouseOver: 'x' }), /not allowed/);
});

test('handlers go through the on map as listeners', () => {
  const fn = () => {};
  const el = h('button', { on: { click: fn } }, 'Go');
  assert.deepEqual(el.listeners.click, [fn]);
  assert.equal(el.getAttribute('onclick'), null);
  assert.throws(() => h('button', { on: { click: 'alert(1)' } }), /not a function/);
});

test('classes from the tag and the class attribute merge; false values are skipped', () => {
  const el = h('span.k-badge', { class: ['k-badge--warning', false, ''], title: 'x', hidden: false, 'aria-label': null });
  assert.equal(el.getAttribute('class'), 'k-badge k-badge--warning');
  assert.equal(el.getAttribute('title'), 'x');
  assert.equal(el.getAttribute('hidden'), null);
  assert.equal(el.getAttribute('aria-label'), null);
});

test('bidi controls in customer text are made visible', () => {
  assert.equal(showBidi('abc‮def'), 'abc⟨U+202E⟩def');
  assert.equal(showBidi('‪‫‬‭'), '⟨U+202A⟩⟨U+202B⟩⟨U+202C⟩⟨U+202D⟩');
  assert.equal(showBidi('x⁦y⁧z⁨w⁩'), 'x⟨U+2066⟩y⟨U+2067⟩z⟨U+2068⟩w⟨U+2069⟩');
  assert.equal(showBidi('Tiếng Việt 日本語 ‏'), 'Tiếng Việt 日本語 ‏');
  assert.equal(h('td', 'evil‮txt.exe').textContent, 'evil⟨U+202E⟩txt.exe');
  assert.equal(h('td', ['a⁦', h('b', '⁩')]).textContent, 'a⟨U+2066⟩⟨U+2069⟩');
});

test('inline emphasis and code become elements, the rest stays text', () => {
  const parts = inline('**Câu hỏi:** dùng `CalcTotal` <script>');
  assert.equal(parts[0].tagName, 'STRONG');
  assert.equal(parts[0].textContent, 'Câu hỏi:');
  assert.equal(parts[1], ' dùng ');
  assert.equal(parts[2].tagName, 'CODE');
  assert.equal(parts[3], ' <script>');
});

test('mount replaces children', () => {
  const el = h('div', [h('span', 'old')]);
  mount(el, h('i', 'new'), 'text');
  assert.equal(el.textContent, 'newtext');
  assert.equal(el.childNodes.length, 2);
});

test('a status icon is a focusable anchor named by its tip, with the tip as its tooltip', () => {
  const el = statusIcon('warn', 'clock', 'Waiting for <you>');
  assert.equal(el.tagName, 'SPAN');
  assert.equal(el.getAttribute('class'), 'yh-tip-anchor st st--warn');
  assert.equal(el.getAttribute('tabindex'), '0');
  assert.equal(el.getAttribute('role'), 'img');
  assert.equal(el.getAttribute('aria-label'), 'Waiting for <you>');
  const [svg, tip] = el.children;
  assert.equal(svg.tagName, 'SVG');
  assert.equal(svg.getAttribute('class'), 'yh-icon');
  assert.equal(svg.getAttribute('aria-hidden'), 'true');
  assert.equal(tip.getAttribute('class'), 'yh-tip');
  assert.equal(tip.getAttribute('role'), 'tooltip');
  assert.equal(tip.textContent, 'Waiting for <you>');
  assert.throws(() => statusIcon('great', 'check', 'x'), RangeError);
});

test('status icons and glyphs take their tone from the same class map', () => {
  assert.deepEqual(Object.keys(STATUS_CLASSES), ['ok', 'warn', 'busy', 'bad']);
  for (const [kind, cls] of Object.entries(STATUS_CLASSES)) {
    assert.ok(statusIcon(kind, 'check', kind).getAttribute('class').split(' ').includes(cls));
  }
  assert.equal(statusGlyph('done').getAttribute('class'), `k-status ${STATUS_CLASSES.ok}`);
  assert.equal(statusGlyph('crossed', 'text-danger').getAttribute('class'), `k-status ${STATUS_CLASSES.bad} text-danger`);
  assert.equal(statusGlyph('unknown-shape').getAttribute('class'), `k-status ${STATUS_CLASSES.busy}`);
  assert.equal(icon('check', 'yh-icon--sm').getAttribute('class'), 'yh-icon yh-icon--sm');
});
