// Preferences: the testign configuration, read-only, in four groups (general, Git, Backlog,
// console); this browser's theme, tester name and language; and the console's address and version.

import { serverVersion } from '../api.mjs';
import { h, icon, mount } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { LANGS, THEMES, TESTER_NAME_MAX } from '../prefs.mjs';
import { breadcrumb, errorState, LANG_NAMES, langName, loading, pageHead, radioGroup, ybadge } from './shell.mjs';

function show(value) {
  return value === null || value === undefined || value === '' ? NONE : String(value);
}

function agentText(t, st) {
  if (!st) return NONE;
  if (!st.agent || !st.agent.attached) return t('agent_none');
  return st.open && st.open.silent ? t('agent_silent', { min: Math.floor((st.agent.silent_seconds || 0) / 60) }) : t('agent_ok');
}

/** The read-only configuration as panels: [{id, rows: [[i18n label key, value, mono]]}]. */
export function configGroups(cfg) {
  const c = cfg || {};
  const backlog = c.backlog || {};
  const con = c.console || {};
  return [
    { id: 'general', rows: [['pref_output', show(c.output_dir), true], ['pref_report_lang', c.lang ? langName(c.lang) : NONE, false]] },
    { id: 'git', rows: [['pref_branches', `${show(c.master_ref)} / ${show(c.develop_ref)}`, true], ['pref_regex', show(c.ticket_id_regex), true]] },
    { id: 'backlog', rows: [['pref_space', `${show(backlog.space)} · ${show(backlog.project_key)}`, true],
      ['pref_prefix', show(backlog.decisions_log_prefix), true]] },
    { id: 'console', rows: [['pref_port', show(con.port), true], ['pref_idle', show(con.idle_minutes), false]] },
  ];
}

function panel(t, id, title, children, extra) {
  return h('section.panel', { 'aria-labelledby': `pref-${id}` }, [
    h('div.panel-head', [h('h2.yh-h3.m-0', { id: `pref-${id}` }, title), h('span.push'), extra || null]),
    ...children,
  ]);
}

export function render(ctx) {
  const { t, prefs } = ctx;
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_config') }, { label: t('nav_settings') }]));

  const saved = h('span.yh-caption.text-success', { hidden: true, role: 'status' }, [icon('check'), ' ', t('settings_saved')]);
  const nameInput = h('input.yh-input', {
    type: 'text', id: 'tester-name', autocomplete: 'name', maxlength: String(TESTER_NAME_MAX), value: prefs.getTesterName(),
  });
  let timer = null;
  nameInput.addEventListener('input', () => {
    prefs.setTesterName(nameInput.value);
    saved.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(() => { saved.hidden = true; }, 2000);
  });

  const browser = panel(t, 'browser', t('settings_browser'), [
    h('p.yh-caption.yh-muted.m-0', t('settings_browser_note')),
    h('div.yh-field', [
      h('span.yh-field__label', { id: 'lbl-theme' }, t('settings_theme')),
      radioGroup({
        labelledBy: 'lbl-theme', name: 'settings-theme', value: prefs.getTheme(), onChange: ctx.setTheme,
        options: THEMES.map((m) => ({ value: m, label: t(`settings_theme_${m}`) })),
      }),
    ]),
    h('div.yh-field', [
      h('label.yh-field__label', { for: 'tester-name' }, t('settings_tester')),
      nameInput,
      h('span.yh-field__help', t('settings_tester_help')),
    ]),
    h('div.yh-field', [
      h('span.yh-field__label', { id: 'lbl-lang' }, t('ui_lang')),
      radioGroup({
        labelledBy: 'lbl-lang', name: 'settings-lang', value: ctx.lang, onChange: ctx.setLang,
        options: LANGS.map((l) => ({ value: l, label: LANG_NAMES[l], lang: l })),
      }),
      h('span.yh-field__help', t('settings_lang_help')),
    ]),
    saved,
  ]);

  const st = ctx.store.get() || {};
  const consolePanel = panel(t, 'console-info', t('settings_console'), [
    h('p.yh-caption.yh-muted.m-0', t('settings_console_note')),
    h('dl.kv', [
      h('dt', t('settings_version')), h('dd.mono', show(serverVersion())),
      h('dt', t('settings_address')), h('dd.mono', location.host),
      h('dt', t('settings_agent')), h('dd', agentText(t, st)),
      h('dt', t('settings_sessions')), h('dd.yh-num', String((st.browser_sessions || []).length || NONE)),
    ]),
    h('p.yh-caption.yh-muted.m-0', [t('settings_reopen'), ' ', h('code.mono', '/testign:console'), ' ', t('reopen_or'), ' ',
      h('code.mono', 'testign console open')]),
  ]);

  const configBox = h('div.grid2.pref-grid', loading(t, 3));
  const head = pageHead(t('pref_title'), t('settings_subtitle'), null,
    [h('span.yh-caption.yh-muted', [t('pref_stored'), ' ', h('code.mono', '~/.testign-kit/config.json')])]);
  mount(ctx.view, head, configBox, h('p.yh-caption.yh-muted.m-0', [t('settings_config_note'), ' ', h('code.mono', '~/.testign-kit/config.json')]),
    h('div.grid2.pref-grid', [browser, consolePanel]));

  ctx.memo('config', () => ctx.api.config()).then((cfg) => {
    if (!ctx.alive()) return;
    mount(configBox, configGroups(cfg).map((g) => panel(t, g.id, t(`pref_${g.id}`), [
      h('dl.kv', { dataset: { config: g.id } }, g.rows.flatMap(([key, value, mono]) => [h('dt', t(key)), h(mono ? 'dd.mono.break' : 'dd', value)])),
    ], ybadge(t('settings_readonly'), 'outline'))));
    ctx.ready();
  }, (err) => {
    if (!ctx.alive()) return;
    mount(configBox, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
}
