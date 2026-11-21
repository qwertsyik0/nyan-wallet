(() => {
  "use strict";
  const API = "https://nyan-wallet-bridge.qwertsyik.workers.dev";
  const TG = window.Telegram?.WebApp;
  const byId = id => document.getElementById(id);
  const keyPrefix = "nyan-vip-purchase-key:";
  window.NyanVipPurchaseKey = {
    get(id) {
      const storeKey = keyPrefix + String(id);
      try {
        const existing = localStorage.getItem(storeKey);
        if (existing) return existing;
      } catch (_) {}
      const token = typeof crypto?.randomUUID === "function"
        ? crypto.randomUUID()
        : "vip_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2).padEnd(16, "0");
      try { localStorage.setItem(storeKey, token); } catch (_) {}
      return token;
    },
    clear(id) {
      try { localStorage.removeItem(keyPrefix + String(id)); } catch (_) {}
    },
  };
  let current = null;
  let buying = false;
  let overlay = null;

  function formatDate(value) {
    if (!value) return "не определена";
    const date = new Date(value);
    return Number.isFinite(date.getTime())
      ? date.toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })
      : "не определена";
  }

  function say(value, isError = false) {
    const node = byId("nyan-vip-message");
    if (!node) return;
    node.textContent = value || "";
    node.dataset.error = isError ? "true" : "false";
  }

  function requestHeaders() {
    return { "X-Telegram-Init-Data": TG?.initData || "" };
  }

  async function api(path, options = {}) {
    if (!TG?.initData) throw new Error("Открой Nyan Wallet через Telegram.");
    const response = await fetch(API + path, {
      cache: "no-store",
      ...options,
      headers: { ...requestHeaders(), ...(options.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось связаться с Nyan Wallet");
    }
    return data;
  }

  function makeEntry() {
    if (byId("nyan-vip-open")) return;
    const anchor = byId("nyid-front-open");
    if (!anchor) return;
    const button = document.createElement("button");
    button.type = "button";
    button.id = "nyan-vip-open";
    button.className = "nyan-vip-entry";
    button.innerHTML = '<span class="nyan-vip-symbol" aria-hidden="true">✦</span><span class="nyan-vip-copy"><strong>Nyan VIP</strong><small id="nyan-vip-entry-sub">привилегии на 30 дней</small></span><span aria-hidden="true" class="nyan-vip-chevron">›</span>';
    button.addEventListener("click", open);
    anchor.insertAdjacentElement("afterend", button);
  }

  function makeDialog() {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.id = "nyan-vip-overlay";
    overlay.className = "nyan-vip-overlay";
    overlay.hidden = true;
    overlay.innerHTML = [
      '<section class="nyan-vip-dialog" role="dialog" aria-modal="true" aria-labelledby="nyan-vip-heading">',
      '  <header class="nyan-vip-head"><div><div class="nyan-vip-kicker">ПРИВИЛЕГИИ NYAN WALLET</div><h2 id="nyan-vip-heading">Nyan VIP ✦</h2></div><button type="button" id="nyan-vip-close" class="nyan-vip-close" aria-label="Закрыть">×</button></header>',
      '  <div id="nyan-vip-state" class="nyan-vip-state">Загружаем статус подписки…</div>',
      '  <div class="nyan-vip-perks">',
      '    <div><strong>✦ Значок VIP</strong><span>В Nyan ID, независимо от ранга</span></div>',
      '    <div><strong>◇ Рамка профиля</strong><span>Пудрово-ягодное оформление Nyan ID</span></div>',
      '    <div><strong>🐾 Еженедельные бонусы</strong><span>По 25 🐾 на 7, 14, 21 и 28 день</span></div>',
      '  </div>',
      '  <p class="nyan-vip-footnote">Подписка действует 30 дней. Продление сохраняет оставшийся срок, максимум 90 дней оплаченного времени. Ранг за достижения не меняется.</p>',
      '  <button type="button" id="nyan-vip-buy" class="nyan-vip-buy" disabled>Загружаем…</button>',
      '  <div id="nyan-vip-message" class="nyan-vip-message" role="status" aria-live="polite"></div>',
      '</section>'
    ].join("");
    document.body.appendChild(overlay);
    byId("nyan-vip-close")?.addEventListener("click", close);
    byId("nyan-vip-buy")?.addEventListener("click", buy);
    overlay.addEventListener("click", event => { if (event.target === overlay) close(); });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && overlay && !overlay.hidden) close();
    });
  }

  function render(data) {
    current = data;
    const active = Boolean(data.active);
    const entry = byId("nyan-vip-entry-sub");
    if (entry) entry.textContent = active
      ? "активен до " + formatDate(data.expires_at)
      : "значок, рамка и бонусы каждую неделю";
    const state = byId("nyan-vip-state");
    if (state) {
      state.replaceChildren();
      const title = document.createElement("strong");
      const sub = document.createElement("span");
      if (active) {
        title.textContent = "VIP активен";
        sub.textContent = "До " + formatDate(data.expires_at) +
          " · за текущий период начислено " +
          Number(data.weekly_paid_in_term || 0) + "/100 🐾" +
          (data.next_weekly_at ? " · следующий бонус " + formatDate(data.next_weekly_at) : "");
      } else {
        title.textContent = "VIP пока не активен";
        sub.textContent = "30 дней статуса и до 100 🐾 в виде еженедельных бонусов.";
      }
      state.append(title, sub);
      state.classList.toggle("active", active);
    }
    const buyButton = byId("nyan-vip-buy");
    if (buyButton) {
      buyButton.disabled = buying || !Number.isInteger(data.reward_id) || !Number.isFinite(Number(data.price));
      buyButton.textContent = data.reward_id == null
        ? "Подписка временно недоступна"
        : (active ? "Продлить VIP" : "Активировать VIP") + " за " + Number(data.price).toLocaleString("ru-RU") + " 🐾";
    }
  }

  async function refresh() {
    try {
      const data = await api("/api/vip/status");
      render(data);
      if (data.newly_credited) {
        say("Начислен VIP бонус: +" + Number(data.newly_credited) + " 🐾");
        const balance = byId("balance");
        if (balance && balance.textContent !== "∞") {
          balance.textContent = Number(data.balance).toLocaleString("ru-RU");
        }
      } else {
        say("");
      }
    } catch (error) {
      if (overlay && !overlay.hidden) say(error.message, true);
    }
  }

  async function buy() {
    if (buying || !current?.reward_id) return;
    const price = Number(current.price);
    const confirmText = (current.active ? "Продлить" : "Активировать") +
      " Nyan VIP на 30 дней за " + price.toLocaleString("ru-RU") + " 🐾?";
    const confirmed = TG?.showConfirm
      ? await new Promise(resolve => TG.showConfirm(confirmText, resolve))
      : window.confirm(confirmText);
    if (!confirmed) return;
    buying = true;
    render(current);
    try {
      const key = window.NyanVipPurchaseKey.get(current.reward_id);
      const data = await api("/api/rewards/" + current.reward_id + "/request", {
        method: "POST",
        headers: { "X-VIP-Purchase-Key": key },
      });
      if (data.request?.status !== "fulfilled") {
        throw new Error("Покупка создана, но VIP ещё не активирован. Проверь статус заявки.");
      }
      const balance = byId("balance");
      if (balance && balance.textContent !== "∞") {
        balance.textContent = Number(data.balance).toLocaleString("ru-RU");
      }
      window.NyanVipPurchaseKey.clear(current.reward_id);
      TG?.HapticFeedback?.notificationOccurred?.("success");
      await refresh();
      say("VIP активирован. Привилегии уже доступны!");
      window.dispatchEvent(new Event("nyan:vip-updated"));
    } catch (error) {
      say(error.message, true);
    } finally {
      buying = false;
      if (current) render(current);
    }
  }

  function open() {
    makeDialog();
    overlay.hidden = false;
    document.documentElement.classList.add("nyan-vip-opened");
    byId("nyan-vip-close")?.focus();
    refresh();
  }

  function close() {
    if (!overlay) return;
    overlay.hidden = true;
    document.documentElement.classList.remove("nyan-vip-opened");
    byId("nyan-vip-open")?.focus();
  }

  function init() {
    makeEntry();
    window.addEventListener("nyan:vip-updated", refresh);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) refresh();
    });
    if (TG?.initData) refresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
