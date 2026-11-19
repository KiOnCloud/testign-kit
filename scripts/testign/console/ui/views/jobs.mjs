// Jobs: the queue and history of agent jobs, a detail panel with progress, the agent's question
// (questions asks answered in place, Close review asks opened on their own screen) and the tester's
// actions: Cancel (queued), Mark failed and Release agent (silent), Queue again (failed).

import { h, icon, mount } from '../dom.mjs';
import { dateTime, NONE, timeOrDay } from '../format.mjs';
import { askBody } from '../markdown.mjs';
import { href } from '../router.mjs';
import { renderQuestions } from './ask-form.mjs';
import {
  jobErrorText, jobTitle, kindLabel, queueJob, reasonShort, requeueBody, revOf, shortId, stateBadge, stateGlyph, stateLabel,
} from './job-actions.mjs';
import { banner, emptyState, errorState, loading, pageHead, spacer, topbarTitle } from './shell.mjs';

const ACTIVE = new Set(['queued', 'offered', 'running', 'needs-input']);
const REVIEW_TYPES = new Set(['review-rows', 'confirm-diff', 'paste-pages']);
let tab = 'open';

/** The banner shown wherever the agent matters: none attached, or silent on its job. */
export function agentBanner(t, state) {
  if (!state) return null;
  if (!state.agent || !state.agent.attached) {
    return banner('warning', t('agent_none'), (state.queue || []).length ? t('agent_none_queued') : t('agent_none_body'));
  }
  return null;
}

