// Playwright steps as one line each, for a Login Recipe or a suite's replay spec. A step holds a
// locator and a value (a path, a text, or a {{placeholder}} for a sign-in value), never a secret.

import { h } from '../dom.mjs';

/** A locator in words: role "button" name "Sign in", label "User", css "body". */
export function locatorText(loc) {
  if (!loc || typeof loc !== 'object') return '';
  const parts = [];
  for (const key of ['role', 'name', 'label', 'text', 'placeholder', 'test_id', 'css']) {
    if (loc[key] !== undefined && loc[key] !== null && loc[key] !== '') parts.push(`${key}=${JSON.stringify(String(loc[key]))}`);
  }
  if (loc.nth !== undefined) parts.push(`nth=${loc.nth}`);
  return parts.join(' ');
}

/** One step as `action locator → value`. */
export function stepText(step) {
  if (!step || typeof step !== 'object') return '';
  const loc = locatorText(step.locator);
  const value = step.value === undefined || step.value === null ? '' : String(step.value);
  return [step.action || '?', loc, value ? `→ ${value}` : ''].filter(Boolean).join(' ');
}

/** The steps as an ordered list in monospace. */
export function stepList(steps) {
  return h('ol.signin-steps.mono', (steps || []).map((s) => h('li', stepText(s))));
}
