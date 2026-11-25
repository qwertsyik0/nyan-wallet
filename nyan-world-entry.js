(() => {
  "use strict";
  const wallet = document.getElementById("wallet-view");
  if (!wallet) return;
  if (!document.getElementById("nyan-world-entry-style")) {
    const link = document.createElement("link");
    link.id = "nyan-world-entry-style";
    link.rel = "stylesheet";
    link.href = "./nyan-world-entry.css?v=20261125-card1";
    document.head.append(link);
  }
  let scheduled = false;
  function mount() {
    scheduled = false;
    let button = document.getElementById("nyan-world-open");
    if (!button) {
      button = document.createElement("button");
      button.id = "nyan-world-open";
    }
    if (!button.classList.contains("nyan-world-entry")) {
      button.type = "button";
      button.className = "nyan-world-entry";
      button.hidden = false;
      button.removeAttribute("aria-hidden");
      button.innerHTML = '<img class="nyan-world-entry-icon" src="./assets/nyan-world/globe.webp" width="52" height="52" alt="" aria-hidden="true"><span class="nyan-world-entry-copy"><strong>NYAN WORLD</strong><small>твоя страна, бюджет и решения</small></span><svg class="nyan-world-entry-chevron" width="18" height="24" viewBox="0 0 18 24" fill="none" aria-hidden="true"><path d="m6 5 6 7-6 7" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      button.addEventListener("click", () => {
        location.href = "./nyan-world.html" + location.search + location.hash;
      });
    }
    const anchor = document.getElementById("nyan-vip-open") || document.getElementById("nyid-front-open");
    if (anchor && wallet.contains(anchor)) {
      if (anchor.nextElementSibling !== button) anchor.insertAdjacentElement("afterend", button);
      return;
    }
    let balance = document.getElementById("wallet-card");
    if (balance && wallet.contains(balance)) {
      while (balance.parentElement !== wallet) balance = balance.parentElement;
      if (balance.previousElementSibling !== button) wallet.insertBefore(button, balance);
    } else if (button.parentElement !== wallet) wallet.append(button);
  }
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(mount);
  }
  new MutationObserver(schedule).observe(wallet, { childList: true, subtree: true });
  mount();
})();