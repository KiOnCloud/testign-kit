// The new-run form: Figma change table, project (its hosts come from the Login screen), base URL,
// name, template and ticket. It queues a webtest-plan job; no row runs before the tester confirms
// the review table. The checks mirror the server's; the server stays authoritative.

import { h, icon, mount } from '../dom.mjs';
import { href } from '../router.mjs';
import { jobErrorText, queueJob } from './job-actions.mjs';

const FIGMA = /^https:\/\/(?:www\.)?figma\.com\/(?:design|file|proto)\/[A-Za-z0-9]{10,64}(?:\/[^?#]*)?\?(?:[^#]*&)?node-id=\d+[-:]\d+(?:[&#]|$)/;

/**
 * The host of an http(s) URL in lower case, or null. Like the server, it refuses a backslash,
 * whitespace, a control character, user info or an escaped host: a browser reads `https://a\@b/`
 * as host `a`, which a looser parser reads as `b`.
 */
export function hostOf(url) {
  const s = String(url || '').trim();
  // eslint-disable-next-line no-control-regex
  if (/[\\\s\u0000-\u001f\u007f]/.test(s)) return null;
  const m = /^https?:\/\/([^/?#:@%]+)(?::\d+)?(?:[/?#]|$)/i.exec(s);
  return m ? m[1].toLowerCase().replace(/\.$/, '') : null;
}

/** Field problems as {field: i18n key}; empty when the values can be sent. */
export function checkRunForm(v, projects) {
  const errors = {};
  if (!FIGMA.test(String(v.figma_url || '').trim())) errors.figma_url = 'runform_err_figma';
  const project = (projects || []).find((p) => p.name === v.project);
  if (!project) errors.project = 'runform_err_project';
  const host = hostOf(v.base_url);
  if (!host) errors.base_url = 'runform_err_base';
  else if (project && !(project.hosts || []).includes(host)) errors.base_url = 'runform_err_off_host';
  const name = String(v.name || '').trim();
  if (!name || name.length > 80) errors.name = 'runform_err_name';
  if (!v.template) errors.template = 'runform_err_template';
  return errors;
}

/** Templates for a web run: the web test ones first, then the rest. */
export function templateChoices(listing) {
  const list = (listing && listing.templates) || [];
  const web = list.filter((x) => x.purpose === 'webtest');
  const other = list.filter((x) => x.purpose !== 'webtest');
  return [...web, ...other];
}

export function renderRunForm(ctx, { projects, templates }) {
  const { t } = ctx;
  const fields = {};
  const errors = {};
  const field = (name, label, input, help, wrapper) => {
    input.id = `runform-${name}`;
    errors[name] = h('div', { role: 'alert' });
    fields[name] = input;
    return h('div.k-field', [h('label.k-field__label', { for: input.id }, label), wrapper || input,
      help ? h('span.k-field__help', help) : null, errors[name]]);
  };
  const text = (placeholder) => h('input.k-input', { type: 'text', autocomplete: 'off', spellcheck: 'false', placeholder });
  const select = (options) => h('select.k-select', options);
  const wrap = (el) => h('span.k-select-wrap', [el, icon('chevron', 'k-icon--sm chevron-down')]);

  const choices = templateChoices(templates);
  const projectSelect = select(projects.map((p) => h('option', { value: p.name }, p.name)));
  const templateSelect = select(choices.map((x) => h('option', {
    value: x.name, selected: x.purpose === 'webtest' ? x === choices[0] : x.name === templates.default && choices[0].purpose !== 'webtest',
  }, x.purpose === 'webtest' ? `${x.name} · ${t('tpl_purpose_webtest')}` : x.name)));
  const hostsLine = h('p.k-note.break');
  const drawHosts = () => {
    const p = projects.find((x) => x.name === projectSelect.value);
    mount(hostsLine, p ? [t('runform_hosts'), ' ', h('code.k-mono', (p.hosts || []).join(', ')), ' · ',
      h('a', { href: href(['login'], { project: p.name }) }, t('runform_edit_hosts'))] : null);
  };
  projectSelect.addEventListener('change', drawHosts);
  const submit = h('button.k-btn.k-btn--primary', { type: 'button' }, t('runform_queue'));

  if (!projects.length) {
    return h('div.panel-body.stack-12', [
      h('h2.panel-title', { id: 'run-form-title' }, t('runform_title')),
      h('p.panel-text', t('runform_no_project')),
      h('div.row-8', h('a.k-btn.k-btn--secondary', { href: href(['login']) }, t('runform_go_login'))),
    ]);
  }
  if (!choices.length) {
    return h('div.panel-body.stack-12', [
      h('h2.panel-title', { id: 'run-form-title' }, t('runform_title')),
      h('p.panel-text', t('runform_no_template')),
      h('div.row-8', h('a.k-btn.k-btn--secondary', { href: href(['templates']) }, t('nav_templates'))),
    ]);
  }

  const form = h('div.stack-16.run-form', [
    h('h2.panel-title.flush', { id: 'run-form-title' }, t('runform_title')),
    field('figma_url', t('runform_figma'), text('https://www.figma.com/design/…?node-id=…'), t('runform_figma_help')),
    h('div.stack-4', [field('project', t('runform_project'), projectSelect, null, wrap(projectSelect)), hostsLine]),
    field('base_url', t('runform_base'), text('https://')),
    field('name', t('runform_name'), h('input.k-input', { type: 'text', maxlength: '80', autocomplete: 'off' })),
    field('template', t('runform_template'), templateSelect, null, wrap(templateSelect)),
    field('ticket', [t('runform_ticket'), ' ', h('span.k-muted.ws-sub', t('runform_optional'))], text('DEMO-1')),
    h('div.k-banner.k-banner--info', { role: 'note' }, [icon('info'),
      h('div.k-banner__text', [h('strong', t('runform_next_title')), h('span', t('runform_next_body'))])]),
    h('div.row-8', submit),
  ]);
  drawHosts();

  submit.addEventListener('click', async () => {
    const v = {
      figma_url: fields.figma_url.value.trim(), project: projectSelect.value, base_url: fields.base_url.value.trim(),
      name: fields.name.value.trim(), template: templateSelect.value, ticket: fields.ticket.value.trim(),
    };
    const problems = checkRunForm(v, projects);
    for (const [name, box] of Object.entries(errors)) {
      mount(box, problems[name] ? h('p.k-field__error', [icon('warning'), t(problems[name])]) : null);
      if (fields[name] && fields[name].classList) fields[name].classList.toggle('is-error', Boolean(problems[name]));
    }
    const first = Object.keys(problems)[0];
    if (first) {
      fields[first].focus();
      return;
    }
    submit.disabled = true;
    const job = { kind: 'webtest-plan', figma_url: v.figma_url, project: v.project, base_url: v.base_url, name: v.name,
      template: v.template };
    if (v.ticket) job.ticket = v.ticket;
    const queued = await queueJob(ctx, job, { open: false });
    submit.disabled = false;
    if (queued) ctx.navigate(href(['jobs', queued.id]));
  });
  return form;
}

export { jobErrorText };
