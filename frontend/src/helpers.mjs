/** Selected days are inclusive starts in UTC; the API uses half-open intervals. */
export function dateBoundary(value) { return value ? (value.length === 10 ? `${value}T00:00:00Z` : `${value}:00Z`) : undefined; }
/** Only external web protocols may become clickable provenance links. */
export function safeSourceUrl(value) {
  if (!value) return null;
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? value : null; }
  catch { return null; }
}
export function inputDateTime(value) { return new Date(value).toISOString().slice(0, 16); }
export function profilePath(path, profileId) {
  const [pathname, search = ''] = path.split('?');
  const params = new URLSearchParams(search);
  params.set('profile_id', profileId);
  return `${pathname}?${params.toString()}`;
}
/** A minute-resolution control must not move an untouched imported boundary backwards. */
export function eventBoundary(original, edited) { return edited === undefined ? original : dateBoundary(edited); }
