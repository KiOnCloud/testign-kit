// Login scenarios: how each role signs in on each project, grouped by project, with a status icon
// (approved, waiting for approval, rejected). A scenario comes from the agent as a draft; only the
// tester approves, rejects (with a note) or removes it, in its detail dialog. The agent knows only
// the scenario name, never an account: the tester signs in in their own Chrome.

import { h, icon, mount, statusIcon } from '../dom.mjs';
import { NONE, timeOrDay } from '../format.mjs';
import { href } from '../router.mjs';
import { jobErrorText } from './job-actions.mjs';
import { alertBox, breadcrumb, emptyState, errorState, field, loading, openDialog, pageHead, searchBox, tableBox, ybadge } from './shell.mjs';
import { urlLink } from './sign-in-card.mjs';

/** A scenario's status: approved, rejected (with the tester's note) or waiting for approval. */
export function scenarioStatus(s) {
  if (s && s.approved) return 'approved';
  if (s && s.rejection) return 'rejected';
  return 'waiting';
}

const STATUS_ICONS = { approved: ['ok', 'check', 'login_approved'], waiting: ['warn', 'clock', 'scen_waiting'], rejected: ['bad', 'close', 'login_rejected'] };

/** The status as an icon whose tooltip is the status in words. */
export function scenarioIcon(t, s) {
  const [kind, name, key] = STATUS_ICONS[scenarioStatus(s)];
  return statusIcon(kind, name, t(key));
}

/** Scenarios matching the search words: name, label, project or a URL. */
export function filterScenarios(groups, text) {
  const words = String(text || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return groups;
  return groups.map((g) => ({
    ...g,
    scenarios: g.scenarios.filter((s) => {
      const hay = [g.project, s.name, s.label, s.login_url, s.signout_url].filter(Boolean).join(' ').toLowerCase();
      return words.every((w) => hay.includes(w));
    }),
  })).filter((g) => g.scenarios.length);
}

/** One scenario in a dialog: its checklist, and approve, reject (needs a note) or remove. */
export function openScenario(ctx, project, s, after) {
  const { t } = ctx;
  const note = h('textarea.yh-textarea', { id: `note-${s.name}`, rows: '2', maxlength: '1000', placeholder: t('login_note_ph') });
  const errorBox = h('div', { role: 'alert' });
  const buttons = [];
  const act = async (button, fn, okText) => {
    for (const b of buttons) b.disabled = true;
    try {
      await fn();
      ctx.toast(okText);
      dlg.close();
      after();
    } catch (err) {
      for (const b of buttons) b.disabled = false;
      if (err && err.code === 'scenario-changed') { dlg.close(); after(); }
      mount(errorBox, h('p.k-field__error', [icon('warning'), jobErrorText(t, err)]));
    }
  };
  const approve = h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { approve: s.name } }, t('login_approve'));
  approve.addEventListener('click', () => act(approve, () => ctx.api.approveScenario(project, s.name, s.hash), t('login_approved_toast')));
  const reject = h('button.yh-btn', { type: 'button', dataset: { reject: s.name } }, t('login_reject'));
  reject.addEventListener('click', () => {
    if (!note.value.trim()) {
      mount(errorBox, h('p.k-field__error', [icon('warning'), t('login_err_note')]));
      note.focus();
      return;
    }
    act(reject, () => ctx.api.rejectScenario(project, s.name, note.value.trim()), t('login_rejected_toast'));
  });
  const remove = h('button.yh-btn.yh-btn--ghost.yh-btn--destructive', { type: 'button', dataset: { remove: s.name } }, [icon('trash'), t('login_remove')]);
  let confirming = false;
  remove.addEventListener('click', () => {
    if (!confirming) {
      confirming = true;
      mount(errorBox, alertBox('warning', 'warning', t('login_remove_title', { name: s.label || s.name }), t('login_remove_body')));
      remove.textContent = t('scen_remove_confirm');
      return;
    }
    act(remove, () => ctx.api.removeScenario(project, s.name), t('login_removed_toast'));
  });
  buttons.push(approve, reject, remove);
  const check = s.signed_in_check || {};
  const status = scenarioStatus(s);
  const dlg = openDialog({
    t, title: s.label || s.name, wide: true,
    body: h('div.stack-16', { dataset: { scenarioDialog: s.name } }, [
      h('div.st-row', [scenarioIcon(t, s), h('span', t(STATUS_ICONS[status][2])), h('code.mono', s.name), h('span.yh-muted', project),
        s.approved_at ? h('span.yh-caption.yh-muted', timeOrDay(s.approved_at)) : null]),
      s.rejection ? alertBox('warning', 'warning', t('login_rejected'), s.rejection.note || '') : null,
      h('dl.kv', [
        h('dt', t('login_login_url')), h('dd.break', urlLink(s.login_url)),
        h('dt', t('login_signout_url')), h('dd.break', urlLink(s.signout_url)),
        h('dt', t('login_check')), h('dd.break', [check.text || NONE, check.url ? [' · ', urlLink(check.url)] : null]),
        h('dt', t('login_hint')), h('dd', s.account_hint || NONE),
      ]),
      h('div.yh-stack', [h('h3.yh-h3.m-0', t('login_steps')),
        (s.steps || []).length ? h('ol.signin-steps', s.steps.map((x) => h('li', x))) : h('p.yh-muted.m-0', NONE),
        h('p.yh-caption.yh-muted.m-0', t('login_steps_readonly'))]),
      field([t('login_note'), ' ', h('span.yh-muted', t('login_note_when'))], note),
      h('p.yh-caption.yh-muted.m-0', t('login_no_values')),
      errorBox,
    ]),
    footer: [remove, h('span.push'), reject, s.approved ? null : approve],
  });
  return dlg;
}

