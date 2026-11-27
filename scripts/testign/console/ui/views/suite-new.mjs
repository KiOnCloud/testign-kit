// New test suite in four steps: Source → Input → Details → Review. Only step 2 depends on the
// source: its form comes from SOURCE_FORMS, keyed by the kinds the server lists. Figma and Backlog
// suites are written by the agent in one job; Excel and manual suites are made at once.

import { UPLOAD_CAP } from '../api.mjs';
import { h, icon, mount, statusIcon } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { href } from '../router.mjs';
import { reportLangs } from './survey-form.mjs';
import { freshnessIcon } from './survey.mjs';
import { suiteErrorText } from './suites.mjs';
import {
  alertBox, breadcrumb, errorState, field, langName, loading, pageHead, selectEl, selectWrap, srcBadge,
} from './shell.mjs';

export const STEPS = ['source', 'input', 'details', 'review'];
export const NAME_MAX = 120;
export const DEPTHS = ['smoke', 'standard', 'thorough'];
const FIGMA = /^https:\/\/(?:www\.)?figma\.com\/(?:design|file|proto)\/[A-Za-z0-9]{10,64}(?:\/[^?#]*)?\?(?:[^#]*&)?node-id=\d+[-:]\d+(?:[&#]|$)/;
const EXCEL = /\.(xlsx|xlsm)$/i;

const text = (v) => String(v ?? '').trim();

/** Tickets a Backlog suite can start from: readable, with a survey report. */
export function reportTickets(tickets) {
  return (tickets || []).filter((tk) => tk && !tk.error && tk.latest && Number.isFinite(tk.revision));
}

/** Templates to read an Excel file with: test case templates first, then the rest. */
export function caseTemplates(listing) {
  const list = (listing && listing.templates) || [];
  return [...list.filter((x) => x.purpose !== 'webtest'), ...list.filter((x) => x.purpose === 'webtest')];
}

/**
 * Step 2 per source kind: `check(draft)` gives {field: i18n key} problems, `payload(draft)` the
 * body fields the server reads, `summary(t, draft)` the line on the review step, `render` the form.
 */
export const SOURCE_FORMS = {
  figma: {
    check: (d) => (FIGMA.test(text(d.figma_url)) ? {} : { figma_url: 'wiz_err_figma' }),
    payload: (d) => ({ figma_url: text(d.figma_url) }),
    summary: (t, d) => text(d.figma_url),
    render: (ctx, d, data, errors, set) => [
      field(ctx.t('wiz_figma_link'), h('input.yh-input', {
        type: 'url', id: 'wiz-figma', value: d.figma_url || '', placeholder: 'https://www.figma.com/design/…?node-id=…',
        autocomplete: 'off', spellcheck: 'false', class: errors.figma_url ? 'is-error' : '', on: { input: (e) => set('figma_url', e.target.value) },
      }), ctx.t('wiz_figma_help'), errorLine(ctx.t, errors.figma_url)),
    ],
  },
  backlog: {
    check: (d) => (text(d.ticket) ? {} : { ticket: 'wiz_err_ticket' }),
    payload: (d) => ({ ticket: text(d.ticket) }),
    summary: (t, d, data) => {
      const tk = reportTickets(data.tickets).find((x) => x.id === d.ticket);
      return tk ? t('suite_ref_report', { ticket: tk.id, rev: tk.revision }) : text(d.ticket);
    },
    render: (ctx, d, data, errors, set) => {
      const { t } = ctx;
      const list = reportTickets(data.tickets);
      const surveyLink = h('a.lnk', { href: href(['survey']) }, t('wiz_open_survey'));
      if (!list.length) {
        return [alertBox('warning', 'warning', t('wiz_no_reports'), h('span', [t('wiz_no_reports_body'), ' ', surveyLink]))];
      }
      const picked = list.find((x) => x.id === d.ticket) || null;
      const select = selectEl({ id: 'wiz-ticket', class: errors.ticket ? 'is-error' : '', on: { change: (e) => set('ticket', e.target.value, true) } },
        [['', t('wiz_pick_ticket')], ...list.map((tk) => [tk.id, `${tk.id} · ${tk.title || tk.latest} · r${tk.revision}`])], d.ticket || '');
      const fresh = picked ? freshnessIcon(t, picked.freshness) : null;
      return [
        field(t('wiz_ticket'), selectWrap(select), h('span', [t('wiz_ticket_help'), ' ', surveyLink]), errorLine(t, errors.ticket), 'wiz-ticket'),
        picked ? h('div.yh-card.yh-card--sunken', h('div.yh-card__body', [
          h('div.st-row', [
            h('span.yh-caption.yh-muted', t('wiz_ticket_meta', { rev: picked.revision, n: picked.open_questions || 0 })),
            statusIcon(fresh.kind, fresh.icon, fresh.tip),
            picked.open_questions ? statusIcon('warn', 'chat', t('fr_questions')) : null,
          ]),
          h('div.yh-card__title', { lang: picked.lang || undefined }, picked.title || picked.latest),
        ])) : null,
      ];
    },
  },
  excel: {
    check: (d) => {
      const errors = {};
      if (!d.file) errors.file = 'wiz_err_file';
      else if (!EXCEL.test(d.file.name || '')) errors.file = 'wiz_err_file_type';
      else if (d.file.size > UPLOAD_CAP) errors.file = 'wiz_err_file_size';
      if (!text(d.template)) errors.template = 'wiz_err_template';
      return errors;
    },
    payload: (d) => ({ template: text(d.template), ...(text(d.sheet) ? { sheet: text(d.sheet) } : {}) }),
    summary: (t, d) => [d.file ? d.file.name : NONE, text(d.template)].filter(Boolean).join(' · '),
    upload: true,
    render: (ctx, d, data, errors, set) => {
      const { t } = ctx;
      const templates = caseTemplates(data.templates);
      if (!templates.length) {
        return [alertBox('warning', 'warning', t('wiz_no_templates'), h('a.lnk', { href: href(['templates']) }, t('nav_templates')))];
      }
      const file = h('input.yh-input', { type: 'file', id: 'wiz-file', accept: '.xlsx,.xlsm', class: errors.file ? 'is-error' : '',
        on: { change: (e) => set('file', (e.target.files && e.target.files[0]) || null, true) } });
      const tpl = selectEl({ id: 'wiz-template', class: errors.template ? 'is-error' : '', on: { change: (e) => set('template', e.target.value) } },
        templates.map((x) => [x.name, x.purpose === 'webtest' ? `${x.name} · ${t('tpl_purpose_webtest')}` : x.name]), d.template);
      return [
        field(t('wiz_excel_file'), file, d.file ? t('wiz_file_chosen', { name: d.file.name }) : t('wiz_excel_help'), errorLine(t, errors.file)),
        h('div.grid2', [
          field(t('wiz_excel_template'), selectWrap(tpl), null, errorLine(t, errors.template), 'wiz-template'),
          field(t('wiz_excel_sheet'), h('input.yh-input', { type: 'text', id: 'wiz-sheet', maxlength: '100', value: d.sheet || '',
            on: { input: (e) => set('sheet', e.target.value) } }), t('wiz_excel_sheet_help')),
        ]),
      ];
    },
  },
  manual: {
    check: () => ({}),
    payload: (d) => (text(d.note) ? { note: text(d.note) } : {}),
    summary: (t, d) => text(d.note) || NONE,
    render: (ctx, d, data, errors, set) => [
      alertBox('', 'info', ctx.t('wiz_manual_input_t'), ctx.t('wiz_manual_input_d')),
      field(ctx.t('wiz_manual_note'), h('textarea.yh-textarea.sm', { id: 'wiz-note', rows: '2', maxlength: '300', value: d.note || '',
        on: { input: (e) => set('note', e.target.value) } }), ctx.t('wiz_manual_note_help')),
    ],
  },
};

function errorLine(t, key) {
  return key ? h('p.k-field__error', [icon('warning'), t(key)]) : null;
}

/** The kinds the wizard offers: the server's list, in its order, where a form exists. */
export function offeredSources(sources) {
  return (sources || []).filter((s) => s && Object.prototype.hasOwnProperty.call(SOURCE_FORMS, s.kind));
}

export function checkDetails(d) {
  const name = text(d.name);
  return name && name.length <= NAME_MAX ? {} : { name: 'wiz_err_name' };
}

/** The problems that keep the tester on `step`. */
export function checkStep(step, d) {
  if (step === 1) return d.kind ? {} : { kind: 'wiz_err_kind' };
  if (step === 2) return d.kind ? SOURCE_FORMS[d.kind].check(d) : { kind: 'wiz_err_kind' };
  if (step === 3) return checkDetails(d);
  return {};
}

/** The label of the last button: the agent writes Figma and Backlog cases, the rest are made now. */
export function finishKey(source) {
  return source && source.needs_agent ? 'wiz_queue_gen' : 'wiz_create';
}

/** A name to start from: the ticket and its title, or the file name. */
export function defaultName(d, data) {
  if (d.kind === 'backlog') {
    const tk = reportTickets(data.tickets).find((x) => x.id === d.ticket);
    return tk ? `${tk.id} · ${tk.title || ''}`.replace(/ · $/, '').slice(0, NAME_MAX) : '';
  }
  if (d.kind === 'excel' && d.file) return String(d.file.name || '').replace(EXCEL, '').slice(0, NAME_MAX);
  return '';
}

/** The body of POST /api/webtest/suites (without the upload id of an Excel file). */
export function createBody(d, uiLang) {
  const body = { kind: d.kind, name: text(d.name), ui_lang: uiLang, ...SOURCE_FORMS[d.kind].payload(d) };
  if (text(d.project)) body.project = text(d.project);
  if (text(d.case_lang)) body.case_lang = text(d.case_lang);
  if (DEPTHS.includes(d.depth)) body.depth = d.depth;
  return body;
}

let draft = null;
let draftKey = null;

function freshDraft(query) {
  return { step: query.kind && SOURCE_FORMS[query.kind] ? 2 : 1, kind: SOURCE_FORMS[query.kind] ? query.kind : null,
    ticket: query.ticket || '', figma_url: '', file: null, template: '', sheet: '', note: '', name: '', project: '', case_lang: '', depth: 'standard' };
}

export function render(ctx) {
  const { t, route } = ctx;
  const key = JSON.stringify(route.query || {});
  if (!draft || draftKey !== key) { draft = freshDraft(route.query || {}); draftKey = key; }
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_design') }, { label: t('nav_suites'), href: href(['suites']) }, { label: t('new_suite') }]));
  const page = h('div.narrow');
  mount(ctx.view, page);
  mount(page, loading(t, 4));
  const settle = (p) => p.then((v) => v, () => null);
  Promise.all([
    ctx.memo('sources', () => ctx.api.sources()),
    settle(ctx.memo('tickets', () => ctx.api.tickets())),
    settle(ctx.memo('templates', () => ctx.api.templates())),
    settle(ctx.memo('projects', () => ctx.api.projects())),
    settle(ctx.memo('config', () => ctx.api.config())),
  ]).then(([sources, tickets, templates, projects, config]) => {
    if (!ctx.alive()) return;
    const data = {
      sources: offeredSources(sources.sources), tickets: tickets ? tickets.tickets : [], templates: templates || { templates: [] },
      projects: projects ? projects.projects : [], config: config || {},
    };
    if (!draft.template) {
      const list = caseTemplates(data.templates);
      const def = list.find((x) => x.name === data.templates.default && x.purpose !== 'webtest');
      draft.template = (def || list[0] || {}).name || '';
    }
    if (!draft.case_lang) {
      const langs = reportLangs(data.config);
      draft.case_lang = langs.includes(data.config.lang) ? data.config.lang : langs[0];
    }
    wizard(ctx, page, data);
    ctx.ready();
  }, (err) => {
    if (!ctx.alive()) return;
    mount(page, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
}

function wizard(ctx, page, data) {
  const { t } = ctx;
  let errors = {};
  let busy = false;
  const errorBox = h('div', { role: 'alert' });
  const source = () => data.sources.find((s) => s.kind === draft.kind) || null;
  const set = (name, value, redraw) => {
    draft[name] = value;
    // Typing clears the field's error without a redraw, so the caret stays where it is.
    delete errors[name];
    if (redraw) draw();
  };

  function stepsBar() {
    return h('ol.steps', { 'aria-label': t('wiz_steps') }, STEPS.map((k, i) => h('li', {
      class: i + 1 < draft.step ? 'is-done' : i + 1 === draft.step ? 'is-current' : '',
      'aria-current': i + 1 === draft.step ? 'step' : undefined,
    }, [t(`wiz_step_${k}`), i === 1 && draft.step > 1 && draft.kind ? ` · ${t(`src_${draft.kind}`)}` : ''])));
  }

  function body() {
    if (draft.step === 1) {
      return [h('div.picks', { role: 'radiogroup', 'aria-label': t('wiz_step_source') }, data.sources.map((s) => h('button.yh-card.pick', {
        type: 'button', role: 'radio', 'aria-checked': draft.kind === s.kind ? 'true' : 'false', class: draft.kind === s.kind ? 'is-selected' : '',
        dataset: { src: s.kind }, on: { click: () => { set('kind', s.kind, true); } },
      }, [srcBadge(t, s.kind), h('span.yh-card__title', t(`wiz_${s.kind}_t`)), h('span.yh-card__text', t(`wiz_${s.kind}_d`)),
        h('span.yh-caption.yh-muted', s.needs_agent ? t('wiz_by_agent') : t('wiz_no_agent'))]))),
      errorLine(t, errors.kind)];
    }
    if (draft.step === 2) return [h('div.yh-stack', SOURCE_FORMS[draft.kind].render(ctx, draft, data, errors, set))];
    if (draft.step === 3) {
      const langs = reportLangs(data.config);
      return [h('div.yh-stack', [
        field(t('suite_name'), h('input.yh-input', { type: 'text', id: 'wiz-name', maxlength: String(NAME_MAX), value: draft.name,
          class: errors.name ? 'is-error' : '', on: { input: (e) => set('name', e.target.value) } }), null, errorLine(t, errors.name)),
        h('div.grid2', [
          field(t('col_project'), selectWrap(selectEl({ id: 'wiz-project', on: { change: (e) => set('project', e.target.value) } },
            [['', t('wiz_no_project')], ...data.projects.map((p) => [p.name, p.name])], draft.project)), t('wiz_project_help'), null, 'wiz-project'),
          field(t('wiz_case_lang'), selectWrap(selectEl({ id: 'wiz-lang', on: { change: (e) => set('case_lang', e.target.value) } },
            langs.map((l) => [l, langName(l)]), draft.case_lang)), null, null, 'wiz-lang'),
        ]),
        field(t('depth_label'), selectWrap(selectEl({ id: 'wiz-depth', on: { change: (e) => set('depth', e.target.value, true) } },
          DEPTHS.map((d) => [d, t(`depth_${d}`)]), draft.depth)), t(`depth_${draft.depth}_d`), null, 'wiz-depth'),
      ])];
    }
    const s = source();
    return [
      h('dl.kv', [
        h('dt', t('col_source')), h('dd', h('span.st-row', [srcBadge(t, draft.kind), t(`wiz_${draft.kind}_t`)])),
        h('dt', t('wiz_step_input')), h('dd.break', SOURCE_FORMS[draft.kind].summary(t, draft, data)),
        h('dt', t('suite_name')), h('dd', text(draft.name)),
        h('dt', t('col_project')), h('dd', text(draft.project) || NONE),
        h('dt', t('wiz_case_lang')), h('dd', draft.case_lang ? langName(draft.case_lang) : NONE),
        h('dt', t('depth_label')), h('dd', t(`depth_${draft.depth || 'standard'}`)),
      ]),
      alertBox('', 'info', t('wiz_next_title'),
        t(s && s.needs_agent ? 'wiz_next_gen' : draft.kind === 'excel' ? 'wiz_next_excel' : 'wiz_next_manual')),
    ];
  }

  function draw() {
    const last = draft.step === STEPS.length;
    const back = draft.step > 1
      ? h('button.yh-btn', { type: 'button', dataset: { wiz: 'back' }, on: { click: () => { errors = {}; draft.step -= 1; mount(errorBox, null); draw(); } } }, t('back'))
      : h('a.yh-btn', { href: href(['suites']), dataset: { wiz: 'cancel' } }, t('cancel'));
    const next = h('button.yh-btn.yh-btn--primary', {
      type: 'button', dataset: { wiz: last ? 'done' : 'next' }, disabled: busy || (draft.step === 1 && !draft.kind) ? true : undefined,
      on: { click: () => (last ? finish() : advance()) },
    }, last ? t(finishKey(source())) : t('next'));
    mount(page,
      pageHead(t('wiz_title'), t('wiz_sub')),
      stepsBar(),
      ...body(),
      errorBox,
      h('div.foot', [back, h('span.push'), next]));
  }

  function advance() {
    errors = checkStep(draft.step, draft);
    if (Object.keys(errors).length) { draw(); return; }
    draft.step += 1;
    if (draft.step === 3 && !text(draft.name)) draft.name = defaultName(draft, data);
    draw();
  }

  async function finish() {
    for (const step of [1, 2, 3]) {
      errors = checkStep(step, draft);
      if (Object.keys(errors).length) { draft.step = step; draw(); return; }
    }
    busy = true;
    draw();
    mount(errorBox, null);
    try {
      const body = createBody(draft, ctx.lang);
      if (SOURCE_FORMS[draft.kind].upload) body.upload = (await ctx.api.uploadSuiteFile(draft.file)).upload;
      const made = await ctx.api.createSuite(body);
      ctx.toast(made.job ? t('wiz_queued') : t('wiz_created'));
      ctx.invalidate('count:suites');
      ctx.invalidate('suites');
      if (made.job) ctx.pollNow();
      draft = null;
      draftKey = null;
      ctx.navigate(href(['suites', made.suite]));
    } catch (err) {
      busy = false;
      draw();
      const details = err && err.details && err.details.errors ? Object.entries(err.details.errors).map(([k, v]) => `${k}: ${v}`) : [];
      mount(errorBox, alertBox('danger', 'warning', t('wiz_err_create'),
        h('span', [suiteErrorText(t, err), details.length ? ` (${err.details.case || ''} ${details.join('; ')})` : ''])));
    }
  }

  draw();
}

