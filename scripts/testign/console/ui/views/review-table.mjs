// The review table: the one confirmation of a web test plan. The tester checks the Excel column
// plan against sample rows, the verdict labels, and one line per row (screen, class, who runs it,
// login scenario, viewport and how a phone-width row is checked, preconditions), then confirms once. The pure functions mirror the
// server's rules so problems show before sending; the server checks the answer again.

import { h, icon, mount } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { href } from '../router.mjs';
import { jobErrorText, tooNewNotice } from './job-actions.mjs';
import { hostOf } from './run-form.mjs';
import { badge, banner, breadcrumb, emptyState, errorState, loading, openDialog, pageHead, spacer } from './shell.mjs';

export const FIELDS = ['no', 'type', 'content', 'creator', 'screen', 'viewport', 'mobile_method', 'kind', 'class', 'reason',
  'scenario', 'runner', 'preconditions', 'steps', 'expected', 'target_node', 'verdict', 'actual', 'evidence', 'executed_at', 'by'];
export const RESULT_FIELDS = new Set(['verdict', 'actual', 'evidence', 'executed_at', 'by']);
export const LABEL_KEYS = ['pass', 'fail', 'not-run', 'not-applicable', 'manual'];
export const EDIT_KEYS = ['screen', 'class', 'runner', 'scenario', 'preconditions', 'viewport', 'mobile_method'];
const CLASSES = ['sure', 'choice', 'not-web'];
const RUNNERS = ['agent', 'tester', 'none'];
const VIEWPORTS = ['pc', 'mobile'];
export const MOBILE_METHODS = ['device', 'emulation'];

/** How a row is checked on a phone: none on pc rows; a real device unless the row says emulation. */
export function mobileMethod(viewport, method) {
  if (viewport !== 'mobile') return null;
  return MOBILE_METHODS.includes(method) ? method : 'device';
}

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

/** A screen the server accepts: empty, a path on the base URL (never `//x`), or absolute on a run host. */
export function screenOk(url, hosts) {
  if (url === null || url === undefined || url === '') return true;
  if (typeof url !== 'string' || url.length > 2000) return false;
  if (url.startsWith('/') && !url.startsWith('//') && !url.includes('\\')) return true;
  const host = hostOf(url);
  return host !== null && (hosts || []).map((x) => String(x).toLowerCase()).includes(host);
}

/** The editable state: the agent's column plan and labels, and the tester's edits per row. */
export function initialDraft(ask) {
  return {
    columns: (ask.columns || []).map((c) => ({ field: c.field, letter: String(c.letter || '').toUpperCase(),
      ...(c.new ? { new: true, header: c.header || '' } : {}) })),
    labels: { ...(ask.verdict_labels || {}) },
    rows: {},
  };
}

/** Add a new column for `field` right of every used letter and of the template's last header. */
export function addColumn(draft, ask, field) {
  const used = draft.columns.map((c) => colIndex(c.letter));
  const next = Math.max(colIndex(ask.last_column), ...used, 0) + 1;
  return { ...draft, columns: [...draft.columns, { field, letter: colLetter(next), new: true, header: '' }] };
}

export function removeColumn(draft, index) {
  return { ...draft, columns: draft.columns.filter((_, i) => i !== index) };
}

