// Templates: registered Excel templates with their sheet layout and column roles; register a new
// one (upload, check the detected layout, adjust, name), set the default, remove one.

import { ApiError, UPLOAD_CAP } from '../api.mjs';
import { h, icon, mount, statusIcon } from '../dom.mjs';
import { isoDate, NONE } from '../format.mjs';
import {
  badge, breadcrumb, emptyState, errorState, errorText, loading, openDialog, pageHead, pushEscape, tableBox, ybadge,
} from './shell.mjs';

export const ROLES = ['no', 'item', 'steps', 'expected', 'evidence', 'trace'];
export const PURPOSES = ['testcase', 'webtest'];
/** Roles a purpose needs: a test case template needs the trace column, a web test one only the item. */
export function requiredRoles(purpose) {
  return purpose === 'webtest' ? new Set(['item']) : new Set(['item', 'trace']);
}
const EXTENSIONS = ['.xlsx', '.xlsm'];

let selectedName = null;

const UPLOAD_ERRORS = {
  'bad-filename': 'tpl_err_filename',
  'bad-extension': 'tpl_err_extension',
  'not-a-workbook': 'tpl_err_workbook',
  'too-large': 'tpl_err_too_large',
  'too-large-unzipped': 'tpl_err_too_large',
  'zip-ratio': 'tpl_err_workbook',
  'unsupported-media-type': 'tpl_err_workbook',
  'name-taken': 'tpl_err_name_taken',
  'file-clash': 'tpl_err_file_clash',
  'template-error': 'tpl_err_template',
  'not-found': 'tpl_err_expired',
};

function templateError(t, err) {
  if (err && err.code === 'mapping-failed') {
    const missing = err.details && Array.isArray(err.details.missing) ? err.details.missing : [];
    return t('tpl_err_mapping', { roles: missing.join(', ') || NONE });
  }
  const key = err && UPLOAD_ERRORS[err.code];
  return key ? t(key) : errorText(t, err);
}

function roleLabel(t, role) {
  return t(`tpl_role_${role}`);
}

/** The sheet grid: column letters, rows from the header row, the role row under the header. */
export function grid(t, preview, roles, { upload = false, purpose = 'testcase' } = {}) {
  const required = requiredRoles(purpose);
  const letters = preview.letters || [];
  const byLetter = {};
  for (const [role, letter] of Object.entries(roles || {})) if (letter) byLetter[letter] = role;
  const rows = [];
  for (const r of preview.rows || []) {
    rows.push(h('tr', { class: r.header ? 'is-header' : '' }, [
      h('th.grid-rownum', { scope: 'row' }, String(r.row)),
      ...letters.map((_, i) => h('td', (r.cells || [])[i] ?? '')),
    ]));
    if (r.header) {
      rows.push(h('tr.grid-roles', [
        h('th.grid-rownum', { scope: 'row' }, h('span.sr-only', t('tpl_roles'))),
        ...letters.map((letter) => {
          const role = byLetter[letter];
          return h('td', role ? [badge(role, 'outline'), required.has(role) ? h('span.req-mark', { 'aria-label': t('tpl_required') }, '*') : null] : null);
        }),
      ]));
    }
  }
  const extras = [];
  if (preview.complete === false) {
    extras.push(h('p.k-note', { dataset: { partialPreview: '1' } }, upload ? t('tpl_partial_upload') : t('tpl_partial_large')));
  } else if (preview.merged && preview.merged.length) {
    extras.push(h('p.k-note', [t('tpl_merged'), ' ', h('code.k-mono', preview.merged.join(', '))]));
  }
  if (preview.complete !== false && preview.dropdowns && preview.dropdowns.length) {
    extras.push(h('div.stack-4', [h('span.k-note', t('tpl_dropdowns')), h('ul.plain-list', preview.dropdowns.map((d) =>
      h('li', [h('code.k-mono', d.range), ' → ', h('code.k-mono', d.formula || '')])))]));
  }
  if (preview.size) {
    extras.push(h('p.k-note.num', t('tpl_size', { rows: preview.size.rows, cols: preview.size.cols })));
  }
  return h('div.stack-8', [
    h('div.grid-box', h('table.grid-table', [
      h('thead', h('tr', [h('th.grid-rownum'), ...letters.map((l) => h('th', { scope: 'col' }, l))])),
      h('tbody', rows),
    ])),
    ...extras,
  ]);
}

