import assert from 'node:assert/strict';
import { test } from 'node:test';

import { readLaunchCode } from '../api.mjs';
import * as prefs from '../prefs.mjs';

function memoryStore() {
  const data = new Map();
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    data,
  };
}

const throwing = {
  getItem: () => { throw new Error('blocked'); },
  setItem: () => { throw new Error('blocked'); },
};

test('default language follows the browser: ja, en, else vi', () => {
  assert.equal(prefs.defaultLang(['ja-JP', 'en-US']), 'ja');
  assert.equal(prefs.defaultLang(['en-GB']), 'en');
  assert.equal(prefs.defaultLang(['vi-VN', 'en']), 'vi');
  assert.equal(prefs.defaultLang(['fr-FR', 'en-US']), 'en');
  assert.equal(prefs.defaultLang(['fr-FR']), 'vi');
  assert.equal(prefs.defaultLang([]), 'vi');
  assert.equal(prefs.defaultLang(undefined), 'vi');
});

test('saved values round-trip and unknown ones fall back', () => {
  const store = memoryStore();
  assert.equal(prefs.getTheme(store), 'light');
  prefs.setTheme('dark', store);
  assert.equal(prefs.getTheme(store), 'dark');
  store.setItem('testign.theme', 'neon');
  assert.equal(prefs.getTheme(store), 'light');
  prefs.setLang('ja', store);
  assert.equal(prefs.getLang(store), 'ja');
  assert.equal(store.data.get('testign.uiLang'), 'ja');
  assert.throws(() => prefs.setLang('fr', store), RangeError);
  prefs.setTesterName('  Tester A  ', store);
  assert.equal(prefs.getTesterName(store), 'Tester A');
  prefs.setTesterName('x'.repeat(500), store);
  assert.equal(prefs.getTesterName(store).length, prefs.TESTER_NAME_MAX);
});

test('blocked storage never throws and gives defaults', () => {
  assert.equal(prefs.getTheme(throwing), 'light');
  assert.equal(prefs.getTesterName(throwing), '');
  assert.equal(prefs.setTheme('dark', throwing), false);
  assert.equal(prefs.setTesterName('A', throwing), false);
  assert.ok(prefs.LANGS.includes(prefs.getLang(throwing)));
});

test('the launch code is read only from a #c= hash', () => {
  assert.equal(readLaunchCode('#c=AbC-_123'), 'AbC-_123');
  assert.equal(readLaunchCode('#/tickets'), null);
  assert.equal(readLaunchCode('#c='), null);
  assert.equal(readLaunchCode('#c=a b'), null);
  assert.equal(readLaunchCode('#c=abc&x=1'), null);
  assert.equal(readLaunchCode(''), null);
});
