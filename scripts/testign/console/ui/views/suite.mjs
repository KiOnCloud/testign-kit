// One test suite: its source, state and actions (Export Excel, New run, rename/duplicate/delete),
// the confirm banner while it waits for review, and three tabs. Cases: a searchable table with
// checkboxes, bulk changes and a side form for one case, checked by the server's run rules on every
// save. Source & coverage: the source rows and the cases tracing to each. Checks: the test depth and
// the kit checks of the listed controls it requires. Runs: the runs made from it.

import { h, icon, mount, statusIcon } from '../dom.mjs';
import { NONE, timeOrDay } from '../format.mjs';
import { hostOf } from '../hosts.mjs';
import { href } from '../router.mjs';
import { chooseTemplate } from './job-actions.mjs';
import { stepList } from './spec-steps.mjs';
import { MOBILE_METHODS, mobileMethod } from './mobile-method.mjs';
import { openNewRun } from './new-run.mjs';
import { DEPTHS } from './suite-new.mjs';
import { freshnessIcon } from './survey.mjs';
import { classBadge, resultIcons, runStateBadge } from './runs.mjs';
import { openSuiteMenu, sourceRef, suiteErrorText, suiteStateBadge } from './suites.mjs';
import {
  alertBox, breadcrumb, emptyState, errorState, field, loading, openDialog, pageHead, pushEscape, searchBox, segFilter, selectEl,
  selectWrap, srcBadge, tableBox, ybadge,
} from './shell.mjs';

export const CLASSES = ['sure', 'choice', 'not-web'];
export const RUNNERS = ['agent', 'tester', 'none'];
export const VIEWPORTS = ['pc', 'mobile'];
export const BULK_KEYS = ['class', 'runner', 'scenario'];
const key = (v) => String(v).replace(/-/g, '_');

/** The form's values for a case (or a blank case). */
export function caseToForm(c) {
  const x = c || {};
  return {
    content: x.content || '', preconditions: x.preconditions || '', steps: x.steps || '', expected: x.expected || '',
    screen: (x.screen && x.screen.url) || '', trace: (x.trace || []).join(', '),
    class: x.class || '', runner: x.runner || '', scenario: x.scenario || '', viewport: x.viewport || 'pc',
    mobile_method: x.mobile_method || '', check: x.rule ? `${x.rule}|${x.about}` : '',
  };
}

/** Trace ids typed with commas or spaces. */
export function splitTrace(text) {
  return [...new Set(String(text || '').split(/[\s,、，]+/).map((s) => s.trim()).filter(Boolean))];
}

/**
 * The body of a case save. An unchanged screen keeps its stored name and confidence; a not-web case
 * is run by no one; a pc case has no phone method.
 */
export function formToBody(f, original) {
  const screenText = String(f.screen || '').trim();
  const same = original && original.screen && original.screen.url === screenText;
  const viewport = VIEWPORTS.includes(f.viewport) ? f.viewport : 'pc';
  const cls = f.class || null;
  return {
    content: String(f.content || ''),
    preconditions: String(f.preconditions || ''),
    steps: String(f.steps || ''),
    expected: String(f.expected || ''),
    screen: screenText ? (same ? original.screen : screenText) : null,
    trace: splitTrace(f.trace),
    class: cls,
    runner: cls === 'not-web' ? 'none' : (f.runner || null),
    scenario: f.scenario || null,
    viewport,
    mobile_method: viewport === 'mobile' ? mobileMethod(viewport, f.mobile_method) : null,
    ...checkFields(f.check, original),
  };
}

/** The kit check a case covers, from the form's "rule|about" choice; cleared only when it had one. */
function checkFields(check, original) {
  if (check) {
    const cut = check.indexOf('|');
    return { rule: check.slice(0, cut), about: check.slice(cut + 1) };
  }
  return original && original.rule ? { rule: null, about: null } : {};
}

/** Field messages of a refused save: {field: message} when the error is about `caseId` (or any case). */
export function ruleErrors(err, caseId) {
  if (!err || err.code !== 'case-rules' || !err.details || typeof err.details.errors !== 'object') return {};
  if (caseId && err.details.case && err.details.case !== caseId) return {};
  return { ...err.details.errors };
}

/** The bulk change body for the checked cases. */
export function bulkBody(ids, field, value) {
  if (!BULK_KEYS.includes(field)) throw new RangeError(`bulk edits change ${BULK_KEYS.join(', ')}`);
  return { cases: [...ids], fields: { [field]: value || null } };
}

