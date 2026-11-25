// Agent & jobs. #/agent: the attached Claude Code session with the tools it reported, and every job
// it works (open and history). #/agent/<job>: one job on its own page with progress, the agent's
// question (questions, sign-in, the Close review forms) and the tester's actions: Cancel (queued),
// Mark failed and Release agent (silent), Queue again (failed, when the job kind can be rebuilt).

import { h, icon, mount, statusIcon } from '../dom.mjs';
import { dateTime, NONE, timeOrDay } from '../format.mjs';
import { askBody } from '../markdown.mjs';
import { uiLang } from '../prefs.mjs';
import { href } from '../router.mjs';
import { renderQuestions } from './ask-form.mjs';
import {
  canRequeue, isLegacy, jobErrorText, jobTitle, kindLabel, queueJob, reasonShort, requeueBody, requeuedNote, revOf, shortId,
  stateBadge, stateLabel, tooNewNotice,
} from './job-actions.mjs';
import { closeReview, forgetDraft, REVIEW_TYPES } from './job-review.mjs';
import { fromChat } from './runs.mjs';
import {
  alertBox, breadcrumb, emptyState, errorState, loading, pageHead, rowLink, segFilter, tableBox, ybadge,
} from './shell.mjs';
import { signInCard } from './sign-in-card.mjs';

const ACTIVE = new Set(['queued', 'offered', 'running', 'needs-input']);
export const CAPABILITIES = ['chrome', 'figma', 'backlog'];
const STATE_ICONS = {
  queued: ['busy', 'clock'], offered: ['busy', 'clock'], running: ['busy', 'play'], 'needs-input': ['warn', 'chat'],
  done: ['ok', 'check'], failed: ['bad', 'close'], cancelled: ['busy', 'dash'],
};
let tab = 'open';

/** A job state as a status icon whose tooltip is the state in words. */
export function jobStateIcon(t, state) {
  const [kind, name] = STATE_ICONS[state] || ['busy', 'dash'];
  return statusIcon(kind, name, stateLabel(t, state));
}

/**
 * The tools the attached session reported, as [{name, kind, icon, tip}]: a check when it has the
 * tool, a cross when it does not, a dash while the session has not reported (null).
 */
export function capabilityIcons(t, capabilities) {
  return CAPABILITIES.map((name) => {
    const label = t(`cap_${name}`);
    if (!capabilities || typeof capabilities[name] !== 'boolean') {
      return { name, kind: 'busy', icon: 'dash', tip: t('cap_unknown', { name: label }) };
    }
    return capabilities[name]
      ? { name, kind: 'ok', icon: 'check', tip: t('cap_yes', { name: label }) }
      : { name, kind: 'bad', icon: 'close', tip: t('cap_no', { name: label }) };
  });
}

/** The alert about the agent: none attached, silent, or listening with its tools. */
export function agentAlert(t, state) {
  if (!state) return null;
  const agent = state.agent || {};
  if (!agent.attached) {
    return alertBox('warning', 'warning', t('agent_none'), (state.queue || []).length ? t('agent_none_queued') : t('agent_none_body'));
  }
  const caps = capabilityIcons(t, agent.capabilities);
  const line = h('span.st-row.caps', { dataset: { capabilities: agent.capabilities ? 'reported' : 'unknown' } }, caps.map((c) =>
    h('span.st-row', { dataset: { cap: c.name } }, [statusIcon(c.kind, c.icon, c.tip), h('span.yh-caption', t(`cap_${c.name}`))])));
  const contact = agent.last_contact ? t('agent_last_contact', { when: timeOrDay(agent.last_contact) }) : null;
  return alertBox('success', 'agent', t('agent_listening'), h('div.yh-stack', [contact ? h('span', contact) : null, line]));
}

/** Where a job's work lives: its run, its suite or its ticket. */
export function jobTarget(job) {
  if (job.run) return href(['runs', job.run]);
  if (job.suite) return href(['suites', job.suite]);
  if (job.ticket && (job.kind === 'survey' || job.kind === 'close' || job.kind === 'testcase')) return href(['survey', job.ticket]);
  return null;
}

export function render(ctx) {
  if (ctx.route.params.job) renderJob(ctx, ctx.route.params.job);
  else renderList(ctx);
}

