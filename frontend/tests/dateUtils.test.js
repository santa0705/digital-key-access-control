import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  IST_TIMEZONE,
  formatIstDateTime,
  formatIstDate,
  formatUtcDateTime,
  formatTimeRange,
  calculateDuration,
  isWindowActive,
  isCredentialExpired,
  getEffectiveCredentialStatus
} from '../src/utils/dateUtils.js';

describe('Centralized IST Date/Time Formatter Tests', () => {
  it('1. Confirms the target IANA timezone is Asia/Kolkata', () => {
    assert.strictEqual(IST_TIMEZONE, 'Asia/Kolkata');
  });

  it('2. Formats a standard daytime UTC timestamp to IST (+05:30)', () => {
    // 09:00 UTC + 5:30 = 14:30 IST on same day
    const utcIso = '2026-10-15T09:00:00Z';
    const formatted = formatIstDateTime(utcIso);
    assert.strictEqual(formatted, '2026-10-15 14:30 IST');
  });

  it('3. Formats a UTC timestamp that crosses midnight in IST to the next day', () => {
    // 20:30 UTC on Oct 14 + 5:30 = 02:00 IST on Oct 15
    const utcIso = '2026-10-14T20:30:00Z';
    const formatted = formatIstDateTime(utcIso);
    assert.strictEqual(formatted, '2026-10-15 02:00 IST');

    // Date-only extraction must also reflect the next day
    const dateOnly = formatIstDate(utcIso);
    assert.strictEqual(dateOnly, '2026-10-15');
  });

  it('4. Formats exact midnight boundary (18:30 UTC -> 00:00 IST next day)', () => {
    // 18:30 UTC on Oct 14 + 5:30 = 00:00 IST on Oct 15
    const utcIso = '2026-10-14T18:30:00Z';
    const formatted = formatIstDateTime(utcIso);
    assert.strictEqual(formatted, '2026-10-15 00:00 IST');
    assert.strictEqual(formatIstDate(utcIso), '2026-10-15');
  });

  it('5. Formats timestamp right before midnight (18:00 UTC -> 23:30 IST same day)', () => {
    // 18:00 UTC on Oct 14 + 5:30 = 23:30 IST on Oct 14
    const utcIso = '2026-10-14T18:00:00Z';
    const formatted = formatIstDateTime(utcIso);
    assert.strictEqual(formatted, '2026-10-14 23:30 IST');
    assert.strictEqual(formatIstDate(utcIso), '2026-10-14');
  });

  it('6. Ensures formatUtcDateTime alias delegates to formatIstDateTime', () => {
    const utcIso = '2026-10-15T09:00:00Z';
    assert.strictEqual(formatUtcDateTime(utcIso), '2026-10-15 14:30 IST');
  });

  it('7. Formats time range within the same day in IST', () => {
    // 04:00 UTC (09:30 IST) to 06:00 UTC (11:30 IST) on 2026-10-15
    const start = '2026-10-15T04:00:00Z';
    const end = '2026-10-15T06:00:00Z';
    const range = formatTimeRange(start, end);
    assert.strictEqual(range, '2026-10-15 [09:30 – 11:30 IST]');
  });

  it('8. Formats time range when both UTC timestamps were on previous day but both IST times fall on next day', () => {
    // 20:00 UTC Oct 14 (01:30 IST Oct 15) to 22:00 UTC Oct 14 (03:30 IST Oct 15)
    const start = '2026-10-14T20:00:00Z';
    const end = '2026-10-14T22:00:00Z';
    const range = formatTimeRange(start, end);
    assert.strictEqual(range, '2026-10-15 [01:30 – 03:30 IST]');
  });

  it('9. Formats time range that crosses midnight in IST across two calendar dates', () => {
    // 18:00 UTC Oct 15 (23:30 IST Oct 15) to 20:00 UTC Oct 15 (01:30 IST Oct 16)
    const start = '2026-10-15T18:00:00Z';
    const end = '2026-10-15T20:00:00Z';
    const range = formatTimeRange(start, end);
    assert.strictEqual(range, '2026-10-15 23:30 – 2026-10-16 01:30 IST');
  });

  it('10. Handles missing, null, and invalid inputs gracefully', () => {
    assert.strictEqual(formatIstDateTime(null), '—');
    assert.strictEqual(formatIstDateTime(undefined), '—');
    assert.strictEqual(formatIstDateTime(''), '—');
    assert.strictEqual(formatIstDateTime('not-a-date'), 'not-a-date');

    assert.strictEqual(formatIstDate(null), '—');
    assert.strictEqual(formatIstDate(''), '—');

    assert.strictEqual(formatTimeRange(null, null), '—');
    assert.strictEqual(formatTimeRange('invalid', 'dates'), 'invalid – dates');
  });

  it('11. Duration calculation preserves elapsed wall clock difference', () => {
    const start = '2026-10-15T18:00:00Z';
    const end = '2026-10-15T20:30:00Z';
    assert.strictEqual(calculateDuration(start, end), '2h 30m');
    assert.strictEqual(calculateDuration(start, start), '');
  });

  it('12. Active window check functions correctly across timestamps', () => {
    const past = new Date(Date.now() - 60000).toISOString();
    const future = new Date(Date.now() + 60000).toISOString();
    assert.strictEqual(isWindowActive(past, future), true);
    assert.strictEqual(isWindowActive(future, new Date(Date.now() + 120000).toISOString()), false);
  });

  it('13. isCredentialExpired correctly checks past vs future timestamps', () => {
    const past = new Date(Date.now() - 1000).toISOString();
    const future = new Date(Date.now() + 60000).toISOString();
    assert.strictEqual(isCredentialExpired(past), true);
    assert.strictEqual(isCredentialExpired(future), false);
    assert.strictEqual(isCredentialExpired(null), false);
    assert.strictEqual(isCredentialExpired(''), false);
  });

  it('14. getEffectiveCredentialStatus transitions active credentials past valid_until to expired', () => {
    const pastExpiry = new Date(Date.now() - 1000).toISOString();
    const futureExpiry = new Date(Date.now() + 3600000).toISOString();

    const expiredCred = { status: 'active', valid_until: pastExpiry };
    assert.strictEqual(getEffectiveCredentialStatus(expiredCred), 'expired');

    const activeCred = { status: 'active', valid_until: futureExpiry };
    assert.strictEqual(getEffectiveCredentialStatus(activeCred), 'active');
  });

  it('15. getEffectiveCredentialStatus strictly preserves terminal statuses and handles nulls', () => {
    const pastExpiry = new Date(Date.now() - 10000).toISOString();

    assert.strictEqual(getEffectiveCredentialStatus({ status: 'revoked', valid_until: pastExpiry }), 'revoked');
    assert.strictEqual(getEffectiveCredentialStatus({ status: 'consumed', valid_until: pastExpiry }), 'consumed');
    assert.strictEqual(getEffectiveCredentialStatus({ status: 'expired', valid_until: pastExpiry }), 'expired');

    assert.strictEqual(getEffectiveCredentialStatus(null), '—');
    assert.strictEqual(getEffectiveCredentialStatus({}), '—');
  });
});
