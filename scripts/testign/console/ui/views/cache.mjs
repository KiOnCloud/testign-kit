// Scout cache: read-only list of cached Production briefs per repository and feature.

import { h, icon, mount } from '../dom.mjs';
import { idRanges, isoDate, NONE, shortSha } from '../format.mjs';
import {
  badge, banner, emptyState, errorState, loading, pageHead, pushEscape, spacer, topbarTitle,
} from './shell.mjs';

let selectedKey = null;

const entryKey = (e) => `${e.root_commit}/${e.feature}`;

function sortIds(ids) {
  const num = (id) => {
    const m = /^([A-Z]+)(\d+)$/.exec(id);
    return m ? [m[1], Number(m[2])] : [id, 0];
  };
  return [...(ids || [])].sort((a, b) => {
    const [pa, na] = num(String(a));
    const [pb, nb] = num(String(b));
    return pa === pb ? na - nb : pa.localeCompare(pb);
  });
}

export function render(ctx) {
  const { t } = ctx;
  const body = h('div.page');
  mount(ctx.view, body);
  ctx.topbar(topbarTitle(t('nav_cache')), spacer(),
    h('span.k-note.break', [t('cache_stored_in'), ' ', h('code.k-mono', '~/.testign-kit/cache/<root>/<feature>/')]));
  const head = pageHead(t('cache_title'), t('cache_subtitle'));
  const note = banner('info', t('cache_readonly_title'), t('cache_readonly_body'));
  mount(body, head, note, loading(t, 3));

  ctx.memo('cache', () => ctx.api.cache()).then((data) => {
    if (!ctx.alive()) return;
    ctx.setCount('cache', data.entries.length);
    draw(ctx, body, [head, note], data.entries || []);
  }, (err) => {
    if (!ctx.alive()) return;
    mount(body, head, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
}

function draw(ctx, body, top, entries) {
  const { t } = ctx;
  if (!entries.length) {
    mount(body, ...top, emptyState(t('cache_empty_title'), t('cache_empty_body')));
    ctx.ready();
    return;
  }
  if (selectedKey && !entries.some((e) => entryKey(e) === selectedKey)) selectedKey = null;
  const split = h('div.k-split.split-flex');
  let popEscape = null;

  function reviewed(e) {
    if (e.error) return badge(t('cache_broken'), 'danger');
    if (e.reviewed_by && e.reviewed_by.name) {
      return h('span.inline-status.text-success', [icon('check', 'k-icon--sm'), e.reviewed_by.name]);
    }
    return badge(t('cache_not_reviewed'), 'outline');
  }

  function select(key, focus) {
    selectedKey = selectedKey === key && !focus ? null : key;
    drawAll();
    if (focus) {
      const title = split.querySelector('#cache-panel-title');
      if (title) title.focus();
    }
  }

  function closePanel() {
    const key = selectedKey;
    selectedKey = null;
    drawAll();
    const row = key ? split.querySelector(`tr[data-entry="${CSS.escape(key)}"]`) : null;
    if (row) row.focus();
  }

  function panel(e) {
    return h('aside.k-split__panel.split-panel', { 'aria-labelledby': 'cache-panel-title' }, [
      h('div.k-split__panel-head', [
        h('code.k-mono.text-1', { id: 'cache-panel-title', tabindex: '-1' }, e.feature),
        h('button.k-btn.k-btn--icon.k-btn--xs', { type: 'button', 'aria-label': t('report_close_detail'), on: { click: closePanel } }, icon('close')),
      ]),
      e.error
        ? h('div.panel-body', h('p.panel-text', t('cache_broken_body', { reason: e.error })))
        : h('dl.k-props', [
          h('dt', t('cache_root')), h('dd', h('span.k-chip', h('code.k-mono', shortSha(e.root_commit)))),
          h('dt', t('cache_base')), h('dd', h('span.k-chip', h('code.k-mono', shortSha(e.merge_base)))),
          h('dt', t('cache_th_model')), h('dd', h('span.k-chip', e.scout_model || NONE)),
          h('dt', t('cache_plugin')), h('dd', h('span.k-chip', e.plugin_version || NONE)),
          h('dt', t('cache_th_reviewed')), h('dd', h('span.k-chip', e.reviewed_by && e.reviewed_by.name
            ? `${e.reviewed_by.name} · ${isoDate(e.reviewed_by.date)}` : t('cache_not_reviewed'))),
          h('dt', t('cache_anchors')), h('dd', h('span.k-chip.chip-wrap', (e.anchors || []).join(' · ') || NONE)),
          h('dt', t('cache_th_rows')), h('dd', h('span.k-chip.chip-wrap', h('code.k-mono', sortIds(e.rows).join(' ') || NONE))),
          h('dt', t('cache_unread')), h('dd', h('span.k-chip.chip-wrap', (e.unread || []).join(' · ') || t('cache_none'))),
        ]),
    ]);
  }

  function drawAll() {
    if (popEscape) { popEscape(); popEscape = null; }
    const rows = entries.map((e) => {
      const key = entryKey(e);
      return h('tr', {
        tabindex: '0', class: key === selectedKey ? 'is-selected' : '', 'aria-selected': key === selectedKey ? 'true' : 'false',
        dataset: { entry: key },
        on: {
          click: () => select(key, true),
          keydown: (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); select(key, true); } },
        },
      }, [
        h('td.k-cell-title', h('code.k-mono.text-1', e.feature)),
        h('td.k-id', shortSha(e.root_commit)),
        h('td.k-td-num', e.error ? NONE : String(e.files ?? NONE)),
        h('td.k-mono', e.error ? NONE : (idRanges(sortIds(e.rows)) || NONE)),
        h('td', e.error ? NONE : (e.scout_model || NONE)),
        h('td.k-muted.k-td-num', e.error ? NONE : isoDate(e.saved_at)),
        h('td', reviewed(e)),
      ]);
    });
    const selected = entries.find((e) => entryKey(e) === selectedKey);
    mount(split,
      h('div.k-split__main.split-main', [
        h('div.k-toolbar.toolbar-wrap', [h('div.k-toolbar__spacer'), h('span.k-note.num', t('cache_count', { n: entries.length }))]),
        h('div.scroll-x', h('table.k-table.tbl-mid', [
          h('thead', h('tr', [
            h('th', t('cache_th_feature')), h('th', t('cache_th_repo')), h('th.k-td-num', t('cache_th_files')),
            h('th', t('cache_th_rows')), h('th', t('cache_th_model')), h('th.k-td-num', t('cache_th_saved')),
            h('th', t('cache_th_reviewed')),
          ])),
          h('tbody', rows),
        ])),
      ]),
      selected ? panel(selected) : null);
    if (selected) popEscape = pushEscape(closePanel);
  }

  mount(body, ...top, split);
  drawAll();
  ctx.ready();
}
