// Test suites: every suite with its source, case count, state and runs; search, filter chips and a
// row menu (rename, duplicate, delete). Also the labels other suite screens share.

import { h, icon, mount } from '../dom.mjs';
import { NONE, timeOrDay } from '../format.mjs';
import { href } from '../router.mjs';
import { jobErrorText } from './job-actions.mjs';
import {
  alertBox, breadcrumb, emptyState, errorState, field, loading, openDialog, pageHead, rowLink, searchBox, segFilter, srcBadge,
  tableBox, ybadge,
} from './shell.mjs';

export const FILTERS = ['all', 'needs', 'generating', 'ready'];
const STATE_BADGE = { generating: 'neutral', review: '', ready: 'success' };

/** A suite's state as a badge: generating, needs your review, ready. */
export function suiteStateBadge(t, state) {
  return ybadge(t(`suite_state_${state}`), STATE_BADGE[state] ?? 'outline', { dataset: { suiteState: state } });
}

/** What a source points at, in one short line: a Figma node, a ticket and report, a file. */
export function sourceRef(t, source) {
  const s = source || {};
  if (s.kind === 'figma') return s.node ? t('suite_ref_node', { node: s.node }) : NONE;
  if (s.kind === 'backlog') return s.revision ? t('suite_ref_report', { ticket: s.ticket || NONE, rev: s.revision }) : (s.ticket || NONE);
  if (s.kind === 'excel') return s.file || NONE;
  return s.note || NONE;
}

/** The filter a suite falls under, besides "all". */
export function suiteFilter(suite) {
  if (suite.state === 'generating') return 'generating';
  if (suite.state === 'ready') return 'ready';
  return 'needs';
}

export function suiteCounts(list) {
  const counts = { all: 0, needs: 0, generating: 0, ready: 0 };
  for (const s of list || []) {
    counts.all += 1;
    if (s.readable !== false) counts[suiteFilter(s)] += 1;
  }
  return counts;
}

