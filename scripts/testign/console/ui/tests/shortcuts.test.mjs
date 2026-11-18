import assert from 'node:assert/strict';
import { test } from 'node:test';

import { filterItems, isPaletteKey, isTypingTarget, singleKeyAllowed } from '../palette.mjs';
import { fakeElement } from './fake-dom.mjs';

test('inputs, textareas, selects and contenteditable count as typing targets', () => {
  assert.equal(isTypingTarget(fakeElement('input')), true);
  assert.equal(isTypingTarget(fakeElement('textarea')), true);
  assert.equal(isTypingTarget(fakeElement('select')), true);
  assert.equal(isTypingTarget(fakeElement('div', { contenteditable: 'true' })), true);
  assert.equal(isTypingTarget(fakeElement('div', { contenteditable: '' })), true);
  assert.equal(isTypingTarget(fakeElement('div', { isContentEditable: true })), true);
});

test('a child of an editable host is a typing target too', () => {
  const host = fakeElement('div', { contenteditable: 'true' });
  const child = fakeElement('span', {}, host);
  assert.equal(isTypingTarget(child), true);
});

test('buttons, rows and the body are not typing targets', () => {
  assert.equal(isTypingTarget(fakeElement('button')), false);
  assert.equal(isTypingTarget(fakeElement('tr')), false);
  assert.equal(isTypingTarget(fakeElement('div', { contenteditable: 'false' })), false);
  assert.equal(isTypingTarget(null), false);
});

test('single-key shortcuts are ignored in fields and with modifiers', () => {
  const key = (target, extra = {}) => ({ key: 'j', target, ctrlKey: false, metaKey: false, altKey: false, ...extra });
  assert.equal(singleKeyAllowed(key(fakeElement('body'))), true);
  assert.equal(singleKeyAllowed(key(fakeElement('input'))), false);
  assert.equal(singleKeyAllowed(key(fakeElement('textarea'))), false);
  assert.equal(singleKeyAllowed(key(fakeElement('select'))), false);
  assert.equal(singleKeyAllowed(key(fakeElement('div', { contenteditable: 'true' }))), false);
  assert.equal(singleKeyAllowed(key(fakeElement('body'), { ctrlKey: true })), false);
  assert.equal(singleKeyAllowed(key(fakeElement('body'), { metaKey: true })), false);
});

test('the palette opens with Ctrl+K or Cmd+K, even from a field', () => {
  assert.equal(isPaletteKey({ key: 'k', ctrlKey: true }), true);
  assert.equal(isPaletteKey({ key: 'K', metaKey: true }), true);
  assert.equal(isPaletteKey({ key: 'k' }), false);
  assert.equal(isPaletteKey({ key: 'k', ctrlKey: true, shiftKey: true }), false);
});

test('palette filtering matches every word against label and hint', () => {
  const items = [{ label: 'DEMO-1', hint: '注文確定' }, { label: 'DEMO-2', hint: 'Points' }, { label: 'Templates' }];
  assert.deepEqual(filterItems(items, '').length, 3);
  assert.deepEqual(filterItems(items, 'demo').map((i) => i.label), ['DEMO-1', 'DEMO-2']);
  assert.deepEqual(filterItems(items, 'demo points').map((i) => i.label), ['DEMO-2']);
  assert.deepEqual(filterItems(items, '注文').map((i) => i.label), ['DEMO-1']);
});
