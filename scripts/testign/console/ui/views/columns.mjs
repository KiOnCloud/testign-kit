// The export columns of a run: which run field goes into which sheet column, and the verdict labels.
// A run made from a suite gets a first guess when it is created; the tester changes it here. The
// pure functions mirror the server's checks so problems show before sending; the server checks the
// plan again and refuses it while a job works on the run.

import { h, icon, mount } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { jobErrorText } from './job-actions.mjs';
import { badge, errorState, field, loading, openDialog, selectEl, selectWrap } from './shell.mjs';

export const RESULT_FIELDS = ['verdict', 'actual', 'evidence', 'executed_at', 'by'];
export const LABEL_KEYS = ['pass', 'fail', 'not-run', 'not-applicable', 'manual'];

export function colIndex(letter) {
  let n = 0;
  for (const ch of String(letter || '').toUpperCase()) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n;
}

export function colLetter(index) {
  let s = '';
  let n = index;
  while (n > 0) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

/** Every field a column may carry: the server's case fields, then the result fields. */
export function allFields(info) {
  const out = [];
  for (const f of [...((info && info.fields) || []), ...RESULT_FIELDS]) if (!out.includes(f)) out.push(f);
  return out;
}

/** The editable state from the run's plan. */
export function initialDraft(info) {
  const plan = (info && info.plan) || {};
  return {
    template: plan.template || '',
    columns: (plan.columns || []).map((c) => ({ field: c.field, letter: String(c.letter || '').toUpperCase(),
      ...(c.new ? { new: true, header: c.header || '' } : {}) })),
    labels: { ...(plan.verdict_labels || {}) },
  };
}

/** Add a new column for `field` right of every used letter and of the template's last header. */
export function addColumn(draft, info, fieldName) {
  const used = draft.columns.map((c) => colIndex(c.letter));
  const next = Math.max(colIndex(info.last_column), ...used, 0) + 1;
  return { ...draft, columns: [...draft.columns, { field: fieldName, letter: colLetter(next), new: true, header: '' }] };
}

export function removeColumn(draft, index) {
  return { ...draft, columns: draft.columns.filter((_, i) => i !== index) };
}

/** Swap the fields of two columns; the letters stay where they are in the sheet. */
export function moveColumn(draft, index, other) {
  if (other < 0 || other >= draft.columns.length || other === index) return draft;
  const columns = draft.columns.map((c) => ({ ...c }));
  const a = columns[index];
  const b = columns[other];
  [a.field, b.field] = [b.field, a.field];
  if (a.new && b.new) [a.header, b.header] = [b.header, a.header];
  return { ...draft, columns };
}

export function setColumn(draft, index, patch) {
  return { ...draft, columns: draft.columns.map((c, i) => (i === index ? { ...c, ...patch } : c)) };
}

/** Fields not used by any column yet, for "Add column". */
export function freeFields(draft, info) {
  const used = new Set(draft.columns.map((c) => c.field));
  return allFields(info).filter((f) => !used.has(f));
}

/** The columns in sheet order with their draft index. */
export function sheetOrder(draft) {
  return draft.columns.map((c, index) => ({ ...c, index })).sort((a, b) => colIndex(a.letter) - colIndex(b.letter));
}

/**
 * The PUT body, or the problems that stop it: {ok, body, errors}. Errors carry an i18n key and its
 * params. A changed template is sent; its headers are checked by the server.
 */
export function columnsAnswer(info, draft) {
  const errors = [];
  const headers = (info && info.headers) || {};
  const sameTemplate = !draft.template || draft.template === ((info && info.plan) || {}).template;
  const last = colIndex(info && info.last_column);
  const letters = new Set();
  const fields = new Set();
  if (!draft.columns.length) errors.push({ key: 'rt_err_no_columns' });
  for (const c of draft.columns) {
    const letter = String(c.letter || '').trim().toUpperCase();
    if (!/^[A-Z]{1,3}$/.test(letter)) { errors.push({ key: 'rt_err_letter', params: { field: c.field } }); continue; }
    if (letters.has(letter)) errors.push({ key: 'rt_err_letter_twice', params: { letter } });
    if (fields.has(c.field)) errors.push({ key: 'rt_err_field_twice', params: { letter } });
    letters.add(letter);
    fields.add(c.field);
    if (c.new) {
      const header = String(c.header || '').trim();
      if (!header || header.length > 100) errors.push({ key: 'rt_err_header', params: { letter } });
      if (sameTemplate && colIndex(letter) <= last) errors.push({ key: 'rt_err_new_left', params: { letter, last: info.last_column } });
    } else if (sameTemplate && !(letter in headers)) {
      errors.push({ key: 'rt_err_no_header', params: { letter } });
    }
  }
  for (const need of ['content', 'verdict']) {
    if (!fields.has(need)) errors.push({ key: `rt_err_need_${need}` });
  }
  const labels = {};
  for (const [k, v] of Object.entries(draft.labels || {})) {
    if (!LABEL_KEYS.includes(k)) continue;
    const text = String(v || '').trim();
    if (!text) continue;
    if (text.length > 50) errors.push({ key: 'rt_err_label_long', params: { key: k } });
    labels[k] = text;
  }
  if (!labels.pass || !labels.fail) errors.push({ key: 'rt_err_labels' });
  const columns = draft.columns.map((c) => {
    const out = { field: c.field, letter: String(c.letter || '').trim().toUpperCase() };
    if (c.new) Object.assign(out, { new: true, header: String(c.header || '').trim() });
    return out;
  });
  const body = { columns, verdict_labels: labels };
  if (draft.template && !sameTemplate) body.template = draft.template;
  return { ok: errors.length === 0, body, errors };
}

function fieldLabel(t, name) {
  return t(`wt_field_${name}`);
}

/** The column editor dialog. `onSaved` runs after the server took the plan. */
export function openColumnsEditor(ctx, run, onSaved) {
  const { t } = ctx;
  const holder = h('div.stack-16', loading(t, 4));
  const errorBox = h('div', { role: 'alert' });
  const save = h('button.yh-btn.yh-btn--primary', { type: 'button', disabled: true, dataset: { saveColumns: '1' } }, t('cols_save'));
  const cancel = h('button.yh-btn', { type: 'button' }, t('cancel'));
  const dlg = openDialog({ t, title: t('cols_title', { run: run.name || run.id }), wide: true, body: holder, footer: [cancel, save] });
  cancel.addEventListener('click', () => dlg.close());
  let info = null;
  let draft = null;

  const issuesBox = h('div');
  const tableBox = h('div');
  const labelsBox = h('div');

  function update(next, redraw) {
    draft = next;
    const result = columnsAnswer(info, draft);
    save.disabled = !result.ok;
    mount(issuesBox, result.errors.length ? h('div.yh-alert.yh-alert--danger', { role: 'status' }, [icon('warning'),
      h('div.yh-alert__body', [h('div.yh-alert__title', t('rt_blockers', { n: result.errors.length })),
        h('ul.plain-list', result.errors.slice(0, 8).map((e) => h('li', t(e.key, e.params || {}))))])]) : null);
    if (redraw) drawTable();
  }

  function drawTable() {
    const rows = sheetOrder(draft);
    const free = freeFields(draft, info);
    const addSel = selectEl({ 'aria-label': t('rt_add_col'), class: 'yh-input--sm', id: 'cols-add-field' }, free.map((f) => [f, fieldLabel(t, f)]));
    const add = h('button.yh-btn.yh-btn--sm', { type: 'button', disabled: free.length ? undefined : 'disabled',
      on: { click: () => update(addColumn(draft, info, addSel.value || free[0]), true) } },
    [icon('plus'), t('rt_add_col')]);
    mount(tableBox, h('div.stack-8', [
      h('div.toolbar', [h('span.yh-caption.yh-muted', t('rt_last_header', { letter: info.last_column || NONE })),
        h('span.push'), selectWrap(addSel), add]),
      h('div.tbl-box', h('table.yh-table.tbl--narrow', [
        h('thead', h('tr', [h('th', t('rt_c_letter')), h('th', t('rt_c_header')), h('th', t('rt_c_field')), h('th', t('rt_c_move'))])),
        h('tbody', rows.map((c, pos) => h('tr', { dataset: { col: c.letter } }, [
          h('td', c.new
            ? h('input.yh-input.yh-input--sm.col-letter', { type: 'text', value: c.letter, maxlength: '3', 'aria-label': t('rt_c_letter'),
              on: { change: (e) => update(setColumn(draft, c.index, { letter: e.target.value.trim().toUpperCase() }), true) } })
            : h('code.mono', c.letter)),
          h('td', c.new
            ? h('span.st-row', [h('input.yh-input.yh-input--sm', { type: 'text', value: c.header, maxlength: '100', 'aria-label': t('rt_c_header'),
              on: { input: (e) => update(setColumn(draft, c.index, { header: e.target.value }), false) } }), badge(t('rt_new'), 'accent')])
            : h('span', (info.headers || {})[c.letter] || NONE)),
          h('td', selectWrap(selectEl({ 'aria-label': t('rt_c_field'), class: 'yh-input--sm',
            on: { change: (e) => update(setColumn(draft, c.index, { field: e.target.value }), true) } },
          [[c.field, fieldLabel(t, c.field)], ...free.map((f) => [f, fieldLabel(t, f)])], c.field))),
          h('td', h('span.st-row', [
            h('button.yh-tool', { type: 'button', 'aria-label': t('rt_up'), disabled: pos === 0 ? 'disabled' : undefined,
              on: { click: () => update(moveColumn(draft, c.index, rows[pos - 1].index), true) } }, icon('up')),
            h('button.yh-tool', { type: 'button', 'aria-label': t('rt_down'), disabled: pos === rows.length - 1 ? 'disabled' : undefined,
              on: { click: () => update(moveColumn(draft, c.index, rows[pos + 1].index), true) } }, icon('down')),
            h('button.yh-btn.yh-btn--ghost.yh-btn--sm', { type: 'button', dataset: { removeCol: c.letter },
              on: { click: () => update(removeColumn(draft, c.index), true) } }, t('rt_remove')),
          ])),
        ]))),
      ])),
    ]));
  }

  function drawLabels() {
    mount(labelsBox, h('section.stack-8', [
      h('h3.yh-h3.m-0', t('rt_labels_title')),
      h('div.grid2', LABEL_KEYS.map((k) => field(t(`rt_lbl_${k.replace(/-/g, '_')}`),
        h('input.yh-input.yh-input--sm', { type: 'text', id: `cols-label-${k}`, maxlength: '50', value: draft.labels[k] || '',
          on: { input: (e) => update({ ...draft, labels: { ...draft.labels, [k]: e.target.value } }, false) } }),
        k === 'pass' || k === 'fail' ? null : t('runform_optional')))),
    ]));
  }

  ctx.api.runColumns(run.id).then((data) => {
    info = data;
    draft = initialDraft(info);
    const templates = info.templates || [];
    const tplSelect = selectEl({ id: 'cols-template', on: { change: (e) => update({ ...draft, template: e.target.value }, true) } },
      (templates.includes(draft.template) ? templates : [draft.template, ...templates]).filter(Boolean).map((n) => [n, n]), draft.template);
    mount(holder,
      h('p.m-0.k-note', t('cols_intro')),
      field(t('cols_template'), selectWrap(tplSelect), t('cols_template_help'), null, 'cols-template'),
      tableBox, labelsBox, issuesBox, errorBox);
    drawTable();
    drawLabels();
    update(draft, false);
  }, (err) => mount(holder, errorState(t, err)));

  save.addEventListener('click', async () => {
    const result = columnsAnswer(info, draft);
    if (!result.ok) { update(draft, false); return; }
    save.disabled = true;
    mount(errorBox, null);
    try {
      await ctx.api.putRunColumns(run.id, result.body);
      ctx.toast(t('cols_saved'));
      dlg.close();
      if (onSaved) onSaved();
    } catch (err) {
      save.disabled = false;
      const text = err && err.code === 'run-busy' ? t('cols_err_busy')
        : err && err.code === 'bad-columns' ? t('job_err_bad_columns', { message: err.message || '' }) : jobErrorText(t, err);
      mount(errorBox, h('p.k-field__error', [icon('warning'), text]));
    }
  });
  return dlg;
}
