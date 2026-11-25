// Test runs: every run with its suite, source, environment, results as icons, state and tester; an
// alert for the runs waiting on the tester, and the New run dialog. Also the labels the Run screen
// shares: row states, classes and the result icons.

import { h, icon, mount, statusIcon } from '../dom.mjs';
import { NONE, timeOrDay } from '../format.mjs';
import { hostOf } from '../hosts.mjs';
import { href } from '../router.mjs';
import { openNewRun } from './new-run.mjs';
import {
  alertBox, badge, breadcrumb, emptyState, errorState, loading, pageHead, rowLink, searchBox, segFilter, srcBadge, tableBox, ybadge,
} from './shell.mjs';

export const NEEDS_YOU = new Set(['parked', 'awaiting-tester']);
const ACTIVE_JOB = new Set(['queued', 'offered', 'running', 'needs-input']);

const STATE_KINDS = {
  pass: 'success', fail: 'danger', 'self-run': 'success', parked: 'warning', 'awaiting-tester': 'warning',
  running: 'info', queued: 'outline', draft: 'outline', manual: 'outline', 'not-applicable': 'outline', 'not-run': 'outline',
};

const STATE_ICONS = {
  pass: ['ok', 'check'], fail: ['bad', 'close'], 'self-run': ['ok', 'user'], parked: ['warn', 'chat'],
  'awaiting-tester': ['warn', 'user'], running: ['busy', 'clock'], queued: ['busy', 'clock'], draft: ['busy', 'dash'],
  manual: ['busy', 'eye'], 'not-applicable': ['busy', 'dash'], 'not-run': ['busy', 'dash'],
};

/** A row state in words; a not-run row names its reason. */
export function rowStateLabel(t, state, reason) {
  if (state === 'not-run' && reason) return t('wt_not_run_reason', { reason: t(`wt_reason_${String(reason).replace(/-/g, '_')}`) });
  return t(`wt_state_${String(state).replace(/-/g, '_')}`);
}

export function rowStateBadge(t, state, reason) {
  return badge(rowStateLabel(t, state, reason), STATE_KINDS[state] || 'outline');
}

/** A row state as a status icon whose tooltip is the state in words. */
export function rowStateIcon(t, state, reason) {
  const [kind, name] = STATE_ICONS[state] || ['busy', 'dash'];
  return statusIcon(kind, name, rowStateLabel(t, state, reason));
}

const CLASS_TONE = { sure: 'outline', choice: '', 'not-web': 'neutral' };

/** The case class as a badge, worded and toned the same on suite and run pages. */
export function classBadge(t, cls) {
  if (!cls) return h('span.yh-muted', NONE);
  return ybadge(t(`case_class_${String(cls).replace(/-/g, '_')}`), CLASS_TONE[cls] || 'outline');
}

/**
 * Count groups in display order, nonzero only: [{key, n, kind, icon}]. `kind` is a status tone.
 * Pass and Fail include the rows the tester ran when their verdicts are known (from `cases`);
 * otherwise those rows are "by the tester".
 */
export function countGroups(counts, cases) {
  const c = counts || {};
  let pass = c.pass || 0;
  let fail = c.fail || 0;
  let tester = c['self-run'] || 0;
  if (Array.isArray(cases)) {
    for (const k of cases) {
      if (k.state !== 'self-run' || !k.result) continue;
      if (k.result.verdict === 'pass') { pass += 1; tester -= 1; }
      if (k.result.verdict === 'fail') { fail += 1; tester -= 1; }
    }
  }
  return [
    { key: 'pass', n: pass, kind: 'ok', icon: 'check' },
    { key: 'fail', n: fail, kind: 'bad', icon: 'close' },
    { key: 'tester', n: tester, kind: 'busy', icon: 'user' },
    { key: 'manual', n: (c.manual || 0) + (c['not-applicable'] || 0), kind: 'busy', icon: 'eye' },
    { key: 'needs_you', n: (c.parked || 0) + (c['awaiting-tester'] || 0), kind: 'warn', icon: 'chat' },
    { key: 'queued', n: (c.queued || 0) + (c.running || 0) + (c.draft || 0), kind: 'busy', icon: 'clock' },
    { key: 'not_run', n: c['not-run'] || 0, kind: 'busy', icon: 'dash' },
  ].filter((g) => g.n > 0);
}

