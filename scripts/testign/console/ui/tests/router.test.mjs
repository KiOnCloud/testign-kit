import assert from 'node:assert/strict';
import { test } from 'node:test';

import { href, parseRoute, sectionOf } from '../router.mjs';

test('screens parse from the hash', () => {
  assert.deepEqual(parseRoute(''), { name: 'tickets', params: {}, query: {} });
  assert.deepEqual(parseRoute('#/'), { name: 'tickets', params: {}, query: {} });
  assert.deepEqual(parseRoute('#/tickets'), { name: 'tickets', params: {}, query: {} });
  assert.equal(parseRoute('#/templates').name, 'templates');
  assert.equal(parseRoute('#/cache').name, 'cache');
  assert.equal(parseRoute('#/settings').name, 'settings');
});

test('ticket routes carry the ticket id', () => {
  assert.deepEqual(parseRoute('#/tickets/DEMO-1'), { name: 'report', params: { ticket: 'DEMO-1' }, query: {} });
  assert.deepEqual(parseRoute('#/tickets/DEMO-1/trace'), { name: 'trace', params: { ticket: 'DEMO-1' }, query: {} });
});

test('queries and encoded segments are decoded', () => {
  const r = parseRoute('#/tickets/DEMO-1/trace?workbook=DEMO-1%20tc.xlsx&template=m%E1%BA%ABu');
  assert.deepEqual(r.query, { workbook: 'DEMO-1 tc.xlsx', template: 'mẫu' });
  assert.equal(parseRoute('#/tickets/A%2FB').params.ticket, 'A/B');
  assert.deepEqual(parseRoute('#/tickets/DEMO-1?rev=a&rev=b').query, { rev: 'a' });
});

test('unknown or malformed routes are notfound', () => {
  assert.equal(parseRoute('#/nope').name, 'notfound');
  assert.equal(parseRoute('#/settings/extra').name, 'notfound');
  assert.equal(parseRoute('#/tickets/DEMO-1/other').name, 'notfound');
  assert.equal(parseRoute('#/tickets/%E0%A4%A').name, 'notfound');
  assert.equal(parseRoute('#c=launchcode').name, 'notfound');
});

test('href encodes segments and drops empty query values', () => {
  assert.equal(href(['tickets', 'DEMO-1', 'trace'], { workbook: 'a b.xlsx', template: undefined }),
    '#/tickets/DEMO-1/trace?workbook=a%20b.xlsx');
  assert.equal(href(['tickets', 'A/B']), '#/tickets/A%2FB');
  const round = parseRoute(href(['tickets', 'DEMO-1', 'trace'], { workbook: 'x&y=z.xlsx' }));
  assert.equal(round.query.workbook, 'x&y=z.xlsx');
});

test('report and trace belong to the Tickets section', () => {
  assert.equal(sectionOf(parseRoute('#/tickets/DEMO-1')), 'tickets');
  assert.equal(sectionOf(parseRoute('#/tickets/DEMO-1/trace')), 'tickets');
  assert.equal(sectionOf(parseRoute('#/cache')), 'cache');
});

test('job routes', () => {
  assert.deepEqual(parseRoute('#/jobs'), { name: 'jobs', params: {}, query: {} });
  assert.deepEqual(parseRoute('#/jobs/j-123'), { name: 'jobs', params: { job: 'j-123' }, query: {} });
  assert.deepEqual(parseRoute('#/jobs/j-123/review'), { name: 'review', params: { job: 'j-123' }, query: {} });
  assert.equal(parseRoute('#/jobs/j-123/other').name, 'notfound');
  assert.equal(sectionOf(parseRoute('#/jobs/j-123/review')), 'jobs');
});
