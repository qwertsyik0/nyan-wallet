(() => {
  "use strict";

  const STORAGE_KEY = "nyan-wallet-theme";
  const VALID = new Set(["light", "dark", "system"]);
  const tg = window.Telegram?.WebApp;

  function storedMode() {
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      return VALID.has(value) ? value : "system";
    } catch (_) {
      return "system";
    }
  }

  function systemTheme() {
    const telegram = String(tg?.colorScheme || "").toLowerCase();
    if (telegram === "dark" || telegram === "light") return telegram;
    return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
  }

  function effectiveTheme(mode = storedMode()) {
    return mode === "system" ? systemTheme() : mode;
  }

  function syncTelegramChrome(theme) {
    try {
      const dark = theme === "dark";
      tg?.setHeaderColor?.(dark ? "#151116" : "#fff9fb");
      tg?.setBackgroundColor?.(dark ? "#151116" : "#fff9fb");
      tg?.setBottomBarColor?.(dark ? "#181318" : "#fff9fb");
    } catch (_) {}
  }

  function updateControls(mode) {
    document.querySelectorAll("[data-nyan-theme]").forEach((button) => {
      const active = button.dataset.nyanTheme === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });

    const label = document.getElementById("nyan-theme-current");
    if (label) {
      const effective = effectiveTheme(mode);
      label.textContent = mode === "system"
        ? `Системная · сейчас ${effective === "dark" ? "тёмная" : "светлая"}`
        : (mode === "dark" ? "Тёмная" : "Светлая");
    }
  }

  function apply(mode = storedMode(), persist = false) {
    if (!VALID.has(mode)) mode = "system";
    if (persist) {
      try { localStorage.setItem(STORAGE_KEY, mode); } catch (_) {}
    }

    const theme = effectiveTheme(mode);
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.themeMode = mode;
    document.documentElement.style.colorScheme = theme;
    syncTelegramChrome(theme);
    updateControls(mode);

    window.dispatchEvent(new CustomEvent("nyan-theme-changed", {
      detail: { mode, theme },
    }));
  }

  function ensureThemePanel() {
    const view = document.getElementById("adv-profile-view");
    if (!view || document.getElementById("nyan-theme-panel")) return;

    const panel = document.createElement("section");
    panel.id = "nyan-theme-panel";
    panel.className = "adv-panel nyan-theme-panel";
    panel.innerHTML = `
      <div class="adv-title">Оформление</div>
      <div class="adv-sub">Выберите тему Nyan Wallet. Настройка сохранится на этом устройстве.</div>
      <div class="nyan-theme-selector" role="group" aria-label="Тема интерфейса">
        <button type="button" data-nyan-theme="light">☀️ Светлая</button>
        <button type="button" data-nyan-theme="dark">🌙 Тёмная</button>
        <button type="button" data-nyan-theme="system">◐ Системная</button>
      </div>
      <div id="nyan-theme-current" class="nyan-theme-current"></div>
    `;

    const header = view.querySelector(".subpage-header");
    if (header?.nextSibling) view.insertBefore(panel, header.nextSibling);
    else view.appendChild(panel);

    panel.querySelectorAll("[data-nyan-theme]").forEach((button) => {
      button.addEventListener("click", () => {
        const mode = button.dataset.nyanTheme || "system";
        apply(mode, true);
        try { tg?.HapticFeedback?.selectionChanged?.(); } catch (_) {}
      });
    });

    updateControls(storedMode());
  }

  apply(storedMode(), false);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureThemePanel, { once: true });
  } else {
    ensureThemePanel();
  }

  const observer = new MutationObserver(() => ensureThemePanel());
  observer.observe(document.documentElement, { childList: true, subtree: true });

  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  media?.addEventListener?.("change", () => {
    if (storedMode() === "system") apply("system", false);
  });

  try {
    tg?.onEvent?.("themeChanged", () => {
      if (storedMode() === "system") apply("system", false);
    });
  } catch (_) {}

  window.NyanTheme = {
    get mode() { return storedMode(); },
    get theme() { return effectiveTheme(); },
    set(mode) { apply(mode, true); },
  };
})();
