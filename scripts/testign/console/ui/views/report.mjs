// Report: one revision of a survey report, its sections as tabs, and a split panel for the row
// a tester picks (the row's cells and the finding behind it). Report text is shown as written.

import { h, icon, inline, mount } from '../dom.mjs';
import { isoDate, NONE, shortSha } from '../format.mjs';
import { href } from '../router.mjs';
import {
  badge, banner, breadcrumb, conclusionBadge, emptyState, errorState, hashInline, loading, pushEscape, spacer,
} from './shell.mjs';

const ROW_ID = /^[BRQ]\d+$/;
const Q_ID = /\bQ\d+\b/g;
const DRAFT_LABEL = /(\bja\b|日本語|draft|ドラフト|nháp)/i;
const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const LABELLED = /^\*\*([^*]+?)[:：]?\*\*\s*[:：]?\s*(.*)$/;

// Tab and selected row per ticket and revision, kept across re-renders (language switch).
const uiState = new Map();

function stateFor(key) {
  if (!uiState.has(key)) uiState.set(key, { section: null, row: null });
  return uiState.get(key);
}

/** Paragraphs, headings and lists from report lines; table lines are skipped (tables render apart). */
function prose(lines, lang) {
  const out = [];
  let list = null;
  let listTag = null;
  const flush = () => { if (list) { out.push(h(listTag, { class: 'prose-list', lang }, list)); list = null; listTag = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim() || line.trim() === '---' || line.trim().startsWith('|')) { flush(); continue; }
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      const tag = bullet ? 'ul' : 'ol';
      if (listTag !== tag) { flush(); list = []; listTag = tag; }
      list.push(h('li', inline((bullet || numbered)[1])));
      continue;
    }
    flush();
    if (/^#{3,6}\s/.test(line)) out.push(h('h3.prose-heading', { lang }, inline(line.replace(/^#+\s*/, ''))));
    else out.push(h('p.prose-p', { lang }, inline(line)));
  }
  flush();
  return out;
}

function qIds(cells) {
  const found = [];
  for (const cell of cells) for (const m of String(cell).match(Q_ID) || []) if (!found.includes(m)) found.push(m);
  return found;
}

function copyText(ctx, text) {
  const done = () => ctx.toast(ctx.t('copied'));
  const fail = () => ctx.toast(ctx.t('copy_failed'), 'danger');
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    navigator.clipboard.writeText(text).then(done, fail);
  } else {
    fail();
  }
}

function findingBlock(ctx, view, qid, lang) {
  const { t } = ctx;
  const q = (view.questions || []).find((x) => x.id === qid);
  const finding = (view.findings || {})[qid];
  const parts = [];
  parts.push(h('div.row-6', [
    badge(qid, 'warning'),
    q && q.level ? badge(q.level, '', { lang }) : null,
    q && q.blocks ? badge(`${t('report_blocks_tc')}: ${q.blocks}`, '', { lang }) : null,
    q && q.qa ? badge(q.qa, 'info', { lang }) : null,
  ]));
  if (q && q.summary) parts.push(h('p.panel-text', { lang }, q.summary));
  if (!finding) {
    parts.push(h('p.k-note', t('report_no_finding')));
    return h('section.panel-section', { 'aria-label': qid }, parts);
  }
  parts.push(h('h3.finding-heading', { lang }, finding.heading));
  let steps = null;
  const flushSteps = () => { if (steps) { parts.push(h('ol.prose-list', { lang }, steps)); steps = null; } };
  for (const raw of finding.lines || []) {
    const line = raw.trim();
    if (!line || line === '---') { flushSteps(); continue; }
    const numbered = NUMBERED.exec(line);
    if (numbered) { (steps = steps || []).push(h('li', inline(numbered[1]))); continue; }
    flushSteps();
    const bullet = BULLET.exec(line);
    const text = bullet ? bullet[1] : line;
    const labelled = LABELLED.exec(text);
    if (labelled) {
      const [, label, value] = labelled;
      const isDraft = DRAFT_LABEL.test(label);
      parts.push(h('div.stack-4', [
        h('span.k-section-label', { lang }, label),
        isDraft ? h('p.draft', { lang: 'ja' }, value) : h('p.panel-text', { lang }, inline(value)),
        isDraft ? h('div.row-8', h('button.k-btn.k-btn--ghost.k-btn--sm', {
          type: 'button', on: { click: () => copyText(ctx, value) },
        }, [icon('copy'), t('copy')])) : null,
      ]));
    } else {
      parts.push(h('p.panel-text', { lang }, inline(text)));
    }
  }
  flushSteps();
  return h('section.panel-section', { 'aria-label': qid }, parts);
}

