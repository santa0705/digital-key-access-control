/**
 * Centralized Date/Time Formatting Utilities (Indian Standard Time - IST, UTC+05:30)
 *
 * Implements centralized formatting using IANA timezone `Asia/Kolkata` via Intl.DateTimeFormat.
 * All backend storage, database records, API contracts, and sync protocols remain in strict UTC.
 */

export const IST_TIMEZONE = 'Asia/Kolkata';

const istDateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: IST_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23'
});

/**
 * Safely parse an ISO-8601 string or date value.
 * Appends 'Z' to naive date-time strings so they parse as UTC.
 */
function parseIsoDate(isoString) {
  if (!isoString) return null;
  let str = String(isoString).trim();
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(str)) {
    str += 'Z';
  }
  const d = new Date(str);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Extract IST components (dateStr: YYYY-MM-DD, timeStr: HH:mm) using Intl.DateTimeFormat.
 */
function getIstParts(date) {
  const parts = istDateTimeFormatter.formatToParts(date);
  const map = {};
  for (const p of parts) {
    map[p.type] = p.value;
  }
  return {
    year: map.year,
    month: map.month,
    day: map.day,
    hour: map.hour,
    minute: map.minute,
    dateStr: `${map.year}-${map.month}-${map.day}`,
    timeStr: `${map.hour}:${map.minute}`
  };
}

/**
 * Format a UTC ISO timestamp as Indian Standard Time (IST).
 * Output format: YYYY-MM-DD HH:mm IST
 *
 * Example: '2026-10-15T09:00:00Z' -> '2026-10-15 14:30 IST'
 * Midnight crossing: '2026-10-14T20:30:00Z' -> '2026-10-15 02:00 IST'
 */
export function formatIstDateTime(isoString) {
  if (!isoString) return '—';
  try {
    const d = parseIsoDate(isoString);
    if (!d) return isoString;
    const { dateStr, timeStr } = getIstParts(d);
    return `${dateStr} ${timeStr} IST`;
  } catch {
    return isoString;
  }
}

/**
 * Format date-only in Indian Standard Time (IST).
 * Correctly shifts boundary when a UTC timestamp crosses midnight in IST.
 * Output format: YYYY-MM-DD
 */
export function formatIstDate(isoString) {
  if (!isoString) return '—';
  try {
    const d = parseIsoDate(isoString);
    if (!d) return isoString;
    const { dateStr } = getIstParts(d);
    return dateStr;
  } catch {
    return isoString;
  }
}

/**
 * Backward compatibility alias for formatIstDateTime.
 * Ensures any callers expecting formatUtcDateTime automatically render IST.
 */
export const formatUtcDateTime = formatIstDateTime;

/**
 * Format a validity or access window in IST.
 *
 * If start and end fall on the same date in IST:
 *   YYYY-MM-DD [HH:mm – HH:mm IST]
 * If start and end cross midnight in IST:
 *   YYYY-MM-DD HH:mm – YYYY-MM-DD HH:mm IST
 */
export function formatTimeRange(startIso, endIso) {
  if (!startIso || !endIso) return '—';
  try {
    const s = parseIsoDate(startIso);
    const e = parseIsoDate(endIso);
    if (!s || !e) return `${startIso} – ${endIso}`;

    const startParts = getIstParts(s);
    const endParts = getIstParts(e);

    if (startParts.dateStr === endParts.dateStr) {
      return `${startParts.dateStr} [${startParts.timeStr} – ${endParts.timeStr} IST]`;
    }
    return `${startParts.dateStr} ${startParts.timeStr} – ${endParts.dateStr} ${endParts.timeStr} IST`;
  } catch {
    return `${startIso} – ${endIso}`;
  }
}

/**
 * Calculate the duration between two ISO timestamps.
 */
export function calculateDuration(startIso, endIso) {
  if (!startIso || !endIso) return '';
  try {
    const s = parseIsoDate(startIso);
    const e = parseIsoDate(endIso);
    if (!s || !e) return '';
    const diffMs = e.getTime() - s.getTime();
    if (diffMs <= 0) return '';
    const diffMins = Math.round(diffMs / 60000);
    const hours = Math.floor(diffMins / 60);
    const mins = diffMins % 60;
    if (hours > 0 && mins > 0) return `${hours}h ${mins}m`;
    if (hours > 0) return `${hours}h`;
    return `${mins}m`;
  } catch {
    return '';
  }
}

/**
 * Determine if current wall clock time falls within the validity window.
 */
export function isWindowActive(startIso, endIso) {
  if (!startIso || !endIso) return false;
  try {
    const now = Date.now();
    const s = parseIsoDate(startIso);
    const e = parseIsoDate(endIso);
    if (!s || !e) return false;
    return now >= s.getTime() && now <= e.getTime();
  } catch {
    return false;
  }
}

/**
 * Determine if a validity deadline has passed.
 * Compares wall clock time against valid_until timestamp.
 */
export function isCredentialExpired(validUntil) {
  if (!validUntil) return false;
  try {
    const until = parseIsoDate(validUntil);
    if (!until) return false;
    return Date.now() >= until.getTime();
  } catch {
    return false;
  }
}

/**
 * Derive the effective status of a credential.
 *
 * If credential.status is 'active', checks whether current time has reached or passed valid_until.
 * If now >= valid_until, returns 'expired'.
 * Otherwise returns credential.status (preserving 'active', 'consumed', 'revoked', 'expired').
 */
export function getEffectiveCredentialStatus(credential) {
  if (!credential || !credential.status) return '—';
  if (credential.status === 'active' && credential.valid_until) {
    if (isCredentialExpired(credential.valid_until)) {
      return 'expired';
    }
  }
  return credential.status;
}
