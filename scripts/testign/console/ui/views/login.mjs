// Login scenarios: projects and their allowed hosts (edited only here, by the tester), and the
// sign-in checklists the agent drafts and the tester approves or rejects. No screen takes or stores
// an account value. Also the sign-in card a run shows while its job waits for the tester to sign in.

import { h, icon, mount } from '../dom.mjs';
import { NONE, timeOrDay } from '../format.mjs';
import { href } from '../router.mjs';
import { jobErrorText, tooNewNotice } from './job-actions.mjs';
import { hostOf } from './run-form.mjs';
import { badge, banner, emptyState, errorState, loading, openDialog, pageHead, spacer, topbarTitle } from './shell.mjs';

const NAME = /^[a-z0-9][a-z0-9-]{0,39}$/;
const HOST = /^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)*$/;
const RESERVED = new Set(['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
  'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']);
export const MAX_HOSTS = 20;

/** Hosts typed one per line or separated by commas or spaces → lower-case, without duplicates. */
export function splitHosts(text) {
  const out = [];
  for (const part of String(text || '').split(/[\s,、，]+/)) {
    const host = part.trim().toLowerCase().replace(/\.$/, '');
    if (host && !out.includes(host)) out.push(host);
  }
  return out;
}

/** An i18n key for what is wrong with a host list, or null. */
export function checkHosts(hosts, required) {
  if (required && !hosts.length) return 'login_err_hosts_empty';
  if (hosts.length > MAX_HOSTS) return 'login_err_hosts_many';
  if (hosts.some((x) => !HOST.test(x))) return 'login_err_host';
  return null;
}

export function checkProjectName(name) {
  return NAME.test(String(name || '')) && !RESERVED.has(String(name).toUpperCase()) ? null : 'login_err_project_name';
}

/** An http(s) URL whose host reads the same in every parser as a link in a new tab; anything else as text. */
function urlLink(url) {
  if (!url) return h('span.k-muted', NONE);
  if (hostOf(url) === null) return h('code.k-mono.break', url);
  return h('a.break', { href: url, target: '_blank', rel: 'noopener noreferrer' }, [h('code.k-mono', url), ' ', icon('external', 'k-icon--sm')]);
}

/** The sign-in card for a webtest-run job whose ask is `sign-in` (the full job record). */
export function signInCard(ctx, job) {
  const { t } = ctx;
  const ask = job.ask;
  const list = ask.checklist || {};
  const prev = ask.previous;
  if (job.can_answer === false) {
    return h('section.k-card.signin-card.stack-12', { 'aria-labelledby': `signin-${ask.id}`, dataset: { signInCard: ask.id } }, [
      h('div.row-8', [icon('key'), h('h2.panel-title.flush', { id: `signin-${ask.id}` },
        t('login_ask_title', { label: list.label || ask.scenario }))]),
      tooNewNotice(t),
    ]);
  }
  const errorBox = h('div', { role: 'alert' });
  const send = async (choice, button) => {
    button.disabled = true;
    try {
      await ctx.api.answer(job.id, ask.id, { choice });
      ctx.toast(t('ask_sent'));
      ctx.invalidate(`job:${job.id}`);
      ctx.pollNow();
    } catch (err) {
      button.disabled = false;
      if (err && err.status === 409) ctx.pollNow();
      mount(errorBox, h('p.k-field__error', [icon('warning'), jobErrorText(t, err)]));
    }
  };
  const signedIn = h('button.k-btn.k-btn--primary', { type: 'button', dataset: { signIn: 'signed-in' } }, t('login_signed_in'));
  const skip = h('button.k-btn.k-btn--ghost', { type: 'button', dataset: { signIn: 'skip' } }, t('login_skip'));
  signedIn.addEventListener('click', () => send('signed-in', signedIn));
  skip.addEventListener('click', () => send('skip', skip));
  const steps = [];
  if (prev) {
    steps.push(h('li', [t('login_sign_out_of', { label: prev.label || prev.name }), ' ', urlLink(prev.signout_url)]));
  }
  if (list.login_url) steps.push(h('li', [t('login_open_signin'), ' ', urlLink(list.login_url)]));
  for (const s of list.steps || []) steps.push(h('li', s));
  const check = list.signed_in_check || {};
  return h('section.k-card.signin-card.stack-12', { 'aria-labelledby': `signin-${ask.id}`, dataset: { signInCard: ask.id } }, [
    h('div.row-8', [icon('key'), h('h2.panel-title.flush', { id: `signin-${ask.id}` },
      t('login_ask_title', { label: list.label || ask.scenario }))]),
    h('p.panel-text', prev ? t('login_ask_switch', { from: prev.label || prev.name, to: list.label || ask.scenario }) : t('login_ask_body')),
    h('ol.signin-steps', steps),
    list.account_hint ? h('p.k-note', [h('strong', t('login_hint')), ' ', list.account_hint]) : null,
    check.text || check.url ? h('p.k-note', [h('strong', t('login_check')), ' ', check.text || '', check.url ? [' · ', urlLink(check.url)] : null]) : null,
    h('p.k-note', t('login_no_values')),
    errorBox,
    h('div.row-8', [signedIn, skip, h('span.k-note', t('login_skip_note'))]),
  ]);
}