function summaryStrip(ctx, view, ticketId, lang) {
  const { t } = ctx;
  const c = view.counts || {};
  const sev = c.severity || {};
  const blocks = c.blocks || {};
  const questions = view.questions || [];
  const byQa = new Map();
  for (const q of questions) byQa.set(q.qa, (byQa.get(q.qa) || 0) + 1);
  const rowsFor = (qid) => [...(view.behaviors || []), ...(view.regressions || [])]
    .filter((r) => Object.values(r).some((v) => typeof v === 'string' && v.split(/[^A-Za-z0-9]/).includes(qid)))
    .map((r) => r.id);
  const blockNotes = questions.filter((q) => String(q.blocks).trim().toLowerCase() !== 'no')
    .map((q) => `${q.id} → ${rowsFor(q.id).join(', ') || q.blocks}`);
  const regs = view.regressions || [];
  const cov = view.coverage;
  const cell = (label, value, note) => h('div.summary-cell', [h('span.k-section-label', label), value, note ? h('span.k-note', note) : null]);
  return h('section.summary-strip', { 'aria-label': t('report_summary') }, [
    cell(t('report_sum_findings'),
      h('span.text-1.num', `${sev.blocking || 0} Blocking · ${sev.major || 0} Major · ${sev.minor || 0} Minor`),
      byQa.size ? h('span', { lang }, [...byQa].map(([qa, n]) => `${qa} ${n}`).join(' · ')) : t('report_no_questions')),
    cell(t('report_sum_blocks'),
      h('span.text-1.num', `${blocks.block || 0} Block · ${blocks.partial || 0} Partial`),
      blockNotes.length ? blockNotes.join(' · ') : null),
    cell(t('report_sum_regression'),
      regs.length ? h('span.text-1', { lang }, regs.map((r) => r.area).join(' · ')) : h('span.k-muted', t('report_none')),
      regs.length ? regs.map((r) => r.id).join(' · ') : null),
    cell(t('report_sum_cases'),
      cov && Number.isFinite(cov.total_cases)
        ? h('span.text-1.num', t('report_cases_summary', { covered: cov.rows_with_case ?? NONE, total: cov.rows_total ?? NONE, n: cov.total_cases }))
        : h('span.k-muted', t('tickets_not_written')),
      h('a', { href: href(['tickets', ticketId, 'trace']) }, t('report_open_trace'))),
  ]);
}

