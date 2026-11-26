// The frame around every screen (top bar, menu, content area) and the building blocks the views
// share: crumbs, page heads, fields, tables, loading, empty and error states, alerts, badges,
// dialogs, toasts and the Esc stack.

import { h, icon, mount } from '../dom.mjs';
import { trapFocus } from '../palette.mjs';
import { LANGS } from '../prefs.mjs';
import { HOME, href } from '../router.mjs';

export const LANG_NAMES = { en: 'English', ja: '日本語' };
/** The name of any language code, in the language itself (report languages may be more than the UI's). */
export function langName(code) {
  if (LANG_NAMES[code]) return LANG_NAMES[code];
  try {
    return new Intl.DisplayNames([code], { type: 'language' }).of(code) || code;
  } catch {
    return code;
  }
}

/** The id of the top bar's language select, so a re-render can give it focus back. */
export const LANG_SELECT_ID = 'ui-lang';

// Esc closes the topmost thing that registered itself: a dialog, then a split panel.
const escapeStack = [];

/** The product name as a wordmark: one span per letter. */
export function wordmark(name) {
  return h('span.wordmark', [...name].map((ch) => h('span', ch)));
}

export function pushEscape(fn) {
  escapeStack.push(fn);
  return () => {
    const i = escapeStack.lastIndexOf(fn);
    if (i >= 0) escapeStack.splice(i, 1);
  };
}

export function runEscape() {
  const fn = escapeStack[escapeStack.length - 1];
  if (!fn) return false;
  fn();
  return true;
}

export function clearEscapes() {
  escapeStack.length = 0;
}

export function isMac() {
  const nav = globalThis.navigator || {};
  const platform = (nav.userAgentData && nav.userAgentData.platform) || nav.platform || '';
  return /mac/i.test(platform);
}

/** A segmented radio group with one tab stop; arrows move and select. */
export function radioGroup({ label, labelledBy, options, value, onChange, name }) {
  const buttons = options.map((opt) => h('button.k-tab', {
    type: 'button', role: 'radio', 'aria-checked': opt.value === value ? 'true' : 'false',
    class: opt.value === value ? 'is-active' : '', tabindex: opt.value === value ? '0' : '-1',
    lang: opt.lang, dataset: { radio: name, value: opt.value },
    on: { click: () => { if (opt.value !== value) onChange(opt.value); } },
  }, opt.label));
  const group = h('div.k-tabs.k-tabs--segmented', {
    role: 'radiogroup', 'aria-label': labelledBy ? undefined : label, 'aria-labelledby': labelledBy,
    on: {
      keydown: (event) => {
        const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
        if (!(event.key in keys)) return;
        event.preventDefault();
        const i = options.findIndex((o) => o.value === value);
        const next = options[(i + keys[event.key] + options.length) % options.length];
        onChange(next.value);
      },
    },
  }, buttons);
  return group;
}

// The menu: three groups, each a bold row with a caret over its screens. Counts sit on the rows.
export const NAV = Object.freeze([
  { id: 'design', icon: 'design', items: [['suites', 'suite'], ['survey', 'search']] },
  { id: 'run', icon: 'play', items: [['runs', 'refresh'], ['defects', 'warning'], ['agent', 'agent']] },
  { id: 'config', icon: 'settings', items: [['projects', 'folder'], ['scenarios', 'key'], ['templates', 'layers'], ['cache', 'database'],
    ['settings', 'sliders']] },
]);

/** The group a menu row belongs to. */
export function groupOf(section) {
  const group = NAV.find((g) => g.items.some(([id]) => id === section));
  return group ? group.id : null;
}