/** Swap the fields of two neighbouring columns; the letters stay where they are in the sheet. */
export function moveColumn(draft, index, dir) {
  const other = index + dir;
  if (other < 0 || other >= draft.columns.length) return draft;
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

/** Columns that are not used yet, for "Add column". */
export function freeFields(draft) {
  const used = new Set(draft.columns.map((c) => c.field));
  return FIELDS.filter((f) => !used.has(f));
}

/**
 * The grid of the column plan in sheet order: [{letter, header, field, new, cells: [sample text]}].
 * Result columns have no sample (they are filled after the run).
 */
export function sampleGrid(ask, draft) {
  const samples = ask.samples || [];
  return draft.columns
    .map((c, index) => ({ ...c, index }))
    .sort((a, b) => colIndex(a.letter) - colIndex(b.letter))
    .map((c) => ({
      index: c.index, letter: c.letter, field: c.field, new: Boolean(c.new),
      header: c.new ? c.header : (ask.headers || {})[c.letter] || '',
      cells: samples.map((s) => (RESULT_FIELDS.has(c.field) ? null : (s.cells || {})[c.letter] || '')),
    }));
}

const norm = (v) => (v === undefined || v === null ? '' : v);

/** Set one edit; an edit equal to the agent's line is dropped. */
export function setEdit(draft, line, key, value) {
  const rows = { ...draft.rows };
  const edit = { ...(rows[line.row] || {}) };
  if (norm(value) === norm(line[key])) delete edit[key];
  else edit[key] = value;
  if (Object.keys(edit).length) rows[line.row] = edit;
  else delete rows[line.row];
  return { ...draft, rows };
}

/** The line as confirmation stores it: a not-web row is run by no one, a pc row has no phone check. */
export function finalLine(draft, line) {
  const f = { ...line, ...(draft.rows[line.row] || {}) };
  return { ...f, runner: f.class === 'not-web' ? 'none' : f.runner, mobile_method: mobileMethod(f.viewport, f.mobile_method) };
}

/**
 * The answer, or the problems that stop it: {ok, answer, errors, warnings}. Errors carry an i18n key
 * and its params; warnings do not block (the server does not refuse them either).
 */
export function reviewTableAnswer(ask, draft) {
  const errors = [];
  const warnings = [];
  const headers = ask.headers || {};
  const last = colIndex(ask.last_column);
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
      if (colIndex(letter) <= last) errors.push({ key: 'rt_err_new_left', params: { letter, last: ask.last_column } });
    } else if (!(letter in headers)) {
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
  const scenarios = new Map((ask.scenarios || []).map((s) => [s.name, s]));
  const rows = {};
  for (const line of ask.lines || []) {
    const edit = draft.rows[line.row] || {};
    const final = finalLine(draft, line);
    if (final.class === 'choice' && final.runner === 'agent' && !String(final.preconditions || '').trim()) {
      errors.push({ key: 'rt_err_preconditions', row: line.row, params: { row: line.row } });
    }
    if (final.runner === 'agent' && final.mobile_method === 'device') {
      errors.push({ key: 'rt_err_mobile_agent', row: line.row, params: { row: line.row } });
    }
    const scenarioChecked = 'scenario' in edit || final.runner === 'agent';
    if (scenarioChecked && final.scenario && final.scenario !== 'none' && !scenarios.has(final.scenario)) {
      errors.push({ key: 'rt_err_scenario', row: line.row, params: { row: line.row } });
    }
    if (!screenOk(final.screen || '', ask.hosts)) errors.push({ key: 'rt_err_screen', row: line.row, params: { row: line.row } });
    if (final.runner === 'agent' && !final.screen) warnings.push({ key: 'rt_warn_no_screen', row: line.row, params: { row: line.row } });
    const sc = final.scenario && scenarios.get(final.scenario);
    if (final.runner === 'agent' && sc && !sc.approved) warnings.push({ key: 'rt_warn_unapproved', row: line.row, params: { row: line.row, name: sc.name } });
    const clean = {};
    for (const k of EDIT_KEYS) {
      if (!(k in edit)) continue;
      clean[k] = k === 'scenario' ? (edit[k] || null) : k === 'preconditions' ? String(edit[k] || '') : edit[k];
    }
    // Send what confirmation keeps, so the server never refuses a value the tester cannot see or clear.
    if (final.class === 'not-web' && ('runner' in clean || 'class' in clean)) clean.runner = 'none';
    if (final.viewport !== 'mobile') delete clean.mobile_method;
    if (Object.keys(clean).length) rows[line.row] = clean;
  }
  const columns = draft.columns.map((c) => {
    const out = { field: c.field, letter: String(c.letter || '').trim().toUpperCase() };
    if (c.new) Object.assign(out, { new: true, header: String(c.header || '').trim() });
    return out;
  });
  const answer = { columns, verdict_labels: labels, rows, confirm: true };
  return { ok: errors.length === 0, answer, errors, warnings };
}

/** Apply one bulk change to the selected rows. */
export function bulkEdit(draft, ask, rowIds, key, value) {
  let next = draft;
  for (const line of ask.lines || []) {
    if (!rowIds.has(line.row)) continue;
    // A check method means nothing on a pc row: leave those rows as they are.
    if (key === 'mobile_method' && finalLine(next, line).viewport !== 'mobile') continue;
    next = setEdit(next, line, key, value);
  }
  return next;
}

const drafts = new Map();

export function render(ctx) {
  const { t, route } = ctx;
  const jobId = route.params.job;
  const body = h('div.page.page-wide');
  mount(ctx.view, body);
  ctx.topbar(breadcrumb(t, [{ label: t('nav_jobs'), href: href(['jobs']) }, { label: t('job_kind_webtest_plan'), href: href(['jobs', jobId]) },
    { label: t('rt_crumb') }]), spacer(), badge(t('rt_nothing_runs'), 'warning'));
  mount(body, loading(t, 6));
  let shownAsk = null;

  const load = async () => {
    let job;
    try {
      job = await ctx.memo(`job:${jobId}`, () => ctx.api.job(jobId));
    } catch (err) {
      if (!ctx.alive()) return;
      mount(body, errorState(t, err, () => ctx.refresh()));
      ctx.ready();
      return;
    }
    if (!ctx.alive()) return;
    const ask = job.state === 'needs-input' && job.ask && job.ask.type === 'review-table' ? job.ask : null;
    if (ask && shownAsk === ask.id) return;
    shownAsk = ask ? ask.id : null;
    if (!ask) {
      mount(body, pageHead(t('rt_title_plain'), null), emptyState(t('rt_none'), t('rt_none_body'),
        h('a.k-btn.k-btn--secondary', { href: href(['jobs', jobId]) }, t('rt_back_to_job'))));
      ctx.ready();
      return;
    }
    if (job.can_answer === false) {
      mount(body, pageHead(t('rt_title_plain'), null), tooNewNotice(t),
        h('div.row-8', h('a.k-btn.k-btn--secondary', { href: href(['jobs', jobId]) }, t('rt_back_to_job'))));
      ctx.ready();
      return;
    }
    if (!drafts.has(ask.id)) drafts.set(ask.id, { draft: initialDraft(ask), selected: new Set() });
    drawTable(ctx, body, job, ask, drafts.get(ask.id));
    ctx.ready();
  };
  load();
  ctx.onStoreChange(() => {
    ctx.invalidate(`job:${jobId}`);
    load();
  });
}

function fieldLabel(t, field) {
  return t(`wt_field_${field}`);
}

function selectEl(id, options, value, onChange, label, disabled = false) {
  const el = h('select.k-select.select-sm', { id, 'aria-label': label, disabled: disabled ? 'disabled' : undefined,
    on: { change: (e) => onChange(e.target.value) } },
    options.map(([v, text]) => h('option', { value: v, selected: v === (value ?? '') }, text)));
  return h('span.k-select-wrap', [el, icon('chevron', 'k-icon--sm chevron-down')]);
}

function drawTable(ctx, body, job, ask, state) {
  const { t } = ctx;
  const lang = job.ui_lang;
  const hosts = ask.hosts || [];
  const scenarioOptions = [['', NONE], ['none', t('login_l_none')],
    ...(ask.scenarios || []).map((s) => [s.name, s.approved ? (s.label || s.name) : `${s.label || s.name} · ${t('rt_not_approved')}`])];
  const issuesBox = h('div');
  const colsBox = h('div');
  const labelsBox = h('div');
  const rowsBox = h('div');
  const bulkBox = h('div');
  const confirm = h('button.k-btn.k-btn--primary', { type: 'button', dataset: { confirmTable: '1' } }, t('rt_confirm'));
  const reject = h('button.k-btn.k-btn--ghost', { type: 'button', dataset: { rejectTable: '1' } }, t('rt_reject'));
  const sendError = h('div', { role: 'alert' });
  const update = (draft) => {
    state.draft = draft;
    drawIssues();
  };

  function drawIssues() {
    const result = reviewTableAnswer(ask, state.draft);
    const list = [...result.errors.map((e) => ['danger', e]), ...result.warnings.map((w) => ['warning', w])];
    confirm.disabled = !result.ok;
    mount(issuesBox, list.length ? h('div.k-banner', { class: result.ok ? 'k-banner--warning' : 'k-banner--danger', role: 'status' }, [
      icon('warning', result.ok ? 'icon-warn' : ''),
      h('div.k-banner__text', [h('strong', result.ok ? t('rt_warnings', { n: list.length }) : t('rt_blockers', { n: result.errors.length })),
        h('ul.plain-list.rt-issues', list.slice(0, 12).map(([kind, e]) => h('li', { class: kind === 'danger' ? 'text-danger' : '' }, [
          t(e.key, e.params || {}), e.row ? [' ', h('a', { href: `#rt-${e.row}`, on: { click: (ev) => { ev.preventDefault(); focusRow(e.row); } } }, t('rt_go_row'))] : null]))),
        list.length > 12 ? h('span.k-note', t('rt_more_issues', { n: list.length - 12 })) : null]),
    ]) : null);
  }

  function focusRow(row) {
    const el = rowsBox.querySelector(`[data-rt-row="${row}"]`);
    if (el) { el.scrollIntoView({ block: 'center' }); const first = el.querySelector('input, select, textarea'); if (first) first.focus(); }
  }

  function drawColumns() {
    const grid = sampleGrid(ask, state.draft);
    const samples = ask.samples || [];
    const free = freeFields(state.draft);
    const addSel = h('select.k-select.select-sm', { id: 'rt-add-field', 'aria-label': t('rt_add_col') },
      free.map((f) => h('option', { value: f }, fieldLabel(t, f))));
    const addBtn = h('button.k-btn.k-btn--secondary.k-btn--sm', {
      type: 'button', disabled: free.length ? undefined : 'disabled',
      on: { click: () => { update(addColumn(state.draft, ask, addSel.value)); drawColumns(); } },
    }, [icon('plus'), t('rt_add_col')]);
    const rows = grid.map((c, pos) => h('tr', { dataset: { rtCol: c.letter } }, [
      h('td', c.new
        ? h('input.k-input.k-input--sm.rt-letter', { type: 'text', value: c.letter, maxlength: '3', 'aria-label': t('rt_c_letter'),
          on: { change: (e) => { update(setColumn(state.draft, c.index, { letter: e.target.value.trim().toUpperCase() })); drawColumns(); } } })
        : h('code.k-mono', c.letter)),
      h('td', c.new
        ? h('div.row-4', [h('input.k-input.k-input--sm', { type: 'text', value: c.header, maxlength: '100', 'aria-label': t('rt_c_header'),
          on: { input: (e) => update(setColumn(state.draft, c.index, { header: e.target.value })) } }), badge(t('rt_new'), 'accent')])
        : h('span', c.header || NONE)),
      h('td', selectEl(`rt-field-${c.index}`, [[c.field, fieldLabel(t, c.field)], ...free.map((f) => [f, fieldLabel(t, f)])], c.field,
        (v) => { update(setColumn(state.draft, c.index, { field: v })); drawColumns(); }, t('rt_c_field'))),
      ...samples.map((_, i) => h('td.wrap-cell.rt-sample', c.cells[i] === null ? h('span.k-muted', t('rt_filled_after')) : (c.cells[i] || h('span.k-muted', NONE)))),
      h('td', h('div.row-4', [
        h('button.k-btn.k-btn--icon.k-btn--xs', { type: 'button', 'aria-label': t('rt_up'), disabled: pos === 0 ? 'disabled' : undefined,
          on: { click: () => { update(moveColumn(state.draft, c.index, sortedNeighbour(grid, pos, -1, c.index))); drawColumns(); } } }, icon('up')),
        h('button.k-btn.k-btn--icon.k-btn--xs', { type: 'button', 'aria-label': t('rt_down'), disabled: pos === grid.length - 1 ? 'disabled' : undefined,
          on: { click: () => { update(moveColumn(state.draft, c.index, sortedNeighbour(grid, pos, 1, c.index))); drawColumns(); } } }, icon('down')),
        h('button.k-btn.k-btn--ghost.k-btn--xs', { type: 'button', dataset: { removeCol: c.letter },
          on: { click: () => { update(removeColumn(state.draft, c.index)); drawColumns(); } } }, t('rt_remove')),
      ])),
    ]));
    mount(colsBox, h('section.k-card.stack-12', { 'aria-labelledby': 'rt-cols-title' }, [
      h('div.row-8.wrap', [h('h2.panel-title.flush', { id: 'rt-cols-title' }, t('rt_cols_title')),
        h('span.k-note', `${ask.template || NONE} · ${t('rt_last_header', { letter: ask.last_column })}`),
        h('div.row-4.push-right', [h('span.k-select-wrap', [addSel, icon('chevron', 'k-icon--sm chevron-down')]), addBtn])]),
      h('div.scroll-x', h('table.k-table.tbl-rt-cols', [
        h('thead', h('tr', [h('th', t('rt_c_letter')), h('th', t('rt_c_header')), h('th', t('rt_c_field')),
          ...samples.map((s) => h('th', t('rt_c_sample', { row: s.row, cls: t(`wt_class_${String(s.class).replace(/-/g, '_')}`) }))),
          h('th', t('rt_c_move'))])),
        h('tbody', rows),
      ])),
    ]));
  }

  function drawLabels() {
    const options = ask.verdict_options || [];
    const fields = LABEL_KEYS.map((k) => {
      const id = `rt-label-${k}`;
      const input = h('input.k-input.k-input--sm', { type: 'text', id, maxlength: '50', value: state.draft.labels[k] || '',
        list: options.length ? 'rt-verdict-options' : undefined,
        on: { input: (e) => update({ ...state.draft, labels: { ...state.draft.labels, [k]: e.target.value } }) } });
      return h('div.k-field', [h('label.k-field__label', { for: id }, [t(`rt_lbl_${k.replace(/-/g, '_')}`),
        k === 'pass' || k === 'fail' ? null : [' ', h('span.k-muted', t('runform_optional'))]]), input]);
    });
    mount(labelsBox, h('section.k-card.stack-12', { 'aria-labelledby': 'rt-labels-title' }, [
      h('h2.panel-title.flush', { id: 'rt-labels-title' }, t('rt_labels_title')),
      options.length ? h('datalist', { id: 'rt-verdict-options' }, options.map((o) => h('option', { value: o }))) : null,
      h('div.rt-label-grid', fields),
      options.length ? h('p.k-note', t('rt_lbl_note', { options: options.join(', ') })) : null,
    ]));
  }

  function drawBulk() {
    const n = state.selected.size;
    if (!n) { mount(bulkBox, null); return; }
    const keySel = h('select.k-select.select-sm', { id: 'rt-bulk-key', 'aria-label': t('rt_bulk') }, [
      ['runner:agent', t('rt_bulk_delegate')], ['runner:tester', t('rt_bulk_self')], ['runner:none', t('rt_bulk_manual')],
      ...(ask.scenarios || []).map((s) => [`scenario:${s.name}`, t('rt_bulk_scenario', { name: s.label || s.name })]),
      ['scenario:none', t('rt_bulk_scenario', { name: t('login_l_none') })],
      ...CLASSES.map((c) => [`class:${c}`, t('rt_bulk_class', { cls: t(`wt_class_${c.replace(/-/g, '_')}`) })]),
      ...VIEWPORTS.map((v) => [`viewport:${v}`, t('rt_bulk_viewport', { vp: t(`wt_viewport_${v}`) })]),
      ...MOBILE_METHODS.map((m) => [`mobile_method:${m}`, t('rt_bulk_mobile_method', { method: t(`wt_mobile_${m}`) })]),
    ].map(([v, text]) => h('option', { value: v }, text)));
    mount(bulkBox, h('div.k-toolbar.toolbar-wrap.rt-bulk', [
      h('span.k-note', t('rt_selected', { n })),
      h('span.k-select-wrap', [keySel, icon('chevron', 'k-icon--sm chevron-down')]),
      h('button.k-btn.k-btn--secondary.k-btn--sm', { type: 'button', on: { click: () => {
        const [key, value] = keySel.value.split(':');
        update(bulkEdit(state.draft, ask, state.selected, key, value));
        drawRows();
      } } }, t('rt_apply')),
      h('button.k-btn.k-btn--ghost.k-btn--sm', { type: 'button', on: { click: () => { state.selected.clear(); drawRows(); } } }, t('rt_clear')),
    ]));
  }

  function drawRows() {
    const lines = ask.lines || [];
    const all = h('input', { type: 'checkbox', 'aria-label': t('rt_select_all'), checked: lines.length && state.selected.size === lines.length ? 'checked' : undefined,
      on: { change: (e) => { if (e.target.checked) lines.forEach((l) => state.selected.add(l.row)); else state.selected.clear(); drawRows(); } } });
    const rows = lines.map((line) => {
      const f = finalLine(state.draft, line);
      const set = (key, value, redraw) => { update(setEdit(state.draft, line, key, value)); if (redraw) drawRows(); };
      const pick = h('input', { type: 'checkbox', 'aria-label': t('rt_select', { row: line.row }), checked: state.selected.has(line.row) ? 'checked' : undefined,
        on: { change: (e) => { if (e.target.checked) state.selected.add(line.row); else state.selected.delete(line.row); drawBulk(); } } });
      const screen = h('input.k-input.k-input--sm.k-mono', { type: 'text', value: f.screen || '', placeholder: t('rt_screen_ph'), 'aria-label': t('rt_col_screen'),
        class: screenOk(f.screen || '', hosts) ? '' : 'is-error', on: { change: (e) => set('screen', e.target.value.trim(), true) } });
      const needsPre = f.class === 'choice' && f.runner === 'agent';
      const pre = h('textarea.k-textarea.textarea-sm', { rows: '2', maxlength: '2000', placeholder: t('rt_precond_ph'), 'aria-label': t('rt_col_precond'),
        class: needsPre && !String(f.preconditions || '').trim() ? 'is-error' : '', on: { change: (e) => set('preconditions', e.target.value, true) } });
      pre.value = f.preconditions || '';
      const edited = Boolean(state.draft.rows[line.row]);
      return h('tr', { id: `rt-${line.row}`, class: edited ? 'is-edited' : '', dataset: { rtRow: line.row } }, [
        h('td', pick),
        h('td.wrap-cell.rt-content', [h('span.row-4', [h('span.k-id', line.row), line.no ? h('span.k-note', `#${line.no}`) : null]),
          h('span.block', { lang }, line.content || NONE),
          line.reason ? h('span.k-note.block', { lang }, line.reason) : null]),
        h('td.rt-screen', [screen, line.screen_name ? h('span.k-note.block', { lang }, line.screen_name) : null,
          line.confidence ? h('span.k-note.block', t(`rt_conf_${line.confidence}`)) : null]),
        h('td', selectEl(`rt-class-${line.row}`, CLASSES.map((c) => [c, t(`wt_class_${c.replace(/-/g, '_')}`)]), f.class, (v) => set('class', v, true), t('rt_col_class'))),
        h('td', selectEl(`rt-runner-${line.row}`, RUNNERS.map((r) => [r, t(`wt_runner_${r}`)]), f.runner, (v) => set('runner', v, true), t('rt_col_runner'),
          f.class === 'not-web')),
        h('td', selectEl(`rt-scenario-${line.row}`, scenarioOptions, f.scenario || '', (v) => set('scenario', v || null, true), t('rt_col_scenario'))),
        h('td', h('div.stack-4', [
          selectEl(`rt-viewport-${line.row}`, VIEWPORTS.map((v) => [v, t(`wt_viewport_${v}`)]), f.viewport, (v) => set('viewport', v, true), t('wt_field_viewport')),
          f.mobile_method ? selectEl(`rt-mobile-${line.row}`, MOBILE_METHODS.map((m) => [m, t(`wt_mobile_${m}`)]), f.mobile_method,
            (v) => set('mobile_method', v, true), t('wt_field_mobile_method')) : null,
        ])),
        h('td.rt-pre', [pre, needsPre ? h('span.k-note.block', t('rt_precond_required')) : null]),
      ]);
    });
    mount(rowsBox, h('section.stack-8', { 'aria-labelledby': 'rt-rows-title' }, [
      h('h2.panel-title.flush', { id: 'rt-rows-title' }, t('rt_rows_title', { n: lines.length })),
      bulkBox,
      h('div.k-table-wrap', h('div.scroll-x', h('table.k-table.tbl-rt-rows', [
        h('thead', h('tr', [h('th', all), h('th', t('rt_col_content')), h('th', t('rt_col_screen')), h('th', t('rt_col_class')),
          h('th', t('rt_col_runner')), h('th', t('rt_col_scenario')), h('th', t('wt_field_viewport')), h('th', t('rt_col_precond'))])),
        h('tbody', rows),
      ]))),
    ]));
    drawBulk();
  }

  confirm.addEventListener('click', async () => {
    const result = reviewTableAnswer(ask, state.draft);
    if (!result.ok) { drawIssues(); return; }
    confirm.disabled = true;
    mount(sendError, null);
    try {
      await ctx.api.answer(job.id, ask.id, result.answer);
      drafts.delete(ask.id);
      ctx.toast(t('rt_confirmed'));
      ctx.pollNow();
      ctx.navigate(ask.run ? href(['runs', ask.run]) : href(['jobs', job.id]));
    } catch (err) {
      confirm.disabled = false;
      if (err && err.status === 409) ctx.pollNow();
      mount(sendError, h('p.k-field__error', [icon('warning'), err && err.code === 'bad-request' ? t('job_err_bad_request', { message: err.message || '' }) : jobErrorText(t, err)]));
    }
  });
  reject.addEventListener('click', () => {
    const dlg = openDialog({
      t, title: t('rt_reject_title'), body: h('p', t('rt_reject_body')),
      footer: [
        h('button.k-btn.k-btn--ghost', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')),
        h('button.k-btn.k-btn--danger', { type: 'button', on: { click: async () => {
          dlg.close();
          try {
            await ctx.api.answer(job.id, ask.id, { confirm: false });
            drafts.delete(ask.id);
            ctx.toast(t('rt_rejected'));
            ctx.pollNow();
            ctx.navigate(href(['jobs', job.id]));
          } catch (err) {
            mount(sendError, h('p.k-field__error', [icon('warning'), jobErrorText(t, err)]));
          }
        } } }, t('rt_reject')),
      ],
    });
  });

  mount(body,
    pageHead(t('rt_title', { name: ask.run || NONE }), t('rt_subtitle', { n: (ask.lines || []).length })),
    ask.body ? banner('info', t('rt_agent_note'), ask.body) : null,
    h('section.k-card.row-8.wrap', [h('span.k-section-label', t('rt_hosts')), h('code.k-mono.break', hosts.join(', ') || NONE),
      h('span.k-note', t('rt_hosts_note'))]),
    colsBox, labelsBox, rowsBox,
    h('div.rt-footer.stack-8', [issuesBox, sendError, h('div.row-8', [reject, h('span.push-right'), confirm])]));
  drawColumns();
  drawLabels();
  drawRows();
  drawIssues();
}

/** The step for moveColumn: the draft index distance to the neighbour in sheet order. */
function sortedNeighbour(grid, pos, dir, index) {
  const other = grid[pos + dir];
  return other ? other.index - index : 0;
}
