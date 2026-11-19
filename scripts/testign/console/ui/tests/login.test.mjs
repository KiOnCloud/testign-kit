import assert from 'node:assert/strict';
import { test } from 'node:test';

import { checkHosts, checkProjectName, signInCard, splitHosts } from '../views/login.mjs';
import { requiredRoles } from '../views/templates.mjs';
import { byData, fakeContext, walk } from './web-helpers.mjs';

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
});

test('a web test template needs only the item column', () => {
  assert.deepEqual([...requiredRoles('webtest')], ['item']);
  assert.deepEqual([...requiredRoles('testcase')], ['item', 'trace']);
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
