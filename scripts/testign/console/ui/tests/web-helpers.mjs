// Shared pieces for the web test run screen tests: the real dictionaries, a context that renders
// a view into the fake document, and a walker over the rendered tree.

import { readFileSync } from 'node:fs';

import { createTranslator } from '../i18n.mjs';
import { installFakeDocument } from './fake-dom.mjs';

export const DICTS = Object.fromEntries(['en', 'ja'].map((lang) =>
  [lang, JSON.parse(readFileSync(new URL(`../i18n/${lang}.json`, import.meta.url), 'utf-8'))]));

export function translator(lang = 'en') {
  return createTranslator(DICTS, lang);
}

/** Every element under `root` (depth first). */
export function walk(root, out = []) {
  for (const c of root.childNodes || []) {
    if (c.nodeType === 1) {
      out.push(c);
      walk(c, out);
    }
  }
  return out;
}

export function byData(root, key) {
  return walk(root).filter((el) => el.dataset && el.dataset[key] !== undefined);
}

/** A view context over the fake document; `api` supplies the calls the view makes. */
export function fakeContext(api, { route = { params: {}, query: {} }, lang = 'en' } = {}) {
  const document = installFakeDocument();
  const view = document.createElement('main');
  const calls = { toasts: [], navigated: [], ready: 0 };
  let readyResolve;
  const ready = new Promise((resolve) => { readyResolve = resolve; });
  const ctx = {
    t: translator(lang), lang, route, api, view,
    prefs: { getTesterName: () => 'Tester', setTesterName: () => {} },
    memo: (key, fn) => fn(),
    alive: () => true,
    topbar: () => {},
    ready: () => { calls.ready += 1; readyResolve(); },
    navigate: (to) => calls.navigated.push(to),
    refresh: () => {},
    invalidate: () => {},
    setCount: () => {},
    onKey: () => {},
    onStoreChange: () => {},
    store: { get: () => null },
    pollNow: () => {},
    toast: (text, kind) => calls.toasts.push([text, kind]),
  };
  return { ctx, view, calls, ready };
}
