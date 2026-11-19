// Close review: approve each decision row (write, skip, edit), then confirm the tool's own wiki
// diff, or paste the pages by hand in manual mode. Agent text, quotes and diffs are shown as given.

import { h, icon, mount } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { askBody } from '../markdown.mjs';
import { href } from '../router.mjs';
import { confirmAnswer, pasteAnswer, reviewAnswer, splitAnchors } from './ask-form.mjs';
import { jobErrorText, jobTitle, revOf, shortId } from './job-actions.mjs';
import { renderPastePages } from './paste-pages.mjs';
import { badge, breadcrumb, emptyState, errorState, loading, spacer } from './shell.mjs';

const REVIEW_TYPES = new Set(['review-rows', 'confirm-diff', 'paste-pages']);
// Choices survive re-renders (language switch, polling) for the same ask.
const drafts = new Map();

function draftFor(jobId, ask) {
  const key = `${jobId}|${ask.id}`;
  if (!drafts.has(key)) drafts.set(key, {});
  return drafts.get(key);
}

export function render(ctx) {
  const { t, route } = ctx;
  const id = route.params.job;
  const body = h('div.page');
  mount(ctx.view, body);
  const crumbs = (label) => breadcrumb(t, [
    { label: t('nav_jobs'), href: href(['jobs']) },
    { label: shortId(id), href: href(['jobs', id]) },
    { label: label || t('review_crumb') },
  ]);
  ctx.topbar(crumbs(), spacer());
  mount(body, loading(t, 4));
  let shownKey = null;

  const load = () => ctx.memo(`job:${id}`, () => ctx.api.job(id)).then((job) => {
    if (!ctx.alive()) return;
    const key = `${job.state}|${job.ask ? job.ask.id : '-'}`;
    if (key === shownKey) return;
    shownKey = key;
    draw(ctx, body, job, crumbs);
  }, (err) => {
    if (!ctx.alive()) return;
    shownKey = null;
    mount(body, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
  load();
  ctx.onStoreChange(() => {
    ctx.invalidate(`job:${id}`);
    load();
  });
}

function steps(t, current) {
  const items = [['review-rows', t('review_step_rows')], ['confirm-diff', t('review_step_diff')]];
  const active = current === 'review-rows' ? 0 : 1;
  return h('ol.review-steps', { 'aria-label': t('review_steps') }, items.map(([, label], i) =>
    h('li', { class: i === active ? 'is-active' : '', 'aria-current': i === active ? 'step' : undefined }, label)));
}

function draw(ctx, body, job, crumbs) {
  const { t } = ctx;
  const ask = job.ask;
  ctx.topbar(crumbs(), spacer(), h('span.k-note', [job.ticket, ' · ', t('trace_report_rev', { rev: revOf(job.base_revision) || NONE })]));
  if (job.state !== 'needs-input' || !ask || !REVIEW_TYPES.has(ask.type)) {
    mount(body, emptyState(t('review_nothing_title'), t('review_nothing_body'),
      h('a.k-btn.k-btn--secondary', { href: href(['jobs', job.id]) }, t('review_open_job'))));
    ctx.ready();
    return;
  }
  const send = async (answer) => {
    try {
      await ctx.api.answer(job.id, ask.id, answer);
      drafts.delete(`${job.id}|${ask.id}`);
      ctx.toast(t('ask_sent'));
      ctx.pollNow();
      ctx.navigate(href(['jobs', job.id]));
    } catch (err) {
      ctx.toast(jobErrorText(t, err), 'danger');
      if (err && err.status === 409) ctx.refresh();
    }
  };
  const head = h('section.page-head', [
    h('div.stack-4', [
      h('h1.page-title', ask.type === 'review-rows' ? t('review_rows_title') : ask.type === 'confirm-diff' ? t('review_diff_title') : t('paste_heading')),
      h('p.k-note', [jobTitle(t, job), ' · ', ask.type === 'review-rows' ? t('review_rows_sub') : ask.type === 'confirm-diff' ? t('review_diff_sub') : t('paste_sub')]),
    ]),
    steps(t, ask.type),
  ]);
  if (ask.type === 'review-rows') mount(body, head, ...reviewRows(ctx, job, ask, send));
  else if (ask.type === 'confirm-diff') mount(body, head, ...confirmDiff(ctx, ask, send));
  else mount(body, head, renderPastePages(ctx, ask), footer(t, [
    h('a.k-btn.k-btn--ghost', { href: href(['jobs', job.id]) }, t('review_back_to_job')),
    h('button.k-btn.k-btn--primary', { type: 'button', on: { click: (e) => { e.currentTarget.disabled = true; send(pasteAnswer()); } } }, t('paste_done')),
  ], t('paste_note')));
  ctx.ready();
}

function footer(t, buttons, note) {
  return h('div.review-footer', [note ? h('span.k-note.push-right-auto', note) : null, ...buttons]);
}

function reviewRows(ctx, job, ask, send) {
  const { t } = ctx;
  const choices = draftFor(job.id, ask);
  const tbody = h('tbody');
  const status = h('span.k-note.inline-status.push-right-auto', { role: 'status' });
  const submit = h('button.k-btn.k-btn--primary', { type: 'button', disabled: true }, t('review_send'));

  function update() {
    const result = reviewAnswer(ask, choices);
    submit.disabled = !result.ok;
    if (result.ok) {
      mount(status, icon('check', 'k-icon--sm'), t('review_ready'));
    } else {
      const parts = [];
      if (result.missing.length) parts.push(t('review_left', { n: result.missing.length }));
      if (result.badEdits.length) parts.push(t('review_bad_edits', { rows: result.badEdits.join(', ') }));
      mount(status, icon('info', 'k-icon--sm'), parts.join(' · '));
    }
    return result;
  }

  function editRow(row) {
    const c = choices[row.row];
    const decision = h('textarea.k-textarea', { rows: '3', id: `edit-decision-${row.row}` });
    decision.value = c.decision ?? row.decision ?? '';
    const anchors = h('input.k-input', { type: 'text', id: `edit-anchors-${row.row}` });
    anchors.value = (c.anchors ?? row.anchors ?? []).join(', ');
    const page = h('input.k-input', { type: 'text', id: `edit-page-${row.row}` });
    page.value = c.page ?? row.page ?? '';
    decision.addEventListener('input', () => { c.decision = decision.value; update(); });
    anchors.addEventListener('input', () => { c.anchors = splitAnchors(anchors.value); update(); });
    page.addEventListener('input', () => { c.page = page.value; update(); });
    return h('tr.edit-row', { dataset: { editRow: row.row } }, h('td', { colspan: '6' }, h('div.edit-grid', [
      h('label.k-field.edit-wide', { for: decision.id }, [h('span.k-field__label', t('review_th_decision')), decision]),
      h('label.k-field', { for: anchors.id }, [h('span.k-field__label', t('review_anchors')), anchors,
        h('span.k-field__help', t('review_anchors_help'))]),
      h('label.k-field', { for: page.id }, [h('span.k-field__label', t('review_th_page')), page]),
    ])));
  }

  function drawRows() {
    const rows = [];
    for (const row of ask.rows || []) {
      const c = choices[row.row] || {};
      const group = h('div.k-tabs.k-tabs--segmented', { role: 'radiogroup', 'aria-label': `${t('review_th_review')} ${row.row}` },
        ['write', 'skip', 'edit'].map((action) => h('button.k-tab', {
          type: 'button', role: 'radio', 'aria-checked': c.action === action ? 'true' : 'false',
          class: c.action === action ? 'is-active' : '', dataset: { row: row.row, action },
          on: {
            click: () => {
              choices[row.row] = action === 'edit' ? { ...(choices[row.row] || {}), action } : { action };
              drawRows();
              if (action === 'edit') {
                const el = tbody.querySelector(`#edit-decision-${CSS.escape(row.row)}`);
                if (el) el.focus();
              } else {
                const el = tbody.querySelector(`[data-row="${CSS.escape(row.row)}"][data-action="${action}"]`);
                if (el) el.focus();
              }
            },
          },
        }, t(`review_${action}`))));
      rows.push(h('tr', { class: c.action ? '' : 'is-pending', dataset: { reviewRow: row.row } }, [
        h('td.k-id.top', row.q || NONE),
        h('td.top', row.class ? badge(row.class, 'outline') : NONE),
        h('td.top.wrap-cell', [h('span.text-1', row.decision || NONE),
          h('span.k-note.block', [row.row, row.decided_by ? ` · ${row.decided_by}` : '', row.date ? ` · ${row.date}` : ''])]),
        h('td.top.wrap-cell', [
          row.quote ? h('span.quote', { lang: row.quote_lang || undefined }, row.quote) : h('span.k-muted', NONE),
          row.source ? h('span.k-note.block', row.source) : null,
        ]),
        h('td.top.wrap-cell', [h('code.k-mono.block', row.page || NONE),
          row.feature ? h('span.k-note.block', row.feature) : null,
          row.anchors && row.anchors.length ? h('span.k-note.block', `${t('review_anchors')}: ${row.anchors.join(', ')}`) : null]),
        h('td.top', group),
      ]));
      if (c.action === 'edit') rows.push(editRow(row));
    }
    mount(tbody, rows);
    update();
  }

  submit.addEventListener('click', () => {
    const result = update();
    if (!result.ok) return;
    submit.disabled = true;
    send(result.answer);
  });
  drawRows();
  return [
    ask.body ? askBody(ask.body) : null,
    h('div.k-table-wrap', h('div.scroll-x', h('table.k-table.review-table', [
      h('thead', h('tr', [
        h('th.col-q', 'Q'), h('th', t('review_th_class')), h('th', t('review_th_decision')), h('th', t('review_th_quote')),
        h('th', t('review_th_page')), h('th', t('review_th_review')),
      ])),
      tbody,
    ]))),
    h('div.review-footer', [status,
      h('a.k-btn.k-btn--ghost', { href: href(['jobs', job.id]) }, t('review_back_to_job')), submit]),
  ];
}

function diffLines(text) {
  const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
  if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop();
  return lines.map((line) => {
    let cls = '';
    if (line.startsWith('+++') || line.startsWith('---')) cls = 'diff-file';
    else if (line.startsWith('@@')) cls = 'diff-hunk';
    else if (line.startsWith('+')) cls = 'diff-add';
    else if (line.startsWith('-')) cls = 'diff-del';
    return h('span.diff-line', { class: cls }, line || ' ');
  });
}

function countLines(diff, sign) {
  return String(diff).split('\n').filter((l) => l.startsWith(sign) && !l.startsWith(sign.repeat(3))).length;
}

function confirmDiff(ctx, ask, send) {
  const { t } = ctx;
  const p = ask.preview || {};
  const lists = ['added', 'skipped', 'superseded', 'index_repaired'].map((key) => {
    const items = Array.isArray(p[key]) ? p[key] : [];
    return h('div.summary-cell', [
      h('span.k-section-label', `${t(`review_list_${key}`)} · ${items.length}`),
      items.length ? h('span.id-list', items.map((x) => h('code.k-mono', String(x)))) : h('span.k-muted', t('report_none')),
    ]);
  });
  const pages = (p.pages || []).map((page) => h('section.diff-box', { 'aria-label': page.name }, [
    h('div.diff-head', [
      icon('file', 'k-icon--sm'), h('code.k-mono.text-1.break', page.name),
      page.exists ? null : badge(t('review_new_page'), 'info'),
      h('span.k-badge.k-badge--success', `+${countLines(page.diff, '+')}`),
      countLines(page.diff, '-') ? h('span.k-badge.k-badge--danger', `−${countLines(page.diff, '-')}`) : null,
    ]),
    h('pre.diff', diffLines(page.diff)),
  ]));
  const write = h('button.k-btn.k-btn--primary', { type: 'button' }, t('review_write_wiki'));
  const back = h('button.k-btn.k-btn--ghost', { type: 'button' }, t('review_decline'));
  write.addEventListener('click', () => { write.disabled = true; back.disabled = true; send(confirmAnswer(true)); });
  back.addEventListener('click', () => { write.disabled = true; back.disabled = true; send(confirmAnswer(false)); });
  return [
    ask.body ? askBody(ask.body) : null,
    h('section.summary-strip', { 'aria-label': t('review_lists') }, lists),
    h('div.stack-12', pages.length ? pages : [h('p.k-note', t('review_no_pages'))]),
    footer(t, [back, write], t('review_diff_note')),
  ];
}
