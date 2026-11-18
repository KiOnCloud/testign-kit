// Browser session and HTTP calls. The session token lives in sessionStorage of this origin only;
// every /api/* call carries it in X-Testign-Session. A 403 means the console must be reopened.

const TOKEN_KEY = 'testign.session';
const VERSION_KEY = 'testign.version';
const SESSION_HEADER = 'X-Testign-Session';
export const UPLOAD_CAP = 10 * 1024 * 1024;

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message || code);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let token = null;
let version = null;
let onForbidden = () => {};

function session() {
  try {
    return globalThis.sessionStorage || null;
  } catch {
    return null;
  }
}

function remember(key, value) {
  try {
    const s = session();
    if (!s) return;
    if (value === null) s.removeItem(key);
    else s.setItem(key, value);
  } catch {
    // Storage blocked: the token stays in memory for this page only.
  }
}

function recall(key) {
  try {
    const s = session();
    return s ? s.getItem(key) : null;
  } catch {
    return null;
  }
}

/** The launch code from a `#c=<code>` hash, or null. */
export function readLaunchCode(hash) {
  const m = /^#c=([A-Za-z0-9_-]{1,200})$/.exec(String(hash || ''));
  return m ? m[1] : null;
}

export function setForbiddenHandler(fn) {
  onForbidden = typeof fn === 'function' ? fn : () => {};
}

export function serverVersion() {
  return version;
}

/**
 * Exchange the launch code (read once from the hash, then removed from the URL) for a session,
 * or reuse this tab's session. Returns true when a session is available.
 */
export async function bootstrap(loc = globalThis.location, hist = globalThis.history) {
  const code = readLaunchCode(loc.hash);
  if (loc.hash.startsWith('#c=')) hist.replaceState(null, '', `${loc.pathname}${loc.search}#/tickets`);
  token = recall(TOKEN_KEY);
  version = recall(VERSION_KEY);
  if (!code) return Boolean(token);
  try {
    const res = await fetch('/api/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
      credentials: 'same-origin',
      cache: 'no-store',
    });
    const data = await res.json().catch(() => null);
    if (res.ok && data && typeof data.session === 'string') {
      token = data.session;
      version = typeof data.version === 'string' ? data.version : null;
      remember(TOKEN_KEY, token);
      remember(VERSION_KEY, version);
      return true;
    }
  } catch {
    // The server is unreachable; fall through to whatever session this tab already had.
  }
  return Boolean(token);
}

async function parseError(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  const err = body && body.error && typeof body.error === 'object' ? body.error : {};
  return new ApiError(res.status, typeof err.code === 'string' ? err.code : `http-${res.status}`,
    typeof err.message === 'string' ? err.message : res.statusText, err.details);
}

/** One API call. `json` sends a JSON body; `binary` sends raw bytes with optional extra headers. */
export async function request(method, path, { json, binary, headers, signal } = {}) {
  if (!token) {
    onForbidden();
    throw new ApiError(403, 'forbidden', 'no session');
  }
  const init = { method, headers: { [SESSION_HEADER]: token, ...(headers || {}) }, signal, cache: 'no-store', credentials: 'same-origin' };
  if (binary !== undefined) {
    init.headers['Content-Type'] = 'application/octet-stream';
    init.body = binary;
  } else if (json !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(json);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (exc) {
    if (exc && exc.name === 'AbortError') throw exc;
    throw new ApiError(0, 'network', 'the console server did not answer');
  }
  if (res.status === 403) {
    const err = await parseError(res);
    // A tab opened after a job started may not answer it; the session itself is still good.
    if (err.code === 'session-too-new') throw err;
    token = null;
    remember(TOKEN_KEY, null);
    onForbidden();
    throw err;
  }
  if (!res.ok) throw await parseError(res);
  try {
    return await res.json();
  } catch {
    throw new ApiError(res.status, 'bad-response', 'the answer was not JSON');
  }
}

const seg = (s) => encodeURIComponent(String(s));

export const api = {
  config: () => request('GET', '/api/config'),
  tickets: () => request('GET', '/api/tickets'),
  ticket: (t) => request('GET', `/api/tickets/${seg(t)}`),
  revision: (t, rev) => request('GET', `/api/tickets/${seg(t)}/revisions/${seg(rev)}`),
  hash: (t) => request('GET', `/api/tickets/${seg(t)}/hash`),
  trace: (t, workbook, template) => {
    const q = new URLSearchParams({ workbook });
    if (template) q.set('template', template);
    return request('GET', `/api/tickets/${seg(t)}/trace?${q}`);
  },
  cache: () => request('GET', '/api/cache'),
  templates: () => request('GET', '/api/templates'),
  templatePreview: (name) => request('GET', `/api/templates/${seg(name)}/preview`),
  upload: async (file) => {
    if (file.size > UPLOAD_CAP) throw new ApiError(413, 'too-large', 'file larger than 10 MB');
    const bytes = await file.arrayBuffer();
    return request('POST', '/api/templates/uploads', {
      binary: bytes,
      headers: { 'X-Filename': `UTF-8''${encodeURIComponent(file.name)}` },
    });
  },
  uploadPreview: (upload, body) => request('POST', `/api/templates/uploads/${seg(upload)}/preview`, { json: body }),
  register: (body) => request('POST', '/api/templates', { json: body }),
  setDefault: (name) => request('POST', `/api/templates/${seg(name)}/default`, { json: {} }),
  remove: (name) => request('DELETE', `/api/templates/${seg(name)}`),
  state: () => request('GET', '/api/state'),
  jobs: () => request('GET', '/api/jobs'),
  job: (id) => request('GET', `/api/jobs/${seg(id)}`),
  createJob: (body) => request('POST', '/api/jobs', { json: body }),
  answer: (id, askId, answer) => request('POST', `/api/jobs/${seg(id)}/answer`, { json: { ask_id: askId, answer } }),
  cancelJob: (id) => request('POST', `/api/jobs/${seg(id)}/cancel`, { json: {} }),
  failJob: (id) => request('POST', `/api/jobs/${seg(id)}/fail`, { json: {} }),
  releaseAgent: () => request('POST', '/api/agent/release', { json: {} }),
};
