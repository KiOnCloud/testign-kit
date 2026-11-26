// Entry point: preferences, strings, session, then the shell and the view for the current hash.

import { api, bootstrap, readLaunchCode, setForbiddenHandler } from './api.mjs';
import { h, mount } from './dom.mjs';
import { createTranslator, loadDictionaries } from './i18n.mjs';
import { closePalette, isPaletteKey, openPalette, paletteOpen, singleKeyAllowed } from './palette.mjs';
import * as prefs from './prefs.mjs';
import { HOME, href, legacyReviewTarget, parseRoute, redirectOf, sectionOf } from './router.mjs';
import { createStore, openJobClosed } from './store.mjs';
import {
  clearEscapes, LANG_SELECT_ID, renderReopen, renderShell, runEscape, setNavCount, showSessionNotice, toast, updateAgentStatus,
} from './views/shell.mjs';
import * as suites from './views/suites.mjs';
import * as suiteNew from './views/suite-new.mjs';
import * as suite from './views/suite.mjs';
import * as survey from './views/survey.mjs';
import * as report from './views/report.mjs';
import * as trace from './views/trace.mjs';
import * as runs from './views/runs.mjs';
import * as run from './views/run.mjs';
import * as defects from './views/defects.mjs';
import * as agent from './views/jobs.mjs';
import * as projects from './views/projects.mjs';
import * as scenarios from './views/scenarios.mjs';
import * as templates from './views/templates.mjs';
import * as cache from './views/cache.mjs';
import * as settings from './views/settings.mjs';

const VIEWS = {
  suites, suiteNew, suite, survey, report, trace, runs, run, defects, agent, projects, scenarios, templates, cache, settings,
};
const SESSIONS_KEY = 'testign.knownSessions';
const store = createStore({
  fetchState: () => api.state(),
  sessions: {
    load: () => { try { return JSON.parse(sessionStorage.getItem(SESSIONS_KEY) || 'null'); } catch { return null; } },
    save: (list) => { try { sessionStorage.setItem(SESSIONS_KEY, JSON.stringify(list)); } catch { /* blocked */ } },
  },
});

const app = {
  dicts: {},
  lang: prefs.DEFAULT_LANG,
  t: (key) => key,
  routeKey: null,
  memo: new Map(),
  counts: {},
  ticketList: null,
  keyHandler: null,
  storeHandler: null,
  generation: 0,
  forbidden: false,
};

function applyPrefs() {
  app.lang = prefs.getLang();
  app.t = createTranslator(app.dicts, app.lang);
  const root = document.documentElement;
  root.lang = app.lang;
  root.dataset.theme = prefs.getTheme();
  updateTitle();
}

/** The tab title carries the number of jobs waiting for an answer. */
function updateTitle() {
  const st = store.get();
  const n = st ? st.needs_input || 0 : 0;
  document.title = n ? `(${n}) ${app.t('app_title')}` : app.t('app_title');
}

function showReopen() {
  if (app.forbidden) return;
  app.forbidden = true;
  store.stop();
  closePalette();
  clearEscapes();
  for (const layer of document.querySelectorAll('.layer')) layer.remove();
  mount(document.getElementById('app'), renderReopen(app.t));
}

function memo(key, fn) {
  if (!app.memo.has(key)) {
    const p = Promise.resolve().then(fn);
    app.memo.set(key, p);
    p.catch(() => { if (app.memo.get(key) === p) app.memo.delete(key); });
  }
  return app.memo.get(key);
}

function setCount(key, value) {
  app.counts[key] = value;
  setNavCount(key, value);
}

/** Counts again after a job closed: it may have added a ticket, a revision or a cache entry. */
function reloadCounts() {
  for (const key of [...app.memo.keys()]) if (key.startsWith('count:')) app.memo.delete(key);
  app.ticketList = null;
  loadCounts();
}

