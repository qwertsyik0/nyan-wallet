(() => {
  "use strict";
  const API = "https://nyan-wallet-api.onrender.com";
  const tg = window.Telegram?.WebApp;
  const TARGET = "./finance-workspace.html";
  let activeRole = "user";
  let watching = null;

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
    if (!["trainee", "owner"].includes(activeRole)) return;
    if (activeRole === "trainee") {
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
    if (activeRole === "owner") {
      const button = document.getElementById("owner-finance-workspace");
      if (button && !button.dataset.fwBound) {
        button.dataset.fwBound = "1";
        button.hidden = false;
        button.addEventListener("click", openWorkspace);
      }
    }
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
  async function start() {
    ensureStyle();
    if (!tg?.initData) return;
    try {
      const response = await fetch(API + "/api/finance/workspace/access", {
        headers: {"X-Telegram-Init-Data":tg.initData}, cache:"no-store"
      });
      if (!response.ok) return;
      const data = await response.json();
      activeRole = data.role || "user";
      if (!["owner", "trainee"].includes(activeRole)) return;
      installEntries();
      watching = new MutationObserver(() => {
        installEntries();
        if ((activeRole === "trainee" && document.getElementById("fw-profile-entry"))
          || (activeRole === "owner" && document.getElementById("owner-finance-workspace")?.dataset.fwBound)) {
          watching.disconnect();
          watching = null;
        }
      });
      watching.observe(document.body, {childList:true, subtree:true});
    } catch (_) { /* No role granted or offline: keep buttons hidden. */ }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else void start();
})();