let search = '';

export function render(ctx) {
  const { t, route } = ctx;
  const wanted = route.query && route.query.project;
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_config') }, { label: t('nav_scenarios') }]));
  const head = pageHead(t('scen_title'), t('scen_sub'));
  mount(ctx.view, head, loading(t, 4));
  const tableHolder = h('div');
  let lastKey = null;

  const load = async () => {
    let groups;
    try {
      const projects = (await ctx.memo('projects', () => ctx.api.projects())).projects || [];
      groups = await Promise.all(projects.map(async (p) => {
        try {
          const d = await ctx.memo(`scenarios:${p.name}`, () => ctx.api.scenarios(p.name));
          return { project: p.name, scenarios: d.scenarios || [] };
        } catch (err) {
          return { project: p.name, scenarios: [], error: err };
        }
      }));
    } catch (err) {
      if (!ctx.alive()) return;
      lastKey = null;
      mount(ctx.view, head, errorState(t, err, () => ctx.refresh()));
      ctx.ready();
      return;
    }
    if (!ctx.alive()) return;
    if (wanted) groups.sort((a, b) => (a.project === wanted ? -1 : b.project === wanted ? 1 : 0));
    const key = JSON.stringify(groups.map((g) => [g.project, g.scenarios, Boolean(g.error)]));
    if (key === lastKey) return;
    lastKey = key;
    ctx.setCount('scenarios', groups.reduce((n, g) => n + g.scenarios.length, 0));
    draw(groups);
    ctx.ready();
  };

  const reload = (project) => {
    ctx.invalidate('projects');
    ctx.invalidate(`scenarios:${project}`);
    ctx.invalidate('count:scenarios');
    load();
  };

  function draw(groups) {
    const notes = [
      alertBox('', 'info', t('scen_how_t'), t('login_how_created')),
    ];
    if (!groups.length) {
      mount(ctx.view, head, emptyState(t('runform_no_project'), t('scen_no_project'),
        h('a.yh-btn.yh-btn--primary', { href: href(['projects']) }, t('nav_projects'))));
      return;
    }
    mount(ctx.view, head, ...notes, h('div.toolbar', searchBox(t('scen_search'), search, (v) => { search = v; drawTable(groups); })), tableHolder);
    drawTable(groups);
  }

  function drawTable(groups) {
    const shown = filterScenarios(groups, search);
    const rows = [];
    for (const g of shown) {
      rows.push(h('tr.group-row', { dataset: { group: g.project } }, h('th', { colspan: '5', scope: 'colgroup' },
        h('span.st-row', [h('strong.mono', g.project), h('span.yh-caption.yh-muted', t('scen_group_count', { n: g.scenarios.length })),
          g.project === wanted ? ybadge(t('scen_selected'), 'outline') : null]))));
      if (g.error) {
        rows.push(h('tr', h('td', { colspan: '5' }, h('span.text-danger', jobErrorText(t, g.error)))));
        continue;
      }
      rows.push(h('tr', { dataset: { scenario: 'none', project: g.project } }, [
        h('td', h('span.st-row', [statusIcon('ok', 'check', t('login_builtin')), h('span', t('login_l_none'))])),
        h('td.mono', 'none'), h('td.yh-muted', NONE), h('td.yh-muted', NONE), h('td', ybadge(t('login_builtin'), 'outline')),
      ]));
      for (const s of g.scenarios) {
        const check = s.signed_in_check || {};
        rows.push(h('tr.click', { dataset: { scenario: s.name, project: g.project },
          on: { click: (e) => { const el = e && e.target; if (el && typeof el.closest === 'function' && el.closest('a')) return; openScenario(ctx, g.project, s, () => reload(g.project)); } } }, [
          h('td', h('span.st-row', [scenarioIcon(t, s), h('button.lnk.btn-link', { type: 'button', dataset: { openScenario: s.name } }, s.label || s.name)])),
          h('td.mono', s.name),
          h('td.mono.yh-muted.wrap', s.login_url || NONE),
          h('td.wrap', check.text || (check.url ? check.url : NONE)),
          h('td', scenarioStatus(s) === 'approved' ? h('span.yh-caption.yh-muted', s.approved_at ? timeOrDay(s.approved_at) : '')
            : h('button.yh-btn.yh-btn--sm', { type: 'button', dataset: { review: s.name } }, t('scen_review'))),
        ]));
      }
    }
    mount(tableHolder, shown.length ? tableBox([h('th', t('scen_col_name')), h('th', t('scen_col_id')), h('th', t('login_login_url')),
      h('th', t('login_check')), h('th', h('span.sr-only', t('scen_review')))], rows)
      : alertBox('', 'info', t('scen_no_match'), null));
  }

  load();
}
