// One web test run: header with project, hosts, signed-in scenario and progress; the run's actions
// (Run, Finish with open rows, Export); the review table or sign-in card while a job waits on them;
// the rows table with a filter; and the row panel with its design capture, evidence, expected result,
// the answer form of a parked row and the result form of a row the tester runs.

import { h, icon, mount } from '../dom.mjs';
import { NONE, timeOrDay } from '../format.mjs';
import { askBody } from '../markdown.mjs';
import { href } from '../router.mjs';
import { askTesterName, jobErrorText, queueJob, tooNewNotice } from './job-actions.mjs';
import { signInCard } from './login.mjs';
import { activeJob, classBadge, countStrip, fromChat, NEEDS_YOU, reviewJob, rowStateBadge } from './runs.mjs';
import { mobileMethod } from './review-table.mjs';
import {
  badge, banner, breadcrumb, emptyState, errorState, loading, openDialog, pageHead, pushEscape, radioGroup, spacer,
} from './shell.mjs';

const PARK_ACTIONS = ['delegate', 'self-run', 'skip'];
const FINAL = new Set(['pass', 'fail', 'manual', 'not-applicable', 'self-run', 'not-run']);

/** The rows a filter shows: all, the ones waiting on the tester, or the failed ones. */
export function filterCases(cases, filter) {
  const list = cases || [];
  if (filter === 'needs') return list.filter((c) => NEEDS_YOU.has(c.state) && !c.answer && !c.tester_result);
  if (filter === 'fail') return list.filter((c) => c.state === 'fail' || (c.result && c.result.verdict === 'fail'));
  return list;
}

/** Done and total, for the progress bar: rows in a final state over all rows. */
export function progressOf(cases) {
  const list = cases || [];
  return { done: list.filter((c) => FINAL.has(c.state)).length, total: list.length };
}

/** An i18n key for what is wrong with a parked-row answer, or null when it can be sent. */
export function checkParkAnswer(answer) {
  if (!answer || !PARK_ACTIONS.includes(answer.action)) return 'run_err_pick_action';
  if (answer.action === 'delegate' && !String(answer.preconditions || '').trim()) return 'run_err_preconditions';
  return null;
}

/** The answer body for a parked row: preconditions only when delegating. */
export function parkAnswerBody(answer) {
  const body = { action: answer.action };
  if (answer.action === 'delegate') body.preconditions = String(answer.preconditions || '').trim();
  return body;
}

/** The last path part of "source/r01.png" or "evidence/r02-a1-1.png". */
export function fileName(path) {
  const parts = String(path || '').split('/');
  return parts[parts.length - 1];
}

/** Evidence files of the row's current attempt (older attempts stay on disk, out of view). */
export function currentEvidence(c) {
  return (c.evidence || []).filter((e) => e && e.attempt === c.attempt).map((e) => fileName(e.file));
}

let filter = 'all';