export function render(ctx) {
  const { t, route } = ctx;
  const id = route.params.ticket;
  const rev = route.query.rev || null;
  const body = h('div.page');
  mount(ctx.view, body);
  const crumbs = (current) => breadcrumb(t, [
    { label: t('nav_tickets'), href: href(['tickets']) },
    { label: id, href: current ? href(['tickets', id]) : undefined },
    ...(current ? [{ label: current }] : []),
  ]);
  ctx.topbar(crumbs(null), spacer());
  mount(body, loading(t, 5));

  ctx.memo('ticket', () => ctx.api.ticket(id)).then(async (ticket) => {
    let view = ticket.latest;
    const latestName = view ? view.name : null;
    if (rev && rev !== latestName) {
      view = await ctx.memo(`rev:${rev}`, () => ctx.api.revision(id, rev));
    }
    if (!ctx.alive()) return;
    draw(ctx, body, ticket, view, latestName, crumbs);
  }).catch((err) => {
    if (!ctx.alive()) return;
    mount(body, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
}

function revisionPicker(ctx, ticket, view, latestName) {
  const { t } = ctx;
  const id = ticket.id;
  const current = view ? view.name : null;
  const options = [...(ticket.revisions || [])].reverse().map((r) => {
    const parts = [`r${r.revision}`, isoDate(r.generated_at)];
    if (r.name === latestName) parts.push(t('report_latest'));
    if (r.state !== 'ok') parts.push(t(r.state === 'unreadable' ? 'tickets_unreadable' : 'tickets_inconsistent'));
    return h('option', { value: r.name, selected: r.name === current, disabled: r.state === 'unreadable' }, parts.join(' · '));
  });
  if (!current) options.unshift(h('option', { value: '', selected: true, disabled: true }, t('report_revision')));
  const select = h('select.k-select.k-input--sm', {
    on: { change: (e) => ctx.navigate(href(['tickets', id], { rev: e.target.value === latestName ? undefined : e.target.value })) },
  }, options);
  return h('label.k-select-wrap.rev-picker', [h('span.sr-only', t('report_revision')), select, icon('chevron', 'k-icon--sm chevron-down')]);
}

function draw(ctx, body, ticket, view, latestName, crumbs) {
  const { t } = ctx;
  const id = ticket.id;
  const traceLink = h('a.k-btn.k-btn--ghost.k-btn--sm', { href: href(['tickets', id, 'trace']) }, [icon('layers'), t('report_open_trace')]);
  if (!view) {
    ctx.topbar(crumbs(null), spacer(), ticket.revisions && ticket.revisions.length ? revisionPicker(ctx, ticket, null, latestName) : null);
    const key = ticket.error === 'inconsistent' ? 'report_inconsistent' : 'report_unreadable';
    mount(body, banner('danger', t('err_title'), t(key)));
    ctx.ready();
    return;
  }
  const fm = view.frontmatter || {};
  const lang = typeof fm.lang === 'string' && fm.lang ? fm.lang : undefined;
  const isLatest = view.name === latestName;
  const revLabel = Number.isFinite(fm.revision) ? `r${fm.revision}` : view.name;
  ctx.topbar(crumbs(t('report_crumb', { rev: revLabel })), spacer(), revisionPicker(ctx, ticket, view, latestName), traceLink);

  const hashSlot = h('span');
  const head = h('section.report-head', [
    h('div.row-8', [
      h('span.k-id', id), conclusionBadge(t, view.conclusion),
      view.state && view.state !== 'ok' ? badge(t('tickets_inconsistent'), 'danger') : null,
      isLatest ? null : badge(t('report_older'), 'outline'),
    ]),
    h('h1.page-title', { lang }, view.title || view.name),
    h('div.meta-row', [
      h('span.inline-status', [icon('branch', 'k-icon--sm'), t('report_production'), ' ', h('span.text-2', String(fm.master_ref || '')), ' ', h('code.k-mono.text-2', shortSha(fm.merge_base))]),
      h('span', [t('report_phase'), ' ', h('span.text-2', String(fm.develop_ref || '')), ' ', h('code.k-mono.text-2', shortSha(fm.develop_head))]),
      isLatest ? hashSlot : null,
      h('span', [t('report_lang'), ': ', badge(lang || NONE, 'outline')]),
      h('span.num', [t('report_generated'), ' ', isoDate(fm.generated_at)]),
    ]),
  ]);

  const sections = view.sections || [];
  const st = stateFor(`${id}|${view.name}`);
  if (st.section === null || !sections.some((s) => s.number === st.section)) {
    st.section = (sections.find((s) => s.number === 3) || sections[0] || {}).number ?? null;
  }
  const tabs = h('div.k-tabs.tabs-wrap', { role: 'tablist', 'aria-label': t('report_sections') });
  const panelBox = h('div', { role: 'tabpanel', id: 'report-tabpanel', tabindex: '-1' });

  mount(body, head, summaryStrip(ctx, view, id, lang), sections.length ? tabs : null,
    sections.length ? panelBox : emptyState(t('report_no_sections'), t('report_no_sections_body')));

  if (isLatest) {
    mount(hashSlot, hashInline(t, 'loading'));
    ctx.memo('hash', () => ctx.api.hash(id)).then(
      (state) => { if (ctx.alive()) mount(hashSlot, hashInline(t, state)); },
      (err) => { if (ctx.alive()) mount(hashSlot, hashInline(t, { error: err })); },
    );
  }

  function drawTabs() {
    const buttons = sections.map((s) => {
      const active = s.number === st.section;
      const rows = (s.tables || []).reduce((n, tb) => n + tb.rows.length, 0);
      return h('button.k-tab', {
        type: 'button', role: 'tab', id: `tab-${s.number}`, 'aria-selected': active ? 'true' : 'false',
        'aria-controls': 'report-tabpanel', tabindex: active ? '0' : '-1', class: active ? 'is-active' : '',
        lang, dataset: { section: s.number },
        on: { click: () => { st.section = s.number; st.row = null; drawTabs(); drawPanel(); } },
      }, [`${s.number}. ${s.heading}`, rows ? h('span.k-count', String(rows)) : null]);
    });
    mount(tabs, buttons);
    panelBox.setAttribute('aria-labelledby', `tab-${st.section}`);
  }

  tabs.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    const items = [...tabs.querySelectorAll('[role="tab"]')];
    const i = items.indexOf(document.activeElement);
    if (i < 0) return;
    event.preventDefault();
    items[(i + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length].focus();
  });

  let popEscape = null;

  function drawPanel() {
    if (popEscape) { popEscape(); popEscape = null; }
    const section = sections.find((s) => s.number === st.section);
    if (!section) { mount(panelBox); return; }
    const tables = section.tables || [];
    const selectable = tables.find((tb) => tb.rows.some((r) => ROW_ID.test(r[0] || '')));
    const proseNodes = prose(section.lines || [], lang);
    const tableNodes = tables.filter((tb) => tb !== selectable).map((tb) => reportTable(tb, lang));
    if (!selectable) {
      mount(panelBox, h('div.section-body', [...proseNodes, ...tableNodes]));
      if (!proseNodes.length && !tableNodes.length) mount(panelBox, h('p.k-note', t('report_section_empty')));
      return;
    }
    const selected = st.row ? selectable.rows.find((r) => r[0] === st.row) : null;
    if (!selected) st.row = null;
    const tbody = h('tbody', selectable.rows.map((cells) => {
      const rid = cells[0] || '';
      const pick = ROW_ID.test(rid);
      return h('tr', {
        class: rid === st.row ? 'is-selected' : '', tabindex: pick ? '0' : undefined,
        'aria-selected': pick ? (rid === st.row ? 'true' : 'false') : undefined, dataset: { row: rid },
        on: pick ? {
          click: () => select(rid, true),
          keydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(rid, true); } },
        } : undefined,
      }, cells.map((cell, i) => (i === 0 ? h('td.k-id', cell) : h('td', { lang, dataset: { cell: `${rid}:${i}` } }, inline(cell)))));
    }));
    const main = h('div.k-split__main.split-main', [
      h('div.scroll-x', h('table.k-table.report-table', { 'aria-label': section.heading }, [
        h('thead', h('tr', selectable.header.map((x) => h('th', { lang }, x)))),
        tbody,
      ])),
    ]);
    const nodes = [];
    if (proseNodes.length) nodes.push(h('div.section-body', proseNodes));
    nodes.push(h('div.k-split.split-flex', [main, selected ? rowPanel(selectable.header, selected) : null]));
    nodes.push(...tableNodes);
    mount(panelBox, nodes);
    if (selected) popEscape = pushEscape(() => closeRow());
  }

  function rowPanel(header, cells) {
    const rid = cells[0];
    const qs = rid.startsWith('Q') ? [rid] : qIds(cells.slice(1));
    const title = h('h2.panel-title', { tabindex: '-1', lang, id: 'row-panel-title' }, cells[1] || rid);
    return h('aside.k-split__panel.split-panel', { 'aria-labelledby': 'row-panel-title' }, [
      h('div.k-split__panel-head', [
        h('span.k-id', rid), ...qs.flatMap((q) => [h('span.k-muted', '·'), h('span.k-id', q)]),
        h('button.k-btn.k-btn--icon.k-btn--xs', { type: 'button', 'aria-label': t('report_close_detail'), on: { click: () => closeRow() } }, icon('close')),
      ]),
      title,
      h('dl.k-props', header.slice(2).flatMap((label, i) => [
        h('dt', { lang }, label),
        h('dd', { lang }, h('span.k-chip.chip-wrap', inline(cells[i + 2] || ''))),
      ])),
      qs.length ? h('div.panel-body', qs.map((q) => findingBlock(ctx, view, q, lang))) : null,
    ]);
  }

  function select(rid, focusPanel) {
    st.row = st.row === rid && !focusPanel ? null : rid;
    drawPanel();
    if (focusPanel) {
      const title = panelBox.querySelector('#row-panel-title');
      if (title) title.focus();
    }
  }

  function closeRow() {
    const rid = st.row;
    st.row = null;
    drawPanel();
    const row = rid ? panelBox.querySelector(`tr[data-row="${CSS.escape(rid)}"]`) : null;
    if (row) row.focus();
  }

  ctx.onKey((event) => {
    const key = event.key.toLowerCase();
    if (key !== 'j' && key !== 'k') return false;
    const rows = [...panelBox.querySelectorAll('tr[tabindex]')];
    if (!rows.length) return false;
    // j/k move focus between rows; while the panel is open they also move the selection.
    let i = rows.indexOf(document.activeElement);
    if (i < 0) i = rows.findIndex((r) => r.dataset.row === st.row);
    const next = rows[i < 0 ? 0 : Math.max(0, Math.min(rows.length - 1, i + (key === 'j' ? 1 : -1)))];
    const rid = next.dataset.row;
    if (st.row) {
      st.row = rid;
      drawPanel();
    }
    const row = panelBox.querySelector(`tr[data-row="${CSS.escape(rid)}"]`);
    if (row) row.focus();
    return true;
  });

  if (sections.length) {
    drawTabs();
    drawPanel();
  }
  ctx.ready();
}

function reportTable(table, lang) {
  return h('div.k-table-wrap.table-box', h('div.scroll-x', h('table.k-table.report-table', [
    h('thead', h('tr', table.header.map((x) => h('th', { lang }, x)))),
    h('tbody', table.rows.map((cells) => h('tr', cells.map((c) => h('td', { lang }, inline(c)))))),
  ])));
}
