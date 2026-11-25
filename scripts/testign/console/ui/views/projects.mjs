// Projects & hosts: each system under test with the hosts the agent may open and the sign-in hosts
// it may pass through, and how many of its login scenarios are approved. Only the tester adds a
// project or edits its hosts, here; no agent or CLI command writes them.

import { h, icon, mount, statusIcon } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { checkHosts, checkProjectName, splitHosts } from '../hosts.mjs';
import { href } from '../router.mjs';
import { jobErrorText } from './job-actions.mjs';
import { alertBox, breadcrumb, emptyState, errorState, field, loading, openDialog, pageHead, tableBox } from './shell.mjs';

/** The values of the project dialog checked like the server does: an i18n key per field, or {}. */
export function checkProject(v, isNew) {
  const errors = {};
  if (isNew) {
    const bad = checkProjectName(v.name);
    if (bad) errors.name = bad;
  }
  const hosts = checkHosts(splitHosts(v.hosts), true);
  if (hosts) errors.hosts = hosts;
  const signin = checkHosts(splitHosts(v.signin_hosts), false);
  if (signin) errors.signin_hosts = signin;
  return errors;
}

/** Add a project (no `project`) or edit one project's hosts, in a dialog. `after(name)` runs once saved. */
export function openProjectDialog(ctx, project, after) {
  const { t } = ctx;
  const isNew = !project;
  const controls = {
    name: h('input.yh-input.mono', { type: 'text', id: 'project-name', maxlength: '40', autocomplete: 'off', spellcheck: 'false' }),
    hosts: h('textarea.yh-textarea.mono', { id: 'project-hosts', rows: '3', spellcheck: 'false',
      value: project ? (project.hosts || []).join('\n') : '' }),
    signin_hosts: h('textarea.yh-textarea.mono', { id: 'project-signin', rows: '2', spellcheck: 'false',
      value: project ? (project.signin_hosts || []).join('\n') : '' }),
  };
  const boxes = { name: h('div', { role: 'alert' }), hosts: h('div', { role: 'alert' }), signin_hosts: h('div', { role: 'alert' }) };
  const formError = h('div', { role: 'alert' });
  const save = h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { saveProject: '1' } }, t('login_save_hosts'));
  const dlg = openDialog({
    t, title: isNew ? t('login_new_project') : t('proj_edit_title', { name: project.name }),
    body: h('div.stack-16', { dataset: { projectDialog: isNew ? 'new' : project.name } }, [
      isNew ? field(t('login_project'), controls.name, t('login_project_help'), boxes.name) : null,
      field(t('login_hosts'), controls.hosts, t('login_hosts_help'), boxes.hosts),
      field([t('login_signin_hosts'), ' ', h('span.yh-muted', t('runform_optional'))], controls.signin_hosts, t('login_signin_help'),
        boxes.signin_hosts),
      alertBox('', 'info', t('proj_safety_t'), t('proj_safety_d')),
      formError,
    ]),
    footer: [h('button.yh-btn', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')), save],
  });
  save.addEventListener('click', async () => {
    const v = { name: isNew ? controls.name.value.trim() : project.name, hosts: controls.hosts.value, signin_hosts: controls.signin_hosts.value };
    const problems = checkProject(v, isNew);
    for (const [name, box] of Object.entries(boxes)) {
      mount(box, problems[name] ? h('p.k-field__error', [icon('warning'), t(problems[name])]) : null);
      if (controls[name].classList) controls[name].classList.toggle('is-error', Boolean(problems[name]));
    }
    const bad = Object.keys(problems)[0];
    if (bad) { controls[bad].focus(); return; }
    save.disabled = true;
    try {
      await ctx.api.saveProject(v.name, { hosts: splitHosts(v.hosts), signin_hosts: splitHosts(v.signin_hosts) });
      ctx.toast(t('login_hosts_saved'));
      dlg.close();
      after(v.name);
    } catch (err) {
      save.disabled = false;
      mount(formError, h('p.k-field__error', [icon('warning'), err && err.code === 'bad-request' && err.message ? err.message : jobErrorText(t, err)]));
    }
  });
  return dlg;
}

export function render(ctx) {
  const { t } = ctx;
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_config') }, { label: t('nav_projects') }]));
  const reload = () => {
    ctx.invalidate('projects');
    ctx.invalidate('count:projects');
    ctx.invalidate('count:scenarios');
    load();
  };
  const add = () => openProjectDialog(ctx, null, reload);
  const head = pageHead(t('proj_title'), t('proj_sub'), [
    h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { newProject: '1' }, on: { click: add } }, [icon('plus'), t('login_new_project')]),
  ]);
  mount(ctx.view, head, loading(t, 3));
  let lastKey = null;

  const load = () => ctx.memo('projects', () => ctx.api.projects()).then((data) => {
    if (!ctx.alive()) return;
    const list = data.projects || [];
    const key = JSON.stringify(list);
    if (key === lastKey) return;
    lastKey = key;
    ctx.setCount('projects', list.length);
    ctx.setCount('scenarios', list.reduce((n, p) => n + (p.scenarios || 0), 0));
    const note = h('p.yh-caption.yh-muted.m-0', t('proj_note'));
    if (!list.length) {
      mount(ctx.view, head, emptyState(t('runform_no_project'), t('proj_empty_body'),
        h('button.yh-btn.yh-btn--primary', { type: 'button', on: { click: add } }, [icon('plus'), t('login_new_project')])), note);
      ctx.ready();
      return;
    }
    const rows = list.map((p) => {
      const waiting = (p.scenarios || 0) - (p.approved || 0);
      return h('tr', { dataset: { project: p.name } }, [
        h('td', h('strong.mono', p.name)),
        h('td.wrap.mono', (p.hosts || []).join(', ') || NONE),
        h('td.wrap.mono.yh-muted', (p.signin_hosts || []).join(', ') || NONE),
        h('td', h('span.st-row', [
          h('a.lnk', { href: href(['scenarios'], { project: p.name }) }, t('login_count', { approved: p.approved || 0, n: p.scenarios || 0 })),
          waiting > 0 ? statusIcon('warn', 'clock', t('proj_waiting', { n: waiting })) : null,
        ])),
        h('td', h('button.yh-btn.yh-btn--sm', { type: 'button', dataset: { editProject: p.name },
          on: { click: () => openProjectDialog(ctx, p, reload) } }, t('proj_edit'))),
      ]);
    });
    mount(ctx.view, head, tableBox([h('th', t('login_project')), h('th', t('login_hosts')), h('th', t('login_signin_hosts')),
      h('th', t('nav_scenarios')), h('th', h('span.sr-only', t('proj_edit')))], rows), note);
    ctx.ready();
  }, (err) => {
    if (!ctx.alive()) return;
    lastKey = null;
    mount(ctx.view, head, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
  load();
}
