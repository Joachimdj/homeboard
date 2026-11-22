// A very small keyed DOM renderer.
//
//   patch(container, h("div.card", { key: id, onclick }, "text", h("span", ...)))
//
// h() builds plain vnodes, patch() reconciles a container's children against
// them. Elements with a `key` are matched by key and moved, never recreated, so
// a live push keeps focus, scroll positions and an ongoing drag intact.
// Text is always set as text content; there is no way to inject HTML.

class VNode {
  constructor(tag, props, children) {
    this.tag = tag;
    this.props = props;
    this.children = children;
    this.key = props.key == null ? null : String(props.key);
  }
}

const specCache = new Map();

function parseSpec(spec) {
  let parsed = specCache.get(spec);
  if (!parsed) {
    const [tag, ...classes] = spec.split(".");
    parsed = { tag, classes: classes.join(" ") };
    specCache.set(spec, parsed);
  }
  return parsed;
}

function flatten(list, out) {
  for (const child of list) {
    if (child == null || child === false || child === true) continue;
    if (Array.isArray(child)) flatten(child, out);
    else if (child instanceof VNode) out.push(child);
    else out.push(String(child));
  }
  return out;
}

/** h("tag.class1.class2", props?, ...children) */
export function h(spec, props, ...children) {
  let attrs = props;
  let kids = children;
  if (props == null || typeof props !== "object" || Array.isArray(props) || props instanceof VNode) {
    attrs = {};
    kids = props == null ? children : [props, ...children];
  }
  const { tag, classes } = parseSpec(spec);
  const merged = classes ? { ...attrs, class: attrs.class ? `${classes} ${attrs.class}` : classes } : attrs;
  return new VNode(tag, merged, flatten(kids, []));
}

const DOM_PROPS = new Set(["value", "checked", "selected", "indeterminate"]);
const SKIP = new Set(["key", "ref"]);

function dispatch(event) {
  const handler = event.currentTarget.__handlers?.[event.type];
  if (handler) handler(event);
}

function setHandler(el, type, handler) {
  const handlers = (el.__handlers ||= {});
  if (!handler) {
    if (handlers[type]) {
      el.removeEventListener(type, dispatch);
      delete handlers[type];
    }
    return;
  }
  if (!handlers[type]) el.addEventListener(type, dispatch);
  handlers[type] = handler;
}

function setStyle(el, next, prev) {
  if (typeof next === "string" || typeof prev === "string" || next == null) {
    if (next !== prev) el.setAttribute("style", next || "");
    return;
  }
  const before = prev || {};
  for (const name in before) if (!(name in next)) el.style.removeProperty(toCssName(name));
  for (const name in next) {
    if (next[name] === before[name]) continue;
    if (next[name] == null || next[name] === false) el.style.removeProperty(toCssName(name));
    else el.style.setProperty(toCssName(name), String(next[name]));
  }
}

function toCssName(name) {
  return name.startsWith("--") ? name : name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
}

function setAttr(el, name, value) {
  if (value == null || value === false) el.removeAttribute(name);
  else el.setAttribute(name, value === true ? "" : String(value));
}

function applyProps(el, next, prev) {
  for (const name in prev) {
    if (name in next || SKIP.has(name) || DOM_PROPS.has(name)) continue;
    if (name.startsWith("on")) setHandler(el, name.slice(2), null);
    else if (name === "style") setStyle(el, null, prev.style);
    else el.removeAttribute(name);
  }
  for (const name in next) {
    if (SKIP.has(name) || DOM_PROPS.has(name)) continue;
    const value = next[name];
    if (name.startsWith("on")) setHandler(el, name.slice(2), value); // handlers are fresh closures each render
    else if (name === "style") setStyle(el, value, prev.style);
    else if (value !== prev[name]) setAttr(el, name, value);
  }
}

function applyDomProps(el, next, prev) {
  for (const name of DOM_PROPS) {
    if (!(name in next)) continue;
    const value = next[name];
    if (name === "value") {
      const text = value == null ? "" : String(value);
      // A focused field whose bound value did not change keeps what the user is typing.
      const typing = prev.value === value && el.getRootNode().activeElement === el;
      if (el.value !== text && !typing) el.value = text;
    } else if (el[name] !== Boolean(value)) {
      el[name] = Boolean(value);
    }
  }
}

function create(vnode) {
  if (typeof vnode === "string") return document.createTextNode(vnode);
  const el = document.createElement(vnode.tag);
  el.__key = vnode.key;
  el.__props = {};
  update(el, vnode);
  vnode.props.ref?.(el);
  return el;
}

function update(el, vnode) {
  const prev = el.__props;
  applyProps(el, vnode.props, prev);
  el.__props = vnode.props;
  patchChildren(el, vnode.children);
  applyDomProps(el, vnode.props, prev);
}

function matches(node, vnode) {
  if (typeof vnode === "string") return node.nodeType === 3;
  return node.nodeType === 1 && node.localName === vnode.tag && node.__key == null;
}

/** Reconcile `parent`'s child nodes against the list of vnodes / strings. */
function patchChildren(parent, vnodes) {
  const old = Array.from(parent.childNodes);
  const keyed = new Map();
  const unkeyed = [];
  for (const node of old) {
    if (node.__key != null) keyed.set(node.__key, node);
    else unkeyed.push(node);
  }

  const next = [];
  const used = new Set();
  let cursor = 0;
  for (const vnode of vnodes) {
    let node = null;
    if (typeof vnode !== "string" && vnode.key != null) {
      const candidate = keyed.get(vnode.key);
      if (candidate && candidate.localName === vnode.tag && !used.has(candidate)) node = candidate;
    } else {
      for (let i = cursor; i < unkeyed.length; i++) {
        if (matches(unkeyed[i], vnode)) {
          node = unkeyed[i];
          cursor = i + 1;
          break;
        }
      }
    }
    if (node) {
      if (typeof vnode === "string") {
        if (node.nodeValue !== vnode) node.nodeValue = vnode;
      } else {
        update(node, vnode);
      }
    } else {
      node = create(vnode);
    }
    used.add(node);
    next.push(node);
  }

  for (const node of old) if (!used.has(node)) node.remove();

  let ref = parent.firstChild;
  for (const node of next) {
    if (node === ref) ref = ref.nextSibling;
    else parent.insertBefore(node, ref);
  }
}

export function patch(container, vnodes) {
  patchChildren(container, flatten([vnodes], []));
}

/** Constructable stylesheets when available, otherwise a <style> element. */
export function adoptStyles(shadowRoot, ...cssParts) {
  const css = cssParts.join("\n");
  if ("adoptedStyleSheets" in shadowRoot && typeof CSSStyleSheet !== "undefined") {
    try {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(css);
      shadowRoot.adoptedStyleSheets = [sheet];
      return;
    } catch {
      // fall through to the <style> element
    }
  }
  const style = document.createElement("style");
  style.textContent = css;
  shadowRoot.prepend(style);
}

/** Deepest focused element, looking through open shadow roots. */
export function deepActiveElement(root = document) {
  let active = root.activeElement;
  while (active?.shadowRoot?.activeElement) active = active.shadowRoot.activeElement;
  return active;
}