/** Suites matching the search words (name, id, project, source) and the filter chip. */
export function filterSuites(t, list, text, filter) {
  const words = String(text || '').toLowerCase().split(/\s+/).filter(Boolean);
  return (list || []).filter((s) => {
    if (filter && filter !== 'all' && (s.readable === false || suiteFilter(s) !== filter)) return false;
    if (!words.length) return true;
    const hay = [s.name, s.id, s.project, s.kind, s.readable === false ? '' : sourceRef(t, s.source),
      (s.source || {}).ticket, (s.source || {}).url].filter(Boolean).join(' ').toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** Suite errors as text: a store refusal keeps the server's own sentence. */
export function suiteErrorText(t, err) {
  if (err && (err.code === 'conflict' || err.code === 'bad-request') && err.message) return err.message;
  return jobErrorText(t, err);
}

/** Rename, duplicate or delete one suite, in a dialog. `after(result)` runs when one of them worked. */
export function openSuiteMenu(ctx, suite, after) {
  const { t } = ctx;
  const errorBox = h('div', { role: 'alert' });
  const name = h('input.yh-input', { type: 'text', id: 'suite-rename', maxlength: '120', value: suite.name || '' });
  const fail = (err) => mount(errorBox, h('p.k-field__error', [icon('warning'), suiteErrorText(t, err)]));
  const busy = (on) => { for (const b of [rename, dup, del]) b.disabled = on; };
  const rename = h('button.yh-btn.yh-btn--sm', { type: 'button', dataset: { suiteAction: 'rename' } }, t('suite_rename'));
  const dup = h('button.yh-btn', { type: 'button', dataset: { suiteAction: 'duplicate' } }, [icon('copy'), t('duplicate')]);
  const del = h('button.yh-btn.yh-btn--destructive', { type: 'button', dataset: { suiteAction: 'delete' },
    disabled: suite.state === 'generating' ? true : undefined }, [icon('trash'), t('delete')]);
  const dlg = openDialog({
    t, title: t('suite_menu_title', { name: suite.name || suite.id }),
    body: h('div.stack-16', [
      h('div.toolbar', [h('div.grow', field(t('suite_name'), name)), rename]),
      suite.state === 'generating' ? h('p.k-note', t('suite_err_generating')) : null,
      h('p.k-note', t('suite_delete_note')),
      errorBox,
    ]),
    footer: [dup, del],
  });
  rename.addEventListener('click', async () => {
    const value = name.value.trim();
    if (!value) { mount(errorBox, h('p.k-field__error', [icon('warning'), t('suite_err_name')])); return; }
    busy(true);
    try {
      await ctx.api.patchSuite(suite.id, { name: value });
      ctx.toast(t('suite_renamed'));
      dlg.close();
      after({ action: 'rename' });
    } catch (err) { busy(false); fail(err); }
  });
  dup.addEventListener('click', async () => {
    busy(true);
    try {
      const copy = await ctx.api.duplicateSuite(suite.id, {});
      ctx.toast(t('suite_duplicated'));
      dlg.close();
      after({ action: 'duplicate', suite: copy && copy.id });
    } catch (err) { busy(false); fail(err); }
  });
  del.addEventListener('click', async () => {
    busy(true);
    try {
      await ctx.api.removeSuite(suite.id);
      ctx.toast(t('suite_deleted'));
      dlg.close();
      after({ action: 'delete' });
    } catch (err) { busy(false); fail(err); }
  });
  return dlg;
}

let search = '';
let filter = 'all';

export function render(ctx) {
  const { t } = ctx;
  mount(ctx.view, loading(t, 5));
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_design') }, { label: t('nav_suites') }]));
  const head = pageHead(t('suites_title'), t('suites_sub'),
    [h('a.yh-btn.yh-btn--primary', { href: href(['suites', 'new']), dataset: { newSuite: '1' } }, [icon('plus'), t('new_suite')])]);

  let lastKey = null;
  const load = () => ctx.memo('suites', () => ctx.api.suites()).then((data) => {
    if (!ctx.alive()) return;
    const list = data.suites || [];
    const key = JSON.stringify(list);
    if (key === lastKey) return;
    lastKey = key;
    ctx.setCount('suites', list.length);
    draw(list);
    ctx.ready();
  }, (err) => {
    if (!ctx.alive()) return;
    lastKey = null;
    mount(ctx.view, head, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });

  const tableHolder = h('div');
  function draw(list) {
    const counts = suiteCounts(list);
    const chips = segFilter(t('suites_filter'), FILTERS.map((f) => ({ value: f, label: `${t(`suites_f_${f}`)} ${counts[f]}` })), filter,
      (v) => { filter = v; draw(list); });
    const toolbar = h('div.toolbar', [searchBox(t('suites_search'), search, (v) => { search = v; drawTable(list); }), chips]);
    mount(ctx.view, head, list.length ? [toolbar, tableHolder] : emptyState(t('suites_empty'), t('suites_empty_body'),
      h('a.yh-btn.yh-btn--primary', { href: href(['suites', 'new']) }, [icon('plus'), t('new_suite')])));
    if (list.length) drawTable(list);
  }

  function drawTable(list) {
    const shown = filterSuites(t, list, search, filter);
    const rows = shown.map((s) => {
      if (s.readable === false) {
        return h('tr', { dataset: { suite: s.id } }, [
          h('td', [h('code.id', s.id), h('span.sub.text-danger', t('suite_unreadable'))]),
          h('td', NONE), h('td.is-num', NONE), h('td', NONE), h('td', NONE), h('td', NONE), h('td', NONE), h('td'),
        ]);
      }
      const target = href(['suites', s.id]);
      return h('tr.click', { dataset: { suite: s.id }, on: rowLink(target, ctx.navigate) }, [
        h('td', [h('a.lnk', { href: target }, s.name || s.id), h('span.sub.mono', s.id)]),
        h('td', h('span.st-row', [srcBadge(t, s.kind), h('span.yh-muted.mono', sourceRef(t, s.source))])),
        h('td.is-num', s.state === 'generating' && !s.cases ? '…' : String(s.cases ?? 0)),
        h('td', suiteStateBadge(t, s.state)),
        h('td', s.runs ? h('a.lnk', { href: href(['suites', s.id], { tab: 'runs' }) }, t('suite_n_runs', { n: s.runs }))
          : h('span.yh-muted', NONE)),
        h('td', s.project || h('span.yh-muted', NONE)),
        h('td.yh-num.yh-muted', timeOrDay(s.updated_at || s.created_at)),
        h('td', h('button.yh-tool', { type: 'button', 'aria-label': t('suite_more'), dataset: { suiteMenu: s.id },
          on: { click: () => openSuiteMenu(ctx, s, () => { ctx.invalidate('suites'); ctx.invalidate('count:suites'); lastKey = null; load(); }) } },
        icon('more'))),
      ]);
    });
    mount(tableHolder, shown.length
      ? tableBox([h('th', t('nav_suites')), h('th', t('col_source')), h('th.is-num', t('col_cases')), h('th', t('col_state')),
        h('th', t('col_runs')), h('th', t('col_project')), h('th', t('col_updated')), h('th', h('span.sr-only', t('suite_more')))], rows)
      : alertBox('', 'info', t('suites_no_match'), null));
  }

  load();
  ctx.onStoreChange(() => {
    ctx.invalidate('suites');
    load();
  });
}