export function render(ctx) {
  const { t, route } = ctx;
  const runId = route.params.run;
  const body = h('div.page.page-wide');
  mount(ctx.view, body);
  const crumbs = (name) => ctx.topbar(breadcrumb(t, [{ label: t('nav_runs'), href: href(['runs']) }, { label: name || runId }]),
    spacer());
  crumbs(runId);
  mount(body, loading(t, 5));
  let selected = route.query && route.query.row ? route.query.row : null;
  let lastKey = null;
  let popEscape = null;

  const load = async () => {
    let run;
    let signInJob = null;
    try {
      run = await ctx.memo(`run:${runId}`, () => ctx.api.run(runId));
      const active = activeJob(run.jobs);
      if (active && active.ask && active.ask.type === 'sign-in') {
        signInJob = await ctx.memo(`job:${active.id}`, () => ctx.api.job(active.id));
      }
    } catch (err) {
      if (!ctx.alive()) return;
      lastKey = null;
      mount(body, errorState(t, err, () => ctx.refresh()));
      ctx.ready();
      return;
    }
    if (!ctx.alive()) return;
    const st = ctx.store.get();
    const stale = Boolean(st && st.open && st.open.progress_stale && (run.jobs || []).some((j) => j.id === st.open.id));
    const key = JSON.stringify([run, signInJob && signInJob.ask, stale, selected, filter]);
    if (key === lastKey) return;
    lastKey = key;
    crumbs(run.name);
    draw(run, signInJob, stale);
    ctx.ready();
  };

  function draw(run, signInJob, stale) {
    const active = activeJob(run.jobs);
    const review = reviewJob(run.jobs);
    const runJob = (run.jobs || []).find((j) => j.kind === 'webtest-run' && j.state !== 'queued' && active === j) || null;
    const finished = Boolean(run.finish && run.finish.at && runJob && Date.parse(run.finish.at) >= Date.parse(runJob.created_at));
    const actions = [];
    if (run.confirmed && !active && !run.closed) {
      actions.push(h('button.k-btn.k-btn--primary.k-btn--sm', { type: 'button', dataset: { runAction: 'run' }, on: { click: () => queue('run') } },
        [icon('play'), t('run_run')]));
    }
    if (runJob && run.open > 0 && !finished && run.can_act !== false) {
      actions.push(h('button.k-btn.k-btn--secondary.k-btn--sm', { type: 'button', dataset: { runAction: 'finish' }, on: { click: () => finishRun(run) } },
        t('run_finish')));
    }
    if (run.confirmed && !active) {
      actions.push(h('button.k-btn.k-btn--secondary.k-btn--sm', { type: 'button', dataset: { runAction: 'export' }, on: { click: () => queue('export') } },
        t('run_export')));
    }
    const { done, total } = progressOf(run.cases);
    const signed = run.signed_in && run.signed_in.scenario ? run.signed_in.scenario : null;
    const head = pageHead(run.name || run.id, null, actions);
    const meta = h('div.run-meta', [
      h('dl.k-props.run-props', [
        h('dt', t('run_project')), h('dd', run.project || NONE),
        h('dt', t('run_hosts')), h('dd', h('code.k-mono.break', (run.hosts || []).join(', ') || NONE)),
        h('dt', t('run_signed_as')), h('dd', signed || NONE),
        h('dt', t('run_template')), h('dd', run.template || NONE),
        run.ticket ? h('dt', t('run_ticket')) : null, run.ticket ? h('dd', run.ticket) : null,
      ]),
      h('div.stack-4.run-progress-box', [
        h('div.row-8', [h('span.k-section-label', t('run_progress')), h('span.k-note.num.push-right', `${done} / ${total}`)]),
        h('progress.run-progress', { value: String(done), max: String(Math.max(total, 1)), 'aria-label': t('run_progress') }),
        h('div.scroll-x', countStrip(t, run.counts, run.cases)),
      ]),
    ]);
    const notices = [];
    if (run.can_act === false && active) notices.push(tooNewNotice(t));
    if (stale) notices.push(banner('warning', t('run_stale_title'), t('run_stale_body')));
    if (!run.confirmed && !review) notices.push(banner('info', t('run_not_confirmed'), t('run_not_confirmed_body')));
    if (review) {
      notices.push(h('div.k-banner.k-banner--info', { role: 'status' }, [icon('info'),
        h('div.k-banner__text', [h('strong', t('run_review_waiting')), h('span', t('run_review_waiting_body'))]),
        h('a.k-btn.k-btn--primary.k-btn--sm', { href: href(['jobs', review.id, 'review-table']), dataset: { openReviewTable: review.id } },
          t('runs_open_review'))]));
    }
    if (active && fromChat(active)) notices.push(banner('info', t('runs_from_chat'), t('run_from_chat_body')));
    if (run.halted) notices.push(banner('warning', t('run_halted'), t('run_halted_body')));
    if (signInJob && signInJob.state === 'needs-input' && signInJob.ask && signInJob.ask.type === 'sign-in') {
      notices.push(signInCard(ctx, signInJob));
    }
    if (finished) notices.push(banner('info', t('run_finished'), t('run_finished_body')));
    const exportsList = (run.exports || []).length ? h('div.stack-4', [h('span.k-section-label', t('run_exports')),
      h('ul.plain-list', run.exports.slice().reverse().map((e) => h('li.k-note.break', [timeOrDay(e.at), ' · ',
        h('code.k-mono', e.workbook || NONE), ' · ', h('code.k-mono', e.report || NONE)])))]) : null;

    const tabs = radioGroup({
      label: t('run_filter'), name: 'run-filter', value: filter,
      options: [
        { value: 'all', label: `${t('run_all')} ${(run.cases || []).length}` },
        { value: 'needs', label: `${t('wt_count_needs_you')} ${filterCases(run.cases, 'needs').length}` },
        { value: 'fail', label: `${t('wt_count_fail')} ${filterCases(run.cases, 'fail').length}` },
      ],
      onChange: (v) => { filter = v; lastKey = null; load(); },
    });
    const shown = filterCases(run.cases, filter);
    const table = shown.length ? h('div.k-table-wrap', h('div.scroll-x', h('table.k-table.tbl-run-rows', [
      h('thead', h('tr', [h('th', '#'), h('th', t('run_col_content')), h('th', t('run_col_screen')), h('th', t('run_col_class')),
        h('th', t('run_col_scenario')), h('th', t('run_col_state'))])),
      h('tbody', shown.map((c) => h('tr.run-row', {
        class: c.row === selected ? 'is-selected' : '', tabindex: '0', dataset: { row: c.row },
        'aria-selected': c.row === selected ? 'true' : 'false',
        on: {
          click: () => select(c.row),
          keydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(c.row); } },
        },
      }, [
        h('td.k-id', c.row),
        h('td.wrap-cell.run-content', c.content || NONE),
        h('td.wrap-cell.run-screen', c.screen && c.screen.url ? h('code.k-mono.break', c.screen.url) : h('span.k-muted', t('run_no_screen'))),
        h('td', classBadge(t, c.class)),
        h('td', c.scenario || NONE),
        h('td', [rowStateBadge(t, c.state, c.not_run_reason), c.answer || c.tester_result ? h('span.k-note.block', t('run_answer_pending')) : null]),
      ]))),
    ]))) : emptyState(filter === 'all' ? t('run_no_rows') : t('run_no_rows_filter'));
    const current = (run.cases || []).find((c) => c.row === selected);
    if (popEscape) { popEscape(); popEscape = null; }
    if (current) popEscape = pushEscape(() => select(current.row));
    mount(body, head, meta, notices.length ? h('div.stack-8', notices) : null, exportsList,
      h('div.k-split.split-flex', [
        h('div.k-split__main.split-main.stack-8', [h('div.k-toolbar.toolbar-wrap', h('div.k-toolbar__group', tabs)), table]),
        current ? h('aside.k-split__panel.split-panel.run-panel', { 'aria-labelledby': 'run-row-title' }, rowPanel(ctx, run, current, () => {
          ctx.invalidate(`run:${runId}`);
          lastKey = null;
          ctx.pollNow();
          load();
        }, () => select(current.row))) : null,
      ]));
  }

  function select(row) {
    selected = selected === row ? null : row;
    lastKey = null;
    load();
  }

  async function queue(mode) {
    const tester = await askTesterName(ctx);
    if (!tester) return;
    const job = await queueJob(ctx, { kind: 'webtest-run', run: runId, tester, mode }, { open: false });
    if (job) {
      ctx.invalidate(`run:${runId}`);
      lastKey = null;
      load();
    }
  }

  function finishRun(run) {
    const dlg = openDialog({
      t, title: t('run_finish_title'),
      body: h('p', t('run_finish_body', { n: run.open })),
      footer: [
        h('button.k-btn.k-btn--ghost', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')),
        h('button.k-btn.k-btn--danger', {
          type: 'button',
          on: {
            click: async () => {
              dlg.close();
              try {
                await ctx.api.finishRun(runId);
                ctx.toast(t('run_finish_sent'));
              } catch (err) {
                ctx.toast(jobErrorText(t, err), 'danger');
              }
              ctx.invalidate(`run:${runId}`);
              lastKey = null;
              ctx.pollNow();
              load();
            },
          },
        }, t('run_finish')),
      ],
    });
  }

  load();
  ctx.onStoreChange((st) => {
    ctx.invalidate(`run:${runId}`);
    if (st && st.open) ctx.invalidate(`job:${st.open.id}`);
    load();
  });
}

