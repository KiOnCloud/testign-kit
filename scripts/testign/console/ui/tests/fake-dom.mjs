// A minimal document for testing DOM builders under node: elements, text nodes, attributes,
// listeners and textContent. Nothing here parses markup.

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

  set textContent(value) {
    this.childNodes = [];
    this.ownText = String(value);
  }

  get textContent() { return this.ownText + this.childNodes.map((c) => c.textContent).join(''); }
}

export function installFakeDocument() {
  const document = {
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
