// Entry point: preferences, strings, session, then the shell and the view for the current hash.

import { api, bootstrap, readLaunchCode, setForbiddenHandler } from './api.mjs';
import { h, mount } from './dom.mjs';
import { createTranslator, loadDictionaries } from './i18n.mjs';
import { closePalette, isPaletteKey, openPalette, paletteOpen, singleKeyAllowed } from './palette.mjs';
import * as prefs from './prefs.mjs';
import { href, parseRoute, sectionOf } from './router.mjs';
import { clearEscapes, renderReopen, renderShell, runEscape, setNavCount, toast } from './views/shell.mjs';
import * as tickets from './views/tickets.mjs';
import * as report from './views/report.mjs';
import * as trace from './views/trace.mjs';
import * as templates from './views/templates.mjs';
import * as cache from './views/cache.mjs';
import * as settings from './views/settings.mjs';

const VIEWS = { tickets, report, trace, templates, cache, settings };

const app = {
  dicts: {},
  lang: 'vi',
  t: (key) => key,
  routeKey: null,
  memo: new Map(),
  counts: {},
  ticketList: null,
  keyHandler: null,
  generation: 0,
  forbidden: false,
};

function applyPrefs() {
  app.lang = prefs.getLang();
  app.t = createTranslator(app.dicts, app.lang);
  const root = document.documentElement;
  root.lang = app.lang;
  root.dataset.theme = prefs.getTheme();
  document.title = app.t('app_title');
}

function showReopen() {
  if (app.forbidden) return;
  app.forbidden = true;
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

function loadCounts() {
  memo('count:tickets', () => api.tickets()).then((d) => {
    app.ticketList = d.tickets;
    setCount('tickets', d.tickets.length);
  }, () => {});
  memo('count:templates', () => api.templates()).then((d) => setCount('templates', d.templates.length), () => {});
  memo('count:cache', () => api.cache()).then((d) => setCount('cache', d.entries.length), () => {});
}

function paletteItems() {
  const t = app.t;
  const go = (hash) => () => { location.hash = hash; };
  const screens = [
    ['tickets', 'file', 'nav_tickets'], ['templates', 'layers', 'nav_templates'],
    ['cache', 'folder', 'nav_cache'], ['settings', 'settings', 'nav_settings'],
  ].map(([name, ic, key]) => ({ group: t('palette_screens'), label: t(key), icon: ic, run: go(href([name])) }));
  const ticketItems = (list) => list.flatMap((tk) => [
    { group: t('palette_tickets'), label: tk.id, hint: tk.title || '', icon: 'file', run: go(href(['tickets', tk.id])) },
    ...(tk.workbooks && tk.workbooks.length
      ? [{ group: t('palette_tickets'), label: `${tk.id} · ${t('trace_crumb')}`, icon: 'layers', run: go(href(['tickets', tk.id, 'trace'])) }]
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

/** Render the shell and the current route. Data loaded for the same route is reused. */
function render({ keepFocus } = {}) {
  if (app.forbidden) return;
  const focusGroup = keepFocus && document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.radio : null;
  const route = parseRoute(location.hash);
  if (route.name === 'notfound') {
    location.replace(href(['tickets']));
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
  const generation = ++app.generation;
  const shell = renderShell({
    t: app.t, lang: app.lang, section: sectionOf(route), counts: app.counts, onLang, onPalette: showPalette,
  });
  mount(document.getElementById('app'), ...shell.root);
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
    setTickets: (list) => { app.ticketList = list; setCount('tickets', list.length); },
    onKey: (fn) => { app.keyHandler = fn; },
    toast,
    setLang: onLang,
    setTheme: onTheme,
  };
  VIEWS[route.name].render(ctx);
  if (focusGroup) {
    const el = document.querySelector(`[data-radio="${focusGroup}"][aria-checked="true"]`);
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
  if (!location.hash || location.hash === '#') history.replaceState(null, '', `${location.pathname}${href(['tickets'])}`);
  render();
  loadCounts();
}

async function start() {
  app.dicts = await loadDictionaries();
  applyPrefs();
  setForbiddenHandler(showReopen);
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
