// New run: a ready suite copied onto one environment. The tester picks the suite, the project
// (its hosts come from the Projects screen), the base URL on one of those hosts, their name and
// the result template; the run starts at once. Hosts and sign-in scenarios are never set here:
// only the tester sets them, on the Projects and Scenarios screens. The server checks everything again.

import { h, icon, mount } from '../dom.mjs';
import { hostOf } from '../hosts.mjs';
import { href } from '../router.mjs';
import { queueJob } from './job-actions.mjs';
import { suiteErrorText } from './suites.mjs';
import { alertBox, field, openDialog, selectEl, selectWrap } from './shell.mjs';

const NAME_MAX = 80;

/** The browsers a replay can run a row in; Chromium is the default. */
export const BROWSERS = ['chromium', 'msedge', 'firefox', 'webkit'];

/** Templates for a web run: the web test ones first, then the rest. */
export function templateChoices(listing) {
  const list = (listing && listing.templates) || [];
  return [...list.filter((x) => x.purpose === 'webtest'), ...list.filter((x) => x.purpose !== 'webtest')];
}

/** The template a run starts with: the first web test template, else the default. */
export function defaultTemplate(listing) {
  const choices = templateChoices(listing);
  if (!choices.length) return '';
  if (choices[0].purpose === 'webtest') return choices[0].name;
  return choices.some((x) => x.name === listing.default) ? listing.default : choices[0].name;
}

/** Field problems as {field: i18n key}; empty when the values can be sent. */
export function checkNewRun(v, projects, suites) {
  const errors = {};
  if (!(suites || []).some((s) => s.id === v.suite && s.state === 'ready')) errors.suite = 'nr_err_suite';
  const project = (projects || []).find((p) => p.name === v.project);
  if (!project) errors.project = 'runform_err_project';
  const host = hostOf(v.base_url);
  if (!host) errors.base_url = 'runform_err_base';
  else if (project && !(project.hosts || []).includes(host)) errors.base_url = 'runform_err_off_host';
  if (String(v.name || '').trim().length > NAME_MAX) errors.name = 'runform_err_name';
  const tester = String(v.tester || '').trim();
  if (!tester || tester.length > 100) errors.tester = 'nr_err_tester';
  if (!v.template) errors.template = 'runform_err_template';
  return errors;
}

/** Scenario names the suite's cases sign in with, and which of them the project has not approved. */
export function neededScenarios(cases, scenarios) {
  const names = [...new Set((cases || []).map((c) => c.scenario).filter((s) => s && s !== 'none'))].sort();
  const approved = new Set((scenarios || []).filter((s) => s.approved).map((s) => s.name));
  return { names, missing: names.filter((n) => !approved.has(n)) };
}

/**
 * The New run dialog. `opts.suite` preselects a suite. Resolves after the run is created and its
 * job queued (or the dialog closed).
 */
