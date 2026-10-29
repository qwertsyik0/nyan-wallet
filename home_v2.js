(() => {
  "use strict";

  // Only one visible navigation block: the compact "Ещё" menu.
  // Existing hidden action buttons remain click targets for their original handlers.
  const MORE_ACTIONS = [
    ["earn", "＋", "Заработать", "earn-button"],
    ["spend", "🐾", "Потратить", "spend-button"],
    ["transfer", "↗", "Перевести", "transfer-button"],
    ["receive", "▣", "QR / Получить", "wallet-qr-button"],
    ["profile", "◇", "Профиль", "adv-profile-button"],
    ["notifications", "◌", "Уведомления", "adv-notifications-button"],
    ["giveaways", "✦", "Розыгрыши", "nyg-my-button"],
    ["lottery", "🎫", "Лотерея", "nyan-lottery-link"],
    ["fortune", "🎡", "Колесо фортуны", "nyan-fortune-link"],
    ["halloween", "◈", "Ночь Няника · 31 октября", "nyan-halloween-link"],
    ["purchases", "▤", "Покупки", "nyg-my-purchases-button"],
    ["appeals", "✉", "Обращения", "appeals-button"],
    ["studio", "✳", "Интерактивы", "nyan-studio-link"],
  ];

  let scheduled = false;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function proxyClick(id) {
    const target = document.getElementById(id);
    if (target) {
      target.click();
      return;
    }

    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      const retry = document.getElementById(id);
      if (retry) {
        clearInterval(timer);
        retry.click();
      } else if (attempts >= 12) {
        clearInterval(timer);
      }
    }, 100);
  }

  function ensureHome() {
    const wallet = document.getElementById("wallet-view");
    const card = document.getElementById("wallet-card");
    if (!wallet || !card) return null;

    // Some earlier style bundles forced the old grid back to display:grid!important.
    // Keep those original buttons accessible to proxyClick without rendering them.
    const legacyActions = wallet.querySelector(":scope > .actions");
    if (legacyActions) {
      if (!legacyActions.hidden) legacyActions.hidden = true;
      if (legacyActions.style.getPropertyValue("display") !== "none" ||
          legacyActions.style.getPropertyPriority("display") !== "important") {
        legacyActions.style.setProperty("display", "none", "important");
      }
    }

    let home = document.getElementById("nyan-home-v2");
    if (!home) {
      home = document.createElement("section");
      home.id = "nyan-home-v2";
      home.className = "nyan-home-v2";
      home.innerHTML = `
        <section class="nyan-home-panel">
          <div class="nyan-home-panel-head">
            <div class="nyan-home-panel-title">Сегодня</div>
            <div class="nyan-home-panel-note">ваша активность</div>
          </div>
          <div class="nyan-home-today">
            <button type="button" class="nyan-home-today-card" data-home-target="earn-button">
              <div class="nyan-home-today-kicker">серия активности</div>
              <div id="nyan-home-streak-value" class="nyan-home-today-value">…</div>
              <div id="nyan-home-streak-meta" class="nyan-home-today-meta">загружаем</div>
            </button>
            <button type="button" class="nyan-home-today-card" data-home-target="earn-button">
              <div class="nyan-home-today-kicker">ежедневные задания</div>
              <div id="nyan-home-tasks-value" class="nyan-home-today-value">…</div>
              <div id="nyan-home-tasks-meta" class="nyan-home-today-meta">загружаем</div>
              <div id="nyan-home-tasks-track" class="nyan-home-tasks-track" aria-hidden="true" hidden>
                <span id="nyan-home-tasks-progress"></span>
              </div>
            </button>
          </div>
        </section>

        <section class="nyan-home-panel">
          <div class="nyan-home-panel-head">
            <div class="nyan-home-panel-title">Ещё</div>
            <div class="nyan-home-panel-note">разделы Nyan Wallet</div>
          </div>
          <div class="nyan-home-more">
            ${MORE_ACTIONS.map(([key, icon, label, target]) => `
              <button type="button" class="nyan-home-more-button" data-home-target="${escapeHtml(target)}" data-home-secondary="${escapeHtml(key)}"><span class="nyan-home-more-icon" aria-hidden="true">${escapeHtml(icon)}</span><span class="nyan-home-more-label">${escapeHtml(label)}</span></button>
            `).join("")}
            <button id="nyan-home-owner" class="nyan-home-more-button" type="button" data-home-target="owner-button" hidden>
              <span class="nyan-home-more-icon" aria-hidden="true">⚙</span><span class="nyan-home-more-label">Управление</span>
            </button>
          </div>
        </section>
      `;

      home.addEventListener("click", (event) => {
        const button = event.target.closest("[data-home-target]");
        if (!button) return;
        const target = button.dataset.homeTarget;
        if (target === "nyan-studio-link") {
          window.location.assign("./interactive-builder.html");
          return;
        }
        if (target === "nyan-lottery-link") {
          window.location.assign("./lottery.html");
          return;
        }
        if (target === "nyan-fortune-link") {
          window.location.assign("./fortune.html");
          return;
        }
        if (target === "nyan-halloween-link") {
          window.location.assign("./halloween.html");
          return;
        }
        if (target) proxyClick(target);
      });
    }

    if (home.parentElement !== wallet) {
      card.insertAdjacentElement("afterend", home);
    }

    return home;
  }

  function normalizedText(node) {
    return String(node?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function syncActivity() {
    const streakValue = document.getElementById("nyan-home-streak-value");
    const streakMeta = document.getElementById("nyan-home-streak-meta");
    const taskValue = document.getElementById("nyan-home-tasks-value");
    const taskMeta = document.getElementById("nyan-home-tasks-meta");
    const taskTrack = document.getElementById("nyan-home-tasks-track");
    const taskProgress = document.getElementById("nyan-home-tasks-progress");

    const streakCard = document.getElementById("activity-streak-card");
    const streakNumbers = streakCard?.querySelectorAll(".activity-streak-number");
    const streak = streakNumbers?.[0]?.textContent?.trim();
    const streakStatus = normalizedText(streakCard?.querySelector(".activity-streak-status"));

    if (streakValue) streakValue.textContent = streak ? `${streak} дн.` : "…";
    if (streakMeta) {
      streakMeta.textContent = streakStatus
        ? streakStatus.replace(/Всего входов:.*/i, "").trim().slice(0, 72)
        : "заходите каждый день";
    }

    const summary = document.getElementById("daily-tasks-summary")?.textContent?.trim();
    const taskList = document.getElementById("daily-task-list");
    const taskRows = Array.from(taskList?.querySelectorAll(".daily-task-row") || []);
    const emptyLabel = normalizedText(taskList?.querySelector(".daily-empty"));
    const loaded = taskRows.length > 0 || /заданий пока нет/i.test(emptyLabel);
    const counts = summary?.match(/^(\d+)\s+из\s+(\d+)$/i);
    const completed = counts ? Number(counts[1]) : taskRows.filter(row => row.querySelector(".daily-task-done")).length;
    const total = counts ? Number(counts[2]) : taskRows.length;

    if (taskValue) {
      taskValue.textContent = loaded ? (summary || (total ? `${completed} из ${total}` : "0 из 0")) : "…";
    }

    if (taskMeta) {
      if (!loaded) taskMeta.textContent = /загружаем/i.test(emptyLabel) || !taskList ? "загружаем задания" : "данные временно недоступны";
      else if (!total) taskMeta.textContent = "заданий пока нет";
      else if (completed >= total) taskMeta.textContent = "всё выполнено";
      else taskMeta.textContent = `осталось ${Math.max(0, total - completed)}`;
    }

    // Read the real task summary; never invent progress while tasks are unavailable.
    const trackHidden = !loaded || total <= 0;
    if (taskTrack && taskTrack.hidden !== trackHidden) taskTrack.hidden = trackHidden;
    if (taskProgress && !trackHidden) {
      const percent = Math.round((Math.min(Math.max(completed, 0), total) / total) * 100);
      taskProgress.style.width = `${percent}%`;
    }
  }

  function syncSecondary() {
    for (const [, , , target] of MORE_ACTIONS) {
      const proxy = document.getElementById(target);
      const homeButton = document.querySelector(`.nyan-home-more-button[data-home-target="${target}"]`);
      if (!homeButton) continue;
      // Never offer a dead action before its original handler exists.
      const hide = !proxy || proxy.hidden || proxy.disabled;
      const unavailable = ["nyan-studio-link", "nyan-lottery-link", "nyan-fortune-link", "nyan-halloween-link"].includes(target) ? false : hide;
      const halloweenVisible = target !== "nyan-halloween-link" || (Date.now() >= Date.parse("2026-10-28T21:00:00Z") && Date.now() < Date.parse("2026-11-01T21:00:00Z"));
      if (homeButton.hidden !== Boolean(unavailable || !halloweenVisible)) homeButton.hidden = Boolean(unavailable || !halloweenVisible);
    }

    const unreadSource = document.getElementById("adv-unread-badge");
    const notifications = document.querySelector('[data-home-secondary="notifications"]');
    if (notifications) {
      notifications.querySelector(".nyan-home-badge")?.remove();
      const unread = normalizedText(unreadSource);
      if (unread && unread !== "0") {
        const badge = document.createElement("span");
        badge.className = "nyan-home-badge";
        badge.textContent = unread;
        notifications.appendChild(badge);
      }
    }

    const ownerProxy = document.getElementById("owner-button");
    const owner = document.getElementById("nyan-home-owner");
    if (owner) {
      const hide = !ownerProxy || ownerProxy.hidden || ownerProxy.disabled;
      if (owner.hidden !== Boolean(hide)) owner.hidden = Boolean(hide);
    }
  }

  function syncHistory() {
    const history = document.querySelector("#wallet-view > .history");
    if (!history) return;

    const list = history.querySelector(".transactions-list");
    const count = list?.querySelectorAll(".transaction-row").length || 0;
    let toggle = history.querySelector(".nyan-history-toggle");

    if (count <= 4) {
      toggle?.remove();
      history.classList.remove("nyan-history-expanded");
      return;
    }

    if (!toggle) {
      toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "nyan-history-toggle";
      toggle.addEventListener("click", () => {
        const expanded = history.classList.toggle("nyan-history-expanded");
        toggle.textContent = expanded ? "Свернуть" : `Показать все (${count})`;
      });
      history.appendChild(toggle);
    }

    if (!history.classList.contains("nyan-history-expanded")) {
      toggle.textContent = `Показать все (${count})`;
    }
  }

  function apply() {
    scheduled = false;
    ensureHome();
    syncActivity();
    syncSecondary();
    syncHistory();
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(apply);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", schedule, { once: true });
  } else {
    schedule();
  }

  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["hidden", "disabled", "class"],
  });

  window.addEventListener("focus", schedule);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) schedule();
  });
})();