function navGroups(t, section, counts, prefs) {
  const closed = prefs && prefs.getNavGroups ? prefs.getNavGroups() : {};
  const current = groupOf(section);
  return NAV.flatMap((g) => {
    // The group of the current screen stays open, so the menu always shows where the tester is.
    const open = g.id === current || closed[g.id] !== false;
    const sub = h('div.nav-sub', { id: `nav-sub-${g.id}`, hidden: open ? undefined : true, dataset: { navSub: g.id } },
      g.items.map(([id, iconName]) => h('a.nav-row', {
        href: href([id]), class: section === id ? 'is-active' : '', 'aria-current': section === id ? 'page' : undefined, dataset: { nav: id },
      }, [icon(iconName), h('span.nav-label', { title: t(`nav_${id}`) }, t(`nav_${id}`)),
        id === 'agent' ? h('span.n', { id: 'nav-jobs-badge' })
          : h('span.n', { dataset: { count: id } }, counts[id] === undefined ? '' : String(counts[id]))])));
    const button = h('button.nav-row.nav-group', {
      type: 'button', 'aria-expanded': open ? 'true' : 'false', 'aria-controls': sub.getAttribute('id'), dataset: { group: g.id },
      on: {
        click: () => {
          const next = button.getAttribute('aria-expanded') !== 'true';
          button.setAttribute('aria-expanded', next ? 'true' : 'false');
          sub.hidden = !next;
          if (prefs && prefs.setNavGroup) prefs.setNavGroup(g.id, next);
        },
      },
    }, [icon(g.icon), h('span.nav-label', t(`nav_group_${g.id}`)), icon('down', 'yh-icon--sm caret')]);
    return [button, sub];
  });
}

/** The top bar, the menu and the content area. Returns the parts the router fills. */
export function renderShell({ t, lang, section, counts, onLang, onPalette, prefs }) {
  const mod = isMac() ? '⌘' : 'Ctrl';
  const shell = h('div.shell');
  const navToggle = h('button.yh-tool.nav-toggle', {
    type: 'button', 'aria-label': t('nav_menu'), 'aria-controls': 'nav', 'aria-expanded': 'false',
    on: {
      click: () => {
        const open = !shell.classList.contains('is-nav-open');
        shell.classList.toggle('is-nav-open', open);
        navToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      },
    },
  }, icon('menu'));
  const langSelect = h('select.yh-select.yh-input--sm.lang-select', {
    id: LANG_SELECT_ID, 'aria-label': t('ui_lang'),
    on: { change: (event) => { if (LANGS.includes(event.target.value)) onLang(event.target.value); } },
  }, LANGS.map((l) => h('option', { value: l, lang: l, selected: l === lang }, LANG_NAMES[l])));
  const top = h('header.top', [
    navToggle,
    h('a.yh-logo', { href: href([HOME]) }, ['TESTIGN', ' ', h('small', t('nav_console'))]),
    h('div.top-tools', [
      h('button.yh-tool.top-search', {
        type: 'button', 'aria-label': `${t('nav_search')} (${mod}+K)`, 'aria-keyshortcuts': 'Control+K Meta+K', on: { click: onPalette },
      }, icon('search')),
      h('a.agent', { id: 'agent-status', href: href(['agent']), role: 'status' }),
      h('span.yh-select-wrap', langSelect),
    ]),
  ]);
  const nav = h('nav.nav', { id: 'nav', 'aria-label': t('nav_main') }, [
    ...navGroups(t, section, counts, prefs),
    h('p.nav-foot.k-note', t('local_only')),
  ]);
  // Views fill the crumbs row and the view; session notices stay between them across screens.
  const topbar = h('div.crumbs-row');
  const view = h('div.view', { id: 'view' });
  const notices = h('div.notices', { id: 'session-notices', 'aria-live': 'polite' });
  drawNotices(t, notices);
  const main = h('main.content', { id: 'main', tabindex: '-1' }, [topbar, notices, view]);
  mount(shell, top, h('div.frame', [nav, h('div.scroll', main)]));
  return { root: [shell], topbar, view, main };
}

