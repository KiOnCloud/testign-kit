// Per-viewer settings kept in localStorage. Storage can be missing or throw (private mode,
// blocked storage); every read and write is guarded and falls back to the default.

export const LANGS = ['vi', 'en', 'ja'];
export const THEMES = ['light', 'dark'];
const KEYS = { uiLang: 'testign.uiLang', theme: 'testign.theme', testerName: 'testign.testerName', lastRepo: 'testign.lastRepo' };
const NAME_MAX = 100;

function storage() {
  try {
    return globalThis.localStorage || null;
  } catch {
    return null;
  }
}

function read(key, store = storage()) {
  try {
    return store ? store.getItem(key) : null;
  } catch {
    return null;
  }
}

function write(key, value, store = storage()) {
  try {
    if (!store) return false;
    store.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

/** ja → ja, en → en, anything else → vi, from the first language the browser lists. */
export function defaultLang(languages) {
  const list = Array.isArray(languages) ? languages : [];
  for (const raw of list) {
    const tag = String(raw || '').toLowerCase();
    if (tag === 'ja' || tag.startsWith('ja-')) return 'ja';
    if (tag === 'en' || tag.startsWith('en-')) return 'en';
    if (tag === 'vi' || tag.startsWith('vi-')) return 'vi';
  }
  return 'vi';
}

function browserLanguages() {
  const nav = globalThis.navigator;
  if (!nav) return [];
  if (Array.isArray(nav.languages) && nav.languages.length) return nav.languages;
  return nav.language ? [nav.language] : [];
}

export function getLang(store) {
  const saved = read(KEYS.uiLang, store);
  return LANGS.includes(saved) ? saved : defaultLang(browserLanguages());
}

export function setLang(lang, store) {
  if (!LANGS.includes(lang)) throw new RangeError(`unknown language ${lang}`);
  return write(KEYS.uiLang, lang, store);
}

export function getTheme(store) {
  const saved = read(KEYS.theme, store);
  return THEMES.includes(saved) ? saved : 'light';
}

export function setTheme(theme, store) {
  if (!THEMES.includes(theme)) throw new RangeError(`unknown theme ${theme}`);
  return write(KEYS.theme, theme, store);
}

export function getTesterName(store) {
  const saved = read(KEYS.testerName, store);
  return typeof saved === 'string' ? saved.slice(0, NAME_MAX) : '';
}

export function setTesterName(name, store) {
  return write(KEYS.testerName, String(name ?? '').trim().slice(0, NAME_MAX), store);
}

export const TESTER_NAME_MAX = NAME_MAX;

/** The repo path last used for a survey, typed by the tester; empty when none. */
export function getLastRepo(store) {
  const saved = read(KEYS.lastRepo, store);
  return typeof saved === 'string' ? saved.slice(0, 1000) : '';
}

export function setLastRepo(path, store) {
  return write(KEYS.lastRepo, String(path ?? '').trim().slice(0, 1000), store);
}
