/**
 * Clean ISO date formatting utilities
 * Displays strict UTC representations as per contracts-v1
 */

export function formatUtcDateTime(isoString) {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    // YYYY-MM-DD HH:mm UTC
    const year = d.getUTCFullYear();
    const month = String(d.getUTCMonth() + 1).padStart(2, '0');
    const day = String(d.getUTCDate()).padStart(2, '0');
    const hours = String(d.getUTCHours()).padStart(2, '0');
    const minutes = String(d.getUTCMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes} UTC`;
  } catch {
    return isoString;
  }
}

export function formatTimeRange(startIso, endIso) {
  if (!startIso || !endIso) return '—';
  try {
    const s = new Date(startIso);
    const e = new Date(endIso);
    const dateStr = s.toISOString().slice(0, 10);
    const startHour = s.toISOString().slice(11, 16);
    const endHour = e.toISOString().slice(11, 16);
    return `${dateStr} [${startHour} – ${endHour} UTC]`;
  } catch {
    return `${startIso} – ${endIso}`;
  }
}

export function calculateDuration(startIso, endIso) {
  if (!startIso || !endIso) return '';
  try {
    const diffMs = new Date(endIso).getTime() - new Date(startIso).getTime();
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

export function isWindowActive(startIso, endIso) {
  if (!startIso || !endIso) return false;
  const now = Date.now();
  const s = new Date(startIso).getTime();
  const e = new Date(endIso).getTime();
  return now >= s && now <= e;
}