export function render(ctx) {
  const { t } = ctx;
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_config') }, { label: t('nav_templates') }]));
  const registerBtn = h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { register: '1' }, on: { click: () => openRegister(ctx) } },
    [icon('plus'), t('tpl_register')]);
  const head = pageHead(t('tpl_title'), t('tpl_subtitle'), [registerBtn],
    [h('span.yh-caption.yh-muted.break', [t('tpl_stored_in'), ' ', h('code.mono', '~/.testign-kit/templates/')])]);
  mount(ctx.view, head, loading(t, 3));

  ctx.memo('templates', () => ctx.api.templates()).then((data) => {
    if (!ctx.alive()) return;
    ctx.setCount('templates', data.templates.length);
    draw(ctx, head, data);
  }, (err) => {
    if (!ctx.alive()) return;
    mount(ctx.view, head, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
}

function draw(ctx, head, data) {
  const { t } = ctx;
  const list = data.templates || [];
  if (!list.length) {
    mount(ctx.view, head, emptyState(t('tpl_empty_title'), t('tpl_empty_body')));
    ctx.ready();
    return;
  }
  if (!list.some((x) => x.name === selectedName)) selectedName = data.default || list[0].name;
  const tableHolder = h('div');
  const detail = h('div');
  let popEscape = null;

  function drawList() {
    const rows = list.map((x) => {
      const cols = Object.keys(x.columns || {}).length;
      return h('tr.click', {
        tabindex: '0', 'aria-selected': x.name === selectedName ? 'true' : 'false',
        class: x.name === selectedName ? 'is-sel' : '', dataset: { template: x.name },
        on: {
          click: () => pick(x.name),
          keydown: (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) { e.preventDefault(); pick(x.name); } },
        },
      }, [
        h('td', [h('strong', x.name), h('span.sub', x.source_name || x.file || NONE)]),
        h('td', ybadge(t(`tpl_purpose_${x.purpose || 'testcase'}`), x.purpose === 'webtest' ? '' : 'outline')),
        h('td', [h('span', x.sheet || NONE), h('span.sub', `${t('tpl_header_row', { n: x.header_row ?? NONE })} · ${t('tpl_columns', { n: cols })}`)]),
        h('td', x.default ? statusIcon('ok', 'check', t('templates_default')) : h('span.yh-muted', NONE)),
        h('td.yh-num.yh-muted', isoDate(x.registered_at)),
      ]);
    });
    mount(tableHolder, tableBox([h('th', t('tpl_col_name')), h('th', t('tpl_purpose')), h('th', t('tpl_col_sheet')),
      h('th', t('templates_default')), h('th', t('tpl_registered'))], rows));
  }

  function pick(name) {
    selectedName = selectedName === name ? null : name;
    drawAll();
  }

  function drawDetail() {
    const x = list.find((y) => y.name === selectedName);
    if (!x) { mount(detail); return; }
    const previewBox = h('div.yh-stack', loading(t, 3));
    mount(detail, h('section.panel.sticky', { 'aria-labelledby': 'tpl-panel-title', dataset: { templatePanel: x.name } }, [
      h('div.panel-head', [
        h('h2.yh-h3.m-0', { id: 'tpl-panel-title' }, x.name),
        h('button.yh-tool', { type: 'button', 'aria-label': t('close'), on: { click: () => pick(x.name) } }, icon('close')),
      ]),
      h('dl.kv', [
        h('dt', t('tpl_purpose')), h('dd', t(`tpl_purpose_${x.purpose || 'testcase'}`)),
        h('dt', t('tpl_source')), h('dd.break', x.source_name || NONE),
        h('dt', t('tpl_stored')), h('dd.mono.break', x.file || NONE),
        h('dt', t('tpl_sheet')), h('dd', x.sheet || NONE),
        h('dt', t('tpl_header')), h('dd', t('tpl_header_row', { n: x.header_row ?? NONE })),
        h('dt', t('tpl_registered')), h('dd.yh-num', isoDate(x.registered_at)),
        h('dt', t('tpl_roles')), h('dd.break', ROLES.filter((r) => (x.columns || {})[r]).map((r) => `${r} ${x.columns[r]}`).join(' · ') || NONE),
      ]),
      h('h3.yh-h3.m-0', t('tpl_layout')), previewBox, h('p.yh-caption.yh-muted.m-0', t('tpl_legend')),
      h('div.foot', [
        h('button.yh-btn.yh-btn--ghost.yh-btn--destructive.yh-btn--sm', { type: 'button', on: { click: () => confirmRemove(ctx, x.name) } },
          [icon('trash'), t('tpl_remove')]),
        h('span.push'),
        h('button.yh-btn.yh-btn--sm', { type: 'button', disabled: Boolean(x.default), on: { click: () => setDefault(ctx, x.name) } }, t('tpl_set_default')),
      ]),
    ]));
    ctx.memo(`preview:${x.name}`, () => ctx.api.templatePreview(x.name)).then((p) => {
      if (ctx.alive() && selectedName === x.name) mount(previewBox, h('div.tbl-scroll', grid(t, p, x.columns, { purpose: x.purpose })));
    }, (err) => {
      if (ctx.alive() && selectedName === x.name) mount(previewBox, errorState(t, err));
    });
  }

  function drawAll() {
    if (popEscape) { popEscape(); popEscape = null; }
    const selected = list.some((x) => x.name === selectedName);
    if (selected) popEscape = pushEscape(() => pick(selectedName));
    mount(ctx.view, head, h('div.split', { class: selected ? '' : 'split--single' }, [tableHolder, selected ? detail : null]),
      h('p.yh-caption.yh-muted.m-0', t('tpl_note')));
    drawList();
    drawDetail();
  }

  drawAll();
  ctx.ready();
}

function afterChange(ctx, data, message) {
  ctx.invalidate('templates');
  ctx.invalidate('count:templates');
  if (data && Array.isArray(data.templates)) ctx.setCount('templates', data.templates.length);
  ctx.toast(message);
  ctx.refresh();
}

function setDefault(ctx, name) {
  ctx.api.setDefault(name).then(
    (data) => afterChange(ctx, data, ctx.t('tpl_default_done', { name })),
    (err) => ctx.toast(templateError(ctx.t, err), 'danger'),
  );
}

function confirmRemove(ctx, name) {
  const { t } = ctx;
  let dlg = null;
  const removeBtn = h('button.yh-btn.yh-btn--destructive', {
    type: 'button',
    on: {
      click: () => {
        removeBtn.disabled = true;
        ctx.api.remove(name).then((data) => {
          dlg.close();
          if (selectedName === name) selectedName = null;
          afterChange(ctx, data, t('tpl_removed', { name }));
        }, (err) => {
          removeBtn.disabled = false;
          dlg.setBody(h('p', t('tpl_remove_body', { name })), h('p.k-field__error', [icon('warning'), templateError(t, err)]));
        });
      },
    },
  }, t('tpl_remove'));
  const cancelBtn = h('button.yh-btn', { type: 'button', on: { click: () => dlg.close() } }, t('cancel'));
  dlg = openDialog({
    t, title: t('tpl_remove_title', { name }),
    body: h('p', t('tpl_remove_body', { name })),
    footer: [cancelBtn, removeBtn],
    initialFocus: () => cancelBtn,
  });
}

/** The client-side checks before an upload: extension and size. Returns an i18n key or null. */
export function checkFile(file) {
  if (!file) return 'tpl_err_pick';
  const lower = String(file.name || '').toLowerCase();
  if (!EXTENSIONS.some((ext) => lower.endsWith(ext))) return 'tpl_err_extension';
  if (file.size > UPLOAD_CAP) return 'tpl_err_too_large';
  if (file.size === 0) return 'tpl_err_workbook';
  return null;
}

function stem(name) {
  return String(name || '').replace(/\.(xlsx|xlsm)$/i, '').trim().slice(0, 100);
}

function openRegister(ctx) {
  const { t } = ctx;
  const s = { upload: null, map: {}, sheet: null, headerRow: null, busy: false, error: null, purpose: 'testcase' };
  const errorBox = h('div', { role: 'alert' });
  const fileInput = h('input.k-input.file-input', { type: 'file', accept: EXTENSIONS.join(','), id: 'tpl-file' });
  const nameInput = h('input.k-input', { type: 'text', id: 'tpl-name', maxlength: '100', autocomplete: 'off' });
  const makeDefault = h('input', { type: 'checkbox' });
  const replace = h('input', { type: 'checkbox' });
  const layoutBox = h('div.stack-16');
  const registerBtn = h('button.yh-btn.yh-btn--primary', { type: 'button', disabled: true, on: { click: submit } }, t('tpl_register_submit'));
  const cancelBtn = h('button.yh-btn', { type: 'button', on: { click: () => dlg.close() } }, t('cancel'));

  function showError(message) {
    mount(errorBox, message ? h('p.k-field__error', [icon('warning'), message]) : null);
  }

  function setBusy(busy) {
    s.busy = busy;
    registerBtn.disabled = busy || !s.upload;
    fileInput.disabled = busy;
  }

  function apply(resp) {
    s.upload = resp;
    s.sheet = resp.layout.sheet;
    s.headerRow = resp.layout.header_row;
    s.map = { ...(resp.layout.columns || {}) };
    if (!nameInput.value) nameInput.value = stem(resp.name);
    drawLayout();
    setBusy(false);
  }

  async function adjust(body) {
    setBusy(true);
    showError(null);
    try {
      apply(await ctx.api.uploadPreview(s.upload.upload, body));
    } catch (err) {
      setBusy(false);
      showError(templateError(t, err));
    }
  }

  function drawLayout() {
    const resp = s.upload;
    if (!resp) { mount(layoutBox); return; }
    const preview = resp.preview || {};
    const letters = preview.letters || [];
    const headers = Object.fromEntries((preview.columns || []).map((c) => [c.letter, c.header]));
    const sheetSelect = h('select.k-select', {
      id: 'tpl-sheet', on: { change: (e) => adjust({ sheet: e.target.value }) },
    }, (resp.sheets || []).map((name) => h('option', { value: name, selected: name === s.sheet }, name)));
    const rowInput = h('input.k-input.row-input', { type: 'number', min: '1', step: '1', id: 'tpl-row', value: s.headerRow ? String(s.headerRow) : '' });
    const applyBtn = h('button.yh-btn', {
      type: 'button',
      on: {
        click: () => {
          const n = Number(rowInput.value);
          if (!Number.isInteger(n) || n < 1) { showError(t('tpl_err_row')); return; }
          adjust({ sheet: s.sheet, header_row: n });
        },
      },
    }, t('tpl_apply'));
    const roleFields = ROLES.map((role) => {
      const select = h('select.k-select', {
        id: `tpl-role-${role}`,
        on: { change: (e) => { if (e.target.value) s.map[role] = e.target.value; else delete s.map[role]; drawGrid(); } },
      }, [h('option', { value: '' }, t('tpl_role_none')), ...letters.map((l) => h('option', {
        value: l, selected: s.map[role] === l,
      }, headers[l] ? `${l} · ${headers[l]}` : l))]);
      return h('label.k-field.role-field', [
        h('span.k-field__label', [roleLabel(t, role), requiredRoles(s.purpose).has(role) ? h('span.k-req', { 'aria-label': t('tpl_required') }, '*') : null]),
        h('span.k-select-wrap', [select, icon('chevron', 'k-icon--sm chevron-down')]),
      ]);
    });
    const gridBox = h('div');
    function drawGrid() { mount(gridBox, grid(t, preview, s.map, { upload: true, purpose: s.purpose })); }
    const purposeBox = h('fieldset.stack-4.plain-fieldset', [h('legend.k-field__label', t('tpl_purpose')),
      h('div.row-16', PURPOSES.map((p) => {
        const input = h('input', { type: 'radio', name: 'tpl-purpose', id: `tpl-purpose-${p}`, value: p, checked: s.purpose === p,
          on: { change: () => { s.purpose = p; drawLayout(); } } });
        return h('label.k-radio', { for: input.id }, [input, h('span.k-radio__dot'), h('span', t(`tpl_purpose_${p}`))]);
      })),
      h('span.k-field__help', t(`tpl_purpose_${s.purpose}_help`))]);
    mount(layoutBox,
      h('p.k-note', [t('tpl_uploaded'), ' ', h('code.k-mono', resp.name)]),
      purposeBox,
      h('div.form-row', [
        h('label.k-field', [h('span.k-field__label', t('tpl_sheet')), h('span.k-select-wrap', [sheetSelect, icon('chevron', 'k-icon--sm chevron-down')])]),
        h('div.k-field', [h('label.k-field__label', { for: 'tpl-row' }, t('tpl_header')), h('div.row-8.nowrap', [rowInput, applyBtn])]),
      ]),
      gridBox,
      h('fieldset.role-grid', [h('legend.k-field__label', t('tpl_roles')), ...roleFields]),
      h('span.k-field__help', t('tpl_roles_help')),
      h('label.k-field', [h('span.k-field__label', [t('tpl_name'), h('span.k-req', '*')]), nameInput]),
      h('label.k-check', [makeDefault, h('span.k-check__box', icon('check')), t('tpl_make_default')]),
      h('label.k-check', [replace, h('span.k-check__box', icon('check')), t('tpl_replace')]),
    );
    drawGrid();
  }

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files && fileInput.files[0];
    const problem = checkFile(file);
    if (problem) { showError(t(problem)); return; }
    setBusy(true);
    showError(null);
    try {
      s.upload = null;
      nameInput.value = '';
      apply(await ctx.api.upload(file));
    } catch (err) {
      setBusy(false);
      showError(templateError(t, err instanceof ApiError ? err : new ApiError(0, 'network', '')));
    }
  });

  async function submit() {
    if (!s.upload || s.busy) return;
    const name = nameInput.value.trim();
    if (!name) { showError(t('tpl_err_name')); nameInput.focus(); return; }
    const missing = [...requiredRoles(s.purpose)].filter((r) => !s.map[r]);
    if (missing.length) { showError(t('tpl_err_mapping', { roles: missing.join(', ') })); return; }
    setBusy(true);
    showError(null);
    try {
      const data = await ctx.api.register({
        upload: s.upload.upload, name, sheet: s.sheet || undefined, header_row: s.headerRow || undefined,
        map: s.map, make_default: makeDefault.checked, replace: replace.checked, purpose: s.purpose,
      });
      selectedName = data.template && data.template.name ? data.template.name : name;
      dlg.close();
      afterChange(ctx, data, t('tpl_registered_done', { name }));
    } catch (err) {
      setBusy(false);
      showError(templateError(t, err));
    }
  }

  const dlg = openDialog({
    t, title: t('tpl_register_title'), wide: true,
    body: h('div.stack-16', [
      h('div.k-field', [
        h('label.k-field__label', { for: 'tpl-file' }, t('tpl_file')),
        fileInput,
        h('span.k-field__help', t('tpl_file_help')),
      ]),
      layoutBox,
      errorBox,
    ]),
    footer: [cancelBtn, registerBtn],
  });
}