/** The top bar's agent line and the Agent & jobs row's badge, from a console state (or a polling error). */
export function updateAgentStatus(t, state, error) {
  const box = document.getElementById('agent-status');
  const badgeBox = document.getElementById('nav-jobs-badge');
  if (box) {
    let dot = 'dot--off';
    let text = t('agent_none');
    let note = t('agent_none_hint');
    if (error) {
      dot = 'dot--bad';
      text = t('agent_server_lost');
      note = errorText(t, error);
    } else if (state && state.agent && state.agent.attached) {
      const open = state.open;
      note = '';
      if (open && open.silent) {
        dot = 'dot--warn';
        text = t('agent_silent', { min: Math.floor((state.agent.silent_seconds || 0) / 60) });
        note = t('agent_silent_hint');
      } else if (open && open.state !== 'offered') {
        dot = '';
        text = open.state === 'needs-input' ? t('agent_waiting_you') : t('agent_working');
      } else {
        dot = '';
        text = t('agent_ok');
      }
    } else if (!state) {
      text = t('agent_checking');
      note = '';
    }
    box.setAttribute('aria-label', note ? `${text}. ${note}` : text);
    box.setAttribute('title', note ? `${text}. ${note}` : text);
    mount(box, h('span.dot', { class: dot }), h('span.agent-label', text));
  }
  if (badgeBox) {
    const needs = state ? state.needs_input || 0 : 0;
    const waiting = state ? (state.queue || []).length + (state.open ? 1 : 0) : 0;
    // A short count keeps the menu label readable; the full wording is the badge's name.
    const needsText = needs ? t('nav_needs_you', { n: needs }) : '';
    mount(badgeBox, needs
      ? h('span.yh-badge', { title: needsText }, [h('span', { 'aria-hidden': 'true' }, String(needs)), h('span.sr-only', needsText)])
      : (waiting ? String(waiting) : ''));
  }
}

// Notices of new browser sessions stay until dismissed, across screens.
const NOTICE_KEY = 'testign.sessionNotices';

function loadNotices() {
  try {
    const list = JSON.parse(globalThis.sessionStorage.getItem(NOTICE_KEY) || '[]');
    return Array.isArray(list) ? list.filter((e) => e && typeof e.when === 'string') : [];
  } catch {
    return [];
  }
}

function saveNotices() {
  try {
    globalThis.sessionStorage.setItem(NOTICE_KEY, JSON.stringify(sessionNotices));
  } catch {
    // Storage blocked: the notices last until this page reloads.
  }
}

const sessionNotices = loadNotices();
let releaseAgent = null;

function noticeNode(t, entry) {
  const dismiss = () => {
    const i = sessionNotices.indexOf(entry);
    if (i >= 0) sessionNotices.splice(i, 1);
    saveNotices();
    note.remove();
  };
  const note = h('div.k-banner.k-banner--warning', { role: 'alert', dataset: { sessionNotice: '1' } }, [
    icon('warning', 'icon-warn'),
    h('div.k-banner__text', [h('strong', t('session_new_title', { time: entry.when })), h('span', t('session_new_body'))]),
    h('div.row-4.notice-actions', [
      releaseAgent ? h('button.k-btn.k-btn--secondary.k-btn--sm', {
        type: 'button', dataset: { noticeRelease: '1' }, on: { click: () => releaseAgent() },
      }, t('job_release')) : null,
      h('button.k-btn.k-btn--ghost.k-btn--sm', { type: 'button', on: { click: dismiss } }, t('session_dismiss')),
    ]),
  ]);
  return note;
}

function drawNotices(t, box) {
  if (box) mount(box, sessionNotices.map((entry) => noticeNode(t, entry)));
}

/** A notice in every open tab that another browser session opened the console. */
export function showSessionNotice(t, times, onRelease) {
  if (onRelease) releaseAgent = onRelease;
  const when = times.map((iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }).join(', ');
  sessionNotices.push({ when });
  saveNotices();
  drawNotices(t, document.getElementById('session-notices'));
}

/** Update a sidebar count in place. */
export function setNavCount(key, value) {
  const el = document.querySelector(`[data-count="${key}"]`);
  if (el) el.textContent = value === undefined || value === null ? '' : String(value);
}

export function topbarTitle(text) {
  return h('span.crumbs-title', text);
}

/**
 * Crumbs: [{label, href}]. An item without a link before the last one is a menu group; the last
 * item is the current page.
 */
export function breadcrumb(t, items) {
  const nodes = [];
  items.forEach((item, i) => {
    const last = i === items.length - 1;
    if (i) nodes.push(h('span.yh-chevron', { 'aria-hidden': 'true' }));
    if (last) nodes.push(h('span', { 'aria-current': 'page', lang: item.lang }, item.label));
    else if (item.href) nodes.push(h('a', { href: item.href, lang: item.lang }, item.label));
    else nodes.push(h('span.yh-muted', item.label));
  });
  return h('nav.yh-crumbs', { 'aria-label': t('breadcrumb') }, nodes);
}

