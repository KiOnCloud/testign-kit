// The survey form: ticket, repo path, refs, fetch, feature and report language. "Survey again"
// opens it prefilled from the report; the tester always sees and confirms the values before the
// job is queued. The checks here mirror the server's; the server stays authoritative.

import { h, icon, mount } from '../dom.mjs';
import { LANGS } from '../prefs.mjs';
import { queueJob } from './job-actions.mjs';
import { LANG_NAMES, openDialog } from './shell.mjs';

const REF = /^[A-Za-z0-9._/-]{1,200}$/;
const FEATURE = /^[\p{L}\p{N}_-]{1,80}$/u;

/** An absolute path on Windows (C:\…, \\server\…) or POSIX (/…). */
export function looksAbsolute(path) {
  const p = String(path || '').trim();
  return /^[A-Za-z]:[\\/]/.test(p) || /^\\\\[^\\]/.test(p) || p.startsWith('/');
}

/** Field problems as {field: i18n key}; empty when the values can be sent. */
export function checkSurvey(v) {
  const errors = {};
  if (!String(v.ticket || '').trim()) errors.ticket = 'survey_err_ticket';
  if (!looksAbsolute(v.repo)) errors.repo = 'survey_err_repo';
  for (const key of ['master_ref', 'develop_ref']) {
    if (v[key] && !REF.test(v[key])) errors[key] = 'survey_err_ref';
  }
  if (v.feature && !FEATURE.test(v.feature)) errors.feature = 'survey_err_feature';
  if (!LANGS.includes(v.report_lang)) errors.report_lang = 'survey_err_lang';
  return errors;
}

/**
 * Prefill for "Survey again" from a report's frontmatter. The browser cannot check that the
 * frontmatter's repo still exists, so the last repo the tester typed wins when there is one.
 */
export function prefillFromReport(frontmatter, lastRepo, fallbackLang) {
  const fm = frontmatter || {};
  const text = (v) => (typeof v === 'string' ? v : '');
  const fmRepo = text(fm.repo);
  return {
    ticket: text(fm.ticket),
    repo: lastRepo || (looksAbsolute(fmRepo) ? fmRepo : ''),
    master_ref: text(fm.master_ref),
    develop_ref: text(fm.develop_ref),
    feature: text(fm.cache_feature),
    report_lang: LANGS.includes(fm.lang) ? fm.lang : (LANGS.includes(fallbackLang) ? fallbackLang : 'vi'),
    fetch: false,
  };
}

/** Open the form. `initial` prefills it; `again` marks the "Survey again" path. */
export function openSurveyForm(ctx, { initial = {}, again = false, configLang } = {}) {
  const { t } = ctx;
  const values = {
    ticket: initial.ticket || '',
    repo: initial.repo ?? ctx.prefs.getLastRepo(),
    master_ref: initial.master_ref || '',
    develop_ref: initial.develop_ref || '',
    feature: initial.feature || '',
    report_lang: initial.report_lang || (LANGS.includes(configLang) ? configLang : 'vi'),
  };
  const fields = {};
  const errors = {};
  const field = (name, label, input, help, wrapper) => {
    input.id = `survey-${name}`;
    errors[name] = h('div', { role: 'alert' });
    fields[name] = input;
    return h('div.k-field', [h('label.k-field__label', { for: input.id }, label), wrapper || input,
      help ? h('span.k-field__help', help) : null, errors[name]]);
  };
  const text = (name, placeholder) => {
    const el = h('input.k-input', { type: 'text', autocomplete: 'off', spellcheck: 'false', placeholder });
    el.value = values[name];
    return el;
  };
  const lang = h('select.k-select', LANGS.map((l) => h('option', { value: l, selected: l === values.report_lang }, LANG_NAMES[l])));
  const fetch = h('input', { type: 'checkbox', id: 'survey-fetch' });
  const submit = h('button.k-btn.k-btn--primary', { type: 'button' }, again ? t('survey_queue_again') : t('survey_queue'));

  const body = h('div.stack-16', [
    again ? h('p.k-note', t('survey_again_note')) : null,
    field('ticket', t('survey_ticket'), text('ticket', 'DEMO-1')),
    field('repo', t('survey_repo'), text('repo', 'C:\\work\\app'), t('survey_repo_help')),
    h('div.form-row', [
      field('master_ref', t('survey_master_ref'), text('master_ref', 'master')),
      field('develop_ref', t('survey_develop_ref'), text('develop_ref', 'develop')),
    ]),
    h('div.form-row', [
      field('feature', t('survey_feature'), text('feature', ''), t('survey_feature_help')),
      field('report_lang', t('survey_report_lang'), lang, null, h('span.k-select-wrap', [lang, icon('chevron', 'k-icon--sm chevron-down')])),
    ]),
    h('label.k-check', [fetch, h('span.k-check__box', icon('check')), t('survey_fetch')]),
  ]);

  submit.addEventListener('click', async () => {
    const v = {
      ticket: fields.ticket.value.trim(),
      repo: fields.repo.value.trim(),
      master_ref: fields.master_ref.value.trim(),
      develop_ref: fields.develop_ref.value.trim(),
      feature: fields.feature.value.trim(),
      report_lang: lang.value,
    };
    const problems = checkSurvey(v);
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
    const job = { kind: 'survey', ticket: v.ticket, repo: v.repo, fetch: fetch.checked, report_lang: v.report_lang };
    for (const key of ['master_ref', 'develop_ref', 'feature']) if (v[key]) job[key] = v[key];
    const queued = await queueJob(ctx, job, { open: false });
    submit.disabled = false;
    if (queued) {
      ctx.prefs.setLastRepo(v.repo);
      dlg.close();
      ctx.navigate(`#/jobs/${encodeURIComponent(queued.id)}`);
    }
  });

  const dlg = openDialog({
    t, title: again ? t('survey_again_title', { id: values.ticket }) : t('survey_title'), wide: true, body,
    footer: [h('button.k-btn.k-btn--ghost', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')), submit],
    initialFocus: () => (values.ticket ? fields.repo : fields.ticket),
  });
  return dlg;
}
