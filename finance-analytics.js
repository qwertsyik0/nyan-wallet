(() => {
  "use strict";
  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const auth = tg?.initData || "";
  const $ = id => document.getElementById(id);
  const fmt = n => Number(n || 0).toLocaleString("ru-RU") + " 🐾";
  const num = n => Number(n || 0).toLocaleString("ru-RU");
  let currentDays = 7;
  let requestId = 0;
  tg?.ready?.(); tg?.expand?.();

  const categoryLabels = {
    transfer_out:"исходящие переводы", transfer_in:"входящие переводы",
    owner_grant:"ручные начисления", owner_debit:"ручные списания",
    promo:"промокоды", mass_grant:"массовые начисления",
    interactive_activity_reward:"интерактивы Nyan Studio",
    interactive_idea_reward:"идеи интерактивов", daily_task:"ежедневные задания",
    reward_request:"покупки за лапкоины", giveaway_ticket:"билеты розыгрышей",
    achievement:"достижения", referral_inviter:"реферальные бонусы",
    referral_invitee:"приветствие рефералов", reward_refund:"возвраты",
  };

  function node(tag, cls, value) {
    const result = document.createElement(tag);
    if (cls) result.className = cls;
    if (value !== undefined) result.textContent = String(value);
    return result;
  }

  function render(data) {
    const { wallets, transactions: tx } = data;
    $("finance-circulation").textContent = fmt(wallets.balance_in_circulation);
    $("finance-credited").textContent = fmt(tx.credited_excluding_transfers);
    $("finance-debited").textContent = fmt(tx.debited_excluding_transfers);
    $("finance-moved").textContent = fmt(tx.transfer_volume);
    $("finance-wallets").textContent = num(wallets.total);
    $("finance-new").textContent = num(wallets.new);
    $("finance-active").textContent = num(wallets.active);
    $("finance-count").textContent = num(tx.count);
    $("finance-transfers").textContent = num(tx.transfers_count);

    const graph = $("finance-chart");
    graph.replaceChildren();
    const days = data.daily || [];
    const max = Math.max(1, ...days.flatMap(row => [row.earned, row.spent]));
    // A 30-day chart remains compact on a phone while every day is accessible.
    for (const row of days) {
      const item = node("div", "finance-chart-row");
      item.append(node("span", "", row.day.slice(5)));
      const bars = node("div", "finance-bar-track");
      for (const [value, cls] of [[row.earned, "credit"], [row.spent, "debit"]]) {
        const bar = node("div", `finance-bar ${cls}`);
        bar.style.width = `${Math.max(value ? 1 : 0, 100 * Number(value) / max)}%`;
        bar.title = `${cls === "credit" ? "начислено" : "списано"}: ${fmt(value)}`;
        bars.append(bar);
      }
      item.append(bars, node("span", "", num(row.earned) + " / " + num(row.spent)));
      graph.append(item);
    }

    const categories = $("finance-categories");
    categories.replaceChildren();
    if (!data.categories.length) categories.append(node("p", "studio-hint", "За этот период операций не было."));
    for (const row of data.categories) {
      const item = node("div", "finance-category");
      const description = node("div");
      description.append(node("span", "", categoryLabels[row.type] || row.type),
        node("small", "", num(row.count) + " операций"));
      item.append(description, node("strong", "", `+${num(row.credited)} / −${num(row.debited)}`));
      categories.append(item);
    }
  }

  async function load(days) {
    currentDays = days;
    const thisRequest = ++requestId;
    document.querySelectorAll("[data-days]").forEach(button => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.days) === days));
    });
    $("finance-status").textContent = "Загружаем статистику…";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 18000);
    try {
      const response = await fetch(`${API}/api/owner/finance-analytics?days=${days}`, {
        headers: { "X-Telegram-Init-Data": auth }, cache: "no-store", signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw Error(
        typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`
      );
      if (thisRequest === requestId) {
        render(data);
        $("finance-status").textContent = "";
      }
    } catch (error) {
      if (thisRequest === requestId) $("finance-status").textContent =
        error.name === "AbortError" ? "Сервер долго отвечает. Попробуй ещё раз." : String(error.message);
    } finally { clearTimeout(timer); }
  }

  if (!auth) {
    $("finance-login").hidden = false;
    $("finance-status").textContent = "Для просмотра войди через Telegram.";
  } else {
    $("finance-content").hidden = false;
    document.querySelectorAll("[data-days]").forEach(button => button.addEventListener("click", () => {
      void load(Number(button.dataset.days));
    }));
    void load(currentDays);
  }
})();