/**
 * Results on one line: a status icon and a number per state. The state name and number are the
 * icon's tooltip and accessible name, so the line fits a table cell.
 */
export function resultIcons(t, counts, cases) {
  return h('span.result-icons', countGroups(counts, cases).map((g) => h('span.result-icon', { dataset: { count: g.key } }, [
    statusIcon(g.kind, g.icon, `${t(`wt_count_${g.key}`)} ${g.n}`),
    h('span.yh-num', { 'aria-hidden': 'true' }, String(g.n)),
  ])));
}

/** The run's job that is queued or open, if any. */
export function activeJob(jobs) {
  return (jobs || []).find((j) => ACTIVE_JOB.has(j.state)) || null;
}

/** A job queued by the agent that the tester has not opened yet. */
export function fromChat(job) {
  return Boolean(job && job.queued_by === 'agent' && !job.opened);
}

/** Where a run's cases came from, for a run made before suites: the Figma node. */
export function sourceLabel(source) {
  if (!source || typeof source !== 'object') return NONE;
  if (source.kind === 'figma') return `Figma · ${source.node || NONE}`;
  return String(source.kind || NONE);
}

/** What waits on the tester in a run: rows parked or awaiting their result, and a job's question. */
export function needsYou(run, jobs) {
  if (run.closed) return 0;
  const c = run.counts || {};
  const rows = (c.parked || 0) + (c['awaiting-tester'] || 0);
  const asks = (jobs || []).filter((j) => j.state === 'needs-input').length;
  return rows + asks;
}

/** A run's state: finished, needs you, agent running, or open (waiting for a run). */
export function runState(run, jobs) {
  if (run.closed) return 'done';
  if (needsYou(run, jobs)) return 'needs';
  if (activeJob(jobs)) return 'running';
  return 'open';
}

const RUN_STATE_BADGE = { done: 'success', needs: '', running: 'neutral', open: 'outline' };
export const RUN_FILTERS = ['all', 'needs', 'running', 'done'];

export function runStateBadge(t, state) {
  return ybadge(t(`run_state_${state}`), RUN_STATE_BADGE[state] ?? 'outline', { dataset: { runState: state } });
}

let search = '';
let filter = 'all';

