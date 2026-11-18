// Trace: a filled workbook against the latest report revision, read with an explicit template.
// Workbook and template pickers, header-mismatch warning, hash banner, coverage cards, case table.

import { h, icon, mount } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { href } from '../router.mjs';
import { queueJob } from './job-actions.mjs';
import {
  badge, banner, breadcrumb, conclusionBadge, emptyState, errorState, hashBanner, loading, spacer,
} from './shell.mjs';

const filterState = new Map();

function picker(label, value, options, onChange) {
  const select = h('select.k-select.k-input--sm', { on: { change: (e) => onChange(e.target.value) } },
    options.map((o) => h('option', { value: o.value, selected: o.value === value }, o.label)));
  return h('label.picker', [h('span.picker-label', label),
    h('span.k-select-wrap.picker-select', [select, icon('chevron', 'k-icon--sm chevron-down')])]);
}

export function render(ctx) {
  const { t, route } = ctx;
  const id = route.params.ticket;
  const body = h('div.page');
  mount(ctx.view, body);
  const crumbs = breadcrumb(t, [
    { label: t('nav_tickets'), href: href(['tickets']) },
    { label: id, href: href(['tickets', id]) },
    { label: t('trace_crumb') },
  ]);
  ctx.topbar(crumbs, spacer());
  mount(body, loading(t, 4));

  Promise.all([
    ctx.memo('ticket', () => ctx.api.ticket(id)),
    ctx.memo('templates', () => ctx.api.templates()),
  ]).then(([ticket, tpl]) => {
    if (!ctx.alive()) return;
    ctx.setCount('templates', tpl.templates.length);
    const books = ticket.workbooks || [];
    const head = header(ctx, ticket, null);
    if (!books.length) {
      mount(body, head, emptyState(t('trace_no_workbook_title'), t('trace_no_workbook_body')));
      ctx.ready();
      return;
    }
    if (!tpl.templates.length) {
      mount(body, head, noTemplate(t));
      ctx.ready();
      return;
    }
    const workbook = books.includes(route.query.workbook) ? route.query.workbook : books[0];
    const names = tpl.templates.map((x) => x.name);
    const template = names.includes(route.query.template) ? route.query.template : (tpl.default && names.includes(tpl.default) ? tpl.default : names[0]);
    const go = (wb, tp) => ctx.navigate(href(['tickets', id, 'trace'], { workbook: wb, template: tp }));
    const pickers = h('div.pickers', [
      books.length > 1
        ? picker(t('trace_workbook'), workbook, books.map((b) => ({ value: b, label: b })), (wb) => go(wb, template))
        : h('span.picker', [h('span.picker-label', t('trace_workbook')), h('code.k-mono.text-2.break', workbook)]),
      picker(t('trace_template'), template,
        tpl.templates.map((x) => ({ value: x.name, label: x.default ? `${x.name} · ${t('templates_default')}` : x.name })),
        (tp) => go(workbook, tp)),
    ]);
    const result = h('div.stack-20');
    const fm = (ticket.latest && ticket.latest.frontmatter) || {};
    const next = Number.isFinite(fm.revision) ? `r${fm.revision + 1}` : '';
    const write7 = h('button.k-btn.k-btn--primary', {
      type: 'button', dataset: { trigger: 'write7' },
      on: { click: () => queueJob(ctx, { kind: 'testcase', ticket: id, mode: 'trace', workbook, template }) },
    }, t('trigger_write7', { rev: next }));
    mount(body, header(ctx, ticket, pickers, write7), result);
    mount(result, loading(t, 4));
    ctx.memo(`trace:${workbook}|${template}`, () => ctx.api.trace(id, workbook, template)).then((data) => {
      if (!ctx.alive()) return;
      if (data.state === 'no-template') {
        mount(result, noTemplate(t));
      } else {
        drawResult(ctx, result, data, ticket);
      }
      ctx.ready();
    }, (err) => {
      if (!ctx.alive()) return;
      mount(result, errorState(t, err, () => ctx.refresh()));
      ctx.ready();
    });
  }).catch((err) => {
    if (!ctx.alive()) return;
    mount(body, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
}

function noTemplate(t) {
  return emptyState(t('trace_no_template_title'), t('trace_no_template_body'),
    h('a.k-btn.k-btn--secondary', { href: href(['templates']) }, [icon('layers'), t('trace_go_templates')]));
}

function header(ctx, ticket, pickers, action) {
  const { t } = ctx;
  const latest = ticket.latest || {};
  const fm = latest.frontmatter || {};
  const lang = typeof fm.lang === 'string' && fm.lang ? fm.lang : undefined;
  return h('section.report-top', [h('div.report-head', [
    h('div.row-8', [
      h('span.k-id', ticket.id),
      latest.conclusion ? conclusionBadge(t, latest.conclusion) : null,
      Number.isFinite(fm.revision) ? badge(t('trace_report_rev', { rev: `r${fm.revision}` }), 'outline') : null,
    ]),
    h('h1.page-title', { lang }, latest.title || ticket.id),
    pickers,
  ]), action ? h('div.trigger-box', action) : null]);
}

function headerMismatch(ctx, data) {
  const { t } = ctx;
  const tpl = data.template_headers || {};
  const wb = data.workbook_headers || {};
  const letters = [...new Set([...Object.keys(tpl), ...Object.keys(wb)])]
    .sort((a, b) => a.length - b.length || a.localeCompare(b))
    .filter((l) => tpl[l] !== wb[l]);
  const list = h('ul.mismatch-list', letters.map((l) => h('li', [
    h('code.k-mono', l), `: ${tpl[l] ?? NONE} → ${wb[l] ?? NONE}`,
  ])));
  return h('div.k-banner.k-banner--warning', { role: 'status' }, [
    icon('warning', 'icon-warn'),
    h('div.k-banner__text', [
      h('strong', t('trace_mismatch_title', { template: data.template })),
      h('span', t('trace_mismatch_body')),
      letters.length ? list : null,
    ]),
  ]);
}

function card(label, value, bodyText, opts = {}) {
  return h('div.k-card', { class: opts.danger ? 'card-danger' : '' }, [
    h('span.k-section-label', { class: opts.danger ? 'text-danger' : '' }, label),
    value,
    bodyText ? h('p.k-card__body', bodyText) : null,
    opts.extra || null,
  ]);
}

function drawResult(ctx, box, data, ticket) {
  const { t } = ctx;
  const nodes = [];
  if (!data.header_match) nodes.push(headerMismatch(ctx, data));
  const hashSlot = h('div');
  nodes.push(hashSlot);
  ctx.memo('hash', () => ctx.api.hash(ticket.id)).then((state) => {
    if (!ctx.alive()) return;
    const b = hashBanner(t, state);
    mount(hashSlot, b);
  }, () => {});

  const gaps = data.gaps || [];
  const orphans = data.orphans || [];
  const waiting = data.waiting || [];
  const total = data.rows_total || 0;
  const covered = data.rows_with_case || 0;
  nodes.push(h('div.meta-row', [
    h('span', [t('trace_sheet'), ' ', h('span.text-2', data.sheet || NONE)]),
    h('span', [t('trace_report'), ' ', h('code.k-mono.text-2', data.report || NONE)]),
  ]));
  nodes.push(h('section.cards', { 'aria-label': t('trace_result') }, [
    card(t('trace_coverage'), h('p.big-num', `${covered} / ${total}`), t('trace_coverage_body', { n: data.total_cases || 0 }), {
      extra: h('progress.meter', { max: String(Math.max(total, 1)), value: String(covered), 'aria-label': t('trace_coverage') }),
    }),
    card(`${t('trace_gaps')} · ${gaps.length}`, gaps.length ? h('p.k-card__title', gaps.map((g) => h('span.k-id', g))) : null,
      gaps.length ? t('trace_gaps_body') : t('trace_gaps_none'), {
        danger: gaps.length > 0,
        extra: gaps.length ? h('div.k-card__meta.row-8', gaps.map((g) => h('button.k-btn.k-btn--secondary.k-btn--sm', {
          type: 'button', dataset: { trigger: 'add-case', row: g },
          on: { click: () => queueJob(ctx, { kind: 'testcase', ticket: ticket.id, mode: 'write', workbook: data.workbook, template: data.template, focus: [g] }) },
        }, t('trigger_add_case', { row: g })))) : null,
      }),
    card(`${t('trace_orphans')} · ${orphans.length}`, orphans.length ? h('p.k-card__title', orphans.map((o) => h('span.k-id', o))) : null,
      orphans.length ? t('trace_orphans_body') : t('trace_orphans_none'), { danger: orphans.length > 0 }),
    card(`${t('trace_waiting')} · ${waiting.length}`,
      waiting.length ? h('ul.plain-list', waiting.map((w) => h('li', [h('span.k-id', w.case), ' → ', (w.questions || []).join(', ')]))) : null,
      waiting.length ? t('trace_waiting_body') : t('trace_waiting_none')),
  ]));

  const cases = data.cases || [];
  const orphanSet = new Set(orphans);
  const key = `${ticket.id}|${data.workbook}|${data.template}`;
  const tbody = h('tbody');
  const issues = cases.filter((c) => orphanSet.has(c.no) || (c.questions && c.questions.length)).length + gaps.length;
  const tabs = h('div.k-tabs.k-tabs--segmented', { role: 'radiogroup', 'aria-label': t('trace_filter') });

  function status(c) {
    if (orphanSet.has(c.no)) return badge(t('trace_orphan'), 'danger');
    if (c.questions && c.questions.length) return badge(t('trace_status_waiting'), 'warning');
    return h('span.inline-status.text-success', [icon('check', 'k-icon--sm'), t('trace_ok')]);
  }

  function drawTable() {
    const only = filterState.get(key) === 'issues';
    mount(tabs, [['all', `${t('trace_all')} ${cases.length + gaps.length}`], ['issues', `${t('trace_issues')} ${issues}`]].map(([v, label]) =>
      h('button.k-tab', {
        type: 'button', role: 'radio', 'aria-checked': (only ? v === 'issues' : v === 'all') ? 'true' : 'false',
        class: (only ? v === 'issues' : v === 'all') ? 'is-active' : '',
        on: { click: () => { filterState.set(key, v); drawTable(); } },
      }, label)));
    const rows = cases
      .filter((c) => !only || orphanSet.has(c.no) || (c.questions && c.questions.length))
      .map((c) => h('tr', { class: orphanSet.has(c.no) ? 'is-selected' : '' }, [
        h('td.k-id', c.no),
        h('td.k-cell-title.wrap-cell', c.item),
        h('td.k-mono', (c.trace || []).join(' ') || NONE),
        h('td.k-mono', (c.questions || []).join(' ') || NONE),
        h('td.k-td-num.k-muted', String(c.row)),
        h('td', status(c)),
      ]));
    for (const g of gaps) {
      rows.push(h('tr', [
        h('td.k-id.k-muted', NONE), h('td.k-muted', t('trace_no_case')), h('td.k-mono', g), h('td.k-muted', NONE),
        h('td.k-muted', NONE), h('td', badge(t('trace_gap'), 'danger')),
      ]));
    }
    mount(tbody, rows.length ? rows : h('tr.k-table-empty', h('td', { colspan: '6' }, t('trace_no_cases'))));
  }

  nodes.push(h('div.k-table-wrap', [
    h('div.k-toolbar.toolbar-wrap', [h('div.k-toolbar__group', tabs), h('div.k-toolbar__spacer'), h('span.k-note', t('trace_never_overwrite'))]),
    h('div.scroll-x', h('table.k-table.k-table--compact.tbl-mid', [
      h('thead', h('tr', [
        h('th.col-id', t('trace_th_no')), h('th', t('trace_th_item')), h('th', t('trace_th_trace')),
        h('th', t('trace_th_questions')), h('th.k-td-num', t('trace_th_row')), h('th', t('trace_th_status')),
      ])),
      tbody,
    ])),
  ]));
  mount(box, nodes);
  drawTable();
}
