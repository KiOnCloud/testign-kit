import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { createTranslator, interpolate, loadDictionaries } from '../i18n.mjs';

const dicts = {
  vi: { hello: 'Xin chào {name}', only_vi: 'Chỉ tiếng Việt', items: '{n} mục', empty: 'vi-empty' },
  en: { hello: 'Hello {name}', items: '{n} items', items_one: '{n} item', empty: '' },
  ja: { hello: 'こんにちは {name}' },
};

test('interpolation fills named placeholders and leaves unknown ones', () => {
  assert.equal(interpolate('{a} and {b}', { a: 1 }), '1 and {b}');
  assert.equal(interpolate('{a}', { a: 0 }), '0');
  assert.equal(interpolate('{a}', { a: null }), '{a}');
  assert.equal(interpolate('no params'), 'no params');
});

test('a key resolves in the chosen language', () => {
  assert.equal(createTranslator(dicts, 'en')('hello', { name: 'A' }), 'Hello A');
  assert.equal(createTranslator(dicts, 'ja')('hello', { name: 'A' }), 'こんにちは A');
});

test('a missing key falls back to vi, then to the key', () => {
  const t = createTranslator(dicts, 'ja');
  assert.equal(t('only_vi'), 'Chỉ tiếng Việt');
  assert.equal(t('nowhere'), 'nowhere');
  assert.equal(createTranslator(dicts, 'xx')('hello', { name: 'B' }), 'Xin chào B');
});

test('an empty string counts as missing', () => {
  assert.equal(createTranslator(dicts, 'en')('empty'), 'vi-empty');
});

test('n === 1 prefers the _one form when it exists', () => {
  const en = createTranslator(dicts, 'en');
  assert.equal(en('items', { n: 1 }), '1 item');
  assert.equal(en('items', { n: 2 }), '2 items');
  assert.equal(createTranslator(dicts, 'vi')('items', { n: 1 }), '1 mục');
});

test('the shipped dictionaries load through fetch and a failed one falls back', async () => {
  const fake = async (url) => {
    const lang = /\/i18n\/(\w+)\.json$/.exec(url)[1];
    if (lang === 'ja') return { ok: false, json: async () => ({}) };
    const text = readFileSync(new URL(`../i18n/${lang}.json`, import.meta.url), 'utf-8');
    return { ok: true, json: async () => JSON.parse(text) };
  };
  const loaded = await loadDictionaries(fake);
  assert.deepEqual(Object.keys(loaded).sort(), ['en', 'ja', 'vi']);
  assert.deepEqual(loaded.ja, {});
  const t = createTranslator(loaded, 'ja');
  assert.equal(t('nav_tickets'), loaded.vi.nav_tickets);
  assert.equal(createTranslator(loaded, 'en')('tickets_th_questions'), 'Questions');
});
