// Scout cache: read-only list of cached Production briefs per repository and feature.

import { h, icon, mount, statusIcon } from '../dom.mjs';
import { idRanges, isoDate, NONE, shortSha } from '../format.mjs';
import {
  alertBox, breadcrumb, emptyState, errorState, loading, pageHead, pushEscape, tableBox,
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
  const body = ctx.view;
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_config') }, { label: t('nav_cache') }]));
  const head = pageHead(t('cache_title'), t('cache_subtitle'), null,
    [h('span.yh-caption.yh-muted.break', [t('cache_stored_in'), ' ', h('code.mono', '~/.testign-kit/cache/<root>/<feature>/')])]);
  const note = alertBox('', 'info', t('cache_readonly_title'), t('cache_readonly_body'));
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
  const split = h('div.split');
  let popEscape = null;

  function reviewed(e) {
    if (e.error) return h('span.st-row', [statusIcon('bad', 'warning', t('cache_broken')), h('span.yh-caption', t('cache_broken'))]);
    if (e.reviewed_by && e.reviewed_by.name) {
      return h('span.st-row', [statusIcon('ok', 'check', t('cache_reviewed_by', { name: e.reviewed_by.name })), h('span', e.reviewed_by.name)]);
    }
    return h('span.st-row', [statusIcon('busy', 'dash', t('cache_not_reviewed')), h('span.yh-caption.yh-muted', t('cache_not_reviewed'))]);
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
    return h('section.panel.sticky', { 'aria-labelledby': 'cache-panel-title' }, [
      h('div.panel-head', [
        h('code.mono', { id: 'cache-panel-title', tabindex: '-1' }, e.feature),
        h('button.yh-tool', { type: 'button', 'aria-label': t('report_close_detail'), on: { click: closePanel } }, icon('close')),
      ]),
      e.error
        ? h('p.m-0', t('cache_broken_body', { reason: e.error }))
        : h('dl.kv', [
          h('dt', t('cache_root')), h('dd.mono', shortSha(e.root_commit)),
          h('dt', t('cache_base')), h('dd.mono', shortSha(e.merge_base)),
          h('dt', t('cache_th_model')), h('dd', e.scout_model || NONE),
          h('dt', t('cache_plugin')), h('dd', e.plugin_version || NONE),
          h('dt', t('cache_th_reviewed')), h('dd', e.reviewed_by && e.reviewed_by.name
            ? `${e.reviewed_by.name} · ${isoDate(e.reviewed_by.date)}` : t('cache_not_reviewed')),
          h('dt', t('cache_anchors')), h('dd.break', (e.anchors || []).join(' · ') || NONE),
          h('dt', t('cache_th_rows')), h('dd.mono.break', sortIds(e.rows).join(' ') || NONE),
          h('dt', t('cache_unread')), h('dd.break', (e.unread || []).join(' · ') || t('cache_none')),
        ]),
    ]);
  }

  function drawAll() {
    if (popEscape) { popEscape(); popEscape = null; }
    const rows = entries.map((e) => {
      const key = entryKey(e);
      return h('tr.click', {
        tabindex: '0', class: key === selectedKey ? 'is-sel' : '', 'aria-selected': key === selectedKey ? 'true' : 'false',
        dataset: { entry: key },
        on: {
          click: () => select(key, true),
          keydown: (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); select(key, true); } },
        },
      }, [
        h('td', h('code.mono', e.feature)),
        h('td.id', shortSha(e.root_commit)),
        h('td.is-num', e.error ? NONE : String(e.files ?? NONE)),
        h('td.mono.wrap', e.error ? NONE : (idRanges(sortIds(e.rows)) || NONE)),
        h('td', e.error ? NONE : (e.scout_model || NONE)),
        h('td.yh-num.yh-muted', e.error ? NONE : isoDate(e.saved_at)),
        h('td', reviewed(e)),
      ]);
    });
    const selected = entries.find((e) => entryKey(e) === selectedKey);
    split.className = selected ? 'split' : 'split split--single';
    mount(split,
      h('div.yh-stack', [
        h('div.toolbar', [h('span.push'), h('span.yh-caption.yh-muted.yh-num', t('cache_count', { n: entries.length }))]),
        tableBox([
          h('th', t('cache_th_feature')), h('th', t('cache_th_repo')), h('th.is-num', t('cache_th_files')),
          h('th', t('cache_th_rows')), h('th', t('cache_th_model')), h('th', t('cache_th_saved')), h('th', t('cache_th_reviewed')),
        ], rows),
      ]),
      selected ? panel(selected) : null);
    if (selected) popEscape = pushEscape(closePanel);
  }

  mount(body, ...top, split);
  drawAll();
  ctx.ready();
}
