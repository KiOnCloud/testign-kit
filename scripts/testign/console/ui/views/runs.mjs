// Test runs: every web test run with its source and counts by state, the plan jobs still importing,
// and the new-run form. Also the labels the Run screen shares: row states, classes, count badges.

import { h, mount } from '../dom.mjs';
import { NONE, timeOrDay } from '../format.mjs';
import { href } from '../router.mjs';
import { renderRunForm } from './run-form.mjs';
import { badge, emptyState, errorState, loading, pageHead, spacer, topbarTitle } from './shell.mjs';

export const NEEDS_YOU = new Set(['parked', 'awaiting-tester']);
const ACTIVE_JOB = new Set(['queued', 'offered', 'running', 'needs-input']);

const STATE_KINDS = {
  pass: 'success', fail: 'danger', 'self-run': 'success', parked: 'warning', 'awaiting-tester': 'warning',
  running: 'info', queued: 'outline', draft: 'outline', manual: 'outline', 'not-applicable': 'outline', 'not-run': 'outline',
};

/** A row state as a badge; a not-run row names its reason. */
export function rowStateBadge(t, state, reason) {
  const key = `wt_state_${String(state).replace(/-/g, '_')}`;
  const label = state === 'not-run' && reason
    ? t('wt_not_run_reason', { reason: t(`wt_reason_${String(reason).replace(/-/g, '_')}`) })
    : t(key);
  return badge(label, STATE_KINDS[state] || 'outline');
}

export function classBadge(t, cls) {
  if (!cls) return h('span.k-muted', NONE);
  return badge(t(`wt_class_${String(cls).replace(/-/g, '_')}`), cls === 'choice' ? 'accent' : 'outline');
}

/**
 * Count groups in display order, nonzero only: [{key, n, kind}]. Pass and Fail include the rows the
 * tester ran when their verdicts are known (from `cases`); otherwise those rows are "by the tester".
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
    { key: 'pass', n: pass, kind: 'success' },
    { key: 'fail', n: fail, kind: 'danger' },
    { key: 'tester', n: tester, kind: 'outline' },
    { key: 'manual', n: (c.manual || 0) + (c['not-applicable'] || 0), kind: 'outline' },
    { key: 'needs_you', n: (c.parked || 0) + (c['awaiting-tester'] || 0), kind: 'warning' },
    { key: 'queued', n: (c.queued || 0) + (c.running || 0) + (c.draft || 0), kind: 'outline' },
    { key: 'not_run', n: c['not-run'] || 0, kind: 'outline' },
  ].filter((g) => g.n > 0);
}

export function countBadges(t, counts, cases) {
  return countGroups(counts, cases).map((g) => badge(`${t(`wt_count_${g.key}`)} ${g.n}`, g.kind));
}

/** The run's job that is queued or open, if any. */
export function activeJob(jobs) {
  return (jobs || []).find((j) => ACTIVE_JOB.has(j.state)) || null;
}

/** The plan job waiting on its review table, if any. */
export function reviewJob(jobs) {
  return (jobs || []).find((j) => j.state === 'needs-input' && j.ask && j.ask.type === 'review-table') || null;
}

/** A job queued by the agent that the tester has not opened yet. */
export function fromChat(job) {
  return Boolean(job && job.queued_by === 'agent' && !job.opened);
}

export function sourceLabel(source) {
  if (!source || typeof source !== 'object') return NONE;
  if (source.kind === 'figma') return `Figma · ${source.node || NONE}`;
  return String(source.kind || NONE);
}

function baseName(path) {
  const parts = String(path || '').split(/[\\/]/);
  return parts[parts.length - 1] || NONE;
}