/** Cases matching the search words and the filter chip. */
export function filterCases(cases, text, filter, problems) {
  const words = String(text || '').toLowerCase().split(/\s+/).filter(Boolean);
  return (cases || []).filter((c) => {
    if (filter === 'choice' && c.class !== 'choice') return false;
    if (filter === 'not-web' && c.class !== 'not-web') return false;
    if (filter === 'problems' && !(problems && problems[c.case])) return false;
    if (!words.length) return true;
    const hay = [c.case, c.content, (c.trace || []).join(' '), c.screen && c.screen.url, c.scenario].filter(Boolean).join(' ').toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

const states = new Map();
function uiFor(id) {
  if (!states.has(id)) states.set(id, { tab: 'cases', selected: null, checked: new Set(), search: '', filter: 'all', problems: {} });
  return states.get(id);
}

export function render(ctx) {
  const { t, route } = ctx;
  const id = route.params.suite;
  const ui = uiFor(id);
  if (route.query && ['cases', 'source', 'checks', 'runs', 'spec'].includes(route.query.tab)) ui.tab = route.query.tab;
  const crumbs = (name) => ctx.topbar(breadcrumb(t, [{ label: t('nav_group_design') }, { label: t('nav_suites'), href: href(['suites']) },
    { label: name || id }]));
  crumbs(null);
  mount(ctx.view, loading(t, 6));
  let lastKey = null;
  let popEscape = null;
  let data = null;
  const settle = (p) => p.then((v) => v, () => null);

  const load = async (force) => {
    let suite;
    let scenarios = [];
    let tickets = null;
    try {
      suite = await ctx.memo(`suite:${id}`, () => ctx.api.suite(id));
      if (suite.project) {
        const sc = await settle(ctx.memo(`scenarios:${suite.project}`, () => ctx.api.scenarios(suite.project)));
        scenarios = (sc && sc.scenarios) || [];
      }
      if (suite.kind === 'backlog') tickets = await settle(ctx.memo('tickets', () => ctx.api.tickets()));
    } catch (err) {
      if (!ctx.alive()) return;
      lastKey = null;
      mount(ctx.view, errorState(t, err, () => ctx.refresh()));
      ctx.ready();
      return;
    }
    if (!ctx.alive()) return;
    const k = JSON.stringify([suite, scenarios.map((s) => [s.name, s.approved])]);
    if (!force && k === lastKey) return;
    lastKey = k;
    crumbs(suite.name);
    data = { suite, scenarios, tickets: tickets ? tickets.tickets : null };
    draw();
    ctx.ready();
  };

  const reload = () => {
    ctx.invalidate(`suite:${id}`);
    ctx.invalidate('suites');
    ctx.invalidate('count:suites');
    return load(true);
  };

  function draw() {
    const { suite, scenarios, tickets } = data;
    const generating = suite.state === 'generating';
    if (!suite.cases.some((c) => c.case === ui.selected) && ui.selected !== 'new') ui.selected = null;
    for (const c of [...ui.checked]) if (!suite.cases.some((x) => x.case === c)) ui.checked.delete(c);
    if (generating) { ui.selected = null; ui.checked.clear(); }

    const exportBtn = h('button.yh-btn', { type: 'button', dataset: { suiteAction: 'export' }, disabled: suite.cases.length ? undefined : true,
      on: { click: () => exportSuite(suite) } }, [icon('download'), t('suite_export')]);
    const ready = suite.state === 'ready';
    const runBtn = h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { suiteAction: 'new-run' }, disabled: ready ? undefined : true,
      title: ready ? undefined : t('suite_confirm_first'), on: { click: () => openNewRun(ctx, { suite: suite.id }) } }, [icon('play'), t('new_run')]);
    const more = h('button.yh-btn.yh-btn--icon.yh-btn--ghost', { type: 'button', 'aria-label': t('suite_more'), dataset: { suiteMenu: suite.id },
      on: { click: () => openSuiteMenu(ctx, suite, (r) => {
        if (r.action === 'delete') { ctx.invalidate('suites'); ctx.invalidate('count:suites'); ctx.navigate(href(['suites'])); }
        else if (r.action === 'duplicate' && r.suite) { ctx.invalidate('suites'); ctx.invalidate('count:suites'); ctx.navigate(href(['suites', r.suite])); }
        else reload();
      }) } }, icon('more'));
    const head = pageHead(suite.name, null, [exportBtn, runBtn, more], [
      srcBadge(t, suite.kind), h('span.mono', sourceRef(t, suite.source)),
      suite.project ? [h('span', '·'), h('span', suite.project)] : null,
      suiteStateBadge(t, suite.state),
      suite.depth ? ybadge(t(`depth_${suite.depth}`), '', { title: t('depth_label'), dataset: { depth: suite.depth } }) : null,
      suite.confirmed_at ? h('span.yh-muted', t('suite_confirmed_at', { when: timeOrDay(suite.confirmed_at) })) : null,
    ]);

    const banners = [];
    if (generating) banners.push(generatingAlert(suite));
    if (suite.state === 'review') banners.push(reviewAlert(suite));
    const problemIds = Object.keys(ui.problems || {});
    if (problemIds.length && suite.state === 'review') {
      banners.push(alertBox('danger', 'warning', t('suite_problems', { n: problemIds.length }),
        h('ul.plain-list', problemIds.slice(0, 6).map((cid) => h('li', [h('code.id', cid), ' ',
          Object.entries(ui.problems[cid]).map(([f, m]) => `${t(`case_f_${key(f)}`)}: ${m}`).join(' · ')])))));
    }
    const tabs = h('div.yh-tabs', { role: 'tablist', 'aria-label': suite.name }, [
      ['cases', t('suite_tab_cases'), suite.cases.length], ['source', t('suite_tab_source')],
      ['checks', t('suite_tab_checks'), suite.checks && suite.checks.missing ? suite.checks.missing : undefined],
      ['runs', t('suite_tab_runs'), (suite.runs || []).length],
      ...(suite.spec && (suite.spec.exists || suite.spec.eligible) ? [['spec', t('suite_tab_spec'), suite.spec.recorded]] : []),
    ].map(([k, label, n]) => h('button.yh-tab', {
      type: 'button', role: 'tab', 'aria-selected': ui.tab === k ? 'true' : 'false', dataset: { tab: k },
      on: { click: () => { ui.tab = k; draw(); } },
    }, [label, n !== undefined ? h('span.yh-tab__count', String(n)) : null])));
    let content;
    if (ui.tab === 'source') content = sourceTab(suite, tickets);
    else if (ui.tab === 'checks') content = checksTab(suite);
    else if (ui.tab === 'runs') content = runsTab(suite);
    else if (ui.tab === 'spec') content = specTab(suite);
    else content = casesTab(suite, scenarios, generating);
    if (popEscape) { popEscape(); popEscape = null; }
    if (ui.tab === 'cases' && ui.selected) popEscape = pushEscape(() => { ui.selected = null; draw(); });
    mount(ctx.view, head, ...banners, tabs, h('div.tabpanel', { role: 'tabpanel' }, content));
  }

  function generatingAlert(suite) {
    const gen = suite.generate || {};
    const last = (gen.progress || [])[0];
    return h('div.yh-alert', { role: 'status', dataset: { generating: '1' } }, [
      h('span.k-spinner.k-spinner--sm', { 'aria-hidden': 'true' }),
      h('div.yh-alert__body', [h('div.yh-alert__title', t('suite_generating_t')),
        h('span', last && last.message ? last.message : t('suite_generating_d'))]),
      gen.id ? h('a.yh-btn.yh-btn--sm', { href: href(['agent', gen.id]) }, t('suite_open_job')) : null,
    ]);
  }

  function reviewAlert(suite) {
    const confirm = h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { suiteAction: 'confirm' },
      disabled: suite.cases.length ? undefined : true }, t('suite_confirm'));
    confirm.addEventListener('click', async () => {
      confirm.disabled = true;
      try {
        await ctx.api.confirmSuite(suite.id, ctx.prefs.getTesterName());
        ui.problems = {};
        ctx.toast(t('suite_confirmed'));
        reload();
      } catch (err) {
        confirm.disabled = false;
        if (err && err.code === 'coverage-missing') {
          ctx.toast(t('checks_confirm_missing', { n: ((err.details && err.details.missing) || []).length }), 'danger');
          ui.tab = 'checks';
          reload();
        } else if (err && err.code === 'case-rules' && err.details) {
          ui.problems = err.details.problems || (err.details.case ? { [err.details.case]: err.details.errors || {} } : {});
          ui.filter = 'problems';
          reload();
        } else {
          ctx.toast(suiteErrorText(t, err), 'danger');
        }
      }
    });
    const agentWrote = suite.cases.some((c) => c.creator === 'agent');
    return alertBox('warning', 'warning', agentWrote ? t('suite_review_agent_t', { n: suite.cases.length }) : t('suite_review_t'),
      t('suite_review_d'), confirm);
  }

  function exportSuite(suite) {
    ctx.memo('templates', () => ctx.api.templates()).then((listing) => {
      const list = (listing.templates || []).filter((x) => x.purpose !== 'webtest');
      if (!list.length) { ctx.toast(t('suite_err_no_case_template'), 'danger'); return null; }
      const def = list.some((x) => x.name === listing.default) ? listing.default : list[0].name;
      return chooseTemplate(ctx, { templates: list, default: def }, t('suite_export_title'));
    }).then(async (name) => {
      if (!name) return;
      try {
        const out = await ctx.api.exportSuite(suite.id, name);
        ctx.toast(t('suite_exported', { name: out.name, rows: out.rows }));
      } catch (err) {
        ctx.toast(suiteErrorText(t, err), 'danger');
      }
    }, (err) => ctx.toast(suiteErrorText(t, err), 'danger'));
  }

  // replay spec -------------------------------------------------------------------------------
  function specTab(suite) {
    const spec = suite.spec || { status: 'missing', cases: [] };
    const errorBox = h('div', { role: 'alert' });
    const check = spec.check || { status: 'missing' };
    const canReview = spec.exists && spec.status === 'draft' && check.status === 'passed';
    const review = h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { specAction: 'review' },
      disabled: canReview ? undefined : true, title: canReview ? undefined : t('spec_review_needs_check') }, t('spec_review'));
    review.addEventListener('click', async () => {
      review.disabled = true;
      try {
        await ctx.api.reviewSpec(suite.id, spec.hash);
        ctx.toast(t('spec_reviewed_toast'));
        reload();
      } catch (err) {
        review.disabled = false;
        mount(errorBox, h('p.k-field__error', [icon('warning'), suiteErrorText(t, err)]));
        if (err && err.code === 'spec-not-ready') reload();
      }
    });
    const removeCase = async (caseId) => {
      try {
        await ctx.api.removeSpecCases(suite.id, [caseId]);
        ctx.toast(t('spec_removed_toast', { id: caseId }));
        reload();
      } catch (err) {
        mount(errorBox, h('p.k-field__error', [icon('warning'), suiteErrorText(t, err)]));
      }
    };
    const status = h('div.st-row', { dataset: { specStatus: spec.status } }, [
      ybadge(t(`spec_status_${spec.status}`), spec.status === 'reviewed' ? 'success' : 'outline'),
      h('span', t('spec_counts', { recorded: spec.recorded || 0, eligible: spec.eligible || 0 })),
      spec.exists ? h('span.yh-muted', t(`spec_check_${check.status}`)) : null,
      spec.reviewed ? h('span.yh-caption.yh-muted', t('spec_reviewed_by', { by: spec.reviewed.by || NONE, when: timeOrDay(spec.reviewed.at) })) : null,
      h('span.push'), spec.status === 'reviewed' ? null : review,
    ]);
    const cards = (spec.cases || []).map((c) => {
      const res = c.check && c.check.result;
      return h('div.k-card.stack-8', { dataset: { specCase: c.case } }, [
        h('div.st-row', [h('code.id', c.case), h('span', c.content || NONE), h('span.push'),
          res ? ybadge(t(`spec_result_${res}`), res === 'ok' ? 'success' : 'outline') : null,
          c.changed ? ybadge(t('spec_case_changed'), 'outline') : null,
          c.steps ? h('button.yh-btn.yh-btn--sm.yh-btn--ghost', { type: 'button', dataset: { specRemove: c.case },
            on: { click: () => removeCase(c.case) } }, [icon('trash'), t('spec_remove')]) : null]),
        h('p.yh-caption.yh-muted.m-0', [t('case_f_expected'), ': ', c.expected || NONE]),
        c.not_eligible ? h('p.yh-caption.text-danger.m-0', c.not_eligible) : null,
        c.steps ? stepList(c.steps) : h('p.yh-caption.yh-muted.m-0', t('spec_not_recorded')),
        c.check && c.check.error ? h('p.yh-caption.text-danger.m-0', String(c.check.error)) : null,
        (c.warnings || []).length ? h('ul.plain-list.yh-caption', c.warnings.map((w) => h('li', { dataset: { specWarning: w.kind } },
          [icon('warning'), ' ', t(`spec_warn_${w.kind}`, { step: w.step === null || w.step === undefined ? '' : w.step + 1, value: w.value || '' })]))) : null,
      ]);
    });
    return h('div.stack-16', [
      alertBox('', 'info', t('spec_how_t'), t('spec_how_d')),
      status, errorBox,
      cards.length ? h('div.stack-8', cards) : h('p.yh-muted', t('spec_none')),
    ]);
  }

  // cases -----------------------------------------------------------------------------------
  function casesTab(suite, scenarios, generating) {
    const tableHolder = h('div');
    const bulkHolder = h('div');
    const problems = ui.problems || {};
    const filters = [{ value: 'all', label: `${t('filter_all')} ${suite.cases.length}` },
      { value: 'choice', label: `${t('suite_f_choice')} ${suite.cases.filter((c) => c.class === 'choice').length}` },
      { value: 'not-web', label: `${t('suite_f_notweb')} ${suite.cases.filter((c) => c.class === 'not-web').length}` }];
    if (Object.keys(problems).length) filters.push({ value: 'problems', label: `${t('suite_f_problems')} ${Object.keys(problems).length}` });
    if (!filters.some((f) => f.value === ui.filter)) ui.filter = 'all';
    const redraw = () => draw();
    const toolbar = h('div.toolbar', [
      searchBox(t('suite_search_cases'), ui.search, (v) => { ui.search = v; drawTable(); }),
      segFilter(t('suite_filter_cases'), filters, ui.filter, (v) => { ui.filter = v; redraw(); }),
      h('span.push'),
      generating ? null : h('button.yh-btn.yh-btn--sm', { type: 'button', dataset: { addCase: '1' },
        on: { click: () => { ui.selected = 'new'; redraw(); } } }, [icon('plus'), t('suite_add_case')]),
    ]);

    function drawBulk() {
      if (generating || !ui.checked.size) {
        mount(bulkHolder, h('p.yh-caption.yh-muted.m-0', generating ? t('suite_read_only') : t('suite_bulk_hint')));
        return;
      }
      mount(bulkHolder, bulkBar(ctx, suite, scenarios, ui, () => { ui.checked.clear(); reload(); }));
    }

    function drawTable() {
      const shown = filterCases(suite.cases, ui.search, ui.filter, problems);
      const all = h('input', { type: 'checkbox', 'aria-label': t('rt_select_all'), disabled: generating ? true : undefined,
        checked: shown.length && shown.every((c) => ui.checked.has(c.case)) ? true : undefined,
        on: { change: (e) => { for (const c of shown) { if (e.target.checked) ui.checked.add(c.case); else ui.checked.delete(c.case); } drawTable(); drawBulk(); } } });
      const rows = shown.map((c) => {
        const pick = h('input', { type: 'checkbox', 'aria-label': t('rt_select', { row: c.case }), disabled: generating ? true : undefined,
          checked: ui.checked.has(c.case) ? true : undefined,
          on: { change: (e) => { if (e.target.checked) ui.checked.add(c.case); else ui.checked.delete(c.case); drawBulk(); } } });
        const issue = problems[c.case];
        return h('tr.click', {
          class: c.case === ui.selected ? 'is-sel' : '', tabindex: '0', dataset: { case: c.case },
          'aria-selected': c.case === ui.selected ? 'true' : 'false',
          on: {
            click: (e) => {
              const el = e && e.target;
              if (el && typeof el.closest === 'function' && el.closest('label, input')) return;
              if (generating) return;
              ui.selected = ui.selected === c.case ? null : c.case;
              redraw();
            },
            keydown: (e) => { if ((e.key === 'Enter' || e.key === ' ') && !generating && e.target === e.currentTarget) { e.preventDefault(); ui.selected = c.case; redraw(); } },
          },
        }, [
          h('td.is-check', h('label.yh-check', [pick, h('span.yh-check__box')])),
          h('td.id', issue ? h('span.st-row', [c.case, statusIcon('bad', 'warning',
            Object.entries(issue).map(([f, m]) => `${t(`case_f_${key(f)}`)}: ${m}`).join(' · '))]) : c.case),
          h('td.id', (c.trace || []).join(', ') || NONE),
          h('td.wrap', { lang: suite.case_lang || undefined }, c.content || h('span.yh-muted', NONE)),
          h('td.mono.yh-muted', (c.screen && c.screen.url) || NONE),
          h('td', classBadge(t, c.class)),
          h('td', c.runner ? t(`case_runner_${c.runner}`) : NONE),
          h('td.mono', c.scenario || NONE),
          h('td', c.viewport === 'mobile' ? t(`wt_mobile_${mobileMethod(c.viewport, c.mobile_method)}`) : t('wt_viewport_pc')),
        ]);
      });
      mount(tableHolder, shown.length ? tableBox([
        h('th.is-check', h('label.yh-check', [all, h('span.yh-check__box')])), h('th', '#'), h('th', t('case_f_trace')),
        h('th', t('case_f_content')), h('th', t('case_f_screen')), h('th', t('case_f_class')), h('th', t('case_f_runner')),
        h('th', t('case_f_scenario')), h('th', t('case_f_viewport')),
      ], rows) : (suite.cases.length ? alertBox('', 'info', t('suite_no_match'), null)
        : emptyState(generating ? t('suite_generating_t') : t('suite_no_cases'), generating ? t('suite_generating_d') : t('suite_no_cases_body'))));
    }

    drawTable();
    drawBulk();
    const selected = ui.selected === 'new' ? null : suite.cases.find((c) => c.case === ui.selected);
    const form = !generating && (ui.selected === 'new' || selected) ? caseForm(ctx, {
      suite, c: selected || null, scenarios,
      onClose: () => { ui.selected = null; redraw(); },
      onSaved: (saved) => { ui.selected = saved && saved.case ? saved.case : ui.selected; if (ui.problems) delete ui.problems[ui.selected]; reload(); },
      onDeleted: () => { ui.selected = null; reload(); },
    }) : null;
    return h('div.split', { class: form ? '' : 'split--single' }, [h('div.yh-stack', [toolbar, bulkHolder, tableHolder]), form]);
  }

  // source & coverage -----------------------------------------------------------------------
  function sourceTab(suite, tickets) {
    const s = suite.source || {};
    const cov = suite.coverage || {};
    const parts = [];
    const bar = [srcBadge(t, suite.kind), h('strong', sourceRef(t, s))];
    if (suite.kind === 'backlog') {
      if (s.develop_head) bar.push(h('span.yh-caption.yh-muted.mono', `develop ${String(s.develop_head).slice(0, 7)}`));
      if (s.merge_base) bar.push(h('span.yh-caption.yh-muted.mono', `master ${String(s.merge_base).slice(0, 7)}`));
      const tk = (tickets || []).find((x) => x.id === s.ticket);
      if (tk && tk.revision === s.revision) {
        const fresh = freshnessIcon(t, tk.freshness);
        bar.push(statusIcon(fresh.kind, fresh.icon, fresh.tip));
      }
      bar.push(h('a.lnk', { href: href(['survey', s.ticket]) }, t('suite_open_report')));
      if (tk && Number.isFinite(tk.revision) && tk.revision > (s.revision || 0)) {
        parts.push(alertBox('warning', 'warning', t('suite_newer_report', { rev: tk.revision }), t('suite_newer_report_d'),
          h('a.yh-btn.yh-btn--sm', { href: href(['suites', 'new'], { kind: 'backlog', ticket: s.ticket }) }, [icon('refresh'), t('suite_regen')])));
      }
    }
    if (suite.kind === 'figma' && s.url && hostOf(s.url)) {
      bar.push(h('a.lnk', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, [t('suite_open_figma'), ' ', icon('external', 'k-icon--sm')]));
    }
    parts.unshift(h('div.toolbar', bar));
    if (cov.error) parts.push(alertBox('danger', 'warning', t('suite_cov_error'), cov.error));
    if (cov.mode === 'generate' && (cov.rows || []).length) {
      const covered = cov.rows.filter((r) => (r.cases || []).length).length;
      parts.push(tableBox([h('th', t('cov_row')), h('th', t('cov_text')), h('th.is-num', t('col_cases')), h('th', t('case_f_trace'))],
        cov.rows.map((r) => h('tr', { dataset: { covRow: r.id } }, [
          h('td.id', r.id),
          h('td.wrap', { lang: suite.case_lang || undefined }, r.label || NONE),
          h('td.is-num', (r.cases || []).length ? String(r.cases.length) : statusIcon('warn', 'warning', t('cov_missing_tip'))),
          h('td.mono.yh-muted', (r.cases || []).join(', ') || NONE),
        ])), { narrow: true }));
      parts.push(h('p.yh-caption.yh-muted.m-0', t('cov_note', { covered, total: cov.rows.length })));
      if ((cov.orphans || []).length) parts.push(alertBox('', 'info', t('cov_orphans', { n: cov.orphans.length }), cov.orphans.join(', ')));
    } else if (cov.mode === 'extract') {
      parts.push(h('dl.kv', suite.kind === 'excel'
        ? [h('dt', t('wiz_excel_file')), h('dd.mono', s.file || NONE), h('dt', t('wiz_excel_template')), h('dd', s.template || NONE),
          h('dt', t('wiz_excel_sheet')), h('dd', s.sheet || NONE)]
        : [h('dt', t('suite_figma_file')), h('dd.mono', s.file || NONE), h('dt', t('suite_figma_node')), h('dd.mono', s.node || NONE)]));
      parts.push(h('p.yh-caption.yh-muted.m-0', t(suite.kind === 'excel' ? 'cov_excel_note' : 'cov_figma_note')));
    } else if (!cov.error) {
      parts.push(h('p.yh-caption.yh-muted.m-0', s.note ? s.note : t('cov_manual_note')));
    }
    return h('div.yh-stack', parts);
  }

  // test depth and checks ------------------------------------------------------------------
  function checksTab(suite) {
    const view = suite.checks;
    const generating = suite.state === 'generating';
    const errorBox = h('div', { role: 'alert' });
    const fail = (err) => mount(errorBox, h('p.k-field__error', [icon('warning'), suiteErrorText(t, err)]));
    const current = view ? view.depth : null;
    const pick = selectEl({ id: 'suite-depth', disabled: generating ? true : undefined },
      [...(current ? [] : [['', t('depth_none')]]), ...DEPTHS.map((d) => [d, t(`depth_${d}`)])], current || '');
    const apply = h('button.yh-btn.yh-btn--sm', { type: 'button', dataset: { checksAction: 'depth' }, disabled: true }, t('depth_change'));
    pick.addEventListener('change', () => { apply.disabled = !pick.value || pick.value === current; });
    apply.addEventListener('click', async () => {
      apply.disabled = true;
      try {
        const out = await ctx.api.suiteDepth(suite.id, pick.value);
        ctx.toast(out.more ? t('depth_changed_more', { depth: t(`depth_${out.depth}`) }) : t('depth_changed', { depth: t(`depth_${out.depth}`) }));
        reload();
      } catch (err) { apply.disabled = false; fail(err); }
    });
    const parts = [h('div.toolbar', [field(t('depth_label'), selectWrap(pick), current ? t(`depth_${current}_d`) : t('depth_none_d'), null, 'suite-depth'), apply]), errorBox];
    if (!view) return h('div.yh-stack', parts);
    const canExtend = ['figma', 'backlog'].includes(suite.kind) && !generating && view.missing > 0;
    if (canExtend) {
      const extend = h('button.yh-btn.yh-btn--sm.yh-btn--primary', { type: 'button', dataset: { checksAction: 'extend' } }, [icon('plus'), t('checks_extend')]);
      extend.addEventListener('click', async () => {
        extend.disabled = true;
        try {
          await ctx.api.suiteDepth(suite.id, view.depth, true, ctx.lang);
          ctx.toast(t('checks_extend_queued'));
          reload();
        } catch (err) { extend.disabled = false; fail(err); }
      });
      parts.push(alertBox('warning', 'warning', t('checks_missing_t', { n: view.missing }), t('checks_missing_d'), extend));
    } else if (view.missing > 0) {
      parts.push(alertBox('warning', 'warning', t('checks_missing_t', { n: view.missing }), t('checks_missing_manual_d')));
    }
    if ((view.problems || []).length) {
      parts.push(alertBox('danger', 'warning', t('checks_problems', { n: view.problems.length }),
        h('ul.plain-list', view.problems.slice(0, 6).map((p) => h('li.mono', p)))));
    }
    if (!view.controls) {
      parts.push(h('div.yh-empty', [h('div.yh-empty__title', t('checks_no_controls_t')), h('div.yh-empty__text', t('checks_no_controls_d'))]));
      return h('div.yh-stack', parts);
    }
    parts.push(h('p.yh-caption.yh-muted.m-0', t('checks_summary', { required: view.required, covered: view.covered, skipped: view.skipped,
      missing: view.missing, controls: view.controls })));
    const statusCell = (r) => {
      if (r.status === 'covered') return statusIcon('ok', 'check', t('checks_st_covered'));
      if (r.status === 'skipped') return ybadge(t('checks_st_skipped'), 'neutral');
      if (r.status === 'optional') return h('span.yh-muted', t('checks_st_optional'));
      return ybadge(r.partial ? t('checks_st_partial') : t('checks_st_missing'), 'warning');
    };
    const actionCell = (r) => {
      if (!r.required || generating) return r.reason ? h('span.wrap', r.reason) : NONE;
      if (r.status === 'skipped') {
        const undo = h('button.yh-btn.yh-btn--sm.yh-btn--ghost', { type: 'button', dataset: { checksAction: 'unskip' } }, t('checks_unskip'));
        undo.addEventListener('click', async () => {
          undo.disabled = true;
          try { await ctx.api.suiteSkip(suite.id, r.rule, r.about, '', ctx.prefs.getTesterName()); reload(); } catch (err) { undo.disabled = false; fail(err); }
        });
        return h('div.yh-stack.skip-cell', [h('span', r.reason), undo]);
      }
      if (r.status !== 'missing') return NONE;
      const skip = h('button.yh-btn.yh-btn--sm', { type: 'button', dataset: { checksAction: 'skip' } }, t('checks_skip'));
      skip.addEventListener('click', () => openSkip(suite, r));
      return skip;
    };
    parts.push(tableBox([h('th', t('checks_col_group')), h('th', t('checks_col_check')), h('th', t('checks_col_control')),
      h('th', t('checks_col_required')), h('th', t('col_state')), h('th', t('col_cases')), h('th', t('checks_col_reason'))],
    view.rows.map((r) => h('tr', { class: r.required ? '' : 'is-optional', dataset: { check: `${r.rule}|${r.about}` } }, [
      h('td', t(`checks_group_${r.group}`)),
      h('td', { title: r.case_hint }, r.label),
      h('td.wrap-cell', { title: r.about, lang: suite.case_lang || undefined }, [r.control, r.inputs.length ? h('span.yh-caption.yh-muted', ` (${r.inputs.join(', ')})`) : null]),
      h('td', r.required ? t('checks_yes') : t('checks_from', { depth: t(`depth_${r.level}`) })),
      h('td', statusCell(r)),
      h('td.mono.yh-muted', r.cases.length ? `${r.cases.join(', ')}${r.need > 1 ? ` / ${r.need}` : ''}` : (r.need > 1 ? `0 / ${r.need}` : NONE)),
      h('td.wrap.reason-cell', actionCell(r)),
    ])), { label: t('suite_tab_checks') }));
    parts.push(h('p.yh-caption.yh-muted.m-0', t('checks_note')));
    return h('div.yh-stack', parts);
  }

  function openSkip(suite, r) {
    const reason = h('textarea.yh-textarea', { id: 'skip-reason', rows: '3', maxlength: '500' });
    const errorBox = h('div', { role: 'alert' });
    const save = h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { checksAction: 'skip-save' } }, t('checks_skip'));
    const dlg = openDialog({
      t, title: t('checks_skip_title', { check: r.label, control: r.control }),
      body: h('div.stack-16', [h('p.k-note', r.case_hint), field(t('checks_skip_reason'), reason, t('checks_skip_help')), errorBox]),
      footer: [save],
    });
    save.addEventListener('click', async () => {
      if (!String(reason.value || '').trim()) { mount(errorBox, h('p.k-field__error', [icon('warning'), t('checks_skip_need_reason')])); return; }
      save.disabled = true;
      try {
        await ctx.api.suiteSkip(suite.id, r.rule, r.about, String(reason.value).trim(), ctx.prefs.getTesterName());
        dlg.close();
        reload();
      } catch (err) {
        save.disabled = false;
        mount(errorBox, h('p.k-field__error', [icon('warning'), suiteErrorText(t, err)]));
      }
    });
  }

  // runs ------------------------------------------------------------------------------------
  function runsTab(suite) {
    const list = suite.runs || [];
    if (!list.length) {
      return h('div.yh-empty', [h('div.yh-empty__title', t('suite_no_runs_t')), h('div.yh-empty__text', t('suite_no_runs_d'))]);
    }
    const runsTable = tableBox([h('th', t('col_run')), h('th', t('col_env')), h('th', t('col_result')), h('th', t('col_state')), h('th', t('col_when'))],
      list.map((r) => h('tr', { dataset: { run: r.id } }, [
        h('td', [h('a.lnk.mono', { href: href(['runs', r.id]) }, r.id), r.name ? h('span.sub', r.name) : null,
          suite.suite_digest && r.suite_digest && r.suite_digest !== suite.suite_digest ? h('span.sub', t('suite_run_older')) : null]),
        h('td.mono.yh-muted', hostOf(r.base_url) || r.base_url || NONE),
        h('td', resultIcons(t, r.counts)),
        h('td', runStateBadge(t, r.closed ? 'done' : 'open')),
        h('td.yh-num.yh-muted', timeOrDay(r.created_at)),
      ])));
    return h('div.stack-16', [runsTable, resultsMatrix(t, suite.results)]);
  }

  load();
  ctx.onStoreChange(() => {
    // Only a generating suite changes behind the tester's back: its job writes the cases.
    if (!data || data.suite.state !== 'generating') return;
    ctx.invalidate(`suite:${id}`);
    load();
  });
}

