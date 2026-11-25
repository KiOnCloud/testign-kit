// The Close review asks, answered on the job's own page: approve each decision row (write, skip,
// edit), then confirm the tool's own wiki diff, or paste the pages by hand in manual mode. Agent
// text, quotes and diffs are shown as given.

import { h, icon, mount } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { askBody } from '../markdown.mjs';
import { confirmAnswer, pasteAnswer, reviewAnswer, splitAnchors } from './ask-form.mjs';
import { renderPastePages } from './paste-pages.mjs';
import { badge } from './shell.mjs';

export const REVIEW_TYPES = new Set(['review-rows', 'confirm-diff', 'paste-pages']);
// Choices survive re-renders (language switch, polling) for the same ask.
const drafts = new Map();

function draftFor(jobId, ask) {
  const key = `${jobId}|${ask.id}`;
  if (!drafts.has(key)) drafts.set(key, {});
  return drafts.get(key);
}

export function forgetDraft(jobId, ask) {
  drafts.delete(`${jobId}|${ask.id}`);
}

function steps(t, current) {
  const items = [t('review_step_rows'), t('review_step_diff')];
  const active = current === 'review-rows' ? 0 : 1;
  return h('ol.steps', { 'aria-label': t('review_steps') }, items.map((label, i) =>
    h('li', { class: i === active ? 'is-current' : i < active ? 'is-done' : '', 'aria-current': i === active ? 'step' : undefined }, label)));
}

function footer(buttons, note) {
  return h('div.foot.review-footer', [note ? h('span.k-note', note) : null, h('span.push'), ...buttons]);
}

/** The section that answers a review ask of `job`; `send(answer)` posts it. */
export function closeReview(ctx, job, send) {
  const { t } = ctx;
  const ask = job.ask;
  const title = ask.type === 'review-rows' ? t('review_rows_title') : ask.type === 'confirm-diff' ? t('review_diff_title') : t('paste_heading');
  const sub = ask.type === 'review-rows' ? t('review_rows_sub') : ask.type === 'confirm-diff' ? t('review_diff_sub') : t('paste_sub');
  const head = h('div.stack-8', [h('h2.yh-h2.m-0', title), h('p.k-note', sub), ask.type === 'paste-pages' ? null : steps(t, ask.type)]);
  if (ask.type === 'review-rows') return h('section.stack-16', { dataset: { closeReview: ask.type } }, [head, ...reviewRows(ctx, job, ask, send)]);
  if (ask.type === 'confirm-diff') return h('section.stack-16', { dataset: { closeReview: ask.type } }, [head, ...confirmDiff(ctx, ask, send)]);
  return h('section.stack-16', { dataset: { closeReview: ask.type } }, [head, renderPastePages(ctx, ask), footer([
    h('button.yh-btn.yh-btn--primary', { type: 'button', on: { click: (e) => { e.currentTarget.disabled = true; send(pasteAnswer()); } } }, t('paste_done')),
  ], t('paste_note'))]);
}

