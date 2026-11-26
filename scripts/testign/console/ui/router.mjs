// Routes live in location.hash, each with an optional ?query. The screens of the three menu groups:
//   Test case design  #/suites, #/suites/new, #/suites/<suite>, #/survey, #/survey/<ticket>, #/survey/<ticket>/trace
//   Test runs         #/runs, #/runs/<run>, #/defects, #/agent, #/agent/<job>
//   Settings          #/projects, #/scenarios, #/templates, #/cache, #/settings

export const HOME = 'suites';
export const SCREENS = ['suites', 'survey', 'runs', 'defects', 'agent', 'projects', 'scenarios', 'templates', 'cache', 'settings'];

// Redirect table: links written before the redesign keep working.
//   #/  (and #c=<code> after sign-in, see api.mjs)    → #/suites
//   #/tickets                                        → #/survey
//   #/tickets/<ticket>, #/tickets/<ticket>/trace     → #/survey/<ticket>, #/survey/<ticket>/trace
//   #/jobs, #/jobs/<job>                             → #/agent, #/agent/<job>
//   #/jobs/<job>/review, #/jobs/<job>/review-table   → #/runs/<job.run>, or #/agent/<job> when the job has no run
//   #/login                                          → #/scenarios
const RENAMED = { tickets: 'survey', jobs: 'agent', login: 'scenarios' };
const LEGACY_REVIEW = new Set(['review', 'review-table']);

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

function split(hash) {
  let text = String(hash || '');
  if (text.startsWith('#')) text = text.slice(1);
  const q = text.indexOf('?');
  const path = q < 0 ? text : text.slice(0, q);
  return { path, queryText: q < 0 ? '' : text.slice(q + 1), parts: path.split('/').filter(Boolean).map(decode) };
}

/** Build a hash from path segments and a query; segments and values are percent-encoded. */
export function href(segments, query) {
  const path = '#/' + segments.map((s) => encodeURIComponent(String(s))).join('/');
  const pairs = Object.entries(query || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return pairs.length ? `${path}?${pairs.join('&')}` : path;
}

/**
 * Where an old or empty hash goes now: {to: '<new hash>'}, {job: '<id>'} when the target needs the
 * job's run (see legacyReviewTarget), or null when the hash is current.
 */
export function redirectOf(hash) {
  const { parts, queryText, path } = split(hash);
  if (/^c=/.test(path)) return null; // a launch code: api.mjs exchanges it, then lands on HOME
  if (parts.some((p) => p === null || p === '')) return null;
  const keep = queryText ? `?${queryText}` : '';
  if (parts.length === 0) return { to: href([HOME]) };
  const [head, id, sub, ...rest] = parts;
  if (!(head in RENAMED)) return null;
  if (head === 'jobs' && id && LEGACY_REVIEW.has(sub) && rest.length === 0) return { job: id };
  return { to: href([RENAMED[head], ...[id, sub, ...rest].filter((p) => p !== undefined)]) + keep };
}

/** The new home of a legacy review link, from the job record (`GET /api/jobs/:id`). */
export function legacyReviewTarget(job, id) {
  if (job && typeof job.run === 'string' && job.run) return href(['runs', job.run]);
  return href(['agent', (job && job.id) || id]);
}

/** Parse a hash into {name, params, query}; anything unknown is {name: 'notfound'}. */
export function parseRoute(hash) {
  const { parts, queryText } = split(hash);
  const query = parseQuery(queryText);
  const nf = { name: 'notfound', params: {}, query };
  if (parts.some((p) => p === null || p === '')) return nf;
  if (parts.length === 0) return { name: HOME, params: {}, query };
  const [head, id, sub, ...rest] = parts;
  if (head === 'suites' && id) {
    if (sub) return nf;
    if (id === 'new') return { name: 'suiteNew', params: {}, query };
    return { name: 'suite', params: { suite: id }, query };
  }
  if (head === 'survey' && id) {
    if (!sub) return { name: 'report', params: { ticket: id }, query };
    if (sub === 'trace' && rest.length === 0) return { name: 'trace', params: { ticket: id }, query };
    return nf;
  }
  if (head === 'runs' && id) return sub ? nf : { name: 'run', params: { run: id }, query };
  if (head === 'agent' && id) return sub ? nf : { name: 'agent', params: { job: id }, query };
  if (SCREENS.includes(head) && !id) return { name: head, params: {}, query };
  return nf;
}

/** Which menu row a route belongs to. */
export function sectionOf(route) {
  if (route.name === 'suite' || route.name === 'suiteNew') return 'suites';
  if (route.name === 'report' || route.name === 'trace') return 'survey';
  if (route.name === 'run') return 'runs';
  return route.name;
}
