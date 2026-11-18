// Routes live in location.hash: #/tickets, #/tickets/DEMO-1, #/tickets/DEMO-1/trace,
// #/templates, #/cache, #/settings, each with an optional ?query.

export const SCREENS = ['tickets', 'templates', 'cache', 'settings'];

function decode(segment) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

function parseQuery(text) {
  const query = {};
  if (!text) return query;
  for (const part of text.split('&')) {
    if (!part) continue;
    const eq = part.indexOf('=');
    const key = decode((eq < 0 ? part : part.slice(0, eq)).replace(/\+/g, ' '));
    const value = decode((eq < 0 ? '' : part.slice(eq + 1)).replace(/\+/g, ' '));
    if (key !== null && value !== null && !(key in query)) query[key] = value;
  }
  return query;
}

/** Parse a hash into {name, params, query}; anything unknown is {name: 'notfound'}. */
export function parseRoute(hash) {
  let text = String(hash || '');
  if (text.startsWith('#')) text = text.slice(1);
  const q = text.indexOf('?');
  const path = q < 0 ? text : text.slice(0, q);
  const query = parseQuery(q < 0 ? '' : text.slice(q + 1));
  const parts = path.split('/').filter(Boolean).map(decode);
  if (parts.some((p) => p === null || p === '')) return { name: 'notfound', params: {}, query };
  if (parts.length === 0) return { name: 'tickets', params: {}, query };
  const [head, id, sub, ...rest] = parts;
  if (head === 'tickets') {
    if (!id) return { name: 'tickets', params: {}, query };
    if (!sub) return { name: 'report', params: { ticket: id }, query };
    if (sub === 'trace' && rest.length === 0) return { name: 'trace', params: { ticket: id }, query };
    return { name: 'notfound', params: {}, query };
  }
  if (SCREENS.includes(head) && !id) return { name: head, params: {}, query };
  return { name: 'notfound', params: {}, query };
}

/** Build a hash from path segments and a query; segments and values are percent-encoded. */
export function href(segments, query) {
  const path = '#/' + segments.map((s) => encodeURIComponent(String(s))).join('/');
  const pairs = Object.entries(query || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return pairs.length ? `${path}?${pairs.join('&')}` : path;
}

/** Which nav item a route belongs to. */
export function sectionOf(route) {
  if (route.name === 'report' || route.name === 'trace') return 'tickets';
  return route.name;
}