export function spacer() {
  return h('span.push');
}

/** The page head: title, one line of help, a meta line and the page's actions. */
export function pageHead(title, subtitle, actions, meta, titleLang) {
  return h('div.page-head', [
    h('div.page-head__text', [
      h('h1', { lang: titleLang }, title),
      subtitle ? h('p', subtitle) : null,
      meta ? h('div.meta', meta) : null,
    ]),
    actions && (!Array.isArray(actions) || actions.some(Boolean)) ? h('div.actions', actions) : null,
  ]);
}

/** A Yohaku badge: kind is '', 'neutral', 'outline', 'success', 'danger' or 'inverse'. */
export function ybadge(text, kind, attrs) {
  return h('span.yh-badge', { ...(attrs || {}), class: kind ? `yh-badge--${kind}` : '' }, text);
}

/** The badge of a suite source kind: Figma, Backlog, Excel, Manual. */
export function srcBadge(t, kind) {
  const key = `src_${String(kind || '').replace(/[^a-z]/g, '')}`;
  const label = t(key);
  return ybadge(label === key ? String(kind || '') : label, 'outline', { dataset: { source: kind } });
}

/** A select with [value, label] options. */
export function selectEl(attrs, options, value) {
  return h('select.yh-select', attrs, (options || []).map(([v, label]) =>
    h('option', { value: v, selected: String(v) === String(value ?? '') }, label)));
}

export function selectWrap(select) {
  return h('span.yh-select-wrap', select);
}

/** A labelled field; `id` names the control the label points at (else the control's own id). */
export function field(label, control, help, error, id) {
  const forId = id || (control && control.getAttribute ? control.getAttribute('id') : null);
  return h('div.yh-field', [
    h('label.yh-field__label', { for: forId || undefined }, label),
    control,
    help ? h('span.yh-field__help', help) : null,
    error || null,
  ]);
}

/** A search box for a toolbar; `/` focuses it. */
export function searchBox(placeholder, value, onInput) {
  const input = h('input.yh-input.yh-input--sm', {
    type: 'search', placeholder, 'aria-label': placeholder, value: value || '', dataset: { search: '1' },
    on: { input: (e) => onInput(e.target.value) },
  });
  return h('div.yh-input-wrap', [icon('search'), input]);
}

/** Filter chips: one pressed at a time. items: [{value, label}]. */
export function segFilter(label, items, value, onChange) {
  return h('div.seg', { role: 'group', 'aria-label': label }, items.map((it) => h('button.yh-tag', {
    type: 'button', 'aria-pressed': it.value === value ? 'true' : 'false', dataset: { filter: it.value },
    on: { click: () => { if (it.value !== value) onChange(it.value); } },
  }, it.label)));
}

/** A Yohaku alert: kind '', 'warning', 'success' or 'danger'. */
export function alertBox(kind, iconName, title, body, action) {
  return h('div.yh-alert', { class: kind ? `yh-alert--${kind}` : '', role: kind === 'danger' ? 'alert' : 'status' }, [
    icon(iconName),
    h('div.yh-alert__body', [title ? h('div.yh-alert__title', title) : null, body || null]),
    action || null,
  ]);
}

/** A wide table that scrolls sideways in its box. head: [cell], rows: [tr]. */
export function tableBox(head, rows, { narrow = false, label } = {}) {
  return h('div.tbl-box', h('table.yh-table', { class: narrow ? 'tbl--narrow' : '', 'aria-label': label }, [
    h('thead', h('tr', head)),
    h('tbody', rows),
  ]));
}

/** Rows that open their page on click, keeping links, buttons and inputs inside them clickable. */
export function rowLink(target, navigate) {
  return {
    click: (event) => {
      const el = event && event.target;
      if (el && typeof el.closest === 'function' && el.closest('a, button, input, select, textarea, label')) return;
      navigate(target);
    },
  };
}

export function loading(t, rows = 4) {
  const bars = [];
  for (let i = 0; i < rows; i += 1) {
    bars.push(h('div.k-skeleton-row', [h('span.k-skeleton.sk-id'), h('span.k-skeleton.sk-wide'), h('span.k-skeleton.sk-short')]));
  }
  return h('div.loading-box', { 'aria-busy': 'true', role: 'status' }, [h('span.sr-only', t('loading')), ...bars]);
}