export async function openNewRun(ctx, opts = {}) {
  const { t } = ctx;
  let suites;
  let projects;
  let templates;
  try {
    [suites, projects, templates] = await Promise.all([
      ctx.memo('suites', () => ctx.api.suites()).then((d) => d.suites || []),
      ctx.memo('projects', () => ctx.api.projects()).then((d) => d.projects || []),
      ctx.memo('templates', () => ctx.api.templates()),
    ]);
  } catch (err) {
    ctx.toast(suiteErrorText(t, err), 'danger');
    return null;
  }
  const ready = suites.filter((s) => s.readable !== false && s.state === 'ready');
  const choices = templateChoices(templates);
  const blocker = !ready.length ? ['nr_no_suite', 'nr_no_suite_body', href(['suites']), 'nav_suites']
    : !projects.length ? ['runform_no_project', 'nr_no_project_body', href(['projects']), 'nav_projects']
      : !choices.length ? ['runform_no_template', 'nr_no_template_body', href(['templates']), 'nav_templates'] : null;
  if (blocker) {
    const dlg = openDialog({
      t, title: t('new_run'),
      body: alertBox('warning', 'warning', t(blocker[0]), t(blocker[1])),
      footer: [h('button.yh-btn', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')),
        h('a.yh-btn.yh-btn--primary', { href: blocker[2], on: { click: () => dlg.close() } }, t(blocker[3]))],
    });
    return null;
  }

  const first = ready.find((s) => s.id === opts.suite) || ready[0];
  const v = {
    suite: first.id,
    project: (projects.find((p) => p.name === first.project) || projects[0]).name,
    base_url: '', name: '', tester: ctx.prefs.getTesterName() || '', template: defaultTemplate(templates),
  };
  const controls = {};
  const errorBoxes = {};
  const errLine = (name) => { errorBoxes[name] = h('div', { role: 'alert' }); return errorBoxes[name]; };
  const formError = h('div', { role: 'alert' });
  const hostsBox = h('div');
  const scenariosBox = h('div');

  const suiteSel = selectEl({ id: 'nr-suite', on: { change: (e) => { v.suite = e.target.value; onSuite(); } } },
    ready.map((s) => [s.id, `${s.name} · ${t('nr_cases', { n: s.cases })}`]), v.suite);
  const projectSel = selectEl({ id: 'nr-project', on: { change: (e) => { v.project = e.target.value; drawHosts(); drawScenarios(); } } },
    projects.map((p) => [p.name, p.label ? `${p.name} · ${p.label}` : p.name]), v.project);
  const templateSel = selectEl({ id: 'nr-template', on: { change: (e) => { v.template = e.target.value; } } },
    choices.map((x) => [x.name, x.purpose === 'webtest' ? `${x.name} · ${t('tpl_purpose_webtest')}` : x.name]), v.template);
  const text = (name, attrs) => h('input.yh-input', { type: 'text', id: `nr-${name}`, autocomplete: 'off', spellcheck: 'false', ...attrs,
    on: { input: (e) => { v[name] = e.target.value; } } });
  controls.suite = suiteSel;
  controls.project = projectSel;
  controls.template = templateSel;
  controls.base_url = text('base_url', { placeholder: 'https://', inputmode: 'url' });
  controls.name = text('name', { maxlength: String(NAME_MAX), placeholder: first.name });
  controls.tester = text('tester', { maxlength: '100', value: v.tester });

  const projectOf = () => projects.find((p) => p.name === v.project);
  function drawHosts() {
    const p = projectOf();
    mount(hostsBox, p ? h('p.yh-caption.yh-muted.m-0.break', { dataset: { hosts: p.name } }, [
      t('runform_hosts'), ' ', h('code.mono', (p.hosts || []).join(', ') || '—'), ' · ',
      h('a.lnk', { href: href(['projects']) }, t('runform_edit_hosts')),
    ]) : null);
  }
  let suiteCases = null;
  let projectScenarios = new Map();
  async function onSuite() {
    const s = ready.find((x) => x.id === v.suite);
    if (s && s.project && projects.some((p) => p.name === s.project) && v.project !== s.project) {
      v.project = s.project;
      projectSel.value = s.project;
      drawHosts();
    }
    if (controls.name.setAttribute && s) controls.name.setAttribute('placeholder', s.name);
    suiteCases = null;
    drawScenarios();
    try {
      const full = await ctx.memo(`suite:${v.suite}`, () => ctx.api.suite(v.suite));
      if (full.id === v.suite) { suiteCases = full.cases || []; drawScenarios(); }
    } catch { /* the scenario hint is optional; the server checks the run */ }
  }
  async function drawScenarios() {
    const project = v.project;
    if (!suiteCases) { mount(scenariosBox, null); return; }
    if (!projectScenarios.has(project)) {
      try {
        const d = await ctx.memo(`scenarios:${project}`, () => ctx.api.scenarios(project));
        projectScenarios.set(project, d.scenarios || []);
      } catch { projectScenarios.set(project, []); }
    }
    if (project !== v.project || !suiteCases) return;
    const { names, missing } = neededScenarios(suiteCases, projectScenarios.get(project));
    mount(scenariosBox, names.length ? h('div.stack-4', { dataset: { needed: names.join(' ') } }, [
      h('p.yh-caption.m-0', [t('nr_scenarios'), ' ', h('code.mono', names.join(', '))]),
      missing.length ? alertBox('warning', 'warning', t('nr_scenarios_missing', { names: missing.join(', ') }), null,
        h('a.yh-btn.yh-btn--sm', { href: href(['scenarios'], { project }) }, t('nav_scenarios'))) : null,
    ]) : h('p.yh-caption.yh-muted.m-0', t('nr_no_scenarios')));
  }

  let settle = () => {};
  const outcome = new Promise((resolve) => { settle = resolve; });
  const submit = h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { newRunSubmit: '1' } }, [icon('play'), t('nr_start')]);
  const browserBoxes = BROWSERS.map((b) => h('input', { type: 'checkbox', id: `nr-browser-${b}`, value: b,
    checked: b === 'chromium' ? true : undefined, dataset: { browser: b } }));
  const browsersField = h('fieldset.stack-4', { dataset: { browsers: '1' } }, [
    h('legend', t('nr_browsers')),
    h('div.st-row', BROWSERS.map((b, i) => h('label.st-row', [browserBoxes[i], h('span', t(`browser_${b}`))]))),
    h('p.yh-caption.yh-muted.m-0', t('nr_browsers_help')),
  ]);
  const dlg = openDialog({
    t, title: t('new_run'), wide: true,
    body: h('div.stack-16.new-run', { dataset: { newRun: '1' } }, [
      field(t('nr_suite'), selectWrap(suiteSel), t('nr_suite_help'), errLine('suite'), 'nr-suite'),
      h('div.grid2', [
        h('div.stack-4', [field(t('runform_project'), selectWrap(projectSel), null, errLine('project'), 'nr-project'), hostsBox]),
        field(t('runform_base'), controls.base_url, t('nr_base_help'), errLine('base_url')),
        field([t('runform_name'), ' ', h('span.yh-muted', t('runform_optional'))], controls.name, null, errLine('name')),
        field(t('nr_tester'), controls.tester, t('nr_tester_help'), errLine('tester')),
      ]),
      field(t('runform_template'), selectWrap(templateSel), t('nr_template_help'), errLine('template'), 'nr-template'),
      browsersField,
      scenariosBox,
      alertBox('', 'info', t('nr_safety_t'), t('nr_safety_d')),
      formError,
    ]),
    footer: [h('button.yh-btn', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')), submit],
    initialFocus: () => controls.base_url,
    onClose: () => settle(null),
  });
  drawHosts();
  onSuite();

  submit.addEventListener('click', async () => {
    const problems = checkNewRun(v, projects, ready);
    for (const [name, box] of Object.entries(errorBoxes)) {
      mount(box, problems[name] ? h('p.k-field__error', [icon('warning'), t(problems[name])]) : null);
      if (controls[name] && controls[name].classList) controls[name].classList.toggle('is-error', Boolean(problems[name]));
    }
    const bad = Object.keys(problems)[0];
    if (bad) { if (controls[bad] && controls[bad].focus) controls[bad].focus(); return; }
    submit.disabled = true;
    mount(formError, null);
    const tester = v.tester.trim();
    let made;
    try {
      const browsers = BROWSERS.filter((b, i) => browserBoxes[i].checked);
      made = await ctx.api.createRun({ suite: v.suite, project: v.project, base_url: v.base_url.trim(), template: v.template,
        name: v.name.trim() || undefined, tester, browsers: browsers.length ? browsers : ['chromium'] });
    } catch (err) {
      submit.disabled = false;
      mount(formError, h('p.k-field__error', [icon('warning'), suiteErrorText(t, err)]));
      return;
    }
    ctx.prefs.setTesterName(tester);
    ctx.invalidate('runs');
    ctx.invalidate('count:runs');
    ctx.invalidate('suites');
    ctx.invalidate(`suite:${v.suite}`);
    settle(made);
    dlg.close();
    await queueJob(ctx, { kind: 'webtest-run', ui_lang: ctx.lang, run: made.run, tester, mode: 'run' }, { open: false });
    ctx.navigate(href(['runs', made.run]));
  });
  return outcome;
}
