import test from 'node:test';
import assert from 'node:assert/strict';
import { dateBoundary, safeSourceUrl } from './helpers.mjs';
test('a selected day means its UTC start, never local time', () => {
  assert.equal(dateBoundary('2025-03-01'), '2025-03-01T00:00:00Z');
  assert.equal(dateBoundary(''), undefined);
  assert.equal(dateBoundary('2025-03-01T12:30'), '2025-03-01T12:30:00Z');
});
test('evidence links never activate javascript or local file URLs', () => {
  assert.equal(safeSourceUrl('javascript:alert(1)'), null);
  assert.equal(safeSourceUrl('file:///etc/passwd'), null);
  assert.equal(safeSourceUrl('https://example.org/evidence'), 'https://example.org/evidence');
});
test('date-only presets remain visible in datetime-local controls', async () => {
  const { inputDateTime } = await import('./helpers.mjs');
  assert.equal(inputDateTime('2026-09-01'), '2026-09-01T00:00');
  assert.equal(inputDateTime('2026-09-03T14:30:00.000000Z'), '2026-09-03T14:30');
});
test('profile URLs keep every operation bound to the explicit dataset', async () => {
  const { profilePath } = await import('./helpers.mjs');
  assert.equal(profilePath('/api/query', 'demo'), '/api/query?profile_id=demo');
  assert.equal(profilePath('/api/assertions/a?known_at=2026-09-01', 'p-123'), '/api/assertions/a?known_at=2026-09-01&profile_id=p-123');
  assert.equal(profilePath('/api/query?profile_id=old', 'new'), '/api/query?profile_id=new');
});
test('untouched lifecycle defaults preserve the exact imported sub-minute boundary', async () => {
  const { eventBoundary, inputDateTime } = await import('./helpers.mjs');
  const imported = '2026-09-12T18:30:47.123456Z';
  assert.equal(inputDateTime(imported), '2026-09-12T18:30');
  assert.equal(eventBoundary(imported, undefined), imported);
  assert.equal(eventBoundary(imported, '2026-09-12T18:31'), '2026-09-12T18:31:00Z');
});