function loadCounts() {
  memo('count:suites', () => api.suites()).then((d) => setCount('suites', d.suites.length), () => {});
  memo('count:tickets', () => api.tickets()).then((d) => {
    app.ticketList = d.tickets;
    setCount('survey', d.tickets.length);
  }, () => {});
  memo('count:runs', () => api.runs()).then((d) => setCount('runs', d.runs.length), () => {});
  memo('count:defects', () => api.defects()).then((d) => setCount('defects', d.counts.draft), () => {});
  memo('count:projects', () => api.projects()).then((d) => {
    setCount('projects', d.projects.length);
    setCount('scenarios', d.projects.reduce((n, p) => n + (Number(p.scenarios) || 0), 0));
  }, () => {});
  memo('count:templates', () => api.templates()).then((d) => setCount('templates', d.templates.length), () => {});
  memo('count:cache', () => api.cache()).then((d) => setCount('cache', d.entries.length), () => {});
}

function paletteItems() {
  const t = app.t;
  const go = (hash) => () => { location.hash = hash; };
  const screens = [
    ['suites', 'suite'], ['survey', 'search'], ['runs', 'refresh'], ['defects', 'warning'], ['agent', 'agent'], ['projects', 'folder'],
    ['scenarios', 'key'], ['templates', 'layers'], ['cache', 'database'], ['settings', 'sliders'],
  ].map(([name, ic]) => ({ group: t('palette_screens'), label: t(`nav_${name}`), icon: ic, run: go(href([name])) }));
  screens.splice(1, 0, { group: t('palette_screens'), label: t('new_suite'), icon: 'plus', run: go(href(['suites', 'new'])) });
  const ticketItems = (list) => list.flatMap((tk) => [
    { group: t('palette_tickets'), label: tk.id, hint: tk.title || '', icon: 'file', run: go(href(['survey', tk.id])) },
    ...(tk.workbooks && tk.workbooks.length
      ? [{ group: t('palette_tickets'), label: `${tk.id} · ${t('trace_crumb')}`, icon: 'layers', run: go(href(['survey', tk.id, 'trace'])) }]
      : []),
  ]);
  if (app.ticketList) return { items: screens.concat(ticketItems(app.ticketList)) };
  return {
    items: screens,
    more: memo('count:tickets', () => api.tickets()).then((d) => {
      app.ticketList = d.tickets;
      return ticketItems(d.tickets);
    }),
  };
}

function showPalette() {
  if (app.forbidden || paletteOpen()) return;
  const { items, more } = paletteItems();
  openPalette({ t: app.t, items, more });
}

function onLang(lang) {
  prefs.setLang(lang);
  applyPrefs();
  render({ keepFocus: true });
}

function onTheme(theme) {
  prefs.setTheme(theme);
  applyPrefs();
  render({ keepFocus: true });
}

/** An old review link opens the run its job worked on, or the job itself when it had no run. */
function followLegacyReview(id) {
  const generation = ++app.generation;
  api.job(id).then((job) => legacyReviewTarget(job, id), () => legacyReviewTarget(null, id)).then((target) => {
    if (generation === app.generation && !app.forbidden) location.replace(target);
  });
}