export function render(ctx) {
  const { t, route } = ctx;
  const st0 = ctx.store.get();
  const implicit = route.params.job ? null : (st0 && st0.open ? st0.open.id : null);
  const selected = route.params.job || implicit;
  const body = h('div.page');
  mount(ctx.view, body);
  ctx.topbar(topbarTitle(t('nav_jobs')), spacer(), h('span.k-note', t('jobs_one_at_a_time')));
  const head = pageHead(t('jobs_title'), t('jobs_subtitle'));
  const bannerBox = h('div');
  const listBox = h('div.k-list', { role: 'listbox', 'aria-label': t('jobs_title') });
  const tabs = h('div.k-tabs.k-tabs--segmented', { role: 'radiogroup', 'aria-label': t('jobs_filter') });
  const detail = h('div.split-panel-jobs');
  mount(body, head, loading(t, 3));
  let jobs = null;
  let detailKey = null;
  let drawnShell = false;
  let tabPicked = false;

  function drawShell() {
    if (drawnShell) return;
    drawnShell = true;
    mount(body, head, bannerBox, h('div.k-split.split-flex', [
      h('div.k-split__main.split-main', [h('div.k-toolbar.toolbar-wrap', [h('div.k-toolbar__group', tabs), h('div.k-toolbar__spacer')]), listBox]),
      selected ? detail : null,
    ]));
  }

  function drawBanner() {
    mount(bannerBox, agentBanner(t, ctx.store.get()));
  }

  function drawList() {
    const open = jobs.filter((j) => ACTIVE.has(j.state));
    const history = jobs.filter((j) => !ACTIVE.has(j.state));
    if (selected && !tabPicked) {
      // Show the selected job's tab until the tester picks a tab here.
      if (open.some((j) => j.id === selected)) tab = 'open';
      else if (history.some((j) => j.id === selected)) tab = 'history';
    }
    mount(tabs, [['open', `${t('jobs_open')} ${open.length}`], ['history', `${t('jobs_history')} ${history.length}`]].map(([v, label]) =>
      h('button.k-tab', {
        type: 'button', role: 'radio', 'aria-checked': tab === v ? 'true' : 'false', class: tab === v ? 'is-active' : '',
        on: { click: () => { tab = v; tabPicked = true; drawList(); } },
      }, label)));
    const shown = tab === 'open' ? open : history;
    const st = ctx.store.get();
    const silentId = st && st.open && st.open.silent ? st.open.id : null;
    mount(listBox, shown.length ? shown.map((j) => h('a.k-issue-row.job-row', {
      href: href(['jobs', j.id]), role: 'option', 'aria-selected': j.id === selected ? 'true' : 'false',
      class: j.id === selected ? 'is-selected' : '', dataset: { job: j.id },
    }, [
      stateGlyph(j.state),
      h('span.k-issue-row__title', jobTitle(t, j)),
      stateBadge(t, { ...j, silent: j.id === silentId }),
      h('span.k-issue-row__date.num', timeOrDay(j.finished_at || j.started_at || j.created_at)),
    ])) : emptyState(tab === 'open' ? t('jobs_empty_open') : t('jobs_empty_history'), tab === 'open' ? t('jobs_empty_open_body') : null));
  }

  async function drawDetail(force) {
    if (!selected) return;
    let job;
    try {
      job = await ctx.memo(`job:${selected}`, () => ctx.api.job(selected));
    } catch (err) {
      if (!ctx.alive()) return;
      detailKey = null;
      mount(detail, h('aside.k-split__panel.split-panel-inner', h('div.panel-body', errorState(t, err, () => ctx.refresh()))));
      return;
    }
    if (!ctx.alive()) return;
    const st = ctx.store.get();
    const attached = Boolean(st && st.agent && st.agent.attached);
    const key = JSON.stringify([job.state, job.ask && job.ask.id, (job.progress || []).length, job.silent, job.reason, attached]);
    if (!force && key === detailKey) return;
    detailKey = key;
    mount(detail, jobPanel(ctx, job, attached));
  }

  async function load() {
    try {
      const data = await ctx.memo('jobs', () => ctx.api.jobs());
      if (!ctx.alive()) return;
      jobs = data.jobs || [];
      drawShell();
      drawBanner();
      drawList();
      await drawDetail(false);
      ctx.ready();
    } catch (err) {
      if (!ctx.alive()) return;
      mount(body, head, errorState(t, err, () => ctx.refresh()));
      drawnShell = false;
      ctx.ready();
    }
  }

  load();
  ctx.onStoreChange((st) => {
    const nowOpen = st && st.open ? st.open.id : null;
    if (!route.params.job && nowOpen !== implicit) {
      ctx.refresh();
      return;
    }
    ctx.invalidate('jobs');
    if (selected) ctx.invalidate(`job:${selected}`);
    load();
  });
  ctx.onKey((event) => {
    const key = event.key.toLowerCase();
    if (key !== 'j' && key !== 'k') return false;
    const rows = [...listBox.querySelectorAll('.job-row')];
    if (!rows.length) return false;
    let i = rows.indexOf(document.activeElement);
    if (i < 0) i = rows.findIndex((r) => r.dataset.job === selected);
    const next = rows[i < 0 ? 0 : Math.max(0, Math.min(rows.length - 1, i + (key === 'j' ? 1 : -1)))];
    next.focus();
    return true;
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
  ].filter(([, v]) => v !== null && v !== undefined && v !== '');
  return h('dl.k-props', rows.flatMap(([k, v]) => [h('dt', t(k)), h('dd', h('span.k-chip.chip-wrap', String(v)))]));
}

function progressList(t, job) {
  const items = job.progress || [];
  if (!items.length) {
    return h('p.k-note', job.state === 'queued' || job.state === 'offered' ? t('jobs_no_progress_yet') : t('jobs_no_progress'));
  }
  const live = job.state === 'running' || job.state === 'needs-input';
  return h('ol.progress-steps', items.map((p, i) => {
    const last = i === items.length - 1;
    return h('li', { class: last && live ? 'is-current' : '' }, [
      stateGlyph(last && live ? 'running' : 'done'),
      h('span.progress-text', p.message),
      h('span.k-note.num.push-right', timeOrDay(p.at)),
    ]);
  }));
}

function jobPanel(ctx, job, attached) {
  const { t } = ctx;
  const parts = [];
  const act = async (fn, okText) => {
    try {
      await fn();
      ctx.toast(okText);
      ctx.pollNow();
    } catch (err) {
      ctx.toast(jobErrorText(t, err), 'danger');
    }
  };

  if (job.state === 'queued' || job.state === 'offered') {
    parts.push(h('p.panel-text', attached ? t('jobs_waiting_turn') : t('agent_none_queued')));
  }
  if (job.silent) {
    parts.push(h('div.k-banner.k-banner--warning', { role: 'status' }, [icon('warning', 'icon-warn'),
      h('div.k-banner__text', [h('strong', t('jobs_silent_title')), h('span', t('jobs_silent_body'))])]));
  }
  if (job.state === 'failed') {
    const moved = job.reason === 'revision-moved';
    parts.push(h('div.k-banner.k-banner--danger', { role: 'status' }, [icon('warning'),
      h('div.k-banner__text', [h('strong', reasonShort(t, job.reason)), h('span', t(`job_reason_${String(job.reason || 'agent').replace(/-/g, '_')}_body`))])]));
    parts.push(h('div.row-8', h('button.k-btn.k-btn--secondary', {
      type: 'button', on: { click: () => queueJob(ctx, requeueBody(job, ctx.prefs.getTesterName())) },
    }, [icon('refresh'), moved ? t('jobs_requeue_latest') : t('jobs_requeue')])));
  }
  if (job.summary) {
    parts.push(h('div.stack-4', [h('span.k-section-label', t('jobs_agent_summary')), h('p.agent-text', job.summary)]));
  }
  if (job.state === 'needs-input' && job.ask) {
    if (job.ask.type === 'questions') {
      parts.push(renderQuestions({
        t, ask: job.ask, lang: job.ui_lang,
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
    } else if (REVIEW_TYPES.has(job.ask.type)) {
      parts.push(h('div.ask-form', [
        h('span.k-section-label', t('ask_title')),
        h('p.panel-text', t(`jobs_ask_${job.ask.type.replace('-', '_')}`)),
        job.ask.body ? askBody(job.ask.body, job.ui_lang) : null,
        h('div.row-8', h('a.k-btn.k-btn--secondary', { href: href(['jobs', job.id, 'review']), dataset: { openReview: '1' } },
          t('jobs_open_review'))),
      ]));
    }
  }
  parts.push(h('div.stack-8', [h('span.k-section-label', t('jobs_progress')), progressList(t, job)]));
  if (job.asked && job.asked.length) {
    parts.push(h('div.stack-4', [h('span.k-section-label', t('jobs_asked')), h('ul.plain-list', job.asked.map((a) =>
      h('li.k-note', [t(`jobs_ask_type_${a.type.replace('-', '_')}`), ' · ',
        a.outcome === 'answered' ? `${t('jobs_answered')} ${a.answered_at ? timeOrDay(a.answered_at) : ''}` : t('jobs_unanswered')])))]));
  }

  const actions = [];
  if (job.state === 'queued') {
    actions.push(h('button.k-btn.k-btn--ghost.k-btn--sm', {
      type: 'button', on: { click: () => act(() => ctx.api.cancelJob(job.id), t('jobs_cancelled')) },
    }, t('jobs_cancel')));
  }
  if (job.silent) {
    actions.push(h('button.k-btn.k-btn--danger.k-btn--sm', {
      type: 'button', on: { click: () => act(() => ctx.api.failJob(job.id), t('jobs_marked')) },
    }, t('jobs_mark_failed')));
    actions.push(h('button.k-btn.k-btn--secondary.k-btn--sm', {
      type: 'button', on: { click: () => act(() => ctx.api.releaseAgent(), t('jobs_released')) },
    }, t('job_release')));
  }

  return h('aside.k-split__panel.split-panel-inner', { 'aria-labelledby': 'job-panel-title' }, [
    h('div.k-split__panel-head.panel-head-wrap', [
      stateGlyph(job.state),
      h('span', { id: 'job-panel-title', tabindex: '-1' }, jobTitle(t, job)),
      h('span.k-id', shortId(job.id)),
      actions.length ? h('div.row-4.push-right', actions) : null,
    ]),
    paramList(t, job),
    h('div.panel-body', parts),
    h('p.k-note.panel-foot', [h('span.k-id', job.id), ' · ', kindLabel(t, job.kind)]),
  ]);
}

