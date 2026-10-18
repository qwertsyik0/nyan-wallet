(() => {
  "use strict";
  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const TARGET = "./finance-workspace.html";
  let activeRole = "user";
  let watching = null;
  let checking = false;
  let lastChecked = 0;

  function openWorkspace() {
    const url = new URL(TARGET, location.href);
    if (location.hash) url.hash = location.hash;
    location.assign(url.toString());
  }
  function prepareButton(button) {
    button.type = "button";
    button.addEventListener("click", openWorkspace);
    return button;
  }
  function installEntries() {
    if (activeRole !== "trainee") {
      document.getElementById("fw-profile-entry")?.remove();
      document.getElementById("fw-wallet-entry")?.remove();
    }
    const ownerButton = document.getElementById("owner-finance-workspace");
    if (ownerButton) {
      ownerButton.hidden = activeRole !== "owner";
      if (activeRole === "owner" && !ownerButton.dataset.fwBound) {
        ownerButton.dataset.fwBound = "1";
        ownerButton.addEventListener("click", openWorkspace);
      }
    }
    if (activeRole !== "trainee") return;

    const profile = document.getElementById("adv-profile-view");
    if (profile && !document.getElementById("fw-profile-entry")) {
      const panel = document.createElement("section");
      panel.id = "fw-profile-entry";
      panel.className = "adv-panel";
      const title = document.createElement("div");
      title.className = "adv-title";
      title.textContent = "Управление финансами";
      const description = document.createElement("div");
      description.className = "adv-sub";
      description.textContent = "Кабинет стажёра · заявки на начисления, списания и проверки";
      const button = prepareButton(document.createElement("button"));
      button.className = "fw-entry-button";
      button.textContent = "Открыть управление финансами";
      panel.append(title, description, button);
      const header = profile.querySelector(".subpage-header");
      if (header) header.insertAdjacentElement("afterend", panel);
      else profile.prepend(panel);
    }
    const wallet = document.getElementById("wallet-view");
    if (wallet && !document.getElementById("fw-wallet-entry")) {
      const button = prepareButton(document.createElement("button"));
      button.id = "fw-wallet-entry";
      button.className = "fw-entry-button";
      button.textContent = "Управление финансами · стажировка";
      const history = wallet.querySelector(".history");
      if (history) history.insertAdjacentElement("beforebegin", button);
      else wallet.appendChild(button);
    }
  }
  function watchLateProfile() {
    if (watching || activeRole !== "trainee") return;
    if (document.getElementById("fw-profile-entry") &&
        document.getElementById("fw-wallet-entry")) return;
    watching = new MutationObserver(() => {
      installEntries();
      if (document.getElementById("fw-profile-entry") &&
          document.getElementById("fw-wallet-entry")) {
        watching.disconnect();
        watching = null;
      }
    });
    watching.observe(document.body, {childList: true, subtree: true});
  }
  function ensureStyle() {
    if (document.getElementById("fw-entry-style")) return;
    const style = document.createElement("style");
    style.id = "fw-entry-style";
    style.textContent = `
      .fw-entry-button{display:block;width:100%;padding:15px 16px;margin:15px 0;
        border:1px solid #eac5d9;border-radius:15px;background:#fff1f7;color:#852f58;
        box-shadow:0 6px 18px rgba(148,66,103,.06);font:800 13px system-ui,-apple-system,sans-serif;
        text-align:center;cursor:pointer}
      .fw-entry-button:active{opacity:.76}
      #fw-profile-entry .fw-entry-button{margin-bottom:0}
      #owner-finance-workspace[hidden]{display:none!important}
    `;
    document.head.appendChild(style);
  }
  async function refreshRole(force = false) {
    if (!tg?.initData || checking || (!force && Date.now() - lastChecked < 3500)) return;
    checking = true;
    try {
      const response = await fetch(API + "/api/finance/workspace/access", {
        headers: {"X-Telegram-Init-Data": tg.initData}, cache: "no-store"
      });
      if (!response.ok) return;
      const data = await response.json();
      activeRole = data.role || "user";
      lastChecked = Date.now();
      if (activeRole !== "trainee" && watching) {
        watching.disconnect();
        watching = null;
      }
      installEntries();
      watchLateProfile();
    } catch (_) {
      // A temporary network error never changes server-side permissions.
    } finally {
      checking = false;
    }
  }
  function start() {
    ensureStyle();
    void refreshRole(true);
    window.addEventListener("pageshow", () => void refreshRole());
    window.addEventListener("focus", () => void refreshRole());
    window.addEventListener("nyan-owner-state", () => void refreshRole());
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) void refreshRole();
    });
    // Advanced features can mount the profile asynchronously.
    setTimeout(() => void refreshRole(true), 1700);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, {once: true});
  } else {
    start();
  }
})();
