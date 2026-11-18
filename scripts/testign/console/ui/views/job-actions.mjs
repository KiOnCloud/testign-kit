// Queueing jobs from any screen, and the small labels every job view shares: kind, state glyph,
// revision, failure reason. Every job carries the viewer's ui_lang; the server stays the authority
// on parameters and answers 400 with a code this module turns into a message.

import { h, icon, statusGlyph } from '../dom.mjs';
import { href } from '../router.mjs';
import { badge, errorText, openDialog } from './shell.mjs';

const ERROR_KEYS = {
  'tester-required': 'job_err_tester',
  'template-required': 'job_err_template',
  'unknown-template': 'job_err_unknown_template',
  'workbook-required': 'job_err_workbook',
  'unknown-workbook': 'job_err_unknown_workbook',
  'unknown-row': 'job_err_unknown_row',
  'not-found': 'job_err_no_revision',
  conflict: 'job_err_conflict',
  'session-too-new': 'job_err_session_too_new',
};

export function jobErrorText(t, err) {
  const key = err && ERROR_KEYS[err.code];
  if (key) return t(key);
  if (err && err.code === 'bad-request') return t('job_err_bad_request', { message: err.message || '' });
  return errorText(t, err);
}

/** A short handle for a job id: its last part, e.g. "#c07d". */
export function shortId(id) {
  const parts = String(id || '').split('-');
  return `#${parts[parts.length - 1]}`;
}

/** "r2" from "DEMO-1-survey-r2.md"; empty when the name has no revision number. */
export function revOf(name) {
  const m = /-r(\d+)\.md$/.exec(String(name || ''));
  return m ? `r${m[1]}` : '';
}

export function kindLabel(t, kind) {
  return t(`job_kind_${kind}`) === `job_kind_${kind}` ? kind : t(`job_kind_${kind}`);
}

/** "Close QA · DEMO-1 r2" (plus mode and focus when the full record is known). */
export function jobTitle(t, job) {
  const parts = [kindLabel(t, job.kind), [job.ticket, revOf(job.base_revision)].filter(Boolean).join(' ')];
  const p = job.params || {};
  if (job.kind === 'testcase' && p.mode === 'trace') parts.push(t('job_mode_trace'));
  if (Array.isArray(p.focus) && p.focus.length) parts.push(t('job_focus', { rows: p.focus.join(', ') }));
  return parts.join(' · ');
}

const SHAPES = {
  queued: ['todo', 'k-status--todo'],
  offered: ['todo', 'k-status--todo'],
  running: ['progress', 'k-status--progress'],
  'needs-input': ['progress', 'k-status--progress'],
  done: ['done', 'k-status--done'],
  failed: ['crossed', 'text-danger'],
  cancelled: ['crossed', 'k-status--canceled'],
};

export function stateGlyph(state) {
  const [shape, cls] = SHAPES[state] || SHAPES.queued;
  return statusGlyph(shape, cls);
}

export function stateLabel(t, state) {
  return t(`job_state_${String(state).replace('-', '_')}`);
}

export function stateBadge(t, job) {
  if (job.state === 'needs-input') return badge(t('job_state_needs_input'), 'warning');
  if (job.state === 'failed') return h('span.k-note.text-danger', reasonShort(t, job.reason));
  if (job.silent) return badge(t('job_silent'), 'warning');
  return h('span.k-note', stateLabel(t, job.state));
}

export function reasonShort(t, reason) {
  const key = `job_reason_${String(reason || 'agent').replace(/-/g, '_')}`;
  const text = t(key);
  return text === key ? t('job_state_failed') : text;
}

/** POST a job; on success toast, refresh the store and open the job. Returns the summary or null. */
export async function queueJob(ctx, body, { open = true } = {}) {
  try {
    const job = await ctx.api.createJob({ ...body, ui_lang: ctx.lang });
    ctx.toast(ctx.t('job_queued', { title: jobTitle(ctx.t, job) }));
    ctx.pollNow();
    if (open) ctx.navigate(href(['jobs', job.id]));
    return job;
  } catch (err) {
    ctx.toast(jobErrorText(ctx.t, err), 'danger');
    return null;
  }
}

/** Ask for the tester name (saved to Settings) before a Close job; resolves to the name or null. */
export function askTesterName(ctx) {
  const current = ctx.prefs.getTesterName();
  if (current) return Promise.resolve(current);
  return new Promise((resolve) => {
    const { t } = ctx;
    let done = false;
    const input = h('input.k-input', { type: 'text', id: 'tester-prompt', autocomplete: 'name', maxlength: '100' });
    const errorBox = h('div', { role: 'alert' });
    const finish = (value) => { if (!done) { done = true; resolve(value); } };
    const submit = () => {
      const name = input.value.trim();
      if (!name) {
        errorBox.replaceChildren(h('p.k-field__error', [icon('warning'), t('job_tester_empty')]));
        input.focus();
        return;
      }
      ctx.prefs.setTesterName(name);
      finish(name);
      dlg.close();
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
    const dlg = openDialog({
      t, title: t('job_tester_title'),
      body: h('div.stack-12', [
        h('p', t('job_tester_body')),
        h('div.k-field', [h('label.k-field__label', { for: 'tester-prompt' }, t('settings_tester')), input,
          h('span.k-field__help', t('settings_tester_help'))]),
        errorBox,
      ]),
      footer: [
        h('button.k-btn.k-btn--ghost', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')),
        h('button.k-btn.k-btn--primary', { type: 'button', on: { click: submit } }, t('job_tester_continue')),
      ],
      onClose: () => finish(null),
    });
  });
}

/** Pick one of several templates; resolves to a name or null. One template resolves at once. */
export function chooseTemplate(ctx, listing, title) {
  const names = (listing && listing.templates || []).map((x) => x.name);
  if (names.length <= 1) return Promise.resolve(names[0] || null);
  return new Promise((resolve) => {
    const { t } = ctx;
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const select = h('select.k-select', { id: 'job-template' }, names.map((n) => h('option', {
      value: n, selected: n === listing.default,
    }, n === listing.default ? `${n} · ${t('templates_default')}` : n)));
    const dlg = openDialog({
      t, title,
      body: h('div.k-field', [h('label.k-field__label', { for: 'job-template' }, t('trace_template')),
        h('span.k-select-wrap', [select, icon('chevron', 'k-icon--sm chevron-down')])]),
      footer: [
        h('button.k-btn.k-btn--ghost', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')),
        h('button.k-btn.k-btn--primary', { type: 'button', on: { click: () => { finish(select.value); dlg.close(); } } }, t('job_queue')),
      ],
      onClose: () => finish(null),
    });
  });
}

/** The body that queues the same work again (the server pins it to the latest revision). */
export function requeueBody(job, testerName) {
  const p = job.params || {};
  if (job.kind === 'close') return { kind: 'close', ticket: job.ticket, tester: p.tester || testerName };
  if (job.kind === 'testcase') {
    const body = { kind: 'testcase', ticket: job.ticket, mode: p.mode, template: p.template };
    if (p.workbook) body.workbook = p.workbook;
    if (Array.isArray(p.focus) && p.focus.length) body.focus = p.focus;
    return body;
  }
  const body = { kind: 'survey', ticket: job.ticket, repo: p.repo, fetch: Boolean(p.fetch) };
  for (const k of ['master_ref', 'develop_ref', 'feature']) if (p[k]) body[k] = p[k];
  if (job.report_lang) body.report_lang = job.report_lang;
  return body;
}
