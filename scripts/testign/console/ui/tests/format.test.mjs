import assert from 'node:assert/strict';
import { test } from 'node:test';

import { dateTime, idRanges, isoDate, NONE, shortSha, timeOrDay } from '../format.mjs';

test('ISO strings keep the day as written', () => {
  assert.equal(isoDate('2026-01-01T00:00:00+00:00'), '2026-01-01');
  assert.equal(isoDate('2026-11-18T23:59:59+07:00'), '2026-11-18');
  assert.equal(isoDate('2026-11-18'), '2026-11-18');
  assert.equal(isoDate('2026-11-18 10:00'), '2026-11-18');
});

test('numbers are epoch seconds shown as a local day', () => {
  const d = new Date(2026, 10, 18, 12, 0, 0);
  assert.equal(isoDate(d.getTime() / 1000), '2026-11-18');
  assert.equal(isoDate(new Date(2026, 0, 5)), '2026-01-05');
});

test('anything else is an em dash', () => {
  for (const v of [null, undefined, '', 'yesterday', '18/11/2026', NaN, Infinity, {}]) assert.equal(isoDate(v), NONE);
});

test('short commits', () => {
  assert.equal(shortSha('abcdef1234567890'), 'abcdef1');
  assert.equal(shortSha('develop'), 'develop');
  assert.equal(shortSha(null), NONE);
});

test('id ranges', () => {
  assert.equal(idRanges(['B1', 'B2', 'B3', 'B5', 'R1', 'R2']), 'B1–B3, B5, R1–R2');
  assert.equal(idRanges(['B1']), 'B1');
  assert.equal(idRanges([]), '');
  assert.equal(idRanges(['x', 'B2']), 'x, B2');
});

test('job times: HH:MM today, the day otherwise', () => {
  const now = new Date(2026, 10, 19, 15, 0);
  assert.equal(timeOrDay(new Date(2026, 10, 19, 9, 5).toISOString(), now), '09:05');
  assert.equal(timeOrDay(new Date(2026, 10, 17, 9, 5).toISOString(), now), '2026-11-17');
  assert.equal(timeOrDay('nope', now), NONE);
  assert.equal(dateTime(new Date(2026, 10, 19, 9, 5).toISOString()), '2026-11-19 09:05');
  assert.equal(dateTime(null), NONE);
});
