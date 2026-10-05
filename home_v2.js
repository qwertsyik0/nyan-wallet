(() => {
  "use strict";

  const PRIMARY = [
    ["transfer", "↗", "Перевести", "transfer-button"],
    ["receive", "▣", "Получить", "wallet-qr-button"],
    ["earn", "＋", "Заработать", "earn-button"],
    ["spend", "🐾", "Потратить", "spend-button"],
  ];

  const SECONDARY = [
    ["profile", "Профиль", "adv-profile-button"],
    ["giveaways", "Розыгрыши", "nyg-my-button"],
    ["purchases", "Покупки", "nyg-my-purchases-button"],
    ["notifications", "Уведомления", "adv-notifications-button"],
    ["appeals", "Обращения", "appeals-button"],
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

    let home = document.getElementById("nyan-home-v2");
    if (!home) {
      home = document.createElement("section");
      home.id = "nyan-home-v2";
      home.className = "nyan-home-v2";
      home.innerHTML = `
        <div class="nyan-home-primary">
          ${PRIMARY.map(([key, icon, label, target]) => `
            <button type="button" class="nyan-home-action" data-home-target="${escapeHtml(target)}" data-home-key="${escapeHtml(key)}">
              <span class="nyan-home-action-icon">${icon}</span>
              <span class="nyan-home-action-label">${escapeHtml(label)}</span>
            </button>
          `).join("")}
        </div>

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
            </button>
          </div>
        </section>

        <section class="nyan-home-panel">
          <div class="nyan-home-panel-head">
            <div class="nyan-home-panel-title">Ещё</div>
            <div class="nyan-home-panel-note">разделы Nyan Wallet</div>
          </div>
          <div class="nyan-home-more">
            ${SECONDARY.map(([key, label, target]) => `
              <button type="button" class="nyan-home-more-button" data-home-target="${escapeHtml(target)}" data-home-secondary="${escapeHtml(key)}">${escapeHtml(label)}</button>
            `).join("")}
          </div>
        </section>

        <button id="nyan-home-owner" class="nyan-home-owner" type="button" data-home-target="owner-button" hidden>
          Управление Nyan Wallet
        </button>
      `;

      home.addEventListener("click", (event) => {
        const button = event.target.closest("[data-home-target]");
        if (!button) return;
        const target = button.dataset.homeTarget;
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

    const streakCard = document.getElementById("activity-streak-card");
    const streakNumbers = streakCard?.querySelectorAll(".activity-streak-number");
    const streak = streakNumbers?.[0]?.textContent?.trim();
    const streakStatus = normalizedText(streakCard?.querySelector(".activity-streak-status"));

    if (streakValue) streakValue.textContent = streak ? `${streak} дн.` : "0 дн.";
    if (streakMeta) {
      streakMeta.textContent = streakStatus
        ? streakStatus.replace(/Всего входов:.*/i, "").trim().slice(0, 72)
        : "заходите каждый день";
    }

    const summary = document.getElementById("daily-tasks-summary")?.textContent?.trim();
    const taskRows = Array.from(document.querySelectorAll("#daily-task-list .daily-task-row"));
    const completed = taskRows.filter(row => row.querySelector(".daily-task-done")).length;
    const total = taskRows.length;

    if (taskValue) {
      taskValue.textContent = summary || (total ? `${completed} из ${total}` : "0 из 0");
    }

    if (taskMeta) {
      if (!total) taskMeta.textContent = "заданий пока нет";
      else if (completed >= total) taskMeta.textContent = "всё выполнено";
      else taskMeta.textContent = `осталось ${Math.max(0, total - completed)}`;
    }
  }

  function syncSecondary() {
    for (const [, , target] of SECONDARY) {
      const proxy = document.getElementById(target);
      const homeButton = document.querySelector(`[data-home-target="${target}"]`);
      if (!homeButton) continue;
      homeButton.hidden = proxy ? Boolean(proxy.hidden) : false;
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
    if (owner) owner.hidden = !ownerProxy || ownerProxy.hidden || ownerProxy.disabled;
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
