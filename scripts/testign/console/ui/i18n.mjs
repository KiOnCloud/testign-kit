// UI strings: flat keys, `{name}` interpolation, fallback to vi and then to the key itself.
// Only chrome goes through t(); report content is shown as written.

import { LANGS } from './prefs.mjs';

export const FALLBACK = 'vi';

/** Replace `{name}` with params.name; unknown placeholders stay as they are. */
export function interpolate(text, params) {
  if (!params) return text;
  return text.replace(/\{([a-zA-Z0-9_]+)\}/g, (whole, name) =>
    Object.prototype.hasOwnProperty.call(params, name) && params[name] !== undefined && params[name] !== null
      ? String(params[name])
      : whole);
}

function lookup(dict, key) {
  const value = dict && Object.prototype.hasOwnProperty.call(dict, key) ? dict[key] : undefined;
  return typeof value === 'string' && value !== '' ? value : undefined;
}

/**
 * A translator over `dicts` ({vi: {...}, en: {...}, ja: {...}}) for `lang`.
 * With params.n === 1 a `<key>_one` entry is preferred when it exists.
 */
export function createTranslator(dicts, lang) {
  const primary = dicts[lang] || {};
  const fallback = dicts[FALLBACK] || {};
  return function t(key, params) {
    const keys = params && params.n === 1 ? [`${key}_one`, key] : [key];
    for (const k of keys) {
      const text = lookup(primary, k) ?? lookup(fallback, k);
      if (text !== undefined) return interpolate(text, params);
    }
    return key;
  };
}

/** Fetch the three dictionaries; a dictionary that fails to load is empty, so t() falls back. */
export async function loadDictionaries(fetchImpl = globalThis.fetch) {
  const entries = await Promise.all(LANGS.map(async (lang) => {
    try {
      const res = await fetchImpl(`/i18n/${lang}.json`, { cache: 'no-cache' });
      if (!res.ok) return [lang, {}];
      const data = await res.json();
      return [lang, data && typeof data === 'object' && !Array.isArray(data) ? data : {}];
    } catch {
      return [lang, {}];
    }
  }));
  return Object.fromEntries(entries);
}
