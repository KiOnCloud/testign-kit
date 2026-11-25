// Ticket survey: every surveyed ticket with its report revision, whether the report still matches
// develop (an icon whose meaning is its tooltip), its open questions, the suites made from it and
// one action. Opening a ticket shows its report and trace, as before.

import { h, icon, mount, statusIcon } from '../dom.mjs';
import { isoDate, NONE } from '../format.mjs';
import { href } from '../router.mjs';
import { openSurveyForm, prefillFromReport, reportLangs } from './survey-form.mjs';
import { alertBox, breadcrumb, emptyState, errorState, hashReason, loading, pageHead, searchBox, tableBox, ybadge } from './shell.mjs';

const ACTIVE = new Set(['queued', 'offered', 'running', 'needs-input']);
const BUSY_RETRIES = 6;
const BUSY_WAIT_MS = 4000;

/**
 * The freshness of a report as a status icon: {kind, icon, tip}. `surveying` wins: the agent is
 * writing a new revision. `unknown` is a clock while the server is still computing (`busy`),
 * otherwise a neutral icon with the reason as its tip.
 */
export function freshnessIcon(t, freshness, surveying = false) {
  if (surveying) return { kind: 'busy', icon: 'clock', tip: t('fr_surveying') };
  const f = freshness || {};
  if (f.status === 'same') return { kind: 'ok', icon: 'check', tip: t('fr_same') };
  if (f.status === 'moved_no_impact') return { kind: 'ok', icon: 'check', tip: t('fr_moved') };
  if (f.status === 'stale') return { kind: 'warn', icon: 'warning', tip: t('fr_stale') };
  if (f.reason === 'busy') return { kind: 'busy', icon: 'clock', tip: t('fr_checking') };
  return { kind: 'busy', icon: 'dash', tip: hashReason(t, f.reason) || t('hash_unknown') };
}

/** The one action a row offers: survey again when stale, answer open questions, else create a suite. */
export function surveyAction(tk, surveying) {
  if (surveying || tk.error) return null;
  if (tk.freshness && tk.freshness.status === 'stale') return 'resurvey';
  if (tk.open_questions > 0) return 'answer';
  return 'suite';
}

/** Tickets with an active survey job. */
export function surveyingTickets(jobs) {
  return new Set((jobs || []).filter((j) => j.kind === 'survey' && ACTIVE.has(j.state) && j.ticket).map((j) => j.ticket));
}

export function openSurvey(ctx) {
  ctx.memo('config', () => ctx.api.config()).then(
    (cfg) => openSurveyForm(ctx, { configLang: cfg.lang, langs: reportLangs(cfg) }),
    () => openSurveyForm(ctx, {}),
  );
}

/** "Survey again": the form prefilled from the latest report; the tester checks and confirms. */
export function surveyAgain(ctx, ticketId) {
  Promise.all([
    ctx.memo(`ticket:${ticketId}`, () => ctx.api.ticket(ticketId)),
    ctx.memo('config', () => ctx.api.config()).catch(() => ({})),
  ]).then(([ticket, cfg]) => {
    const fm = ticket.latest && ticket.latest.frontmatter ? ticket.latest.frontmatter : { ticket: ticketId };
    const langs = reportLangs(cfg);
    const initial = prefillFromReport({ ticket: ticketId, ...fm }, ctx.prefs.getLastRepo(), cfg.lang, langs);
    openSurveyForm(ctx, { initial, again: true, configLang: cfg.lang, langs });
  }, () => openSurveyForm(ctx, { initial: { ticket: ticketId }, again: true }));
}

