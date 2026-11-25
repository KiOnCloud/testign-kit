import assert from 'node:assert/strict';
import { test } from 'node:test';

import { checkHosts, checkProjectName, splitHosts } from '../hosts.mjs';
import { checkProject, render as renderProjects } from '../views/projects.mjs';
import { filterScenarios, render as renderScenarios, scenarioIcon, scenarioStatus } from '../views/scenarios.mjs';
import { signInCard } from '../views/sign-in-card.mjs';
import { requiredRoles } from '../views/templates.mjs';
import { installFakeDocument } from './fake-dom.mjs';
import { byData, DICTS, fakeContext, translator, walk } from './web-helpers.mjs';

test('hosts typed one per line or with commas become a clean list', () => {
  assert.deepEqual(splitHosts(' Dev.Example.test\nauth.example.test, dev.example.test.  '), ['dev.example.test', 'auth.example.test']);
  assert.deepEqual(splitHosts(''), []);
});

test('host lists and project names are checked like the server does', () => {
  assert.equal(checkHosts([], true), 'login_err_hosts_empty');
  assert.equal(checkHosts([], false), null);
  assert.equal(checkHosts(['https://x.test/'], true), 'login_err_host');
  assert.equal(checkHosts(['x.test/path'], true), 'login_err_host');
  assert.equal(checkHosts(Array.from({ length: 21 }, (_, i) => `h${i}.test`), true), 'login_err_hosts_many');
  assert.equal(checkHosts(['dev.example.test'], true), null);
  assert.equal(checkProjectName('usupp-2'), null);
  assert.equal(checkProjectName('Usupp'), 'login_err_project_name');
  assert.equal(checkProjectName('nul'), 'login_err_project_name');
  assert.equal(checkProjectName('-x'), 'login_err_project_name');
  assert.deepEqual(checkProject({ name: 'demo', hosts: 'dev.example.test', signin_hosts: '' }, true), {});
  assert.deepEqual(checkProject({ name: 'Demo', hosts: '', signin_hosts: 'bad/host' }, true),
    { name: 'login_err_project_name', hosts: 'login_err_hosts_empty', signin_hosts: 'login_err_host' });
  assert.deepEqual(checkProject({ name: 'IGNORED', hosts: 'dev.example.test', signin_hosts: '' }, false), {});
});

test('a web test template needs only the item column', () => {
  assert.deepEqual([...requiredRoles('webtest')], ['item']);
  assert.deepEqual([...requiredRoles('testcase')], ['item', 'trace']);
});

test('a scenario is approved, waiting or rejected, shown as an icon whose tooltip says which', () => {
  installFakeDocument();
  const t = translator('en');
  const cases = [[{ approved: true }, 'approved', 'st--ok', DICTS.en.login_approved],
    [{ approved: false }, 'waiting', 'st--warn', DICTS.en.scen_waiting],
    [{ approved: false, rejection: { note: 'Wrong URL' } }, 'rejected', 'st--bad', DICTS.en.login_rejected]];
  for (const [s, status, cls, tip] of cases) {
    assert.equal(scenarioStatus(s), status);
    const el = scenarioIcon(t, s);
    assert.match(el.getAttribute('class'), new RegExp(cls));
    assert.equal(el.getAttribute('aria-label'), tip);
  }
  const groups = [{ project: 'demo', scenarios: [{ name: 'client', login_url: 'https://dev.example.test/login' }, { name: 'staff' }] },
    { project: 'other', scenarios: [{ name: 'admin' }] }];
  assert.deepEqual(filterScenarios(groups, 'login').map((g) => [g.project, g.scenarios.map((s) => s.name)]), [['demo', ['client']]]);
  assert.deepEqual(filterScenarios(groups, 'other').map((g) => g.project), ['other']);
});

const PROJECTS = [{ name: 'demo', hosts: ['dev.example.test'], signin_hosts: ['auth.example.test'], scenarios: 2, approved: 1 }];
const SCENARIOS = { demo: { scenarios: [
  { name: 'client', label: 'Client', approved: true, hash: 'h1', steps: [] },
  { name: 'staff', label: 'Staff', approved: false, hash: 'h2', steps: [] },
] } };