export function render(ctx) {
  const { t } = ctx;
  const body = h('div.page');
  mount(ctx.view, body);
  ctx.topbar(topbarTitle(t('nav_runs')), spacer(), h('span.k-note', t('runs_one_row')));
  const head = pageHead(t('runs_title'), t('runs_subtitle'));
  mount(body, head, loading(t, 4));

  const load = () => Promise.all([
    ctx.memo('runs', () => ctx.api.runs()),
    ctx.memo('jobs', () => ctx.api.jobs()),
    ctx.memo('projects', () => ctx.api.projects()),
    ctx.memo('templates', () => ctx.api.templates()),
  ]).then(([runs, jobs, projects, templates]) => {
    if (!ctx.alive()) return;
    ctx.setCount('runs', runs.runs.length);
    draw(ctx, body, head, runs.runs, jobs.jobs || [], projects.projects || [], templates);
  }, (err) => {
    if (!ctx.alive()) return;
    mount(body, head, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
  load();
  ctx.onStoreChange(() => {
    ctx.invalidate('runs');
    ctx.invalidate('jobs');
    load();
  });
}

function draw(ctx, body, head, runs, jobs, projects, templates) {
  const { t } = ctx;
  const byRun = new Map();
  for (const j of jobs) {
    if (!j.run) continue;
    if (!byRun.has(j.run)) byRun.set(j.run, []);
    byRun.get(j.run).push(j);
  }
  // Plan jobs that have no run yet: queued, or importing before `webtest-new` ran.
  const pending = jobs.filter((j) => j.kind === 'webtest-plan' && !j.run && ACTIVE_JOB.has(j.state));
  const rows = [];
  for (const j of pending) {
    rows.push(h('tr', { dataset: { pendingJob: j.id } }, [
      h('td.wrap-cell', [h('a', { href: href(['jobs', j.id]) }, t('runs_importing')),
        fromChat(j) ? h('span.block', badge(t('runs_from_chat'), 'info')) : null]),
      h('td.k-muted', NONE), h('td.k-muted', NONE), h('td.k-muted', NONE),
      h('td.k-note.num', `${timeOrDay(j.created_at)} · ${t(`job_state_${j.state.replace('-', '_')}`)}`),
    ]));
  }
  for (const run of runs) {
    if (!run.readable) {
      rows.push(h('tr', { dataset: { run: run.id } }, [
        h('td.wrap-cell', [h('code.k-mono', run.id), h('span.k-note.block.text-danger', t('runs_unreadable'))]),
        h('td', NONE), h('td', NONE), h('td', NONE), h('td', NONE),
      ]));
      continue;
    }
    const runJobs = byRun.get(run.id) || [];
    const active = activeJob(runJobs);
    const review = reviewJob(runJobs);
    const last = runJobs[0];
    let activity = NONE;
    if (active) activity = `${timeOrDay(active.started_at || active.created_at)} · ${review ? t('runs_wait_confirm') : t(`job_state_${active.state.replace('-', '_')}`)}`;
    else if (run.exports && run.exports.length) activity = timeOrDay(run.exports[run.exports.length - 1].at);
    else if (last) activity = timeOrDay(last.finished_at || last.created_at);
    const exportsBox = run.exports && run.exports.length
      ? h('span.k-note.block', [baseName(run.exports[run.exports.length - 1].workbook), ' · ',
        baseName(run.exports[run.exports.length - 1].report)])
      : null;
    const total = Object.values(run.counts || {}).reduce((a, b) => a + b, 0);
    rows.push(h('tr', { dataset: { run: run.id } }, [
      h('td.wrap-cell', [
        h('a.text-1', { href: href(['runs', run.id]) }, run.name || run.id),
        h('span.k-note.block', h('code.k-mono', run.id)),
        active && fromChat(active) ? h('span.block', badge(t('runs_from_chat'), 'info')) : null,
      ]),
      h('td.wrap-cell', [h('span', sourceLabel(run.source)),
        h('span.k-note.block', `${t('runs_rows', { n: total })} · ${run.project || NONE}`)]),
      h('td.wrap-cell', h('div.row-4', run.confirmed ? countBadges(t, run.counts) : h('span.k-muted', NONE))),
      h('td', review
        ? h('a.k-btn.k-btn--secondary.k-btn--sm', { href: href(['jobs', review.id, 'review-table']), dataset: { openReviewTable: review.id } }, t('runs_open_review'))
        : h('span.num', String(run.open || 0))),
      h('td.wrap-cell', [h('span.k-note.num', activity), exportsBox]),
    ]));
  }
  const table = rows.length
    ? h('div.k-table-wrap', h('div.scroll-x', h('table.k-table.tbl-runs', [
      h('thead', h('tr', [h('th', t('runs_col_run')), h('th', t('runs_col_source')), h('th', t('runs_col_result')),
        h('th', t('runs_col_open')), h('th', t('runs_col_last'))])),
      h('tbody', rows),
    ])))
    : emptyState(t('runs_empty'), t('runs_empty_body'));
  const form = renderRunForm(ctx, { projects, templates });
  mount(body, head, h('div.k-split.split-flex', [
    h('div.k-split__main.split-main', table),
    h('aside.k-split__panel.split-panel', { 'aria-labelledby': 'run-form-title' }, form),
  ]));
  ctx.ready();
}