function lazyImage(ctx, run, kind, name, alt) {
  const img = h('img.run-shot', { alt, loading: 'lazy' });
  const box = h('div.run-shot-box', [h('span.k-spinner.k-spinner--sm', { 'aria-hidden': 'true' })]);
  ctx.memo(`img:${run}:${kind}:${name}`, () => ctx.api.runImage(run, kind, name)).then((src) => {
    if (!ctx.alive()) return;
    img.src = src;
    mount(box, img);
  }, () => {
    if (!ctx.alive()) return;
    mount(box, h('p.k-note', ctx.t('run_image_missing')));
  });
  return box;
}

function textBlock(label, text) {
  if (!text) return null;
  return h('div.stack-4', [h('span.k-section-label', label), h('p.pre-wrap.panel-text', text)]);
}

export function rowPanel(ctx, run, c, onSent, onClose) {
  const { t } = ctx;
  const evidence = currentEvidence(c);
  const method = mobileMethod(c.viewport, c.mobile_method);
  const parts = [
    h('div.run-shots', [
      h('figure.stack-4', [h('figcaption.k-section-label', t('run_cap_design')),
        c.capture ? lazyImage(ctx, run.id, 'capture', fileName(c.capture), t('run_cap_design')) : h('p.k-note', t('run_no_image'))]),
      h('figure.stack-4', [h('figcaption.k-section-label', t('run_cap_evidence')),
        evidence.length ? h('div.stack-4', evidence.map((f) => lazyImage(ctx, run.id, 'evidence', f, t('run_cap_evidence'))))
          : h('p.k-note', t('run_no_image'))]),
    ]),
    h('dl.k-props', [
      h('dt', t('run_col_screen')), h('dd', c.screen && c.screen.url ? h('code.k-mono.break', c.screen.url) : t('run_no_screen')),
      h('dt', t('run_col_class')), h('dd', classBadge(t, c.class)),
      h('dt', t('run_runner')), h('dd', c.runner ? t(`wt_runner_${c.runner}`) : NONE),
      h('dt', t('run_viewport')), h('dd', c.viewport ? t(`wt_viewport_${c.viewport}`) : NONE),
      method ? h('dt', t('wt_field_mobile_method')) : null, method ? h('dd', t(`wt_mobile_${method}`)) : null,
      h('dt', t('run_col_scenario')), h('dd', c.scenario || NONE),
    ]),
    textBlock(t('run_expected'), c.expected),
    textBlock(t('run_steps'), c.steps),
    textBlock(t('run_preconditions'), c.preconditions),
    c.state === 'parked' || !c.reason ? null : textBlock(t('run_reason_class'), c.reason),
  ];
  if (c.result) {
    const r = c.result;
    parts.push(h('div.stack-4', [h('span.k-section-label', t('run_result')),
      h('div.row-8', [badge(t(`wt_verdict_${String(r.verdict).replace(/-/g, '_')}`), r.verdict === 'pass' ? 'success' : r.verdict === 'fail' ? 'danger' : 'outline'),
        r.url ? h('code.k-mono.k-note.break', r.url) : null]),
      r.actual ? h('p.pre-wrap.panel-text', r.actual) : null]));
  }
  if (c.state === 'not-run' && c.not_run_reason) parts.push(h('p.k-note', rowStateBadge(t, c.state, c.not_run_reason)));
  if (c.state === 'parked' && c.question) parts.push(parkForm(ctx, run, c, onSent));
  if (c.state === 'awaiting-tester' && method) parts.push(h('p.k-note', t(`run_howto_${method}`)));
  if (c.state === 'awaiting-tester') parts.push(resultForm(ctx, run, c, onSent));
  return [
    h('div.k-split__panel-head.panel-head-wrap', [
      h('span.k-id', c.row),
      h('span.ellipsis.run-panel-title', { id: 'run-row-title', tabindex: '-1' }, c.content || c.row),
      h('span.row-4.nowrap.push-right', [rowStateBadge(t, c.state, c.not_run_reason),
        onClose ? h('button.k-btn.k-btn--icon.k-btn--xs', { type: 'button', 'aria-label': t('report_close_detail'), dataset: { closeRow: c.row },
          on: { click: onClose } }, icon('close')) : null]),
    ]),
    h('div.panel-body.stack-16', parts),
  ];
}

