// Defects: every failed row's defect across the runs, with its status (draft, sent with the tracker
// key, not a defect). A row opens on its run, where the defect form sits in the row panel. Also the
// pieces the Run screen uses: the status badge, the form checks and the text the tester copies into a
// tracker.

import { h, mount } from '../dom.mjs';
import { NONE, timeOrDay } from '../format.mjs';
import { href } from '../router.mjs';
import {
  alertBox, breadcrumb, emptyState, errorState, loading, pageHead, rowLink, searchBox, segFilter, tableBox, ybadge,
} from './shell.mjs';

export const STATUSES = ['draft', 'sent', 'not-a-defect'];
const FILTERS = ['all', ...STATUSES];

/** The badge of a defect status. */
export function defectBadge(t, status) {
  const kind = status === 'sent' ? 'success' : status === 'not-a-defect' ? 'outline' : 'neutral';
  return ybadge(t(`defect_status_${String(status || 'draft').replace(/-/g, '_')}`), kind, { dataset: { defectStatus: status } });
}

/** The defects a status filter and a search show. */
export function filterDefects(list, filter, search) {
  const words = String(search || '').toLowerCase().split(/\s+/).filter(Boolean);
  return (list || []).filter((d) => {
    if (filter && filter !== 'all' && d.status !== filter) return false;
    if (!words.length) return true;
    const hay = [d.title, d.content, d.tracker, d.run, d.run_name, d.row, d.project].filter(Boolean).join(' ').toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** An i18n key for what the defect form still needs, or null when it can be saved. */
export function checkDefect(body) {
  if (!body || !String(body.title || '').trim()) return 'defect_err_title';
  if (body.status === 'sent' && !String(body.tracker || '').trim()) return 'defect_err_tracker';
  if (body.status === 'not-a-defect' && !String(body.reason || '').trim()) return 'defect_err_reason';
  return null;
}

/** The defect as plain text for a tracker: title, then labelled sections that have content. */
export function defectText(t, d, run) {
  const parts = [String(d.title || '').trim()];
  const add = (label, text) => { if (text && String(text).trim()) parts.push('', `${label}:`, String(text).trim()); };
  add(t('defect_env'), [run && run.base_url, d.url].filter(Boolean).join('\n'));
  add(t('run_steps'), d.steps);
  add(t('run_expected'), d.expected);
  add(t('run_actual'), d.actual);
  add(t('run_cap_evidence'), (d.evidence || []).join('\n'));
  add(t('defect_source'), run ? `${run.name || run.id} · ${d.row || ''}`.trim() : '');
  return parts.join('\n');
}

let filter = 'draft';
let search = '';

export function render(ctx) {
  const { t } = ctx;
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_run') }, { label: t('nav_defects') }]));
  const head = pageHead(t('defects_title'), t('defects_subtitle'), []);
  mount(ctx.view, head, loading(t, 4));
  let lastKey = null;
  const holder = h('div');

  const load = () => ctx.memo('defects', () => ctx.api.defects()).then((data) => {
    if (!ctx.alive()) return;
    const key = JSON.stringify(data);
    if (key === lastKey) return;
    lastKey = key;
    ctx.setCount('defects', (data.counts || {}).draft || 0);
    draw(data);
    ctx.ready();
  }, (err) => {
    if (!ctx.alive()) return;
    lastKey = null;
    mount(ctx.view, head, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });

  function draw(data) {
    const list = data.defects || [];
    if (!list.length) {
      mount(ctx.view, head, emptyState(t('defects_empty'), t('defects_empty_body')));
      return;
    }
    const counts = { all: list.length, ...(data.counts || {}) };
    const toolbar = h('div.toolbar', [
      searchBox(t('defects_search'), search, (v) => { search = v; drawTable(list); }),
      segFilter(t('defects_filter'), FILTERS.map((f) => ({
        value: f, label: `${f === 'all' ? t('run_all') : t(`defect_status_${f.replace(/-/g, '_')}`)} ${counts[f] || 0}`,
      })), filter, (v) => { filter = v; draw(data); }),
    ]);
    mount(ctx.view, head, toolbar, holder, h('p.yh-caption.yh-muted.m-0', t('defects_note')));
    drawTable(list);
  }

  function drawTable(list) {
    const shown = filterDefects(list, filter, search);
    mount(holder, shown.length ? tableBox([
      h('th', t('defect_col_title')), h('th', t('col_run')), h('th', t('defect_col_status')), h('th', t('defect_tracker')),
      h('th', t('col_when')),
    ], shown.map((d) => {
      const target = href(['runs', d.run], { row: d.row });
      return h('tr.click', { dataset: { defect: `${d.run}:${d.row}` }, on: rowLink(target, ctx.navigate) }, [
        h('td', [h('a.lnk', { href: target }, d.title || d.content || d.row),
          d.stale ? h('span.sub', t('defect_stale')) : null]),
        h('td', [h('span', d.run_name || d.run), h('span.sub.mono', `${d.row} · ${d.project || NONE}`)]),
        h('td', defectBadge(t, d.status)),
        h('td.mono', d.tracker || h('span.yh-muted', NONE)),
        h('td.yh-num.yh-muted', d.at ? timeOrDay(d.at) : NONE),
      ]);
    })) : alertBox('', 'info', t('defects_no_match'), null));
  }

  load();
  ctx.onStoreChange(() => {
    ctx.invalidate('defects');
    load();
  });
}