export function render(ctx) {
  const { t } = ctx;
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_run') }, { label: t('nav_runs') }]));
  const newRun = () => openNewRun(ctx);
  ctx.onKey((event) => {
    if (event.key.toLowerCase() !== 'n') return false;
    newRun();
    return true;
  });
  const head = pageHead(t('runs_title'), t('runs_subtitle'), [
    h('button.yh-btn.yh-btn--primary', { type: 'button', 'aria-keyshortcuts': 'N', dataset: { newRun: '1' }, on: { click: newRun } },
      [icon('plus'), t('new_run')]),
  ]);
  mount(ctx.view, head, loading(t, 4));
  let lastKey = null;

  const load = () => Promise.all([
    ctx.memo('runs', () => ctx.api.runs()),
    ctx.memo('jobs', () => ctx.api.jobs()).catch(() => ({ jobs: [] })),
  ]).then(([runs, jobs]) => {
    if (!ctx.alive()) return;
    const key = JSON.stringify([runs.runs, (jobs.jobs || []).filter((j) => j.run).map((j) => [j.id, j.state, j.run, j.opened])]);
    if (key === lastKey) return;
    lastKey = key;
    ctx.setCount('runs', runs.runs.length);
    draw(runs.runs || [], jobs.jobs || []);
    ctx.ready();
  }, (err) => {
    if (!ctx.alive()) return;
    lastKey = null;
    mount(ctx.view, head, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });

  const tableHolder = h('div');
  function draw(runs, jobs) {
    const byRun = new Map();
    for (const j of jobs) {
      if (!j.run) continue;
      if (!byRun.has(j.run)) byRun.set(j.run, []);
      byRun.get(j.run).push(j);
    }
    if (!runs.length) {
      mount(ctx.view, head, emptyState(t('runs_empty'), t('runs_empty_body'),
        h('button.yh-btn.yh-btn--primary', { type: 'button', on: { click: newRun } }, [icon('plus'), t('new_run')])));
      return;
    }
    const waiting = runs.filter((r) => r.readable && needsYou(r, byRun.get(r.id)) > 0);
    const total = waiting.reduce((n, r) => n + needsYou(r, byRun.get(r.id)), 0);
    const alert = waiting.length ? alertBox('warning', 'chat', t('runs_needs_t', { n: total }),
      h('ul.plain-list', waiting.slice(0, 5).map((r) => h('li', { dataset: { needsRun: r.id } }, [
        t('runs_needs_line', { n: needsYou(r, byRun.get(r.id)), name: r.name || r.id }), ' ',
        h('a.lnk', { href: href(['runs', r.id]) }, t('runs_handle')),
      ])))) : null;
    const states = new Map(runs.map((r) => [r.id, r.readable ? runState(r, byRun.get(r.id)) : null]));
    const counts = { all: runs.length, needs: 0, running: 0, done: 0 };
    for (const s of states.values()) if (s && s in counts) counts[s] += 1;
    const toolbar = h('div.toolbar', [
      searchBox(t('runs_search'), search, (v) => { search = v; drawTable(runs, byRun, states); }),
      segFilter(t('runs_filter'), RUN_FILTERS.map((f) => ({ value: f, label: `${t(`runs_f_${f}`)} ${counts[f]}` })), filter,
        (v) => { filter = v; draw(runs, jobs); }),
    ]);
    mount(ctx.view, head, alert, toolbar, tableHolder, h('p.yh-caption.yh-muted.m-0', t('runs_one_row')));
    drawTable(runs, byRun, states);
  }

  function drawTable(runs, byRun, states) {
    const words = search.toLowerCase().split(/\s+/).filter(Boolean);
    const shown = runs.filter((r) => {
      if (filter !== 'all' && states.get(r.id) !== filter) return false;
      if (!words.length) return true;
      const hay = [r.id, r.name, r.suite && r.suite.name, r.project, r.tester, r.base_url, r.ticket].filter(Boolean).join(' ').toLowerCase();
      return words.every((w) => hay.includes(w));
    });
    const rows = shown.map((run) => {
      if (!run.readable) {
        return h('tr', { dataset: { run: run.id } }, [
          h('td', [h('code.id', run.id), h('span.sub.text-danger', t('runs_unreadable'))]),
          h('td', NONE), h('td', NONE), h('td', NONE), h('td', NONE), h('td', NONE), h('td', NONE), h('td', NONE),
        ]);
      }
      const runJobs = byRun.get(run.id) || [];
      const active = activeJob(runJobs);
      const state = states.get(run.id);
      const total = Object.values(run.counts || {}).reduce((a, b) => a + b, 0);
      const target = href(['runs', run.id]);
      const suite = run.suite;
      return h('tr.click', { dataset: { run: run.id }, on: rowLink(target, ctx.navigate) }, [
        h('td', [h('a.lnk', { href: target }, run.name || run.id), h('span.sub.mono', run.id),
          active && fromChat(active) ? h('span.sub', ybadge(t('runs_from_chat'), 'outline')) : null]),
        h('td', suite && suite.id
          ? [h('a.lnk', { href: href(['suites', suite.id]) }, suite.name || suite.id), h('span.sub', t('runs_rows', { n: total }))]
          : [h('span.yh-muted', t('runs_legacy')), h('span.sub', t('runs_rows', { n: total }))]),
        h('td', h('span.st-row', [srcBadge(t, (run.source || {}).kind), suite ? null : h('span.yh-muted.mono', sourceLabel(run.source))])),
        h('td', [h('span.mono', hostOf(run.base_url) || NONE), h('span.sub', run.project || NONE)]),
        h('td', run.confirmed ? resultIcons(t, run.counts) : h('span.yh-muted', NONE)),
        h('td', runStateBadge(t, state)),
        h('td', run.tester || h('span.yh-muted', NONE)),
        h('td.yh-num.yh-muted', timeOrDay(run.created_at)),
      ]);
    });
    mount(tableHolder, shown.length ? tableBox([
      h('th', t('col_run')), h('th', t('col_suite')), h('th', t('col_source')), h('th', t('col_env')), h('th', t('col_result')),
      h('th', t('col_state')), h('th', t('col_tester')), h('th', t('col_when')),
    ], rows) : alertBox('', 'info', t('runs_no_match'), null));
  }

  load();
  ctx.onStoreChange(() => {
    ctx.invalidate('runs');
    ctx.invalidate('jobs');
    load();
  });
}