function matches(tk, words) {
  if (!words.length) return true;
  const hay = `${tk.id} ${tk.title || ''}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

let search = '';

export function render(ctx) {
  const { t } = ctx;
  ctx.topbar(breadcrumb(t, [{ label: t('nav_group_design') }, { label: t('nav_survey') }]));
  ctx.onKey((event) => {
    if (event.key.toLowerCase() !== 'c') return false;
    openSurvey(ctx);
    return true;
  });
  const head = pageHead(t('survey_title_page'), t('survey_sub'), [
    h('button.yh-btn.yh-btn--primary', { type: 'button', 'aria-keyshortcuts': 'C', dataset: { trigger: 'survey' }, on: { click: () => openSurvey(ctx) } },
      [icon('plus'), t('survey_new')]),
  ]);
  mount(ctx.view, head, loading(t, 4));
  const tableHolder = h('div');
  let lastKey = null;
  let retries = 0;

  const load = () => Promise.all([
    ctx.memo('tickets', () => ctx.api.tickets()),
    ctx.memo('jobs', () => ctx.api.jobs()).catch(() => ({ jobs: [] })),
  ]).then(([data, jobs]) => {
    if (!ctx.alive()) return;
    const list = data.tickets || [];
    const surveying = surveyingTickets(jobs.jobs);
    const key = JSON.stringify([list, [...surveying]]);
    if (key !== lastKey) {
      lastKey = key;
      ctx.setTickets(list);
      draw(list, surveying, data.output_dir);
    }
    ctx.ready();
    // A freshness the server is still computing is asked again a few times.
    if (list.some((tk) => tk.freshness && tk.freshness.reason === 'busy') && retries < BUSY_RETRIES) {
      retries += 1;
      setTimeout(() => {
        if (!ctx.alive()) return;
        ctx.invalidate('tickets');
        load();
      }, BUSY_WAIT_MS);
    }
  }, (err) => {
    if (!ctx.alive()) return;
    lastKey = null;
    mount(ctx.view, head, errorState(t, err, () => ctx.refresh()));
    ctx.ready();
  });

  function draw(list, surveying, outputDir) {
    if (!list.length) {
      mount(ctx.view, head, emptyState(t('tickets_empty_title'), t('tickets_empty_body')));
      return;
    }
    mount(ctx.view, head,
      h('div.toolbar', [searchBox(t('tickets_filter'), search, (v) => { search = v; drawTable(list, surveying); }),
        h('span.push'), h('span.yh-caption.yh-muted.break', [t('tickets_output'), ' ', h('code.mono', outputDir || NONE)])]),
      tableHolder,
      h('p.yh-caption.yh-muted.m-0', t('survey_note')));
    drawTable(list, surveying);
  }

  function actionButton(tk, action) {
    if (action === 'resurvey') {
      return h('button.yh-btn.yh-btn--sm', { type: 'button', dataset: { trigger: 'survey-again', ticket: tk.id },
        on: { click: () => surveyAgain(ctx, tk.id) } }, t('survey_again_btn'));
    }
    if (action === 'answer') return h('a.yh-btn.yh-btn--sm', { href: href(['survey', tk.id]), dataset: { rowAction: 'answer' } }, t('survey_answer'));
    if (action === 'suite') {
      return h('a.yh-btn.yh-btn--sm', { href: href(['suites', 'new'], { kind: 'backlog', ticket: tk.id }), dataset: { rowAction: 'suite' } },
        t('survey_make_suite'));
    }
    return null;
  }

  function suitesCell(tk) {
    const list = tk.suites || [];
    if (!list.length) return h('span.yh-muted', NONE);
    return h('span.stack-2', list.slice(0, 3).map((s) => h('a.lnk', { href: href(['suites', s.id]) },
      s.revision ? `${s.name} · r${s.revision}` : s.name)).concat(list.length > 3 ? [h('span.sub', t('survey_more_suites', { n: list.length - 3 }))] : []));
  }

  function drawTable(list, surveying) {
    const words = search.toLowerCase().split(/\s+/).filter(Boolean);
    const shown = list.filter((tk) => matches(tk, words));
    const rows = shown.map((tk) => {
      const busy = surveying.has(tk.id);
      const fresh = freshnessIcon(t, tk.freshness, busy);
      const title = tk.error ? (tk.latest || tk.id) : (tk.title || tk.latest || tk.id);
      return h('tr', { dataset: { ticket: tk.id } }, [
        h('td.wrap', [h('a.lnk', { href: href(['survey', tk.id]) }, h('strong', tk.id)), h('span.sub', { lang: tk.lang || undefined }, title)]),
        h('td.yh-num', tk.error ? ybadge(t(tk.error === 'unreadable' ? 'tickets_unreadable' : 'tickets_inconsistent'), 'danger')
          : `r${tk.revision} · ${isoDate(tk.generated_at)}`),
        h('td', tk.error ? h('span.yh-muted', NONE) : h('span.st-row', { dataset: { freshness: busy ? 'surveying' : (tk.freshness || {}).status || 'unknown' } }, [
          statusIcon(fresh.kind, fresh.icon, fresh.tip),
          tk.open_questions > 0 ? statusIcon('warn', 'chat', t('fr_questions')) : null,
        ])),
        h('td.is-num', tk.error ? NONE : String(tk.open_questions || 0)),
        h('td', suitesCell(tk)),
        h('td', actionButton(tk, surveyAction(tk, busy))),
      ]);
    });
    mount(tableHolder, shown.length ? tableBox([
      h('th', t('col_ticket')), h('th', t('col_report')), h('th', t('col_fresh')), h('th.is-num', t('col_open_q')),
      h('th', t('nav_suites')), h('th', h('span.sr-only', t('col_action'))),
    ], rows) : alertBox('', 'info', t('tickets_no_match'), null));
  }

  load();
  ctx.onStoreChange(() => {
    ctx.invalidate('jobs');
    load();
  });
}