export function emptyState(title, body, action) {
  return h('div.k-empty.k-empty--dashed', [
    icon('info'),
    h('p.k-empty__title', title),
    body ? h('p.k-empty__body', body) : null,
    action ? h('div.k-empty__actions', action) : null,
  ]);
}

const ERROR_KEYS = {
  network: 'err_network',
  'not-found': 'err_not_found',
  unreadable: 'err_unreadable',
  inconsistent: 'err_inconsistent',
  'config-invalid': 'err_config',
  'template-error': 'err_template',
  'workbook-unreadable': 'err_workbook_unreadable',
  forbidden: 'reopen_title',
};

export function errorText(t, err) {
  const code = err && err.code ? String(err.code) : 'error';
  const key = ERROR_KEYS[code];
  return key ? t(key) : t('err_generic', { code });
}

export function errorState(t, err, retry) {
  return h('div.k-banner.k-banner--danger', { role: 'alert' }, [
    icon('warning'),
    h('div.k-banner__text', [h('strong', t('err_title')), h('span', errorText(t, err))]),
    retry ? h('button.k-btn.k-btn--secondary.k-btn--sm', { type: 'button', on: { click: retry } }, t('retry')) : null,
  ]);
}

export function banner(kind, title, body, extra) {
  return h(`div.k-banner.k-banner--${kind}`, { role: kind === 'danger' ? 'alert' : 'status' }, [
    icon(kind === 'info' ? 'info' : kind === 'success' ? 'check' : 'warning', kind === 'warning' ? 'icon-warn' : ''),
    h('div.k-banner__text', [h('strong', title), body ? h('span', body) : null]),
    extra || null,
  ]);
}

export function badge(text, kind, attrs) {
  return h('span.k-badge', { ...(attrs || {}), class: kind ? kind.split(' ').map((k) => `k-badge--${k}`) : '' }, text);
}

const CONCLUSIONS = {
  open: ['warning', 'conclusion_open'],
  'needs-qa': ['danger', 'conclusion_needs_qa'],
  clear: ['success', 'conclusion_clear'],
  unknown: ['outline', 'conclusion_unknown'],
};

export function conclusionBadge(t, value) {
  const [kind, key] = CONCLUSIONS[value] || CONCLUSIONS.unknown;
  return badge(t(key), kind);
}

const HASH_REASONS = new Set(['busy', 'report-unreadable', 'repo-not-found', 'report-incomplete', 'git-error', 'error']);

export function hashReason(t, reason) {
  return HASH_REASONS.has(reason) ? t(`hash_reason_${reason.replace(/-/g, '_')}`) : (reason || '');
}

/** Inline hash state: a spinner while loading, then same / moved / stale / unknown. */
export function hashInline(t, state) {
  if (state === 'loading') {
    return h('span.inline-status', [h('span.k-spinner.k-spinner--sm', { 'aria-hidden': 'true' }), h('span.sr-only', t('hash_loading'))]);
  }
  if (!state || state.error) {
    return h('span.inline-status.k-muted', { title: state && state.error ? errorText(t, state.error) : undefined }, [icon('dash', 'k-icon--sm'), t('hash_unknown')]);
  }
  switch (state.status) {
    case 'same':
      return h('span.inline-status.text-success', [icon('check', 'k-icon--sm'), t('hash_same')]);
    case 'moved_no_impact':
      return h('span.inline-status.text-2', [icon('info', 'k-icon--sm'), t('hash_moved')]);
    case 'stale':
      return h('span.inline-status.text-2', [icon('warning', 'k-icon--sm icon-warn'), t('hash_stale')]);
    default:
      return h('span.inline-status.k-muted', { title: hashReason(t, state.reason) || undefined },
        [icon('dash', 'k-icon--sm'), t('hash_unknown')]);
  }
}