function reviewRows(ctx, job, ask, send) {
  const { t } = ctx;
  const choices = draftFor(job.id, ask);
  const tbody = h('tbody');
  const status = h('span.k-note.inline-status', { role: 'status' });
  const submit = h('button.yh-btn.yh-btn--primary', { type: 'button', disabled: true }, t('review_send'));

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
    const decision = h('textarea.yh-textarea', { rows: '3', id: `edit-decision-${row.row}` });
    decision.value = c.decision ?? row.decision ?? '';
    const anchors = h('input.yh-input', { type: 'text', id: `edit-anchors-${row.row}` });
    anchors.value = (c.anchors ?? row.anchors ?? []).join(', ');
    const page = h('input.yh-input', { type: 'text', id: `edit-page-${row.row}` });
    page.value = c.page ?? row.page ?? '';
    decision.addEventListener('input', () => { c.decision = decision.value; update(); });
    anchors.addEventListener('input', () => { c.anchors = splitAnchors(anchors.value); update(); });
    page.addEventListener('input', () => { c.page = page.value; update(); });
    return h('tr.edit-row', { dataset: { editRow: row.row } }, h('td.wrap', { colspan: '6' }, h('div.edit-grid', [
      h('label.yh-field.edit-wide', { for: decision.id }, [h('span.yh-field__label', t('review_th_decision')), decision]),
      h('label.yh-field', { for: anchors.id }, [h('span.yh-field__label', t('review_anchors')), anchors,
        h('span.yh-field__help', t('review_anchors_help'))]),
      h('label.yh-field', { for: page.id }, [h('span.yh-field__label', t('review_th_page')), page]),
    ])));
  }

  function drawRows() {
    const rows = [];
    for (const row of ask.rows || []) {
      const c = choices[row.row] || {};
      const group = h('div.seg', { role: 'radiogroup', 'aria-label': `${t('review_th_review')} ${row.row}` },
        ['write', 'skip', 'edit'].map((action) => h('button.yh-tag', {
          type: 'button', role: 'radio', 'aria-checked': c.action === action ? 'true' : 'false',
          'aria-pressed': c.action === action ? 'true' : 'false', dataset: { row: row.row, action },
          on: {
            click: () => {
              choices[row.row] = action === 'edit' ? { ...(choices[row.row] || {}), action } : { action };
              drawRows();
            },
          },
        }, t(`review_${action}`))));
      rows.push(h('tr', { class: c.action ? '' : 'is-pending', dataset: { reviewRow: row.row } }, [
        h('td.id', row.q || NONE),
        h('td', row.class ? badge(row.class, 'outline') : NONE),
        h('td.wrap', [h('span', row.decision || NONE),
          h('span.sub', [row.row, row.decided_by ? ` · ${row.decided_by}` : '', row.date ? ` · ${row.date}` : ''])]),
        h('td.wrap', [
          row.quote ? h('span.quote', { lang: row.quote_lang || undefined }, row.quote) : h('span.yh-muted', NONE),
          row.source ? h('span.sub', row.source) : null,
        ]),
        h('td.wrap', [h('code.mono', row.page || NONE),
          row.feature ? h('span.sub', row.feature) : null,
          row.anchors && row.anchors.length ? h('span.sub', `${t('review_anchors')}: ${row.anchors.join(', ')}`) : null]),
        h('td', group),
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
    h('div.tbl-box', h('table.yh-table', [
      h('thead', h('tr', [
        h('th', 'Q'), h('th', t('review_th_class')), h('th', t('review_th_decision')), h('th', t('review_th_quote')),
        h('th', t('review_th_page')), h('th', t('review_th_review')),
      ])),
      tbody,
    ])),
    footer([submit], status),
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
      items.length ? h('span.id-list', items.map((x) => h('code.mono', String(x)))) : h('span.yh-muted', t('report_none')),
    ]);
  });
  const pages = (p.pages || []).map((page) => h('section.diff-box', { 'aria-label': page.name }, [
    h('div.diff-head', [
      icon('file', 'k-icon--sm'), h('code.mono.break', page.name),
      page.exists ? null : badge(t('review_new_page'), 'info'),
      h('span.k-badge.k-badge--success', `+${countLines(page.diff, '+')}`),
      countLines(page.diff, '-') ? h('span.k-badge.k-badge--danger', `−${countLines(page.diff, '-')}`) : null,
    ]),
    h('pre.diff', diffLines(page.diff)),
  ]));
  const write = h('button.yh-btn.yh-btn--primary', { type: 'button' }, t('review_write_wiki'));
  const back = h('button.yh-btn.yh-btn--ghost', { type: 'button' }, t('review_decline'));
  write.addEventListener('click', () => { write.disabled = true; back.disabled = true; send(confirmAnswer(true)); });
  back.addEventListener('click', () => { write.disabled = true; back.disabled = true; send(confirmAnswer(false)); });
  return [
    ask.body ? askBody(ask.body) : null,
    h('section.summary-strip', { 'aria-label': t('review_lists') }, lists),
    h('div.stack-12', pages.length ? pages : [h('p.k-note', t('review_no_pages'))]),
    footer([back, write], t('review_diff_note')),
  ];
}
