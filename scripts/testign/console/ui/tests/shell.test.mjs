import assert from 'node:assert/strict';
import { test } from 'node:test';

import { getNavGroups, setNavGroup } from '../prefs.mjs';
import { capabilityIcons, jobStateIcon, jobTarget, render as renderAgent } from '../views/jobs.mjs';
import { groupOf, NAV, renderShell } from '../views/shell.mjs';
import { installFakeDocument } from './fake-dom.mjs';
import { byData, DICTS, fakeContext, translator, walk } from './web-helpers.mjs';

function memoryStore() {
  const data = new Map();
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) };
}

test('the menu has three groups in order, each with its screens', () => {
  assert.deepEqual(NAV.map((g) => [g.id, g.items.map(([id]) => id)]), [
    ['design', ['suites', 'survey']],
    ['run', ['runs', 'agent']],
    ['config', ['projects', 'scenarios', 'templates', 'cache', 'settings']],
  ]);
  assert.equal(groupOf('survey'), 'design');
  assert.equal(groupOf('agent'), 'run');
  assert.equal(groupOf('cache'), 'config');
  assert.equal(groupOf('nope'), null);
  for (const lang of ['en', 'ja']) {
    for (const g of NAV) {
      assert.ok(DICTS[lang][`nav_group_${g.id}`], `${lang} nav_group_${g.id}`);
      for (const [id] of g.items) assert.ok(DICTS[lang][`nav_${id}`], `${lang} nav_${id}`);
    }
  }
});

test('a closed group stays closed, except the group of the current screen', () => {
  installFakeDocument();
  const store = memoryStore();
  setNavGroup('config', false, store);
  setNavGroup('design', false, store);
  assert.deepEqual(getNavGroups(store), { config: false, design: false });
  const prefs = { getNavGroups: () => getNavGroups(store), setNavGroup: (id, open) => setNavGroup(id, open, store) };
  const { root } = renderShell({ t: translator('en'), lang: 'en', section: 'suites', counts: { suites: 3 }, onLang: () => {}, onPalette: () => {}, prefs });
  const shell = root[0];
  const groups = byData(shell, 'group');
  assert.deepEqual(groups.map((b) => [b.dataset.group, b.getAttribute('aria-expanded')]),
    [['design', 'true'], ['run', 'true'], ['config', 'false']]);
  const subs = Object.fromEntries(byData(shell, 'navSub').map((el) => [el.dataset.navSub, el]));
  assert.equal(subs.config.hidden, true);
  assert.notEqual(subs.design.hidden, true);
  const active = byData(shell, 'nav').find((a) => a.getAttribute('aria-current') === 'page');
  assert.equal(active.dataset.nav, 'suites');
  assert.equal(byData(shell, 'count').find((el) => el.dataset.count === 'suites').textContent, '3');
  groups[2].listeners.click[0]();
  assert.equal(groups[2].getAttribute('aria-expanded'), 'true');
  assert.equal(subs.config.hidden, false);
  assert.equal(getNavGroups(store).config, true);
  assert.equal(getNavGroups({ getItem: () => '{"run": "yes", "x": false}' }).run, undefined, 'only booleans are kept');
});

test('the menu button opens the menu on a narrow screen', () => {
  installFakeDocument();
  const { root } = renderShell({ t: translator('ja'), lang: 'ja', section: 'runs', counts: {}, onLang: () => {}, onPalette: () => {}, prefs: null });
  const shell = root[0];
  const toggle = walk(shell).find((el) => /nav-toggle/.test(el.getAttribute('class') || ''));
  assert.equal(toggle.getAttribute('aria-label'), DICTS.ja.nav_menu);
  toggle.listeners.click[0]();
  assert.match(shell.getAttribute('class'), /is-nav-open/);
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
});

test('the agent\'s tools show as icons: reported yes, reported no, or not reported', () => {
  const t = translator('en');
  assert.deepEqual(capabilityIcons(t, null).map((c) => [c.name, c.kind, c.icon]),
    [['chrome', 'busy', 'dash'], ['figma', 'busy', 'dash'], ['backlog', 'busy', 'dash']]);
  const caps = capabilityIcons(t, { chrome: true, figma: false, backlog: true, at: 'x' });
  assert.deepEqual(caps.map((c) => [c.kind, c.icon]), [['ok', 'check'], ['bad', 'close'], ['ok', 'check']]);
  assert.equal(caps[1].tip, t('cap_no', { name: DICTS.en.cap_figma }));
  installFakeDocument();
  assert.equal(jobStateIcon(t, 'needs-input').getAttribute('aria-label'), DICTS.en.job_state_needs_input);
  assert.equal(jobTarget({ kind: 'suite-generate', suite: 'S1' }), '#/suites/S1');
  assert.equal(jobTarget({ kind: 'webtest-run', run: 'W1' }), '#/runs/W1');
  assert.equal(jobTarget({ kind: 'survey', ticket: 'DEMO-1' }), '#/survey/DEMO-1');
});

test('a legacy plan job reads as legacy and offers no Queue again', async () => {
  const job = { id: 'j-old', kind: 'webtest-plan', state: 'failed', reason: 'agent', created_at: '2026-11-19T10:00:00+09:00', params: {}, progress: [] };
  const { ctx, view, ready } = fakeContext({ job: async () => job }, { route: { params: { job: 'j-old' }, query: {} } });
  renderAgent(ctx);
  await ready;
  assert.equal(byData(view, 'legacy').length, 1);
  assert.equal(byData(view, 'jobAction').filter((el) => el.dataset.jobAction === 'requeue').length, 0);
  assert.ok(view.textContent.includes(DICTS.en.jobs_legacy_t));
  const run = { ...job, id: 'j-run', kind: 'webtest-run', run: 'W1', params: { run: 'W1', tester: 'An', mode: 'run' } };
  const other = fakeContext({ job: async () => run }, { route: { params: { job: 'j-run' }, query: {} } });
  renderAgent(other.ctx);
  await other.ready;
  assert.equal(byData(other.view, 'jobAction').filter((el) => el.dataset.jobAction === 'requeue').length, 1);
  assert.equal(byData(other.view, 'jobTarget')[0].getAttribute('href'), '#/runs/W1');
});

test('the agent screen lists jobs with a status icon and the agent\'s tools', async () => {
  const jobs = [{ id: 'j-1', kind: 'suite-generate', suite: 'S1', state: 'running', created_at: '2026-11-25T10:00:00+09:00' },
    { id: 'j-2', kind: 'webtest-plan', state: 'done', created_at: '2026-11-19T10:00:00+09:00' }];
  const { ctx, view, ready } = fakeContext({ jobs: async () => ({ jobs }) });
  ctx.store = { get: () => ({ agent: { attached: true, capabilities: { chrome: true, figma: false, backlog: false } }, queue: [] }) };
  renderAgent(ctx);
  await ready;
  assert.deepEqual(byData(view, 'job').map((el) => el.dataset.job), ['j-1']);
  assert.equal(byData(view, 'cap').length, 3);
  byData(view, 'filter').find((el) => el.dataset.filter === 'history').listeners.click[0]();
  assert.deepEqual(byData(view, 'job').map((el) => el.dataset.job), ['j-2']);
  assert.equal(byData(view, 'legacy').length, 1);
});