test('Projects edits hosts only; Scenarios lists scenarios by project and edits no host', async () => {
  const p = fakeContext({ projects: async () => ({ projects: PROJECTS }) });
  renderProjects(p.ctx);
  await p.ready;
  assert.deepEqual(byData(p.view, 'project').map((el) => el.dataset.project), ['demo']);
  assert.equal(byData(p.view, 'editProject').length, 1);
  assert.equal(byData(p.view, 'newProject').length, 1);
  assert.equal(byData(p.view, 'approve').length, 0);
  assert.ok(p.view.textContent.includes('dev.example.test') && p.view.textContent.includes('auth.example.test'));
  assert.ok(p.view.textContent.includes(DICTS.en.proj_note));
  const waiting = walk(p.view).find((el) => el.getAttribute && el.getAttribute('aria-label') === translator('en')('proj_waiting', { n: 1 }));
  assert.ok(waiting, 'the waiting scenarios show as an icon with its tooltip');

  const s = fakeContext({ projects: async () => ({ projects: PROJECTS }), scenarios: async (name) => SCENARIOS[name] },
    { route: { params: {}, query: { project: 'demo' } } });
  renderScenarios(s.ctx);
  await s.ready;
  assert.deepEqual(byData(s.view, 'group').map((el) => el.dataset.group), ['demo']);
  assert.deepEqual(byData(s.view, 'scenario').filter((el) => el.tagName === 'TR').map((el) => el.dataset.scenario), ['none', 'client', 'staff']);
  assert.equal(byData(s.view, 'review').map((el) => el.dataset.review).join(), 'staff');
  assert.equal(byData(s.view, 'editProject').length + byData(s.view, 'saveProject').length, 0);
  assert.ok(walk(s.view).some((el) => el.getAttribute && el.getAttribute('aria-label') === DICTS.en.scen_waiting));
});

test('approving a scenario sends the hash the tester saw', async () => {
  const sent = [];
  const api = { projects: async () => ({ projects: PROJECTS }), scenarios: async (name) => SCENARIOS[name],
    approveScenario: async (...args) => { sent.push(args); return { ok: true }; } };
  const { ctx, view, ready } = fakeContext(api);
  renderScenarios(ctx);
  await ready;
  const row = byData(view, 'scenario').find((el) => el.tagName === 'TR' && el.dataset.scenario === 'staff');
  row.listeners.click[0]({ target: row });
  const [approve] = byData(globalThis.document.body, 'approve');
  assert.ok(approve, 'the detail dialog offers Approve for a waiting scenario');
  approve.listeners.click[0]();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(sent, [['demo', 'staff', 'h2']]);
});

test('the sign-in card lists the checklist and answers with the tester\'s choice', async () => {
  const sent = [];
  const { ctx } = fakeContext({ answer: async (...args) => { sent.push(args); return { ok: true }; } });
  const job = {
    id: 'j9', kind: 'webtest-run', state: 'needs-input',
    ask: {
      id: 'signin-1', type: 'sign-in', scenario: 'client',
      checklist: { name: 'client', label: 'Client', login_url: 'https://dev.example.test/login', signout_url: '',
        steps: ['Open the sign-in page', 'Sign in with the client test account'], account_hint: 'The menu shows the client name',
        signed_in_check: { url: '', text: 'My bookings' }, hash: 'h' },
      previous: { name: 'staff', label: 'Staff', signout_url: 'https://dev.example.test/logout' },
    },
  };
  const card = signInCard(ctx, job);
  const text = card.textContent;
  assert.ok(text.includes('Sign out of Staff'));
  assert.ok(text.includes('Sign in with the client test account'));
  assert.ok(text.includes('My bookings'));
  const links = walk(card).filter((el) => el.tagName === 'A');
  assert.ok(links.every((a) => a.getAttribute('rel') === 'noopener noreferrer'));
  const [signedIn] = byData(card, 'signIn').filter((b) => b.dataset.signIn === 'signed-in');
  for (const fn of signedIn.listeners.click) fn();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(sent, [['j9', 'signin-1', { choice: 'signed-in' }]]);
});

test('a tab newer than the job sees a notice instead of the sign-in buttons', () => {
  const { ctx } = fakeContext({ answer: async () => { throw new Error('must not answer'); } });
  const job = {
    id: 'j9', kind: 'webtest-run', state: 'needs-input', can_answer: false,
    ask: { id: 'signin-1', type: 'sign-in', scenario: 'client', checklist: { name: 'client', label: 'Client', steps: [] } },
  };
  const card = signInCard(ctx, job);
  assert.equal(byData(card, 'signIn').length, 0);
  assert.equal(byData(card, 'tooNew').length, 1);
  assert.ok(card.textContent.includes('This tab cannot answer'));
});
