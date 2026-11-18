// Console state from /api/state, polled every 1.5 s while the tab is visible and not at all while
// it is hidden. Views hear about a new state only when it changed (the server's change counter, the
// open job turning silent, or the agent attaching or leaving); the sidebar hears every status change.

export const POLL_MS = 1500;

/** What a view needs to redraw for: job records, the open job's silence, the agent being there. */
export function viewKey(state) {
  if (!state) return null;
  const open = state.open;
  const attached = Boolean(state.agent && state.agent.attached);
  return `${state.change}|${open ? `${open.id}:${open.silent ? 1 : 0}` : '-'}|${attached ? 1 : 0}`;
}

/** What the sidebar shows: agent line, needs-input count and the browser sessions. */
export function statusKey(state) {
  if (!state) return 'none';
  const a = state.agent || {};
  const open = state.open;
  return JSON.stringify([Boolean(a.attached), Boolean(a.waiting), Boolean(open && open.silent),
    open ? open.state : null, state.needs_input || 0, (state.queue || []).length, state.browser_sessions || []]);
}

/** Sessions in `next` that were not in `known`; the first state seen only fills `known`. */
export function newSessions(known, next) {
  const added = [];
  for (const s of next || []) {
    if (!known.has(s)) {
      known.add(s);
      added.push(s);
    }
  }
  return added;
}

/**
 * createStore({fetchState}) → {start, stop, apply, pollNow, get, onChange, onStatus, onSessions, onError}.
 * `doc`, `setTimer` and `clearTimer` are injectable for tests.
 */
export function createStore({
  fetchState, interval = POLL_MS, doc = globalThis.document,
  setTimer = (fn, ms) => setTimeout(fn, ms), clearTimer = (id) => clearTimeout(id), sessions = null,
}) {
  let state = null;
  let lastView = null;
  let lastStatus = null;
  // `sessions` ({load, save}) keeps the known sessions across a reload of this tab.
  let knownSessions = sessions && Array.isArray(sessions.load()) ? new Set(sessions.load()) : null;
  let timer = null;
  let running = false;
  let inFlight = false;
  let error = null;
  const listeners = { change: new Set(), status: new Set(), sessions: new Set(), error: new Set() };

  const emit = (kind, ...args) => {
    for (const fn of [...listeners[kind]]) {
      try {
        fn(...args);
      } catch {
        // A broken listener never stops polling.
      }
    }
  };

  /** Take a state; returns {view, status} telling which listeners were told. */
  function apply(next) {
    if (!next || typeof next !== 'object') return { view: false, status: false };
    state = next;
    const firstSessions = knownSessions === null;
    if (firstSessions) knownSessions = new Set();
    const added = newSessions(knownSessions, next.browser_sessions);
    if (!firstSessions && added.length) emit('sessions', added);
    if (sessions && (firstSessions || added.length)) sessions.save([...knownSessions]);
    const vk = viewKey(next);
    const sk = statusKey(next);
    const view = vk !== lastView;
    const status = sk !== lastStatus || error !== null;
    lastView = vk;
    lastStatus = sk;
    if (error !== null) {
      error = null;
      emit('error', null);
    }
    if (status) emit('status', next);
    if (view) emit('change', next);
    return { view, status };
  }

  function visible() {
    return !doc || doc.visibilityState === undefined || doc.visibilityState === 'visible';
  }

  function schedule() {
    if (timer !== null) clearTimer(timer);
    timer = running && visible() ? setTimer(tick, interval) : null;
  }

  async function tick() {
    timer = null;
    if (!running || !visible()) return;
    await pollNow();
    schedule();
  }

  async function pollNow() {
    if (inFlight) return;
    inFlight = true;
    try {
      apply(await fetchState());
    } catch (err) {
      if (err && err.status === 403) {
        stop();
      } else if (error === null || (err && err.code) !== (error && error.code)) {
        error = err || new Error('poll failed');
        emit('error', error);
      }
    } finally {
      inFlight = false;
    }
  }

  function onVisibility() {
    if (!running) return;
    if (visible()) {
      pollNow().then(schedule);
    } else if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
  }

  function start() {
    if (running) return;
    running = true;
    if (doc && typeof doc.addEventListener === 'function') doc.addEventListener('visibilitychange', onVisibility);
    if (visible()) pollNow().then(schedule);
  }

  function stop() {
    running = false;
    if (timer !== null) clearTimer(timer);
    timer = null;
    if (doc && typeof doc.removeEventListener === 'function') doc.removeEventListener('visibilitychange', onVisibility);
  }

  const sub = (kind) => (fn) => {
    listeners[kind].add(fn);
    return () => listeners[kind].delete(fn);
  };

  return {
    start, stop, apply, pollNow,
    get: () => state,
    error: () => error,
    polling: () => timer !== null,
    onChange: sub('change'),
    onStatus: sub('status'),
    onSessions: sub('sessions'),
    onError: sub('error'),
  };
}
