// DOM building without markup strings. Text always goes in through textContent or text nodes,
// event handlers only through addEventListener, styling only through classes.

const BIDI_RE = /[‪-‮⁦-⁩]/g;
const SVG_NS = 'http://www.w3.org/2000/svg';

function doc() {
  const d = globalThis.document;
  if (!d) throw new Error('no document');
  return d;
}

/** Bidi control characters shown as visible marks, so a quote cannot display differently from what is stored. */
export function showBidi(text) {
  return String(text).replace(BIDI_RE, (ch) => `⟨U+${ch.codePointAt(0).toString(16).toUpperCase()}⟩`);
}

function refused(name) {
  const lower = name.toLowerCase();
  return lower === 'style' || (lower.length > 2 && lower.startsWith('on'));
}

function setAttrs(el, attrs) {
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (name === 'on') {
      for (const [type, fn] of Object.entries(value)) {
        if (typeof fn !== 'function') throw new TypeError(`handler for ${type} is not a function`);
        el.addEventListener(type, fn);
      }
      continue;
    }
    if (refused(name)) throw new Error(`attribute "${name}" is not allowed; use a class or the "on" map`);
    if (name === 'class') {
      const list = Array.isArray(value) ? value.filter(Boolean).join(' ') : String(value);
      if (list) el.setAttribute('class', list);
      continue;
    }
    if (name === 'dataset') {
      for (const [k, v] of Object.entries(value)) {
        if (v !== undefined && v !== null) el.dataset[k] = String(v);
      }
      continue;
    }
    if (name === 'value' || name === 'checked' || name === 'selected' || name === 'disabled' || name === 'hidden') {
      el[name] = value === true ? true : value;
      if (name !== 'value' && value === true) el.setAttribute(name, '');
      continue;
    }
    el.setAttribute(name, value === true ? '' : String(value));
  }
}

function append(el, child) {
  if (child === null || child === undefined || child === false || child === true) return;
  if (Array.isArray(child)) {
    for (const c of child) append(el, c);
    return;
  }
  if (typeof child === 'string' || typeof child === 'number') {
    const node = doc().createTextNode('');
    node.textContent = showBidi(child);
    el.appendChild(node);
    return;
  }
  el.appendChild(child);
}

/**
 * h('tag.class', {attr: value, on: {click: fn}}, children)
 * Strings are set as text with bidi controls made visible; `style` and `on*` attributes are refused.
 */
export function h(tag, attrs, children) {
  if (typeof attrs === 'string' || typeof attrs === 'number' || Array.isArray(attrs) || (attrs && attrs.nodeType)) {
    children = attrs;
    attrs = undefined;
  }
  const [name, ...classes] = String(tag).split('.');
  const el = doc().createElement(name || 'div');
  if (classes.length) el.setAttribute('class', classes.join(' '));
  if (attrs && attrs.class) {
    const extra = Array.isArray(attrs.class) ? attrs.class.filter(Boolean).join(' ') : String(attrs.class);
    attrs = { ...attrs, class: [classes.join(' '), extra].filter(Boolean).join(' ') };
  }
  setAttrs(el, attrs);
  if (typeof children === 'string' || typeof children === 'number') {
    el.textContent = showBidi(children);
  } else {
    append(el, children);
  }
  return el;
}

/** Replace all children of `el`. */
export function mount(el, ...children) {
  while (el.firstChild) el.removeChild(el.firstChild);
  append(el, children);
  return el;
}

// Line icons from the Kestrel set: 16px box, 1.5px stroke, currentColor.
const ICONS = {
  search: [['circle', { cx: 7, cy: 7, r: 4.5 }], ['path', { d: 'm13 13-2.6-2.6' }]],
  file: [['path', { d: 'M4 2.5h5l3 3v8H4v-11Z' }], ['path', { d: 'M9 2.5v3h3M6 8h4M6 10.5h4' }]],
  layers: [['path', { d: 'm8 2.5 5.5 3L8 8.5l-5.5-3Z' }], ['path', { d: 'm2.5 8.5 5.5 3 5.5-3' }], ['path', { d: 'm2.5 11 5.5 3 5.5-3' }]],
  folder: [['path', { d: 'M2.5 4.5a1 1 0 0 1 1-1h3l1.5 1.5h4.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-7.5Z' }]],
  settings: [['circle', { cx: 8, cy: 8, r: 2 }], ['path', { d: 'M8 2v1.5M8 12.5V14M2 8h1.5M12.5 8H14M3.8 3.8l1 1M11.2 11.2l1 1M3.8 12.2l1-1M11.2 4.8l1-1' }]],
  chevron: [['path', { d: 'm6 4 4 4-4 4' }]],
  check: [['path', { d: 'm3.5 8.5 3 3 6-7' }]],
  warning: [['path', { d: 'M7.1 3 2.2 11.5a1 1 0 0 0 .9 1.5h9.8a1 1 0 0 0 .9-1.5L8.9 3a1 1 0 0 0-1.8 0Z' }], ['path', { d: 'M8 6.5v3M8 11.5v.1' }]],
  info: [['circle', { cx: 8, cy: 8, r: 5.5 }], ['path', { d: 'M8 7v4M8 5.2v.1' }]],
  close: [['path', { d: 'm4 4 8 8M12 4l-8 8' }]],
  plus: [['path', { d: 'M8 3v10M3 8h10' }]],
  copy: [['rect', { x: 5.5, y: 5.5, width: 8, height: 8, rx: 1.5 }], ['path', { d: 'M10.5 5.5V3.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2' }]],
  branch: [['circle', { cx: 4.5, cy: 3.5, r: 1.5 }], ['circle', { cx: 4.5, cy: 12.5, r: 1.5 }], ['circle', { cx: 11.5, cy: 5.5, r: 1.5 }], ['path', { d: 'M4.5 5v6M11.5 7a4 4 0 0 1-4 4H6' }]],
  dash: [['path', { d: 'M4 8h8' }]],
};

/** An inline SVG icon built with createElementNS; `extra` adds classes such as 'k-icon--sm'. */
export function icon(name, extra) {
  const d = doc();
  const svg = d.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', ['k-icon', extra].filter(Boolean).join(' '));
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.5');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  for (const [tag, attrs] of ICONS[name] || []) {
    const part = d.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) part.setAttribute(k, String(v));
    svg.appendChild(part);
  }
  return svg;
}

/** Inline Markdown emphasis and code spans as elements; everything else stays text. */
export function inline(text) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/);
  return parts.filter((p) => p !== '').map((p) => {
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4) return h('strong', p.slice(2, -2));
    if (p.startsWith('`') && p.endsWith('`') && p.length > 2) return h('code.k-mono', p.slice(1, -1));
    return p;
  });
}