export function render(ctx) {
  const { t, route } = ctx;
  const body = h('div.page');
  mount(ctx.view, body);
  ctx.topbar(topbarTitle(t('nav_login')), spacer(), h('span.k-note', t('login_no_values')));
  const head = pageHead(t('login_title'), t('login_subtitle'));
  mount(body, head, loading(t, 4));
  const wanted = route.query && route.query.project;
  let creating = false;

  const load = async () => {
    let projects;
    try {
      projects = (await ctx.memo('projects', () => ctx.api.projects())).projects || [];
    } catch (err) {
      if (!ctx.alive()) return;
      mount(body, head, errorState(t, err, () => ctx.refresh()));
      ctx.ready();
      return;
    }
    if (!ctx.alive()) return;
    ctx.setCount('login', projects.length);
    const current = creating ? null : projects.find((p) => p.name === wanted) || projects[0] || null;
    let detail = null;
    if (current) {
      try {
        detail = await ctx.memo(`login:${current.name}`, () => ctx.api.scenarios(current.name));
      } catch (err) {
        if (!ctx.alive()) return;
        detail = { error: err };
      }
      if (!ctx.alive()) return;
    }
    draw(projects, current, detail);
    ctx.ready();
  };

  function reload(name) {
    ctx.invalidate('projects');
    if (name) ctx.invalidate(`login:${name}`);
    ctx.invalidate('count:login');
    load();
  }

  function draw(projects, current, detail) {
    const tabs = h('div.k-list.login-projects', { role: 'list', 'aria-label': t('login_project') }, [
      ...projects.map((p) => h('a.k-issue-row', {
        href: href(['login'], { project: p.name }), role: 'listitem', class: current && current.name === p.name ? 'is-selected' : '',
        'aria-current': current && current.name === p.name ? 'page' : undefined, dataset: { project: p.name },
      }, [icon('key'), h('span.k-issue-row__title', p.name),
        h('span.k-note.num', t('login_count', { approved: p.approved, n: p.scenarios }))])),
      h('button.k-btn.k-btn--ghost.k-btn--sm.login-new', {
        type: 'button', dataset: { newProject: '1' }, on: { click: () => { creating = true; draw(projects, null, null); } },
      }, [icon('plus'), t('login_new_project')]),
    ]);
    const main = [hostsForm(current)];
    if (current && detail && detail.error) main.push(errorState(t, detail.error, () => reload(current.name)));
    else if (current && detail) main.push(scenarioList(current, detail));
    mount(body, head, h('div.login-layout', [h('nav.login-side', tabs), h('div.stack-24.login-main', main)]));
  }

  function hostsForm(project) {
    const nameInput = h('input.k-input', { type: 'text', id: 'login-project-name', maxlength: '40', autocomplete: 'off', spellcheck: 'false' });
    const hosts = h('textarea.k-textarea.k-mono', { id: 'login-hosts', rows: '3', spellcheck: 'false' });
    const signin = h('textarea.k-textarea.k-mono', { id: 'login-signin-hosts', rows: '2', spellcheck: 'false' });
    hosts.value = project ? (project.hosts || []).join('\n') : '';
    signin.value = project ? (project.signin_hosts || []).join('\n') : '';
    const errorBox = h('div', { role: 'alert' });
    const save = h('button.k-btn.k-btn--primary', { type: 'button', dataset: { saveHosts: '1' } }, t('login_save_hosts'));
    save.addEventListener('click', async () => {
      const name = project ? project.name : nameInput.value.trim();
      const list = splitHosts(hosts.value);
      const sso = splitHosts(signin.value);
      const problem = (project ? null : checkProjectName(name)) || checkHosts(list, true) || checkHosts(sso, false);
      mount(errorBox, problem ? h('p.k-field__error', [icon('warning'), t(problem)]) : null);
      if (problem) return;
      save.disabled = true;
      try {
        await ctx.api.saveProject(name, { hosts: list, signin_hosts: sso });
        ctx.toast(t('login_hosts_saved'));
        creating = false;
        if (!project) {
          ctx.navigate(href(['login'], { project: name }));
          return;
        }
        reload(name);
      } catch (err) {
        save.disabled = false;
        mount(errorBox, h('p.k-field__error', [icon('warning'), jobErrorText(t, err)]));
      }
    });
    return h('section.k-card.stack-12', { 'aria-labelledby': 'login-hosts-title' }, [
      h('h2.panel-title.flush', { id: 'login-hosts-title' }, project ? project.name : t('login_new_project')),
      project ? null : h('div.k-field', [h('label.k-field__label', { for: nameInput.id }, t('login_project')), nameInput,
        h('span.k-field__help', t('login_project_help'))]),
      h('div.k-field', [h('label.k-field__label', { for: hosts.id }, t('login_hosts')), hosts, h('span.k-field__help', t('login_hosts_help'))]),
      h('div.k-field', [h('label.k-field__label', { for: signin.id }, [t('login_signin_hosts'), ' ', h('span.k-muted', t('runform_optional'))]),
        signin, h('span.k-field__help', t('login_signin_help'))]),
      errorBox,
      h('div.row-8', save),
    ]);
  }

  function scenarioList(project, detail) {
    const list = detail.scenarios || [];
    const items = [h('li.scenario-item', [h('div.row-8', [h('strong', t('login_l_none')), h('code.k-mono', 'none'),
      badge(t('login_builtin'), 'outline')])])];
    for (const s of list) items.push(scenarioItem(project, s));
    return h('section.stack-12', { 'aria-labelledby': 'login-scenarios-title' }, [
      h('h2.panel-title.flush', { id: 'login-scenarios-title' }, t('login_scenarios')),
      h('p.k-note', t('login_how_created')),
      list.length ? null : emptyState(t('login_no_scenarios'), t('login_how_created')),
      h('ul.plain-list.stack-12', items),
    ]);
  }

  function scenarioItem(project, s) {
    const note = h('textarea.k-textarea', { id: `note-${s.name}`, rows: '2', maxlength: '1000', placeholder: t('login_note_ph') });
    const errorBox = h('div', { role: 'alert' });
    const act = async (button, fn, okText) => {
      button.disabled = true;
      try {
        await fn();
        ctx.toast(okText);
        reload(project.name);
      } catch (err) {
        button.disabled = false;
        if (err && err.code === 'scenario-changed') reload(project.name);
        mount(errorBox, h('p.k-field__error', [icon('warning'), jobErrorText(t, err)]));
      }
    };
    const approve = h('button.k-btn.k-btn--primary.k-btn--sm', { type: 'button', dataset: { approve: s.name } }, t('login_approve'));
    approve.addEventListener('click', () => act(approve, () => ctx.api.approveScenario(project.name, s.name, s.hash), t('login_approved_toast')));
    const reject = h('button.k-btn.k-btn--secondary.k-btn--sm', { type: 'button', dataset: { reject: s.name } }, t('login_reject'));
    reject.addEventListener('click', () => {
      if (!note.value.trim()) {
        mount(errorBox, h('p.k-field__error', [icon('warning'), t('login_err_note')]));
        note.focus();
        return;
      }
      act(reject, () => ctx.api.rejectScenario(project.name, s.name, note.value.trim()), t('login_rejected_toast'));
    });
    const remove = h('button.k-btn.k-btn--ghost.k-btn--sm', { type: 'button', dataset: { remove: s.name } }, t('login_remove'));
    remove.addEventListener('click', () => {
      const dlg = openDialog({
        t, title: t('login_remove_title', { name: s.label || s.name }), body: h('p', t('login_remove_body')),
        footer: [
          h('button.k-btn.k-btn--ghost', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')),
          h('button.k-btn.k-btn--danger', {
            type: 'button', on: { click: () => { dlg.close(); act(remove, () => ctx.api.removeScenario(project.name, s.name), t('login_removed_toast')); } },
          }, t('login_remove')),
        ],
      });
    });
    const check = s.signed_in_check || {};
    return h('li.scenario-item.k-card.stack-12', { dataset: { scenario: s.name } }, [
      h('div.row-8.wrap', [h('strong', s.label || s.name), h('code.k-mono', s.name),
        s.approved ? badge(t('login_approved'), 'success') : badge(t('login_draft'), 'warning'),
        s.approved_at ? h('span.k-note', timeOrDay(s.approved_at)) : null]),
      s.rejection ? banner('warning', t('login_rejected'), s.rejection.note || '') : null,
      h('dl.k-props', [
        h('dt', t('login_login_url')), h('dd', urlLink(s.login_url)),
        h('dt', t('login_signout_url')), h('dd', urlLink(s.signout_url)),
        h('dt', t('login_check')), h('dd', [check.text || NONE, check.url ? [' · ', urlLink(check.url)] : null]),
        h('dt', t('login_hint')), h('dd', s.account_hint || NONE),
      ]),
      h('div.stack-4', [h('span.k-section-label', t('login_steps')),
        (s.steps || []).length ? h('ol.signin-steps', s.steps.map((x) => h('li', x))) : h('p.k-note', NONE),
        h('p.k-note', t('login_steps_readonly'))]),
      h('div.k-field', [h('label.k-field__label', { for: note.id }, [t('login_note'), ' ', h('span.k-muted', t('login_note_when'))]), note]),
      errorBox,
      h('div.row-8.wrap', [s.approved ? null : approve, reject, h('span.push-right', remove)]),
    ]);
  }

  load();
}