function renderList(ctx) {
  const { t } = ctx;
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_run') }, { label: t('nav_agent') }]));
  const head = pageHead(t('jobs_title'), t('jobs_subtitle'));
  const alertHolder = h('div');
  const toolbar = h('div.toolbar');
  const tableHolder = h('div');
  mount(ctx.view, head, loading(t, 3));
  let lastKey = null;
  let drawn = false;

  const draw = (jobs) => {
    if (!drawn) { drawn = true; mount(ctx.view, head, alertHolder, toolbar, tableHolder, h('p.yh-caption.yh-muted.m-0', t('jobs_one_at_a_time'))); }
    mount(alertHolder, agentAlert(t, ctx.store.get()));
    const open = jobs.filter((j) => ACTIVE.has(j.state));
    const history = jobs.filter((j) => !ACTIVE.has(j.state));
    mount(toolbar, segFilter(t('jobs_filter'), [{ value: 'open', label: `${t('jobs_open')} ${open.length}` },
      { value: 'history', label: `${t('jobs_history')} ${history.length}` }], tab, (v) => { tab = v; draw(jobs); }));
    const shown = tab === 'open' ? open : history;
    const st = ctx.store.get();
    const silentId = st && st.open && st.open.silent ? st.open.id : null;
    const rows = shown.map((j) => {
      const target = href(['agent', j.id]);
      const work = jobTarget(j);
      return h('tr.click', { dataset: { job: j.id }, on: rowLink(target, ctx.navigate) }, [
        h('td', h('span.st-row', [jobStateIcon(t, j.state), h('a.lnk', { href: target }, jobTitle(t, j))])),
        h('td', [kindLabel(t, j.kind), isLegacy(j) ? h('span.sub', ybadge(t('jobs_legacy'), 'neutral', { dataset: { legacy: j.kind } })) : null]),
        h('td', work ? h('a.lnk.mono', { href: work }, j.run || j.suite || j.ticket) : h('span.yh-muted', NONE)),
        h('td', [stateBadge(t, { ...j, silent: j.id === silentId }),
          fromChat(j) ? h('span.sub', ybadge(t('runs_from_chat'), 'outline')) : null,
          j.queued_after === 'no-older-tab' ? h('span.sub', ybadge(t('jobs_requeued'), 'outline')) : null]),
        h('td.yh-num.yh-muted', timeOrDay(j.finished_at || j.started_at || j.created_at)),
      ]);
    });
    mount(tableHolder, shown.length ? tableBox([h('th', t('col_job')), h('th', t('col_kind')), h('th', t('col_for')),
      h('th', t('col_state')), h('th', t('col_when'))], rows)
      : emptyState(tab === 'open' ? t('jobs_empty_open') : t('jobs_empty_history'), tab === 'open' ? t('jobs_empty_open_body') : null));
  };

  const load = () => ctx.memo('jobs', () => ctx.api.jobs()).then((data) => {
    if (!ctx.alive()) return;
    const jobs = data.jobs || [];
    const st = ctx.store.get();
    const key = JSON.stringify([jobs, st && st.agent, st && st.open && st.open.silent]);
    if (key === lastKey) return;
    lastKey = key;
    draw(jobs);
    ctx.ready();
  }, (err) => {
    if (!ctx.alive()) return;
    lastKey = null;
    drawn = false;
    mount(ctx.view, head, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });
  load();
  ctx.onStoreChange(() => {
    ctx.invalidate('jobs');
    load();
  });
}

function renderJob(ctx, id) {
  const { t } = ctx;
  const crumbs = (title) => ctx.topbar(breadcrumb(t, [{ label: t('nav_group_run') }, { label: t('nav_agent'), href: href(['agent']) },
    { label: title || shortId(id) }]));
  crumbs(null);
  mount(ctx.view, loading(t, 4));
  let lastKey = null;

  const load = async () => {
    let job;
    try {
      job = await ctx.memo(`job:${id}`, () => ctx.api.job(id));
    } catch (err) {
      if (!ctx.alive()) return;
      lastKey = null;
      mount(ctx.view, errorState(t, err, () => ctx.refresh()));
      ctx.ready();
      return;
    }
    if (!ctx.alive()) return;
    const st = ctx.store.get();
    const attached = Boolean(st && st.agent && st.agent.attached);
    const key = JSON.stringify([job.state, job.ask && job.ask.id, (job.progress || []).length, job.silent, job.progress_stale,
      job.reason, attached, job.opened, job.can_answer]);
    if (key === lastKey) return;
    lastKey = key;
    crumbs(jobTitle(t, job));
    mount(ctx.view, ...jobPage(ctx, job, attached, () => { ctx.invalidate(`job:${id}`); lastKey = null; load(); }));
    ctx.ready();
  };
  load();
  ctx.onStoreChange(() => {
    ctx.invalidate(`job:${id}`);
    load();
  });
}

function paramList(t, job) {
  const p = job.params || {};
  const rows = [
    ['jobs_p_state', stateLabel(t, job.state)],
    ['jobs_p_revision', job.base_revision ? `${revOf(job.base_revision)} · ${job.base_revision}` : null],
    ['jobs_p_created', dateTime(job.created_at)],
    ['jobs_p_started', job.started_at ? dateTime(job.started_at) : null],
    ['jobs_p_finished', job.finished_at ? dateTime(job.finished_at) : null],
    ['jobs_p_lang', job.ui_lang],
    ['jobs_p_report_lang', job.report_lang],
    ['jobs_p_tester', p.tester],
    ['jobs_p_mode', p.mode],
    ['jobs_p_template', p.template],
    ['jobs_p_workbook', p.workbook],
    ['jobs_p_focus', Array.isArray(p.focus) ? p.focus.join(', ') : null],
    ['jobs_p_repo', p.repo],
    ['jobs_p_refs', p.master_ref || p.develop_ref ? `${p.master_ref || NONE} · ${p.develop_ref || NONE}` : null],
    ['jobs_p_feature', p.feature],
    ['jobs_p_fetch', job.kind === 'survey' ? (p.fetch ? t('jobs_yes') : t('jobs_no')) : null],
    ['jobs_p_name', p.name],
    ['jobs_p_project', p.project],
    ['jobs_p_base_url', p.base_url],
    ['jobs_p_source', p.source && p.source.kind === 'figma' ? `Figma · ${p.source.node}` : null],
    ['jobs_p_run', job.run || p.run],
    ['jobs_p_suite', job.suite || p.suite],
    ['jobs_p_signed_in', job.signed_in && job.signed_in.scenario ? `${job.signed_in.scenario} · ${t(`jobs_signed_${String(job.signed_in.choice).replace(/-/g, '_')}`)}` : null],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '');
  return h('dl.kv', rows.flatMap(([k, v]) => [h('dt', t(k)), h('dd.break', String(v))]));
}

function progressList(t, job) {
  const items = job.progress || [];
  if (!items.length) {
    return h('p.yh-caption.yh-muted.m-0', job.state === 'queued' || job.state === 'offered' ? t('jobs_no_progress_yet') : t('jobs_no_progress'));
  }
  const live = job.state === 'running' || job.state === 'needs-input';
  return h('ol.progress-steps', items.map((p, i) => {
    const last = i === items.length - 1;
    return h('li', { class: last && live ? 'is-current' : '' }, [
      last && live ? statusIcon('busy', 'clock', t('job_state_running')) : statusIcon('ok', 'check', t('job_state_done')),
      h('span.progress-text', p.message),
      h('span.yh-caption.yh-muted.yh-num.push', timeOrDay(p.at)),
    ]);
  }));
}

/** The question part of a job page, or null. */
function askPart(ctx, job) {
  const { t } = ctx;
  if (job.state !== 'needs-input' || !job.ask) return null;
  if (job.can_answer === false) return tooNewNotice(t);
  if (job.ask.type === 'questions') {
    return h('section.panel', renderQuestions({
      t, ask: job.ask, lang: uiLang(job.ui_lang),
      onSubmit: async (answer) => {
        try {
          await ctx.api.answer(job.id, job.ask.id, answer);
        } catch (err) {
          if (err && err.status === 409) ctx.pollNow();
          const e = new Error(jobErrorText(t, err));
          e.userText = jobErrorText(t, err);
          throw e;
        }
        ctx.toast(t('ask_sent'));
        ctx.pollNow();
      },
    }));
  }
  if (job.ask.type === 'sign-in') return signInCard(ctx, job);
  if (REVIEW_TYPES.has(job.ask.type)) {
    return closeReview(ctx, job, async (answer) => {
      try {
        await ctx.api.answer(job.id, job.ask.id, answer);
        forgetDraft(job.id, job.ask);
        ctx.toast(t('ask_sent'));
        ctx.pollNow();
      } catch (err) {
        ctx.toast(jobErrorText(t, err), 'danger');
        if (err && err.status === 409) ctx.refresh();
      }
    });
  }
  // An ask this console does not answer here (a legacy job's table): show its text only.
  return alertBox('', 'info', t('ask_title'), job.ask.body ? askBody(job.ask.body, uiLang(job.ui_lang)) : t('jobs_ask_elsewhere'));
}

function jobPage(ctx, job, attached, reload) {
  const { t } = ctx;
  const act = async (fn, okText) => {
    try {
      await fn();
      ctx.toast(okText);
      ctx.pollNow();
      reload();
    } catch (err) {
      ctx.toast(jobErrorText(t, err), 'danger');
    }
  };
  const actions = [];
  const work = jobTarget(job);
  if (work) {
    actions.push(h('a.yh-btn', { href: work, dataset: { jobTarget: '1' } },
      job.run ? [icon('play'), t('jobs_open_run')] : job.suite ? [icon('suite'), t('jobs_open_suite')] : [icon('file'), t('jobs_open_ticket')]));
  }
  if (job.state === 'queued') {
    actions.push(h('button.yh-btn', { type: 'button', dataset: { jobAction: 'cancel' },
      on: { click: () => act(() => ctx.api.cancelJob(job.id), t('jobs_cancelled')) } }, t('jobs_cancel')));
  }
  if (job.silent) {
    actions.push(h('button.yh-btn.yh-btn--destructive', { type: 'button', dataset: { jobAction: 'fail' },
      on: { click: () => act(() => ctx.api.failJob(job.id), t('jobs_marked')) } }, t('jobs_mark_failed')));
    actions.push(h('button.yh-btn', { type: 'button', dataset: { jobAction: 'release' },
      on: { click: () => act(() => ctx.api.releaseAgent(), t('jobs_released')) } }, t('job_release')));
  }
  if (job.state === 'failed' && canRequeue(job)) {
    actions.push(h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { jobAction: 'requeue' },
      on: { click: () => queueJob(ctx, requeueBody(job, ctx.prefs.getTesterName())) } },
    [icon('refresh'), job.reason === 'revision-moved' ? t('jobs_requeue_latest') : t('jobs_requeue')]));
  }
  const head = pageHead(jobTitle(t, job), null, actions, [
    jobStateIcon(t, job.state), stateBadge(t, job), h('span', kindLabel(t, job.kind)),
    isLegacy(job) ? ybadge(t('jobs_legacy'), 'neutral', { dataset: { legacy: job.kind } }) : null,
    h('span.mono.yh-muted', shortId(job.id)),
  ]);

  const notices = [];
  if (isLegacy(job)) notices.push(alertBox('', 'info', t('jobs_legacy_t'), t('jobs_legacy_d')));
  if (job.state === 'queued' || job.state === 'offered') {
    notices.push(alertBox('', 'clock', attached ? t('jobs_waiting_turn') : t('agent_none_queued'), null));
  }
  if (job.silent) notices.push(alertBox('warning', 'warning', t('jobs_silent_title'), t('jobs_silent_body')));
  else if (job.progress_stale) notices.push(alertBox('warning', 'warning', t('run_stale_title'), t('run_stale_body')));
  if (job.queued_by === 'agent') notices.push(alertBox('', 'info', t('runs_from_chat'), t('jobs_from_chat_body')));
  const requeued = requeuedNote(t, job);
  if (requeued) notices.push(requeued);
  if (job.state === 'failed') {
    notices.push(alertBox('danger', 'warning', reasonShort(t, job.reason),
      t(`job_reason_${String(job.reason || 'agent').replace(/-/g, '_')}_body`)));
  }
  const ask = askPart(ctx, job);
  const summary = job.summary ? h('section.panel', [h('h2.yh-h3.m-0', t('jobs_agent_summary')), h('p.agent-text.m-0', job.summary)]) : null;
  const asked = job.asked && job.asked.length ? h('section.panel', [h('h2.yh-h3.m-0', t('jobs_asked')), h('ul.plain-list', job.asked.map((a) =>
    h('li.yh-caption', [t(`jobs_ask_type_${a.type.replace(/-/g, '_')}`), ' · ',
      a.outcome === 'answered' ? `${t('jobs_answered')} ${a.answered_at ? timeOrDay(a.answered_at) : ''}` : t('jobs_unanswered')])))]) : null;
  return [
    head,
    notices.length ? h('div.yh-stack', notices) : null,
    h('div.split', [
      h('div.yh-stack', [ask, summary,
        h('section.panel', [h('h2.yh-h3.m-0', t('jobs_progress')), progressList(t, job)]), asked]),
      h('section.panel.sticky', { 'aria-labelledby': 'job-params-title' }, [
        h('h2.yh-h3.m-0', { id: 'job-params-title' }, t('jobs_details')),
        paramList(t, job),
        h('p.yh-caption.yh-muted.m-0.break', [h('code.mono', job.id), ' · ', kindLabel(t, job.kind)]),
      ]),
    ]),
  ];
}
