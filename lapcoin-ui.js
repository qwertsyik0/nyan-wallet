/* Nyan Wallet official Lapcoin: a pictured coin, never a native emoji.
 * Preserves numeric amounts and underlying business logic across all screens.
 */
(() => {
  "use strict";
  if (window.__NYAN_LAPCOIN_UI_V1__) return;
  window.__NYAN_LAPCOIN_UI_V1__ = true;

  const TOKEN = "\uD83D\uDC3E";
  const script = document.currentScript;
  const url = new URL("./assets/lapcoin/lapcoin.webp", script?.src || location.href).href;
  const OMIT = new Set([
    "SCRIPT", "STYLE", "NOSCRIPT", "TITLE", "TEXTAREA",
    "OPTION", "PRE", "CODE", "SVG", "CANVAS",
  ]);
  const style = document.createElement("style");
  style.textContent = [
    ".nyan-lapcoin-icon{display:inline-block;width:1.12em;height:1.12em;",
    "vertical-align:-.15em;object-fit:contain;flex:none;max-width:none;}",
    ".nyan-lapcoin-icon.is-brand{width:1.45em;height:1.45em}",
    ".wallet-card-mark .nyan-lapcoin-icon,.wallet-mark .nyan-lapcoin-icon{width:1.5em;height:1.5em}",
    ".fortune-brand-paw .nyan-lapcoin-icon{width:1.3em;height:1.3em}",
  ].join("");
  (document.head || document.documentElement).append(style);

  function replacement() {
    const img = document.createElement("img");
    img.className = "nyan-lapcoin-icon";
    img.src = url;
    img.alt = "лапкоин";
    img.width = 22;
    img.height = 22;
    img.decoding = "async";
    img.loading = "eager";
    return img;
  }

  function eligible(textNode) {
    if (textNode.nodeType !== 3 || !textNode.nodeValue.includes(TOKEN)) return false;
    const el = textNode.parentElement;
    if (!el) return false;
    for (let parent = el; parent; parent = parent.parentElement) {
      if (OMIT.has(parent.tagName?.toUpperCase()) ||
          parent.namespaceURI === "http://www.w3.org/2000/svg" ||
          parent.isContentEditable) return false;
    }
    return true;
  }

  function replaceText(textNode) {
    if (!eligible(textNode)) return;
    const fragments = textNode.nodeValue.split(TOKEN);
    const container = document.createDocumentFragment();
    fragments.forEach((text, i) => {
      if (i) container.append(replacement());
      if (text) container.append(document.createTextNode(text));
    });
    textNode.replaceWith(container);
  }

  function scanLabels(root) {
    const current = root.nodeType === 1 ? [root] : [];
    if (root.querySelectorAll) {
      for (const child of root.querySelectorAll("[placeholder], [title], [aria-label]")) {
        current.push(child);
      }
    }
    for (const element of current) {
      if (!element.getAttribute || element.isContentEditable) continue;
      for (const attribute of ["placeholder", "title", "aria-label"]) {
        const value = element.getAttribute(attribute);
        if (value && value.includes(TOKEN)) {
          element.setAttribute(attribute, value.split(TOKEN).join("лапкоинов"));
        }
      }
    }
  }

  function scan(root) {
    if (!root || root.nodeType === 8) return;
    if (root.nodeType === 3) {
      replaceText(root);
      return;
    }
    if (root.nodeType !== 1 && root.nodeType !== 11 && root.nodeType !== 9) return;
    if (root.nodeType === 1 && (
      OMIT.has(root.tagName?.toUpperCase()) ||
      root.namespaceURI === "http://www.w3.org/2000/svg"
    )) return;
    scanLabels(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const matches = [];
    while (walker.nextNode()) {
      if (eligible(walker.currentNode)) matches.push(walker.currentNode);
    }
    for (const textNode of matches) replaceText(textNode);
  }

  const pending = new Set();
  let scheduled = false;
  function flush() {
    scheduled = false;
    const nodes = Array.from(pending);
    pending.clear();
    for (const node of nodes) scan(node);
  }
  function enqueue(node) {
    pending.add(node);
    if (!scheduled) {
      scheduled = true;
      queueMicrotask(flush);
    }
  }
  const observer = new MutationObserver((changes) => {
    for (const change of changes) {
      if (change.type === "characterData") {
        enqueue(change.target);
      } else if (change.type === "attributes") {
        enqueue(change.target);
      } else {
        for (const node of change.addedNodes) enqueue(node);
      }
    }
  });
  function begin() {
    if (!document.body) return;
    scan(document.body);
    observer.observe(document.body, {
      subtree: true, characterData: true, childList: true,
      attributes: true, attributeFilter: ["placeholder", "title", "aria-label"],
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", begin, {once: true});
  } else {
    begin();
  }
  window.NyanLapcoin = Object.freeze({ imageUrl: url });
})();