/** Banner for a hash check that found movement; null when nothing moved or the state is unknown. */
export function hashBanner(t, state) {
  if (!state || state.error || (state.status !== 'stale' && state.status !== 'moved_no_impact')) return null;
  const moves = Array.isArray(state.moves) ? state.moves : [];
  const lines = moves.map((m) => {
    const commits = Array.isArray(m.commits) ? m.commits.length : (Number.isFinite(m.commits) ? m.commits : null);
    return h('span.mono-line', [
      h('code.k-mono', String(m.ref || '')), ' ', h('code.k-mono', String(m.from || '').slice(0, 7)), ' → ',
      h('code.k-mono', String(m.to || '').slice(0, 7)),
      commits !== null ? ` · ${t('hash_commits', { n: commits })}` : '',
    ]);
  });
  if (state.status === 'stale') {
    const rows = Array.isArray(state.stale_rows) ? state.stale_rows : [];
    const files = Array.isArray(state.stale_files) ? state.stale_files : [];
    return h('div.k-banner.k-banner--warning', { role: 'status' }, [
      icon('warning', 'icon-warn'),
      h('div.k-banner__text', [
        h('strong', t('hash_stale_title')),
        h('span', t('hash_stale_body')),
        ...lines,
        rows.length ? h('span', [t('hash_stale_rows'), ' ', h('code.k-mono', rows.join(', '))]) : null,
        files.length ? h('span', [t('hash_stale_files'), ' ', ...files.map((f, i) => [i ? ', ' : '', h('code.k-mono', f)])]) : null,
      ]),
    ]);
  }
  return h('div.k-banner.k-banner--info', { role: 'status' }, [
    icon('info'),
    h('div.k-banner__text', [h('strong', t('hash_moved_title')), h('span', t('hash_moved_body')), ...lines]),
  ]);
}

/** A modal dialog with a focus trap; Esc and the scrim close it and focus returns to the trigger. */
export function openDialog({ t, title, body, footer, wide, onClose, initialFocus }) {
  const trigger = document.activeElement;
  const titleId = `dlg-title-${Math.random().toString(36).slice(2, 8)}`;
  const panel = h('div.k-dialog', {
    class: wide ? 'k-dialog--wide' : '', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId,
  }, [
    h('div.k-dialog__header', [
      h('h2.k-dialog__title', { id: titleId }, title),
      h('button.k-btn.k-btn--icon.k-btn--xs', { type: 'button', 'aria-label': t('close'), on: { click: () => close() } }, icon('close')),
    ]),
    h('div.k-dialog__body', body),
    footer ? h('div.k-dialog__footer.dialog-foot', footer) : null,
  ]);
  const layer = h('div.k-scrim.layer', { role: 'presentation' }, panel);
  layer.addEventListener('mousedown', (event) => {
    if (event.target === layer) close();
  });
  const release = trapFocus(layer);
  const popEscape = pushEscape(() => close());
  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    release();
    popEscape();
    layer.remove();
    if (trigger && trigger.isConnected && typeof trigger.focus === 'function') trigger.focus();
    if (onClose) onClose();
  }
  document.body.appendChild(layer);
  const first = (initialFocus && initialFocus()) || panel.querySelector('.k-dialog__body input, .k-dialog__body select, .k-dialog__body textarea')
    || panel.querySelector('.k-dialog__footer button') || panel.querySelector('button');
  if (first) first.focus();
  return { close, panel, setBody: (...nodes) => mount(panel.querySelector('.k-dialog__body'), ...nodes) };
}

let toastRegion = null;

export function toast(text, kind) {
  if (!toastRegion || !toastRegion.isConnected) {
    toastRegion = h('div.toast-region', { role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(toastRegion);
  }
  const el = h('div.k-toast', { class: kind ? `k-toast--${kind}` : '' }, [
    icon(kind === 'danger' ? 'warning' : 'check'), h('span.k-toast__text', text),
  ]);
  toastRegion.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

/** The full-page message shown without a session. */
export function renderReopen(t) {
  return h('main.reopen', { dataset: { reopen: '1' } }, [
    h('div.k-empty.reopen-box', [
      icon('info'),
      h('h1.k-empty__title', t('reopen_title')),
      h('p.k-empty__body', [t('reopen_body'), ' ', h('code.k-mono', '/testign:console'), ' ', t('reopen_or'), ' ',
        h('code.k-mono', 'testign console open'), '.']),
    ]),
  ]);
}
