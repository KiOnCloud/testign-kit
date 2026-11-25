// A minimal document for testing DOM builders under node: elements, text nodes, attributes,
// listeners, textContent, a body for dialogs and a class list. Nothing here parses markup or
// matches selectors: querySelector finds nothing, so callers fall back to the element they pass.

class FakeText {
  constructor() {
    this.nodeType = 3;
    this.textContent = '';
  }
}

class FakeElement {
  constructor(tag, ns) {
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.namespaceURI = ns || null;
    this.attributes = new Map();
    this.childNodes = [];
    this.listeners = {};
    this.dataset = {};
    this.ownText = '';
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  removeAttribute(name) { this.attributes.delete(name); }

  appendChild(child) {
    this.childNodes.push(child);
    child.parentElement = child.nodeType === 1 ? this : undefined;
    return child;
  }

  removeChild(child) {
    this.childNodes = this.childNodes.filter((c) => c !== child);
    return child;
  }

  get firstChild() { return this.childNodes[0] || null; }

  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }

  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }

  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }

  remove() { if (this.parentElement) this.parentElement.removeChild(this); this.parentElement = undefined; }

  focus() { if (globalThis.document) globalThis.document.activeElement = this; }

  querySelector() { return null; }

  querySelectorAll() { return []; }

  get classList() {
    const el = this;
    const read = () => (el.getAttribute('class') || '').split(/\s+/).filter(Boolean);
    const write = (list) => el.setAttribute('class', list.join(' '));
    return {
      contains: (c) => read().includes(c),
      add: (...cs) => write([...new Set([...read(), ...cs])]),
      remove: (...cs) => write(read().filter((x) => !cs.includes(x))),
      toggle: (c, force) => {
        const on = force === undefined ? !read().includes(c) : Boolean(force);
        write(on ? [...new Set([...read(), c])] : read().filter((x) => x !== c));
        return on;
      },
    };
  }

  set textContent(value) {
    this.childNodes = [];
    this.ownText = String(value);
  }

  get textContent() { return this.ownText + this.childNodes.map((c) => c.textContent).join(''); }
}

export function installFakeDocument() {
  const document = {
    body: new FakeElement('body'),
    activeElement: null,
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (ns, tag) => new FakeElement(tag, ns),
    createTextNode: (text) => {
      const node = new FakeText();
      node.textContent = String(text);
      return node;
    },
  };
  globalThis.document = document;
  return document;
}

export function fakeElement(tag, attrs = {}, parent = null) {
  const el = new FakeElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'isContentEditable') el.isContentEditable = v;
    else el.setAttribute(k, v);
  }
  if (parent) parent.appendChild(el);
  return el;
}
