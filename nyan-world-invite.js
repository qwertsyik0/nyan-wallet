(() => {
  "use strict";
  if (window.__nyanWorldInviteMounted) return;
  window.__nyanWorldInviteMounted = true;
  const wallet = document.getElementById("wallet-view");
  const loading = document.getElementById("loading-view");
  if (!wallet) return;
  const style = document.createElement("link");
  style.rel = "stylesheet";
  style.href = "./nyan-world-invite.css?v=20261125-1";
  document.head.append(style);
  let ready = window.__nyanWalletReady === true;
  let shownThisOpening = false;
  let overlay = null;
  let previousFocus = null;
  let scheduled = false;
  function visible(node) {
    if (!node || node.closest("[hidden], .hidden")) return false;
    for (let current = node; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (current.hidden || style.display === "none" || style.visibility === "hidden") return false;
    }
    return true;
  }
  function anotherDialog() {
    return [...document.querySelectorAll('dialog[open], [role="dialog"][aria-modal="true"]')]
      .some(node => node !== overlay?.querySelector('[role="dialog"]') && visible(node));
  }
  function close() {
    overlay.hidden = true;
    document.documentElement.classList.remove("nwp-open");
    if (previousFocus?.isConnected) previousFocus.focus();
  }
  function build() {
    overlay = document.createElement("div");
    overlay.id = "nyan-world-invite";
    overlay.className = "nwp-backdrop";
    overlay.hidden = true;
    overlay.innerHTML = '<div class="nwp-stage"><section class="nwp-window" role="dialog" aria-modal="true" aria-labelledby="nwp-title" aria-describedby="nwp-description"><img class="nwp-nyanik" src="./assets/nyan-world/nyanik-hold.webp" width="210" height="210" alt="" aria-hidden="true"><div class="nwp-titlebar"><span>NYAN WORLD</span><button id="nwp-close" class="nwp-close" type="button" aria-label="Закрыть приглашение"><svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button></div><div class="nwp-copy"><span class="nwp-kicker">ПОЛИТИЧЕСКИЙ ИВЕНТ</span><h2 id="nwp-title">мир скоро окажется<br>в твоих руках</h2><p id="nwp-description">NYAN WORLD уже открыт для участия. возглавь государство и стань частью мировой политики</p><a id="nwp-learn" class="nwp-learn" href="./nyan-world-info.html">ознакомиться</a></div></section></div>';
    overlay.querySelector("#nwp-close").addEventListener("click", close);
    const learn = overlay.querySelector("#nwp-learn");
    learn.href = "./nyan-world-info.html" + location.search + location.hash;
    document.body.append(overlay);
  }
  function check() {
    scheduled = false;
    if (!ready || document.hidden || !visible(wallet) || visible(loading)) return;
    if (overlay && !overlay.hidden) {
      shownThisOpening = true;
      return;
    }
    if (shownThisOpening || anotherDialog()) return;
    if (!overlay) build();
    previousFocus = document.activeElement;
    shownThisOpening = true;
    overlay.hidden = false;
    document.documentElement.classList.add("nwp-open");
    overlay.querySelector("#nwp-close").focus();
  }
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(check);
  }
  window.addEventListener("nyan-wallet-ready", () => { ready = true; schedule(); });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { shownThisOpening = false; schedule(); }
  });
  window.addEventListener("pageshow", event => {
    if (event.persisted) { shownThisOpening = false; schedule(); }
  });
  document.addEventListener("keydown", event => {
    if (!overlay || overlay.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
    if (event.key === "Tab") {
      const first = overlay.querySelector("#nwp-close");
      const last = overlay.querySelector("#nwp-learn");
      if (event.shiftKey && (document.activeElement === first || !overlay.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !overlay.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    }
  }, true);
  new MutationObserver(schedule).observe(document.body, {
    subtree: true, childList: true, attributes: true, attributeFilter: ["class", "hidden", "open", "style"]
  });
  schedule();
})();