function sentAnswer(t, answer) {
  return h('div.k-banner.k-banner--info', { role: 'status' }, [icon('check'), h('div.k-banner__text', [
    h('strong', t('run_answer_sent', { action: t(`run_act_${answer.action.replace('-', '_')}`) })),
    answer.preconditions ? h('span.pre-wrap', answer.preconditions) : null,
    h('span', t('run_answer_wait')),
  ])]);
}

function parkForm(ctx, run, c, onSent) {
  const { t } = ctx;
  const head = [h('span.k-section-label', t('run_agent_parked')), c.question.body ? askBody(c.question.body, run.report_lang) : null];
  if (c.answer) return h('div.ask-form.stack-12', [...head, sentAnswer(t, c.answer)]);
  if (run.can_act === false) return h('div.ask-form.stack-12', [...head, tooNewNotice(t)]);
  const name = `park-${c.row}`;
  let action = null;
  const errorBox = h('div', { role: 'alert' });
  const pre = h('textarea.k-textarea', { id: `${name}-pre`, rows: '3', placeholder: t('run_precond_ph'), maxlength: '2000' });
  const preField = h('div.k-field', [h('label.k-field__label', { for: pre.id }, t('run_precond')), pre,
    h('span.k-field__help', t('run_precond_help'))]);
  const options = PARK_ACTIONS.map((a, i) => {
    const input = h('input', { type: 'radio', name, id: `${name}-${i}`, value: a,
      on: { change: () => { action = a; preField.hidden = a !== 'delegate'; } } });
    const key = a.replace('-', '_');
    return h('label.k-radio.ask-option', { for: input.id }, [input, h('span.k-radio__dot'),
      h('span.stack-2', [h('span.ask-label', t(`run_opt_${key}`)), h('span.k-note.text-2', t(`run_opt_${key}_note`))])]);
  });
  preField.hidden = true;
  const send = h('button.k-btn.k-btn--primary', { type: 'button' }, t('run_send'));
  send.addEventListener('click', async () => {
    const answer = { action, preconditions: pre.value };
    const problem = checkParkAnswer(answer);
    mount(errorBox, problem ? h('p.k-field__error', [icon('warning'), t(problem)]) : null);
    if (problem) return;
    send.disabled = true;
    try {
      await ctx.api.answerRow(run.id, c.question.id, parkAnswerBody(answer));
      ctx.toast(t('ask_sent'));
      onSent();
    } catch (err) {
      send.disabled = false;
      mount(errorBox, h('p.k-field__error', [icon('warning'), runErrorText(t, err)]));
    }
  });
  return h('div.ask-form.stack-12', [...head,
    h('fieldset.stack-8.plain-fieldset', [h('legend.sr-only', t('run_agent_parked')), ...options]),
    preField, errorBox, h('p.k-note', t('run_queue_continues')), h('div.row-8', send)]);
}

