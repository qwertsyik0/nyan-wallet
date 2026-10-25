(() => {
  "use strict";
  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  let busy = false;
  let nextCursor = null;
  let loaded = false;
  const $ = id => document.getElementById(id);

  function text(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value == null ? "" : String(value);
    return node;
  }

  function ensurePanel() {
    const view = $("adv-profile-view");
    if (!view) return null;
    let panel = $("nyan-profile-overview");
    if (panel) return panel;
    panel = document.createElement("section");
    panel.id = "nyan-profile-overview";
    panel.className = "adv-panel nyan-overview";
    const header = text("div", "nyan-overview-head");
    const heading = text("div", "adv-title", "Мой кошелёк");
    const refresh = text("button", "nyan-overview-refresh", "↻ обновить");
    refresh.type = "button";
    refresh.addEventListener("click", () => load(true));
    header.append(heading, refresh);
    const stats = text("div", "nyan-overview-stats");
    stats.id = "nyan-overview-stats";
    const requestsTitle = text("h3", "nyan-overview-subtitle", "Мои заявки");
    const requests = text("div", "nyan-overview-requests", "загружаем…");
    requests.id = "nyan-overview-requests";
    const opsTitle = text("h3", "nyan-overview-subtitle", "История операций");
    const operations = text("div", "nyan-overview-operations");
    operations.id = "nyan-overview-operations";
    const more = text("button", "nyan-overview-more", "показать ещё");
    more.id = "nyan-overview-more";
    more.hidden = true;
    more.type = "button";
    more.addEventListener("click", () => load(false));
    const status = text("div", "nyan-overview-status", "загружаем данные…");
    status.id = "nyan-overview-status";
    status.setAttribute("aria-live", "polite");
    panel.append(header, stats, requestsTitle, requests, opsTitle, operations, more, status);
    const anchor = $("nyan-achievements-panel");
    if (anchor && anchor.parentElement === view) anchor.insertAdjacentElement("afterend", panel);
    else view.append(panel);
    return panel;
  }

  function date(value) {
    const dt = new Date(value);
    return Number.isFinite(dt.getTime())
      ? dt.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" })
      : "";
  }

  function renderStats(data) {
    const list = $("nyan-overview-stats");
    if (!list) return;
    list.replaceChildren();
    for (const [label, value, hint] of [
      ["получено всего", data.earned, "🐾"],
      ["потрачено всего", data.spent, "🐾"],
      ["операций", data.operations_count, ""],
      ["достижений", data.achievements_count, ""],
    ]) {
      const cell = text("div", "nyan-overview-stat");
      cell.append(text("span", "", label), text("strong", "", `${Number(value || 0).toLocaleString("ru-RU")} ${hint}`.trim()));
      list.append(cell);
    }
  }

  function renderRequests(items) {
    const box = $("nyan-overview-requests");
    if (!box) return;
    box.replaceChildren();
    if (!items.length) {
      box.append(text("p", "nyan-overview-empty", "пока нет заявок"));
      return;
    }
    const labels = {
      new: "отправлена", viewed: "просмотрена", in_progress: "в работе",
      pending: "на модерации", approved: "одобрена", rejected: "отказ",
      completed: "выполнена", closed: "закрыта",
    };
    for (const item of items) {
      const row = text("div", "nyan-overview-request");
      const info = text("div", "");
      info.append(text("strong", "", item.title || "Заявка"), text("small", "", `№${item.id} · ${date(item.created_at)}`));
      row.append(info, text("span", "nyan-overview-status-pill", labels[item.status] || item.status));
      box.append(row);
    }
  }

  function renderOperations(items, replace) {
    const box = $("nyan-overview-operations");
    if (!box) return;
    if (replace) box.replaceChildren();
    if (!items.length && replace) {
      box.append(text("p", "nyan-overview-empty", "операций пока нет"));
      return;
    }
    for (const item of items) {
      const row = text("div", "nyan-overview-operation");
      const info = text("div", "");
      info.append(
        text("strong", "", item.description || "операция Nyan Wallet"),
        text("small", "", date(item.created_at))
      );
      const amount = Number(item.amount || 0);
      row.append(info, text("b", amount < 0 ? "minus" : "plus", `${amount > 0 ? "+" : ""}${amount} 🐾`));
      box.append(row);
    }
  }

  async function load(reset) {
    if (busy || !ensurePanel()) return;
    const initData = window.Telegram?.WebApp?.initData;
    if (!initData) {
      $("nyan-overview-status").textContent = "открой кошелёк через Telegram";
      return;
    }
    if (!reset && nextCursor == null) return;
    busy = true;
    $("nyan-overview-more").disabled = true;
    $("nyan-overview-status").textContent = reset ? "обновляем данные…" : "загружаем операции…";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 18000);
    try {
      const params = new URLSearchParams({ limit: "25" });
      if (!reset && nextCursor) params.set("before_id", String(nextCursor));
      const response = await fetch(`${API}/api/profile/overview?${params}`, {
        headers: { "X-Telegram-Init-Data": initData },
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw Error(`сервер вернул HTTP ${response.status}`);
      const data = await response.json();
      if (!data?.ok || !Array.isArray(data.transactions)) throw Error("некорректный ответ сервера");
      if (reset) {
        renderStats(data);
        renderRequests(data.requests || []);
      }
      renderOperations(data.transactions, reset);
      nextCursor = data.next_cursor;
      $("nyan-overview-more").hidden = !nextCursor;
      $("nyan-overview-status").textContent = "";
      loaded = true;
    } catch (error) {
      $("nyan-overview-status").textContent = error?.name === "AbortError"
        ? "сервер долго отвечает. нажми «обновить», чтобы попробовать снова."
        : `не удалось получить данные: ${error.message}`;
    } finally {
      clearTimeout(timer);
      busy = false;
      $("nyan-overview-more").disabled = false;
    }
  }

  // Profile view is built by a deferred module; delegate its launch click.
  document.addEventListener("click", event => {
    if (!event.target.closest("#adv-profile-button")) return;
    if (!loaded) setTimeout(() => { ensurePanel(); load(true); }, 0);
    else ensurePanel();
  });
  window.addEventListener("nyan-wallet-ready", () => {
    if ($("adv-profile-view") && !$("nyan-profile-overview")) ensurePanel();
  });
})();
