// Tickets: every report folder under output_dir with its latest revision, question count,
// test case summary and hash state (fetched per row after the first paint).

import { h, icon, mount } from '../dom.mjs';
import { isoDate, NONE } from '../format.mjs';
import { href } from '../router.mjs';
import {
  badge, banner, conclusionBadge, emptyState, errorState, hashInline, loading, pageHead, spacer, topbarTitle,
} from './shell.mjs';

const HASH_PARALLEL = 2;
const FILTERS = ['all', 'open', 'needs-qa', 'clear', 'unknown', 'error'];

function questionsCell(t, tk) {
  if (!Number.isFinite(tk.questions)) return h('td.k-muted', NONE);
  return h('td.num', [
    String(tk.questions),
    ' ',
    h('span', { class: tk.block_count ? 'text-danger' : 'k-muted' }, `· ${t('tickets_blocks', { n: tk.block_count || 0 })}`),
  ]);
}

function casesCell(t, tk) {
  const cov = tk.coverage;
  if (cov && Number.isFinite(cov.total_cases)) {
    const issues = [];
    if (cov.gaps && cov.gaps.length) issues.push(t('tickets_gaps', { n: cov.gaps.length }));
    if (cov.orphans && cov.orphans !== '' && !/^(không có|none|なし)$/i.test(cov.orphans)) issues.push(t('tickets_orphans_some'));
    return h('td', [
      h('a.text-1', { href: href(['tickets', tk.id, 'trace']) }, t('tickets_cases', { n: cov.total_cases })),
      issues.length ? h('span.text-danger', ` · ${issues.join(' · ')}`) : null,
    ]);
  }
  if (tk.workbooks && tk.workbooks.length) {
    return h('td', h('a', { href: href(['tickets', tk.id, 'trace']) }, t('tickets_workbooks', { n: tk.workbooks.length })));
  }
  return h('td.k-muted', t('tickets_not_written'));
}

function conclusionCell(t, tk) {
  if (tk.error === 'unreadable') return h('td', badge(t('tickets_unreadable'), 'danger'));
  if (tk.error === 'inconsistent') return h('td', badge(t('tickets_inconsistent'), 'danger'));
  return h('td', conclusionBadge(t, tk.conclusion));
}

