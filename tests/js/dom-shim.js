// Just enough DOM for dom.js `patch()` to run under node: elements with children and attributes, text
// nodes, a `document` with createElement / createTextNode. Lets a test render real vnodes and then look
// at what the page would contain (which elements, which attributes, which text).

class FakeNode {
  constructor(nodeType) {
    this.nodeType = nodeType;
    this.parentNode = null;
  }

  remove() {
    this.parentNode?.removeChild(this);
  }
}

class FakeText extends FakeNode {
  constructor(text) {
    super(3);
    this.nodeValue = text;
  }
}

class FakeElement extends FakeNode {
  constructor(tag) {
    super(1);
    this.localName = tag;
    this.childNodes = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.style = { setProperty() {}, removeProperty() {} };
  }

  get firstChild() {
    return this.childNodes[0] ?? null;
  }

  get nextSibling() {
    const list = this.parentNode?.childNodes;
    return list ? (list[list.indexOf(this) + 1] ?? null) : null;
  }

  removeChild(node) {
    const index = this.childNodes.indexOf(node);
    if (index >= 0) this.childNodes.splice(index, 1);
    node.parentNode = null;
  }

  insertBefore(node, ref) {
    node.parentNode?.removeChild(node);
    const index = ref ? this.childNodes.indexOf(ref) : -1;
    if (index < 0) this.childNodes.push(node);
    else this.childNodes.splice(index, 0, node);
    node.parentNode = this;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  addEventListener(type) {
    this.listeners.set(type, true);
  }

  removeEventListener(type) {
    this.listeners.delete(type);
  }

  getRootNode() {
    return { activeElement: null };
  }
}

/** Installs a fake `document`; returns the function that restores the previous one. */
export function installDom() {
  const previous = globalThis.document;
  globalThis.document = { createElement: (tag) => new FakeElement(tag), createTextNode: (text) => new FakeText(text) };
  return () => {
    if (previous === undefined) delete globalThis.document;
    else globalThis.document = previous;
  };
}

export const newContainer = () => new FakeElement("div");

/** Every node below `node` (depth first), elements and text nodes. */
export function walk(node, visit) {
  for (const child of node.childNodes || []) {
    visit(child);
    walk(child, visit);
  }
}

export function findAll(node, predicate) {
  const found = [];
  walk(node, (n) => {
    if (n.nodeType === 1 && predicate(n)) found.push(n);
  });
  return found;
}

export const hasClass = (el, name) => (el.getAttribute("class") || "").split(/\s+/).includes(name);

export function textOf(node) {
  if (node.nodeType === 3) return node.nodeValue;
  return (node.childNodes || []).map(textOf).join("");
}

export const buttonsOf = (root) => findAll(root, (el) => el.localName === "button");
export const buttonLabels = (root) => buttonsOf(root).map((b) => textOf(b).trim());
