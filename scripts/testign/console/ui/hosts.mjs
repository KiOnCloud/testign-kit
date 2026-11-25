// Hosts as the server reads them. Hosts and sign-in scenarios are set only by the tester; these
// checks show a problem before sending, the server checks again.

/**
 * The host of an http(s) URL in lower case, or null. Like the server, it refuses a backslash,
 * whitespace, a control character, user info or an escaped host: a browser reads `https://a\@b/`
 * as host `a`, which a looser parser reads as `b`.
 */
export function hostOf(url) {
  const s = String(url || '').trim();
  // eslint-disable-next-line no-control-regex
  if (/[\\\s\u0000-\u001f\u007f]/.test(s)) return null;
  const m = /^https?:\/\/([^/?#:@%]+)(?::\d+)?(?:[/?#]|$)/i.exec(s);
  return m ? m[1].toLowerCase().replace(/\.$/, '') : null;
}

const NAME = /^[a-z0-9][a-z0-9-]{0,39}$/;
const HOST = /^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)*$/;
const RESERVED = new Set(['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
  'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']);
export const MAX_HOSTS = 20;

/** Hosts typed one per line or separated by commas or spaces → lower-case, without duplicates. */
export function splitHosts(text) {
  const out = [];
  for (const part of String(text || '').split(/[\s,、，]+/)) {
    const host = part.trim().toLowerCase().replace(/\.$/, '');
    if (host && !out.includes(host)) out.push(host);
  }
  return out;
}

/** An i18n key for what is wrong with a host list, or null. */
export function checkHosts(hosts, required) {
  if (required && !hosts.length) return 'login_err_hosts_empty';
  if (hosts.length > MAX_HOSTS) return 'login_err_hosts_many';
  if (hosts.some((x) => !HOST.test(x))) return 'login_err_host';
  return null;
}

export function checkProjectName(name) {
  return NAME.test(String(name || '')) && !RESERVED.has(String(name).toUpperCase()) ? null : 'login_err_project_name';
}
