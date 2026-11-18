import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createStore, newSessions, statusKey, viewKey } from '../store.mjs';

const base = (over = {}) => ({
  agent: { attached: false, waiting: false, last_contact: null, silent_seconds: null },
  queue: [], open: null, needs_input: 0, browser_sessions: ['2026-11-19T09:00:00+07:00'], change: 1, ...over,
});

function fakeDoc(state = 'visible') {
  const listeners = {};
  return {
    visibilityState: state,
    addEventListener: (type, fn) => { listeners[type] = fn; },
    removeEventListener: (type) => { delete listeners[type]; },
    fire(type) { if (listeners[type]) listeners[type](); },
    listeners,
  };
}

function fakeTimers() {
  const pending = new Map();
  let next = 1;
  return {
    setTimer: (fn, ms) => { const id = next++; pending.set(id, { fn, ms }); return id; },
    clearTimer: (id) => pending.delete(id),
    pending,
    async runAll() {
      const items = [...pending.entries()];
      pending.clear();
      for (const [, item] of items) await item.fn();
    },
  };
}

test('views hear a state only when the change counter (or silence/attachment) moves', () => {
  const store = createStore({ fetchState: async () => null, doc: fakeDoc() });
  const seen = [];
  store.onChange((s) => seen.push(s.change));
  assert.deepEqual(store.apply(base()), { view: true, status: true });
  assert.deepEqual(store.apply(base({ agent: { ...base().agent, silent_seconds: 30 } })), { view: false, status: false });
  assert.equal(store.apply(base({ change: 2 })).view, true);
  assert.equal(store.apply(base({ change: 2 })).view, false);
  const silent = base({ change: 2, agent: { attached: true, waiting: false }, open: { id: 'j1', state: 'running', silent: true } });
  assert.equal(store.apply(silent).view, true);
  assert.deepEqual(seen, [1, 2, 2]);
  assert.equal(store.get(), silent);
});

test('the sidebar hears agent and needs-input changes without a counter change', () => {
  const store = createStore({ fetchState: async () => null, doc: fakeDoc() });
  let statuses = 0;
  store.onStatus(() => { statuses += 1; });
  store.apply(base());
  store.apply(base({ agent: { attached: true, waiting: true } }));
  store.apply(base({ agent: { attached: true, waiting: true } }));
  assert.equal(statuses, 2);
  assert.notEqual(statusKey(base({ needs_input: 1 })), statusKey(base()));
  assert.equal(viewKey(null), null);
});

test('new browser sessions are announced, the first state only learns them', () => {
  const store = createStore({ fetchState: async () => null, doc: fakeDoc() });
  const notices = [];
  store.onSessions((s) => notices.push(s));
  store.apply(base());
  store.apply(base());
  store.apply(base({ browser_sessions: ['2026-11-19T09:00:00+07:00', '2026-11-19T10:00:00+07:00'] }));
  assert.deepEqual(notices, [['2026-11-19T10:00:00+07:00']]);
  const known = new Set(['a']);
  assert.deepEqual(newSessions(known, ['a', 'b', 'b']), ['b']);
});

test('polling runs every interval while visible and stops while hidden', async () => {
  const doc = fakeDoc('visible');
  const timers = fakeTimers();
  let calls = 0;
  const store = createStore({
    fetchState: async () => { calls += 1; return base({ change: calls }); },
    doc, setTimer: timers.setTimer, clearTimer: timers.clearTimer, interval: 1500,
  });
  store.start();
  await new Promise((r) => setImmediate(r));
  assert.equal(calls, 1);
  assert.equal(timers.pending.size, 1);
  assert.equal([...timers.pending.values()][0].ms, 1500);
  await timers.runAll();
  assert.equal(calls, 2);
  doc.visibilityState = 'hidden';
  doc.fire('visibilitychange');
  assert.equal(timers.pending.size, 0);
  await timers.runAll();
  assert.equal(calls, 2);
  doc.visibilityState = 'visible';
  doc.fire('visibilitychange');
  await new Promise((r) => setImmediate(r));
  assert.equal(calls, 3);
  assert.equal(timers.pending.size, 1);
  store.stop();
  assert.equal(timers.pending.size, 0);
  assert.equal(doc.listeners.visibilitychange, undefined);
});

test('a failed poll is reported once and cleared by the next state', async () => {
  let fail = true;
  const store = createStore({
    fetchState: async () => { if (fail) throw Object.assign(new Error('x'), { code: 'network' }); return base(); },
    doc: fakeDoc('hidden'),
  });
  const errors = [];
  store.onError((e) => errors.push(e ? e.code : null));
  await store.pollNow();
  await store.pollNow();
  fail = false;
  await store.pollNow();
  assert.deepEqual(errors, ['network', null]);
  assert.equal(store.error(), null);
});

test('a 403 while polling stops the store', async () => {
  const doc = fakeDoc('visible');
  const timers = fakeTimers();
  const store = createStore({
    fetchState: async () => { throw Object.assign(new Error('forbidden'), { status: 403, code: 'forbidden' }); },
    doc, setTimer: timers.setTimer, clearTimer: timers.clearTimer,
  });
  store.start();
  await new Promise((r) => setImmediate(r));
  assert.equal(timers.pending.size, 0);
});

test('known sessions survive a reload, so a new one is still announced and old ones are not', () => {
  let saved = null;
  const sessions = { load: () => saved, save: (list) => { saved = list; } };
  const first = createStore({ fetchState: async () => null, doc: fakeDoc(), sessions });
  first.apply(base());
  assert.deepEqual(saved, ['2026-11-19T09:00:00+07:00']);
  const reloaded = createStore({ fetchState: async () => null, doc: fakeDoc(), sessions });
  const notices = [];
  reloaded.onSessions((s) => notices.push(s));
  reloaded.apply(base({ browser_sessions: ['2026-11-19T09:00:00+07:00', '2026-11-19T11:00:00+07:00'] }));
  assert.deepEqual(notices, [['2026-11-19T11:00:00+07:00']]);
});
