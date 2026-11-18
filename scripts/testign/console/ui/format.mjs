// Display formats: ISO dates, short commits, counts, compact row ranges.

const ISO_DAY = /^(\d{4}-\d{2}-\d{2})(?:$|[T ])/;
export const NONE = '—';

function pad(n) {
  return String(n).padStart(2, '0');
}

function localDay(date) {
  if (Number.isNaN(date.getTime())) return NONE;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * YYYY-MM-DD. An ISO string keeps the day as written (the report's own date); a number is epoch
 * seconds (file times) shown in local time; anything else is an em dash.
 */
export function isoDate(value) {
  if (value === null || value === undefined || value === '') return NONE;
  if (value instanceof Date) return localDay(value);
  if (typeof value === 'number') return Number.isFinite(value) ? localDay(new Date(value * 1000)) : NONE;
  const m = ISO_DAY.exec(String(value).trim());
  return m ? m[1] : NONE;
}

export function shortSha(value) {
  const text = typeof value === 'string' ? value.trim() : '';
  return /^[0-9a-f]{7,64}$/i.test(text) ? text.slice(0, 7) : (text || NONE);
}

export function count(value) {
  return Number.isFinite(value) ? String(value) : NONE;
}

/** ['B1','B2','B3','B5'] → 'B1–B3, B5'; ids of other shapes are listed as they are. */
export function idRanges(ids) {
  const list = Array.isArray(ids) ? ids : [];
  const parsed = list.map((id) => {
    const m = /^([A-Z]+)(\d+)$/.exec(String(id));
    return m ? { prefix: m[1], n: Number(m[2]), raw: String(id) } : { raw: String(id) };
  });
  const out = [];
  let run = null;
  const flush = () => {
    if (!run) return;
    out.push(run.end === run.start ? `${run.prefix}${run.start}` : `${run.prefix}${run.start}–${run.prefix}${run.end}`);
    run = null;
  };
  for (const item of parsed) {
    if (item.prefix === undefined) {
      flush();
      out.push(item.raw);
    } else if (run && run.prefix === item.prefix && item.n === run.end + 1) {
      run.end = item.n;
    } else {
      flush();
      run = { prefix: item.prefix, start: item.n, end: item.n };
    }
  }
  flush();
  return out.join(', ');
}
