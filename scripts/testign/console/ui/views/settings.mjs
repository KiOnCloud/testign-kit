// Settings: this browser's language, theme and tester name; the console's address and version;
// the testign configuration, read-only.

import { serverVersion } from '../api.mjs';
import { h, icon, mount } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { LANGS, THEMES, TESTER_NAME_MAX } from '../prefs.mjs';
import { errorState, LANG_NAMES, loading, pageHead, radioGroup, spacer, topbarTitle } from './shell.mjs';

function show(value) {
  return value === null || value === undefined || value === '' ? NONE : String(value);
}

function agentText(t, st) {
  if (!st) return NONE;
  if (!st.agent || !st.agent.attached) return t('agent_none');
  return st.open && st.open.silent ? t('agent_silent', { min: Math.floor((st.agent.silent_seconds || 0) / 60) }) : t('agent_ok');
}

export function render(ctx) {
  const { t, prefs } = ctx;
  const body = h('div.page.page-narrow');
  mount(ctx.view, body);
  ctx.topbar(topbarTitle(t('nav_settings')), spacer());

  const saved = h('span.k-note.inline-status.text-success', { hidden: true, role: 'status' }, [icon('check', 'k-icon--sm'), t('settings_saved')]);
  const nameInput = h('input.k-input', {
    type: 'text', id: 'tester-name', autocomplete: 'name', maxlength: String(TESTER_NAME_MAX), value: prefs.getTesterName(),
  });
  let timer = null;
  nameInput.addEventListener('input', () => {
    prefs.setTesterName(nameInput.value);
    saved.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(() => { saved.hidden = true; }, 2000);
  });

  const browser = h('section.k-card.card-loose', { 'aria-labelledby': 's-browser' }, [
    h('div.stack-2', [h('h2.k-card__title.card-h', { id: 's-browser' }, t('settings_browser')), h('p.k-note', t('settings_browser_note'))]),
    h('div.k-field', [
      h('span.k-field__label', { id: 'lbl-lang' }, t('ui_lang')),
      radioGroup({
        labelledBy: 'lbl-lang', name: 'settings-lang', value: ctx.lang, onChange: ctx.setLang,
        options: LANGS.map((l) => ({ value: l, label: LANG_NAMES[l], lang: l })),
      }),
      h('span.k-field__help', t('settings_lang_help')),
    ]),
    h('div.k-field', [
      h('span.k-field__label', { id: 'lbl-theme' }, t('settings_theme')),
      radioGroup({
        labelledBy: 'lbl-theme', name: 'settings-theme', value: prefs.getTheme(), onChange: ctx.setTheme,
        options: THEMES.map((m) => ({ value: m, label: t(`settings_theme_${m}`) })),
      }),
    ]),
    h('div.k-field', [
      h('label.k-field__label', { for: 'tester-name' }, t('settings_tester')),
      nameInput,
      h('span.k-field__help', t('settings_tester_help')),
    ]),
    saved,
  ]);

  const consoleCard = h('section.k-card', { 'aria-labelledby': 's-console' }, [
    h('div.stack-2', [h('h2.k-card__title.card-h', { id: 's-console' }, t('settings_console')), h('p.k-note', t('settings_console_note'))]),
    h('dl.k-props.props-plain', [
      h('dt', t('settings_version')), h('dd', h('span.k-chip', show(serverVersion()))),
      h('dt', t('settings_address')), h('dd', h('span.k-chip', h('code.k-mono', location.host))),
      h('dt', t('settings_agent')), h('dd', h('span.k-chip', agentText(t, ctx.store.get()))),
      h('dt', t('settings_sessions')), h('dd', h('span.k-chip.num', String(((ctx.store.get() || {}).browser_sessions || []).length || NONE))),
    ]),
    h('p.k-note', [t('settings_reopen'), ' ', h('code.k-mono', '/testign:console'), ' ', t('reopen_or'), ' ', h('code.k-mono', 'testign console open')]),
  ]);

  const configBox = h('div', loading(t, 3));
  const configCard = h('section.k-card.span-all', { 'aria-labelledby': 's-config' }, [
    h('div.page-head', [
      h('div.stack-2', [
        h('h2.k-card__title.card-h', { id: 's-config' }, t('settings_config')),
        h('p.k-note', [t('settings_config_note'), ' ', h('code.k-mono', '~/.testign-kit/config.json')]),
      ]),
      h('span.k-badge.k-badge--outline', t('settings_readonly')),
    ]),
    configBox,
  ]);

  mount(body, pageHead(t('nav_settings'), t('settings_subtitle')), h('div.settings-grid', [browser, consoleCard, configCard]));

  ctx.memo('config', () => ctx.api.config()).then((cfg) => {
    if (!ctx.alive()) return;
    const backlog = cfg.backlog || {};
    const rows = [
      ['output_dir', show(cfg.output_dir), 'settings_m_output'],
      ['lang', show(cfg.lang), 'settings_m_lang'],
      ['master_ref · develop_ref', `${show(cfg.master_ref)} · ${show(cfg.develop_ref)}`, 'settings_m_refs'],
      ['backlog.space · project_key', `${show(backlog.space)} · ${show(backlog.project_key)}`, 'settings_m_backlog'],
      ['backlog.decisions_log_prefix', show(backlog.decisions_log_prefix), 'settings_m_prefix'],
    ];
    mount(configBox, h('div.scroll-x', h('table.k-table.k-table--compact.tbl-narrow', [
      h('thead', h('tr', [h('th.col-key', t('settings_th_key')), h('th', t('settings_th_value')), h('th', t('settings_th_meaning'))])),
      h('tbody', rows.map(([key, value, meaning]) => h('tr', [
        h('td.k-mono', key), h('td.k-mono.text-1.wrap-cell', value), h('td.k-muted.wrap-cell', t(meaning)),
      ]))),
    ])));
    ctx.ready();
  }, (err) => {
    if (!ctx.alive()) return;
    mount(configBox, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
}