function runErrorText(t, err) {
  if (err && err.code === 'session-too-new') return t('run_err_session');
  return jobErrorText(t, err);
}

function resultForm(ctx, run, c, onSent) {
  const { t } = ctx;
  if (c.tester_result) {
    const r = c.tester_result;
    return h('div.ask-form.stack-8', [h('span.k-section-label', t('run_self_title', { row: c.row })),
      h('div.k-banner.k-banner--info', { role: 'status' }, [icon('check'), h('div.k-banner__text', [
        h('strong', t('run_result_saved', { verdict: t(`wt_verdict_${r.verdict}`) })),
        r.actual ? h('span.pre-wrap', r.actual) : null,
        h('span', t('run_answer_wait'))])])]);
  }
  if (run.can_act === false) {
    return h('div.ask-form.stack-8', [h('span.k-section-label', t('run_self_title', { row: c.row })), tooNewNotice(t)]);
  }
  const name = `result-${c.row}`;
  let verdict = null;
  const errorBox = h('div', { role: 'alert' });
  const verdicts = ['pass', 'fail'].map((v, i) => {
    const input = h('input', { type: 'radio', name, id: `${name}-${i}`, value: v, on: { change: () => { verdict = v; } } });
    return h('label.k-radio', { for: input.id }, [input, h('span.k-radio__dot'), h('span', t(`wt_verdict_${v}`))]);
  });
  const actual = h('textarea.k-textarea', { id: `${name}-actual`, rows: '3', maxlength: '4000' });
  const file = h('input.k-input', { type: 'file', id: `${name}-image`, accept: 'image/png,image/jpeg' });
  const save = h('button.k-btn.k-btn--primary', { type: 'button' }, t('run_save_result'));
  save.addEventListener('click', async () => {
    if (!verdict) {
      mount(errorBox, h('p.k-field__error', [icon('warning'), t('run_err_verdict')]));
      return;
    }
    mount(errorBox, null);
    save.disabled = true;
    try {
      const body = { verdict, actual: actual.value.trim() };
      const picked = file.files && file.files[0];
      if (picked) body.image = (await ctx.api.uploadImage(run.id, picked)).image;
      await ctx.api.rowResult(run.id, c.row, body);
      ctx.toast(t('run_result_sent'));
      onSent();
    } catch (err) {
      save.disabled = false;
      const text = err && err.code === 'not-an-image' ? t('run_err_image') : err && err.code === 'too-large' ? t('run_err_image_size') : runErrorText(t, err);
      mount(errorBox, h('p.k-field__error', [icon('warning'), text]));
    }
  });
  return h('div.ask-form.stack-12', [
    h('span.k-section-label', t('run_self_title', { row: c.row })),
    h('fieldset.row-16.plain-fieldset', [h('legend.sr-only', t('run_verdict')), ...verdicts]),
    h('div.k-field', [h('label.k-field__label', { for: actual.id }, t('run_actual')), actual]),
    h('div.k-field', [h('label.k-field__label', { for: file.id }, [t('run_image'), ' ', h('span.k-muted', t('runform_optional'))]), file]),
    errorBox, h('div.row-8', save),
  ]);
}