/** Render the shell and the current route. Data loaded for the same route is reused. */
function render({ keepFocus } = {}) {
  if (app.forbidden) return;
  const focusGroup = keepFocus && document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.radio : null;
  const focusLang = Boolean(keepFocus && document.activeElement && document.activeElement.id === LANG_SELECT_ID);
  const moved = redirectOf(location.hash);
  if (moved && moved.to) {
    location.replace(moved.to);
    return;
  }
  if (moved && moved.job) {
    followLegacyReview(moved.job);
    return;
  }
  const route = parseRoute(location.hash);
  if (route.name === 'notfound') {
    location.replace(href([HOME]));
    return;
  }
  const routeKey = `${route.name}|${JSON.stringify(route.params)}|${JSON.stringify(route.query)}`;
  if (routeKey !== app.routeKey) {
    for (const key of [...app.memo.keys()]) if (!key.startsWith('count:')) app.memo.delete(key);
    app.routeKey = routeKey;
  }
  closePalette();
  clearEscapes();
  for (const layer of document.querySelectorAll('.layer')) layer.remove();
  app.keyHandler = null;
  app.storeHandler = null;
  const generation = ++app.generation;
  const shell = renderShell({
    t: app.t, lang: app.lang, section: sectionOf(route), counts: app.counts, onLang, onPalette: showPalette, prefs,
  });
  mount(document.getElementById('app'), ...shell.root);
  updateAgentStatus(app.t, store.get(), store.error());
  const ctx = {
    t: app.t,
    lang: app.lang,
    route,
    api,
    prefs,
    memo,
    alive: () => generation === app.generation && !app.forbidden,
    topbar: (...nodes) => { if (generation === app.generation) mount(shell.topbar, ...nodes); },
    view: shell.view,
    ready: (name) => { if (generation === app.generation) shell.main.dataset.ready = name || route.name; },
    navigate: (hash) => { location.hash = hash; },
    refresh: () => {
      for (const key of [...app.memo.keys()]) if (!key.startsWith('count:')) app.memo.delete(key);
      render();
    },
    invalidate: (key) => app.memo.delete(key),
    setCount,
    setTickets: (list) => { app.ticketList = list; setCount('survey', list.length); },
    onKey: (fn) => { app.keyHandler = fn; },
    store,
    pollNow: () => store.pollNow(),
    onStoreChange: (fn) => { app.storeHandler = fn; },
    toast,
    setLang: onLang,
    setTheme: onTheme,
  };
  VIEWS[route.name].render(ctx);
  if (focusGroup) {
    const el = document.querySelector(`[data-radio="${focusGroup}"][aria-checked="true"]`);
    if (el) el.focus();
  }
  if (focusLang) {
    const el = document.getElementById(LANG_SELECT_ID);
    if (el) el.focus();
  }
}

function onKeydown(event) {
  if (app.forbidden) return;
  if (isPaletteKey(event)) {
    event.preventDefault();
    if (paletteOpen()) closePalette();
    else showPalette();
    return;
  }
  if (event.key === 'Escape') {
    if (closePalette() || runEscape()) event.preventDefault();
    return;
  }
  if (paletteOpen() || !singleKeyAllowed(event) || document.querySelector('.layer')) return;
  if (event.key === '/') {
    const search = document.querySelector('[data-search]');
    if (search) {
      event.preventDefault();
      search.focus();
    }
    return;
  }
  if (app.keyHandler && app.keyHandler(event) === true) event.preventDefault();
}

/** Exchange a launch code (or reuse this tab's session), then show the console or the reopen message. */
async function exchange() {
  const ok = await bootstrap();
  if (!ok) {
    showReopen();
    return;
  }
  app.forbidden = false;
  store.start();
  if (!location.hash || location.hash === '#') history.replaceState(null, '', `${location.pathname}${href([HOME])}`);
  render();
  loadCounts();
}

function wireStore() {
  store.onStatus((st) => {
    updateAgentStatus(app.t, st, null);
    updateTitle();
  });
  store.onError((err) => updateAgentStatus(app.t, store.get(), err));
  store.onSessions((times) => showSessionNotice(app.t, times, () => {
    api.releaseAgent().then((r) => {
      toast(r && r.released ? app.t('jobs_released') : app.t('session_no_agent'));
      store.pollNow();
    }, () => toast(app.t('err_generic', { code: 'release' }), 'danger'));
  }));
  let openId = null;
  store.onChange((st) => {
    if (openJobClosed(openId, st) && !app.forbidden) reloadCounts();
    openId = st && st.open ? st.open.id : null;
    if (app.storeHandler && !app.forbidden) app.storeHandler(st);
  });
}

async function start() {
  app.dicts = await loadDictionaries();
  applyPrefs();
  setForbiddenHandler(showReopen);
  wireStore();
  // A new launch URL pasted into this tab changes only the hash; exchange its code too.
  window.addEventListener('hashchange', () => {
    if (readLaunchCode(location.hash)) exchange().catch(showStartError);
    else render();
  });
  document.addEventListener('keydown', onKeydown);
  await exchange();
}

function showStartError() {
  mount(document.getElementById('app'), h('main.reopen', h('div.k-empty.reopen-box', [
    h('h1.k-empty__title', app.t('err_title')),
    h('p.k-empty__body', app.t('err_start')),
  ])));
}

start().catch(showStartError);