function matches(tk, text, filter) {
  if (filter === 'error' && !tk.error) return false;
  if (filter !== 'all' && filter !== 'error' && (tk.error || tk.conclusion !== filter)) return false;
  if (!text) return true;
  const hay = `${tk.id} ${tk.title || ''}`.toLowerCase();
  return text.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

export function render(ctx) {
  const { t } = ctx;
  const body = h('div.page');
  mount(ctx.view, body);
  ctx.topbar(topbarTitle(t('nav_tickets')), spacer());
  mount(body, pageHead(t('tickets_title'), t('tickets_subtitle')), loading(t, 3));

  const load = () => ctx.memo('tickets', () => ctx.api.tickets());
  load().then((data) => {
    if (!ctx.alive()) return;
    ctx.setTickets(data.tickets);
    ctx.topbar(topbarTitle(t('nav_tickets')), spacer(),
      h('span.k-note.break', [t('tickets_output'), ' ', h('code.k-mono', data.output_dir || NONE)]));
    draw(ctx, body, data);
  }, (err) => {
    if (!ctx.alive()) return;
    mount(body, pageHead(t('tickets_title'), t('tickets_subtitle')), errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
}

function draw(ctx, body, data) {
  const { t } = ctx;
  const list = data.tickets || [];
  if (!list.length) {
    mount(body, pageHead(t('tickets_title'), t('tickets_subtitle')),
      emptyState(t('tickets_empty_title'), t('tickets_empty_body')));
    ctx.ready();
    return;
  }
  const hashCells = new Map();
  const hashStates = new Map();
  const bannerBox = h('div.stack-12');
  const tbody = h('tbody');
  const countNote = h('span.k-note.num');
  const search = h('input.k-input.k-input--sm', {
    type: 'search', placeholder: t('tickets_filter'), 'aria-label': t('tickets_filter'), dataset: { search: '1' },
  });
  const filter = h('select.k-select.k-input--sm', { 'aria-label': t('tickets_filter_conclusion') },
    FILTERS.map((f) => h('option', { value: f }, t(`tickets_filter_${f.replace('-', '_')}`))));

  function hashCell(tk) {
    const cell = h('td');
    hashCells.set(tk.id, cell);
    mount(cell, tk.error ? h('span.k-muted', NONE) : hashInline(t, hashStates.get(tk.id) || 'loading'));
    return cell;
  }

  function row(tk) {
    const title = tk.error ? (tk.latest || tk.id) : (tk.title || tk.latest || tk.id);
    return h('tr', { dataset: { ticket: tk.id } }, [
      h('td.k-id', tk.id),
      h('td.k-cell-title.title-cell', { lang: tk.error ? undefined : (tk.lang || undefined) }, [
        h('a.text-1', { href: href(['tickets', tk.id]) }, title),
        tk.inconsistent && tk.inconsistent.length
          ? h('span.k-muted.note-inline', { title: tk.inconsistent.join(', ') }, ` · ${t('tickets_ignored', { n: tk.inconsistent.length })}`)
          : null,
      ]),
      conclusionCell(t, tk),
      h('td.k-td-num', Number.isFinite(tk.revision) ? `r${tk.revision}` : NONE),
      questionsCell(t, tk),
      casesCell(t, tk),
      hashCell(tk),
      h('td.k-muted.k-td-num', isoDate(tk.generated_at)),
    ]);
  }

  function redraw() {
    const shown = list.filter((tk) => matches(tk, search.value.trim(), filter.value));
    hashCells.clear();
    mount(tbody, shown.length ? shown.map(row)
      : h('tr.k-table-empty', h('td', { colspan: '8' }, t('tickets_no_match'))));
    countNote.textContent = t('tickets_count', { n: shown.length, total: list.length });
  }

  function drawBanners() {
    const stale = list.filter((tk) => (hashStates.get(tk.id) || {}).status === 'stale');
    mount(bannerBox, stale.map((tk) => banner('warning', t('tickets_stale_title', { id: tk.id, rev: `r${tk.revision}` }),
      t('tickets_stale_body'))));
  }

  search.addEventListener('input', redraw);
  filter.addEventListener('change', redraw);

  mount(body,
    pageHead(t('tickets_title'), t('tickets_subtitle')),
    bannerBox,
    h('div.k-table-wrap', [
      h('div.k-toolbar.toolbar-wrap', [
        h('div.k-toolbar__group', h('label.k-input-wrap.search-wrap', [icon('search', 'k-icon--sm'), search])),
        h('div.k-toolbar__group', h('label.k-select-wrap.filter-wrap', [filter, icon('chevron', 'k-icon--sm chevron-down')])),
        h('div.k-toolbar__spacer'),
        countNote,
      ]),
      h('div.scroll-x', h('table.k-table.tbl-wide', [
        h('thead', h('tr', [
          h('th.col-id', t('tickets_th_ticket')), h('th', t('tickets_th_name')), h('th', t('tickets_th_conclusion')),
          h('th.k-td-num', t('tickets_th_rev')), h('th', t('tickets_th_questions')), h('th', t('tickets_th_cases')),
          h('th', t('tickets_th_hash')), h('th.k-td-num', t('tickets_th_updated')),
        ])),
        tbody,
      ])),
    ]));
  redraw();
  ctx.ready();

  // Hash checks run after the first paint, two at a time (the server has two slots).
  const queue = list.filter((tk) => !tk.error).map((tk) => tk.id);
  const worker = async () => {
    while (queue.length && ctx.alive()) {
      const id = queue.shift();
      let state;
      try {
        state = await ctx.memo(`hash:${id}`, () => ctx.api.hash(id));
      } catch (err) {
        state = { error: err };
      }
      if (!ctx.alive()) return;
      hashStates.set(id, state);
      const cell = hashCells.get(id);
      if (cell) mount(cell, hashInline(t, state));
      drawBanners();
    }
  };
  for (let i = 0; i < HASH_PARALLEL; i += 1) worker();
}
