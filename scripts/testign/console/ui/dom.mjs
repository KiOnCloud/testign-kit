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

// Line icons on a 16px box with a 1.5px stroke in currentColor, drawn like Yohaku's icons.
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
  refresh: [['path', { d: 'M13 8A5 5 0 0 1 4.3 11.3M3 8a5 5 0 0 1 8.7-3.3' }], ['path', { d: 'M11.7 2.5v2.2h-2.2M4.3 13.5v-2.2h2.2' }]],
  play: [['path', { d: 'M5 3.5v9l7-4.5-7-4.5Z' }]],
  key: [['circle', { cx: 5.5, cy: 10.5, r: 2.5 }], ['path', { d: 'm7.3 8.7 5.2-5.2M10.5 5.5l1.5 1.5M11.8 4.2l1.2 1.2' }]],
  up: [['path', { d: 'm4 10 4-4 4 4' }]],
  down: [['path', { d: 'm4 6 4 4 4-4' }]],
  external: [['path', { d: 'M9 3h4v4M13 3 7.5 8.5' }], ['path', { d: 'M11 9.5V13H3V5h3.5' }]],
  user: [['circle', { cx: 8, cy: 5.5, r: 2.5 }], ['path', { d: 'M3 13.5a5 5 0 0 1 10 0' }]],
  eye: [['path', { d: 'M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8Z' }], ['circle', { cx: 8, cy: 8, r: 2 }]],
  clock: [['circle', { cx: 8, cy: 8, r: 5.5 }], ['path', { d: 'M8 5v3l2 1.5' }]],
  design: [['path', { d: 'M3 13l2.5-.5L12 6 10 4 3.5 10.5 3 13Z' }], ['path', { d: 'M9 5l2 2' }]],
  suite: [['rect', { x: 2.5, y: 3, width: 11, height: 10 }], ['path', { d: 'M5 6h6M5 8.5h6M5 11h3' }]],
  agent: [['rect', { x: 3, y: 4.5, width: 10, height: 8, rx: 2 }], ['path', { d: 'M8 2v2.5M6 8v1M10 8v1' }]],
  database: [['ellipse', { cx: 8, cy: 4, rx: 5, ry: 1.8 }], ['path', { d: 'M3 4v8c0 1 2.2 1.8 5 1.8s5-.8 5-1.8V4M3 8c0 1 2.2 1.8 5 1.8s5-.8 5-1.8' }]],
  sliders: [['path', { d: 'M3 4h10M3 8h10M3 12h10' }], ['circle', { cx: 6, cy: 4, r: 1.2 }], ['circle', { cx: 10, cy: 8, r: 1.2 }], ['circle', { cx: 5, cy: 12, r: 1.2 }]],
  menu: [['path', { d: 'M2.5 4h11M2.5 8h11M2.5 12h11' }]],
  more: [['circle', { cx: 4, cy: 8, r: 0.8 }], ['circle', { cx: 8, cy: 8, r: 0.8 }], ['circle', { cx: 12, cy: 8, r: 0.8 }]],
  trash: [['path', { d: 'M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.5 8.5h6l.5-8.5' }]],
  download: [['path', { d: 'M8 3v8M4.5 7.5 8 11l3.5-3.5M3 13.5h10' }]],
  chat: [['path', { d: 'M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2Z' }]],
  columns: [['rect', { x: 2.5, y: 3, width: 11, height: 10 }], ['path', { d: 'M6.2 3v10M9.8 3v10' }]],
};

/** An inline SVG icon built with createElementNS; `extra` adds classes such as 'yh-icon--sm'. */
export function icon(name, extra) {
  const d = doc();
  const svg = d.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', ['yh-icon', extra].filter(Boolean).join(' '));
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

// Status tones shared by statusIcon and statusGlyph. Each class sets the tone colours in app.css.
export const STATUS_CLASSES = Object.freeze({ ok: 'st--ok', warn: 'st--warn', busy: 'st--busy', bad: 'st--bad' });

/**
 * A status shown as an icon whose meaning is a tooltip on hover or keyboard focus. The anchor is
 * focusable and carries `tip` as its accessible name, so the meaning is reachable without a mouse.
 * `kind` is one of STATUS_CLASSES' keys.
 */
export function statusIcon(kind, iconName, tip) {
  if (!Object.prototype.hasOwnProperty.call(STATUS_CLASSES, kind)) throw new RangeError(`unknown status kind ${kind}`);
  const label = String(tip ?? '');
  return h('span.yh-tip-anchor.st', { class: STATUS_CLASSES[kind], tabindex: '0', role: 'img', 'aria-label': label }, [
    icon(iconName),
    h('span.yh-tip', { role: 'tooltip' }, label),
  ]);
}

// Status glyphs: shape carries the state (hollow, partial, filled, crossed); the tone comes from STATUS_CLASSES.
const GLYPH_TONES = { todo: 'busy', progress: 'busy', done: 'ok', crossed: 'bad' };
const GLYPHS = {
  todo: [['circle', { cx: 7, cy: 7, r: 5.5, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5 }]],
  progress: [['circle', { cx: 7, cy: 7, r: 5.5, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5 }],
    ['path', { d: 'M7 7 L7 3.8 A3.2 3.2 0 0 1 7 10.2 Z', fill: 'currentColor' }]],
  done: [['circle', { cx: 7, cy: 7, r: 6.25, fill: 'currentColor' }],
    ['path', { class: 'k-status__check', d: 'm4.4 7.3 1.8 1.8 3.6-3.9', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }]],
  crossed: [['circle', { cx: 7, cy: 7, r: 5.5, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5 }],
    ['path', { d: 'm5 5 4 4M9 5l-4 4', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-linecap': 'round' }]],
};

/** A 14px status glyph: 'todo', 'progress', 'done' or 'crossed'; `extra` adds classes that can retone it. */
export function statusGlyph(shape, extra) {
  const known = Object.prototype.hasOwnProperty.call(GLYPHS, shape) ? shape : 'todo';
  const d = doc();
  const svg = d.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', ['k-status', STATUS_CLASSES[GLYPH_TONES[known]], extra].filter(Boolean).join(' '));
  svg.setAttribute('viewBox', '0 0 14 14');
  svg.setAttribute('aria-hidden', 'true');
  for (const [tag, attrs] of GLYPHS[known]) {
    const part = d.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) part.setAttribute(k, String(v));
    svg.appendChild(part);
  }
  return svg;
}
