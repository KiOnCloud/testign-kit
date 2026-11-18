// The frame around every screen (sidebar, top bar, view area) and the building blocks the views
// share: loading, empty and error states, banners, badges, dialogs, toasts and the Esc stack.

import { h, icon, mount } from '../dom.mjs';
import { trapFocus } from '../palette.mjs';
import { LANGS } from '../prefs.mjs';
import { href } from '../router.mjs';

export const LANG_NAMES = { vi: 'Tiếng Việt', en: 'English', ja: '日本語' };

// Esc closes the topmost thing that registered itself: a dialog, then a split panel.
const escapeStack = [];

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

/** The sidebar, top bar and view area. Returns the parts the router fills. */
export function renderShell({ t, lang, section, counts, onLang, onPalette }) {
  const nav = (key, target, iconName, label) => h('a.k-nav-item', {
    href: target, class: section === key ? 'is-active' : '', 'aria-current': section === key ? 'page' : undefined,
    dataset: { nav: key },
  }, [icon(iconName), h('span.nav-label', label),
    h('span.k-nav-item__count', { dataset: { count: key } }, counts[key] === undefined ? '' : String(counts[key]))]);
  const mod = isMac() ? '⌘' : 'Ctrl';
  const sidebar = h('nav.k-sidebar.side', { 'aria-label': t('nav_main') }, [
    h('div.k-sidebar__ws', [h('span.k-avatar', 'T'), 'testign', h('span.k-muted.ws-sub', t('nav_console'))]),
    h('button.k-btn.k-btn--secondary.k-btn--sm.side-search', {
      type: 'button', 'aria-keyshortcuts': 'Control+K Meta+K', on: { click: onPalette },
    }, [icon('search'), h('span.side-search__label', t('nav_search')),
      h('span.k-kbd-group', [h('kbd.k-kbd', mod), h('kbd.k-kbd', 'K')])]),
    h('div.k-sidebar__section', t('nav_work')),
    nav('tickets', href(['tickets']), 'file', t('nav_tickets')),
    h('div.k-sidebar__section', t('nav_setup')),
    nav('templates', href(['templates']), 'layers', t('nav_templates')),
    nav('cache', href(['cache']), 'folder', t('nav_cache')),
    nav('settings', href(['settings']), 'settings', t('nav_settings')),
    h('div.side-foot', [
      h('div.stack-4', [
        h('span.k-section-label', { id: 'side-lang-label' }, t('ui_lang')),
        radioGroup({
          labelledBy: 'side-lang-label', name: 'side-lang', value: lang, onChange: onLang,
          options: LANGS.map((l) => ({ value: l, label: LANG_NAMES[l], lang: l })),
        }),
      ]),
      h('div.stack-2', [
        h('div', { id: 'agent-status', hidden: true }),
        h('span.k-note', t('local_only')),
      ]),
    ]),
  ]);
  const topbar = h('header.k-topbar.topbar-wrap');
  const view = h('div.view', { id: 'view' });
  const main = h('main.main', { id: 'main', tabindex: '-1' }, [topbar, view]);
  return { root: [sidebar, main], topbar, view, main };
}

/** Update a sidebar count in place. */
export function setNavCount(key, value) {
  const el = document.querySelector(`[data-count="${key}"]`);
  if (el) el.textContent = value === undefined || value === null ? '' : String(value);
}

export function topbarTitle(text) {
  return h('span.k-topbar__title', text);
}

export function breadcrumb(t, items) {
  const nodes = [];
  items.forEach((item, i) => {
    if (i) nodes.push(icon('chevron', 'k-icon--sm k-sep'));
    nodes.push(item.href
      ? h('a', { href: item.href }, item.label)
      : h('span.k-breadcrumb__item.is-current', { 'aria-current': 'page' }, item.label));
  });
  return h('nav.k-breadcrumb.crumbs', { 'aria-label': t('breadcrumb') }, nodes);
}

export function spacer() {
  return h('div.k-topbar__spacer');
}

export function pageHead(title, subtitle, actions) {
  return h('section.page-head', [
    h('div.stack-4', [h('h1.page-title', title), subtitle ? h('p.k-note', subtitle) : null]),
    actions ? h('div.row-8', actions) : null,
  ]);
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
