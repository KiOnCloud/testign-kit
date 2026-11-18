// Command palette (Ctrl/Cmd+K), focus trapping for floating layers, and the guard that keeps
// single-key shortcuts away from text fields.

import { h, icon, mount } from './dom.mjs';

const EDITABLE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

/** True when focus is somewhere typing happens: input, textarea, select or contenteditable. */
export function isTypingTarget(el) {
  let node = el;
  while (node && node.nodeType === 1) {
    if (EDITABLE_TAGS.has(String(node.tagName).toUpperCase())) return true;
    if (node.isContentEditable === true) return true;
    const ce = typeof node.getAttribute === 'function' ? node.getAttribute('contenteditable') : null;
    if (ce !== null && ce !== 'false') return true;
    node = node.parentElement || null;
  }
  return false;
}

/** A single-key shortcut may run: no modifier held and focus is not in a field. */
export function singleKeyAllowed(event) {
  if (event.ctrlKey || event.metaKey || event.altKey) return false;
  return !isTypingTarget(event.target);
}

/** Ctrl+K on Windows/Linux, Cmd+K on macOS. */
export function isPaletteKey(event) {
  return Boolean(event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && String(event.key).toLowerCase() === 'k';
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Keep Tab inside `layer`; returns a function that removes the trap. */
export function trapFocus(layer) {
  const onKey = (event) => {
    if (event.key !== 'Tab') return;
    const items = [...layer.querySelectorAll(FOCUSABLE)].filter((el) => !el.hidden && el.offsetParent !== null);
    if (!items.length) {
      event.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = layer.ownerDocument.activeElement;
    if (event.shiftKey && (active === first || !layer.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !layer.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  };
  layer.addEventListener('keydown', onKey);
  return () => layer.removeEventListener('keydown', onKey);
}

/** Items whose label or hint contains every word of the query, case-insensitively. */
export function filterItems(items, query) {
  const words = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return items;
  return items.filter((item) => {
    const hay = `${item.label} ${item.hint || ''}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

let open = null;

export function paletteOpen() {
  return open !== null;
}

export function closePalette() {
  if (!open) return false;
  open.close();
  return true;
}

/**
 * Open the palette. `items` is [{group, label, hint?, icon?, run}], `t` the translator.
 * `more` may be a promise of further items (tickets) that are merged in when it settles.
 */
export function openPalette({ t, items, more }) {
  if (open) return;
  const trigger = document.activeElement;
  let all = items.slice();
  let shown = all;
  let active = 0;
  const listId = 'palette-list';
  const input = h('input', {
    type: 'text', placeholder: t('palette_placeholder'), 'aria-label': t('palette_placeholder'),
    role: 'combobox', 'aria-expanded': 'true', 'aria-controls': listId, autocomplete: 'off', spellcheck: 'false',
  });
  const list = h('div.k-palette__list', { id: listId, role: 'listbox', 'aria-label': t('palette_title') });
  const layer = h('div.k-scrim.layer.palette-layer', { role: 'presentation' }, [
    h('div.k-palette', { role: 'dialog', 'aria-modal': 'true', 'aria-label': t('palette_title') }, [
      h('div.k-palette__input', [icon('search'), input]),
      list,
      h('div.k-palette__footer', [
        h('span.k-hint', [h('kbd.k-kbd', '↑'), h('kbd.k-kbd', '↓'), t('palette_move')]),
        h('span.k-hint', [h('kbd.k-kbd', '↵'), t('palette_open')]),
        h('span.k-hint', [h('kbd.k-kbd', 'Esc'), t('palette_close')]),
      ]),
    ]),
  ]);

  function draw() {
    const nodes = [];
    let group = null;
    shown.forEach((item, i) => {
      if (item.group !== group) {
        group = item.group;
        nodes.push(h('div.k-palette__label', { role: 'presentation' }, group));
      }
      nodes.push(h('div.k-palette__item', {
        id: `palette-opt-${i}`, role: 'option', 'aria-selected': i === active ? 'true' : 'false',
        class: i === active ? 'is-active' : '',
        on: {
          mousemove: () => { if (active !== i) { active = i; draw(); } },
          click: () => run(i),
        },
      }, [icon(item.icon || 'file'), h('span.palette-label', item.label), item.hint ? h('span.k-crumb', item.hint) : null]));
    });
    if (!shown.length) nodes.push(h('div.k-palette__label', t('palette_empty')));
    mount(list, nodes);
    if (shown.length) {
      input.setAttribute('aria-activedescendant', `palette-opt-${active}`);
      const el = list.querySelector(`#palette-opt-${active}`);
      if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
    } else {
      input.removeAttribute('aria-activedescendant');
    }
  }

  function refilter() {
    shown = filterItems(all, input.value);
    active = 0;
    draw();
  }

  function run(i) {
    const item = shown[i];
    if (!item) return;
    close();
    item.run();
  }

  const release = trapFocus(layer);
  function close() {
    if (!open) return;
    open = null;
    release();
    layer.remove();
    if (trigger && typeof trigger.focus === 'function' && trigger.isConnected) trigger.focus();
  }

  input.addEventListener('input', refilter);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!shown.length) return;
      active = (active + (event.key === 'ArrowDown' ? 1 : -1) + shown.length) % shown.length;
      draw();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      run(active);
    }
  });
  layer.addEventListener('mousedown', (event) => {
    if (event.target === layer) close();
  });

  open = { close };
  document.body.appendChild(layer);
  draw();
  input.focus();

  if (more && typeof more.then === 'function') {
    more.then((extra) => {
      if (!open || !Array.isArray(extra) || !extra.length) return;
      all = all.concat(extra);
      shown = filterItems(all, input.value);
      if (active >= shown.length) active = 0;
      draw();
    }, () => {});
  }
}