/** The bulk bar for the checked cases: change class, runner or scenario, or delete them. */
function bulkBar(ctx, suite, scenarios, ui, after) {
  const { t } = ctx;
  const errorBox = h('div', { role: 'alert' });
  const values = {
    class: CLASSES.map((c) => [c, t(`case_class_${key(c)}`)]),
    runner: RUNNERS.map((r) => [r, t(`case_runner_${r}`)]),
    scenario: [['', t('case_no_scenario')], ...scenarios.map((s) => [s.name, s.label ? `${s.name} · ${s.label}` : s.name])],
  };
  let fieldName = 'class';
  const valueHolder = h('span');
  const fieldSel = selectEl({ id: 'bulk-field', class: 'yh-input--sm', 'aria-label': t('suite_bulk_field'),
    on: { change: (e) => { fieldName = e.target.value; drawValue(); } } }, BULK_KEYS.map((k) => [k, t(`case_f_${k}`)]), fieldName);
  let valueSel = null;
  function drawValue() {
    valueSel = selectEl({ id: 'bulk-value', class: 'yh-input--sm', 'aria-label': t('suite_bulk_value') }, values[fieldName]);
    mount(valueHolder, selectWrap(valueSel));
  }
  drawValue();
  const fail = (err) => {
    const rules = ruleErrors(err);
    const detail = Object.entries(rules).map(([f, m]) => `${t(`case_f_${key(f)}`)}: ${m}`).join(' · ');
    mount(errorBox, h('p.k-field__error', [icon('warning'), detail ? `${err.details.case || ''} ${detail}` : suiteErrorText(t, err)]));
  };
  const apply = h('button.yh-btn.yh-btn--sm', { type: 'button', dataset: { bulkApply: '1' } }, t('rt_apply'));
  apply.addEventListener('click', async () => {
    apply.disabled = true;
    try {
      await ctx.api.bulkCases(suite.id, bulkBody(ui.checked, fieldName, valueSel.value));
      ctx.toast(t('suite_bulk_done', { n: ui.checked.size }));
      after();
    } catch (err) { apply.disabled = false; fail(err); }
  });
  const del = h('button.yh-btn.yh-btn--sm.yh-btn--destructive', { type: 'button', dataset: { bulkDelete: '1' } }, [icon('trash'), t('delete')]);
  del.addEventListener('click', () => {
    const n = ui.checked.size;
    const dlg = openDialog({
      t, title: t('suite_delete_cases_title', { n }), body: h('p', t('suite_delete_cases_body', { n })),
      footer: [
        h('button.yh-btn', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')),
        h('button.yh-btn.yh-btn--destructive', { type: 'button', dataset: { confirmDelete: '1' }, on: { click: async () => {
          dlg.close();
          try {
            await ctx.api.bulkCases(suite.id, { cases: [...ui.checked], delete: true });
            ctx.toast(t('suite_cases_deleted', { n }));
            after();
          } catch (err) { fail(err); }
        } } }, t('delete')),
      ],
    });
  });
  return h('div.stack-8', [h('div.toolbar.bulk-bar', [
    h('strong.yh-caption', t('rt_selected', { n: ui.checked.size })),
    selectWrap(fieldSel), valueHolder, apply, h('span.push'), del,
    h('button.yh-btn.yh-btn--ghost.yh-btn--sm', { type: 'button', on: { click: () => { ui.checked.clear(); after(); } } }, t('rt_clear')),
  ]), errorBox]);
}

/**
 * The side form for one case (or a new one). Every save goes through the server's run rules; a
 * refused field shows the server's message under it.
 */
export function caseForm(ctx, { suite, c, scenarios, onClose, onSaved, onDeleted }) {
  const { t } = ctx;
  const f = caseToForm(c);
  const errors = {};
  const errorBoxes = {};
  const controls = {};
  const formError = h('div', { role: 'alert' });
  const lang = suite.case_lang || undefined;
  const id = (name) => `case-${name}`;

  const errorLine = (name) => {
    errorBoxes[name] = h('div');
    return errorBoxes[name];
  };
  const showErrors = (map) => {
    for (const [name, box] of Object.entries(errorBoxes)) {
      mount(box, map[name] ? h('p.k-field__error', [icon('warning'), map[name]]) : null);
      if (controls[name] && controls[name].classList) controls[name].classList.toggle('is-error', Boolean(map[name]));
    }
    const other = Object.entries(map).filter(([name]) => !errorBoxes[name]);
    mount(formError, other.length ? h('p.k-field__error', [icon('warning'), other.map(([n, m]) => `${n}: ${m}`).join(' · ')]) : null);
  };
  const text = (name, rows) => {
    controls[name] = h('textarea.yh-textarea.sm', { id: id(name), rows: String(rows), lang, value: f[name],
      on: { input: (e) => { f[name] = e.target.value; } } });
    return field(t(`case_f_${name}`), controls[name], null, errorLine(name));
  };
  const input = (name, placeholder) => {
    controls[name] = h('input.yh-input.yh-input--sm.mono', { type: 'text', id: id(name), value: f[name], placeholder,
      spellcheck: 'false', autocomplete: 'off', on: { input: (e) => { f[name] = e.target.value; } } });
    return field(t(`case_f_${name}`), controls[name], null, errorLine(name));
  };
  const methodBox = h('div');
  const runnerBox = h('div');
  const choice = (name, options, onChange) => {
    controls[name] = selectEl({ id: id(name), class: 'yh-input--sm',
      on: { change: (e) => { f[name] = e.target.value; if (onChange) onChange(); } } }, options, f[name]);
    return field(t(`case_f_${name}`), selectWrap(controls[name]), null, errorLine(name), id(name));
  };
  const drawRunner = () => {
    if (f.class === 'not-web') f.runner = 'none';
    mount(runnerBox, choice('runner', [['', NONE], ...RUNNERS.map((r) => [r, t(`case_runner_${r}`)])]));
    if (f.class === 'not-web' && controls.runner) controls.runner.disabled = true;
  };
  const drawMethod = () => {
    mount(methodBox, f.viewport === 'mobile'
      ? choice('mobile_method', MOBILE_METHODS.map((m) => [m, t(`wt_mobile_${m}`)]))
      : null);
    if (f.viewport === 'mobile' && !f.mobile_method) f.mobile_method = 'device';
  };
  const scenarioOptions = [['', t('case_no_scenario')], ['none', t('login_l_none')],
    ...scenarios.map((s) => [s.name, s.approved ? s.name : `${s.name} · ${t('rt_not_approved')}`])];
  if (f.scenario && !scenarioOptions.some(([v]) => v === f.scenario)) scenarioOptions.push([f.scenario, f.scenario]);
  const checkRows = (suite.checks && suite.checks.rows) || [];
  const checkOptions = [['', t('case_no_check')], ...checkRows.map((r) => [`${r.rule}|${r.about}`,
    `${r.label} · ${r.control}${r.required ? '' : ` (${t('checks_from', { depth: t(`depth_${r.level}`) })})`}`])];
  if (f.check && !checkOptions.some(([v]) => v === f.check)) checkOptions.push([f.check, f.check.replace('|', ' · ')]);

  drawRunner();
  drawMethod();
  const save = h('button.yh-btn.yh-btn--primary.yh-btn--sm', { type: 'button', dataset: { caseSave: '1' } }, t('save'));
  const dup = c ? h('button.yh-btn.yh-btn--ghost.yh-btn--sm', { type: 'button', dataset: { caseDuplicate: '1' } }, [icon('copy'), t('duplicate')]) : null;
  const del = c ? h('button.yh-btn.yh-btn--ghost.yh-btn--sm', { type: 'button', dataset: { caseDelete: '1' } }, [icon('trash'), t('delete')]) : null;
  const busy = (on) => { for (const b of [save, dup, del]) if (b) b.disabled = on; };

  const submit = async (body, isNew) => {
    busy(true);
    showErrors({});
    try {
      const out = isNew ? await ctx.api.addCase(suite.id, body) : await ctx.api.updateCase(suite.id, c.case, body);
      ctx.toast(isNew ? t('case_added', { id: out.case.case }) : t('case_saved', { id: c.case }));
      if (onSaved) onSaved(out.case);
      return true;
    } catch (err) {
      busy(false);
      const rules = ruleErrors(err);
      if (Object.keys(rules).length) {
        Object.assign(errors, rules);
        showErrors(rules);
      } else {
        mount(formError, h('p.k-field__error', [icon('warning'), suiteErrorText(t, err)]));
      }
      return false;
    }
  };
  save.addEventListener('click', () => submit(formToBody(f, c), !c));
  if (dup) dup.addEventListener('click', () => submit(formToBody(f, c), true));
  if (del) {
    del.addEventListener('click', () => {
      const dlg = openDialog({
        t, title: t('suite_delete_cases_title', { n: 1 }), body: h('p', t('case_delete_body', { id: c.case })),
        footer: [
          h('button.yh-btn', { type: 'button', on: { click: () => dlg.close() } }, t('cancel')),
          h('button.yh-btn.yh-btn--destructive', { type: 'button', dataset: { confirmDelete: '1' }, on: { click: async () => {
            dlg.close();
            busy(true);
            try {
              await ctx.api.bulkCases(suite.id, { cases: [c.case], delete: true });
              ctx.toast(t('suite_cases_deleted', { n: 1 }));
              if (onDeleted) onDeleted();
            } catch (err) {
              busy(false);
              mount(formError, h('p.k-field__error', [icon('warning'), suiteErrorText(t, err)]));
            }
          } } }, t('delete')),
        ],
      });
    });
  }

  const traceLabel = c && c.source && Object.keys(c.source).length
    ? Object.entries(c.source).map(([k, v]) => `${k} ${v}`).join(' · ') : null;
  return h('section.panel.sticky.case-form', { 'aria-labelledby': 'case-form-title', dataset: { caseForm: c ? c.case : 'new' } }, [
    h('div.panel-head', [
      h('span.id', c ? [c.case, (c.trace || []).length ? ` · ${c.trace.join(', ')}` : ''] : t('case_new')),
      h('h2.yh-h3.m-0', { id: 'case-form-title' }, c ? t('case_edit') : t('suite_add_case')),
      h('button.yh-tool', { type: 'button', 'aria-label': t('close'), dataset: { caseClose: '1' }, on: { click: onClose } }, icon('close')),
    ]),
    text('content', 2),
    text('preconditions', 2),
    text('steps', 3),
    text('expected', 2),
    h('div.grid2', [
      input('screen', '/office/edit'),
      input('trace', 'B4, R1'),
      choice('class', [['', NONE], ...CLASSES.map((x) => [x, t(`case_class_${key(x)}`)])], drawRunner),
      runnerBox,
      choice('scenario', scenarioOptions),
      choice('viewport', VIEWPORTS.map((v) => [v, t(`wt_viewport_${v}`)]), drawMethod),
      methodBox,
    ]),
    checkRows.length || f.check ? choice('check', checkOptions) : null,
    h('p.yh-caption.yh-muted.m-0', t('case_safety')),
    c && c.creator === 'agent' ? h('p.yh-caption.yh-muted.m-0', t('case_by_agent')) : null,
    traceLabel ? h('p.yh-caption.yh-muted.m-0', [t('case_source'), ' ', h('span.mono', traceLabel)]) : null,
    formError,
    h('div.foot', [del, dup, h('span.push'), save]),
  ]);
}

/** The label and badge kind of one matrix cell: a verdict, or a row state without one. */
export function cellView(cell) {
  if (!cell) return null;
  if (cell.verdict === 'pass') return { key: cell.fixed ? 'run_fixed' : 'wt_verdict_pass', kind: 'success' };
  if (cell.verdict === 'fail') return { key: 'wt_verdict_fail', kind: 'danger' };
  return { key: `wt_state_${String(cell.verdict || '').replace(/-/g, '_')}`, kind: 'outline' };
}

/** Case by run: each case's result in the suite's newest runs, newest run first. */
function resultsMatrix(t, results) {
  const runs = (results && results.runs) || [];
  if (!runs.length) return null;
  return h('section.stack-8', { dataset: { results: '1' } }, [
    h('h3.yh-h4.m-0', t('suite_results_title')),
    h('p.yh-caption.yh-muted.m-0', t('suite_results_note')),
    tableBox([h('th', '#'), h('th', t('run_col_content')), ...runs.map((r) => h('th', { title: r.id }, [
      h('a.lnk', { href: href(['runs', r.id]) }, r.name || r.id), h('span.sub', timeOrDay(r.created_at))]))],
    results.cases.map((c) => h('tr', { dataset: { case: c.case } }, [
      h('td.id', c.case), h('td.wrap', c.content || NONE),
      ...runs.map((r) => {
        const view = cellView(c.cells[r.id]);
        return h('td', view ? h('span.row-4', [h('a', { href: href(['runs', r.id], { row: c.row }) },
          ybadge(t(view.key), view.kind)), c.cells[r.id].changed ? h('span.sub', t('suite_results_changed')) : null])
          : h('span.yh-muted', NONE));
      }),
    ]))),
  ]);
}
