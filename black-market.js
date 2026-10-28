(() => {
  "use strict";

  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const ICONS = { secret_key: "🗝", nyanik_eye: "👁", backstage: "🎟", midnight: "🖤", dark_nyanik: "👑" };
  const PENDING_KEY = "nyan-black-market-pending-v1";
  let state = null;
  let serverOffset = 0;
  let loading = false;
  let buying = false;
  let selected = null;

  tg?.ready?.();
  tg?.expand?.();

  function info(message, error = false) {
    $("notice").textContent = message || "";
    $("notice").classList.toggle("error", error);
  }

  function authenticated() {
    return Boolean(tg?.initData);
  }

  function currentServerTime() {
    return Date.now() + serverOffset;
  }

  function isLive() {
    return !!state?.is_open && !!state?.closes_at && currentServerTime() < Date.parse(state.closes_at);
  }

  function formatCountdown(ms) {
    const seconds = Math.max(0, Math.ceil(ms / 1000));
    return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function tick() {
    if (!state) return;
    const live = isLive();
    $("market-badge").textContent = live ? "● ЛАВКА ОТКРЫТА" : state.has_opened ? "● ЛАВКА ЗАКРЫТА" : "● СКОРО ОТКРЫТИЕ";
    $("market-badge").classList.toggle("is-open", live);
    $("countdown").textContent = live ? formatCountdown(Date.parse(state.closes_at) - currentServerTime()) : state.has_opened ? "00:00" : "--:--";
    $("time-description").textContent = live ? "успей до исчезновения" : state.has_opened ? "время вышло" : "ожидаем Няника";
    if (!live) document.querySelectorAll(".buy-button:not(.is-owned)").forEach(button => {
      button.disabled = true;
      if (button.dataset.outOfStock !== "true") button.textContent = "Закрыто";
    });
  }

  async function request(path, method = "GET", payload = null) {
    if (!authenticated()) throw new Error("Открой лавку через кнопку бота Nyan Wallet в Telegram.");
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), method === "GET" ? 14000 : 23000);
    try {
      const response = await fetch(API + path, {
        method,
        headers: { "X-Telegram-Init-Data": tg.initData, ...(payload ? { "Content-Type": "application/json" } : {}) },
        body: payload ? JSON.stringify(payload) : undefined,
        cache: "no-store",
        signal: abort.signal,
      });
      const json = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof json.detail === "string" ? json.detail : json.detail?.message || `Ошибка сервера (${response.status})`);
      if (!json.ok) throw new Error("Не удалось прочитать ответ сервера");
      return json;
    } catch (error) {
      if (abort.signal.aborted) throw new Error("Сервер долго отвечает. Попробуй ещё раз.");
      if (error instanceof TypeError) throw new Error("Нет соединения с сервером. Попробуй ещё раз.");
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = String(text);
    return el;
  }

  function renderItems() {
    const container = $("items");
    container.replaceChildren();
    for (const item of state.items || []) {
      const rare = item.kind === "skin";
      const card = node("article", `item${rare ? " is-rare" : ""}`);
      const icon = node("div", "item-icon", ICONS[item.sku] || "✧");
      icon.setAttribute("aria-hidden", "true");
      const content = node("div", "item-content");
      const title = node("div", "item-title", item.title);
      const description = node("p", "item-description", item.description);
      const tags = node("div", "item-meta");
      tags.append(node("span", "", rare ? "эксклюзивный дизайн" : "предмет интерактива"), node("span", "", `осталось ${item.remaining} из ${item.total}`));
      const line = node("div", "item-buy-line");
      const price = node("strong", "item-price", `${item.price.toLocaleString("ru-RU")} 🐾`);
      const button = node("button", `buy-button${item.purchased ? " is-owned" : ""}`, item.purchased ? "Уже куплено" : item.remaining <= 0 ? "Раскуплено" : "Купить");
      button.type = "button";
      button.dataset.outOfStock = item.remaining <= 0 ? "true" : "false";
      button.disabled = !authenticated() || !isLive() || item.purchased || item.remaining <= 0 || state.blocked || state.balance === null || state.balance < item.price;
      if (!item.purchased && isLive() && item.remaining > 0 && state.balance !== null && state.balance < item.price) {
        button.textContent = "Не хватает 🐾";
      }
      button.addEventListener("click", () => selectItem(item.sku));
      line.append(price, button);
      content.append(title, description, tags, line);
      card.append(icon, content);
      container.append(card);
    }
  }

  function ownerControls() {
    $("owner-panel").hidden = !state.is_owner;
    if (!state.is_owner) return;
    $("owner-open").disabled = state.has_opened || !state.ready;
    $("owner-close").disabled = !isLive();
    if (!state.ready) info("Владелец: сервер ещё не подготовил все товары. Открытие недоступно.", true);
  }

  function render() {
    $("telegram-entry").hidden = authenticated();
    $("balance").textContent = !authenticated() ? "в Telegram" : state.balance == null ? "нет кошелька" : `${Number(state.balance).toLocaleString("ru-RU")} 🐾`;
    if (state.blocked) info("Этот аккаунт не может участвовать в продаже.", true);
    else if (!authenticated()) info("Ассортимент доступен для просмотра. Для покупки открой лавку через Nyan Wallet в Telegram.");
    else if (state.balance === null) info("Сначала открой основной Nyan Wallet, чтобы создать кошелёк.", true);
    else if (isLive()) info("Лавка открыта. Остатки обновляются автоматически.");
    else if (state.has_opened) info("Няник закрыл лавку. Все купленные предметы сохранены за вами.");
    else info("Няник ещё не открыл лавку. Можешь посмотреть товары заранее.");
    renderItems();
    ownerControls();
    tick();
  }

  async function refresh(silent = false) {
    if (loading || buying) return;
    loading = true;
    try {
      const data = authenticated() ? await request("/api/black-market") : await publicRequest();
      serverOffset = Date.parse(data.server_now) - Date.now();
      state = data;
      render();
    } catch (error) {
      if (!silent || !state) info(error.message || "Не удалось связаться с Nyan Wallet", true);
    } finally {
      loading = false;
    }
  }

  async function publicRequest() {
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 14000);
    try {
      const response = await fetch(API + "/api/black-market/catalog", { cache: "no-store", signal: abort.signal });
      if (!response.ok) throw new Error("Рынок пока готовится к открытию.");
      const data = await response.json();
      if (!data.ok) throw new Error("Не удалось загрузить рынок");
      return { ...data, balance: null, is_owner: false, blocked: false, purchases: [] };
    } finally { clearTimeout(timeout); }
  }

  function pending() {
    try { return JSON.parse(sessionStorage.getItem(PENDING_KEY) || "null"); } catch { return null; }
  }

  function remember(value) {
    try { if (value) sessionStorage.setItem(PENDING_KEY, JSON.stringify(value)); else sessionStorage.removeItem(PENDING_KEY); } catch (_) {}
  }

  function selectItem(sku) {
    const item = state?.items?.find(row => row.sku === sku);
    if (!item || !isLive() || item.purchased || item.remaining < 1 || buying) return;
    selected = item;
    $("modal-title").textContent = item.title;
    $("modal-description").textContent = item.description;
    $("modal-price").textContent = `${item.price.toLocaleString("ru-RU")} 🐾`;
    $("modal-error").textContent = "";
    $("modal-buy").disabled = false;
    $("modal").hidden = false;
  }

  function hideModal() {
    if (buying) return;
    $("modal").hidden = true;
    selected = null;
  }

  async function purchase() {
    if (!selected || buying) return;
    if (!isLive()) { $("modal-error").textContent = "Лавка уже закрылась"; return; }
    const existing = pending();
    const requestKey = `nym_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
    const payload = existing?.sku === selected.sku ? existing : { sku: selected.sku, request_key: requestKey };
    remember(payload);
    buying = true;
    $("modal-buy").disabled = true;
    $("modal-buy").textContent = "Покупаем…";
    let confirmed = null;
    try {
      const data = await request("/api/black-market/buy", "POST", payload);
      remember(null);
      tg?.HapticFeedback?.notificationOccurred?.("success");
      confirmed = data.purchase;
      $("modal").hidden = true;
      selected = null;
    } catch (error) {
      // Preserve the key after an ambiguous network error for safe retry.
      const uncertain = /соединени|долго отвечает|fetch/i.test(error.message || "");
      if (!uncertain) remember(null);
      $("modal-error").textContent = uncertain ? `${error.message} Нажми ещё раз, повторное списание исключено.` : error.message;
    } finally {
      buying = false;
      $("modal-buy").disabled = false;
      $("modal-buy").textContent = "Купить за 🐾";
    }
    if (confirmed) {
      await refresh();
      info(`Готово! Товар куплен за ${confirmed.price} 🐾. Новый баланс: ${confirmed.balance} 🐾.`);
    }
  }

  async function retryPurchase() {
    const value = pending();
    if (!value || buying) return false;
    buying = true;
    info("Проверяем незавершённую покупку…");
    try {
      const result = await request("/api/black-market/buy", "POST", value);
      remember(null);
      info(`Покупка подтверждена: списано ${result.purchase.price} 🐾.`);
      return true;
    } catch (error) {
      if (!/соединени|долго отвечает/i.test(error.message || "")) remember(null);
      info(`Проверка покупки: ${error.message}`, true);
      return false;
    } finally {
      buying = false;
    }
  }

  async function ownerAction(path, question) {
    if (!state?.is_owner || !window.confirm(question)) return;
    try { await request(path, "POST"); await refresh(); }
    catch (error) { info(error.message, true); }
  }

  async function ownerOrders() {
    if (!state?.is_owner) return;
    try {
      const data = await request("/api/black-market/owner/orders");
      const box = $("owner-orders-list");
      box.replaceChildren();
      if (!data.orders.length) box.append(node("p", "", "Пока никто ничего не купил"));
      for (const order of data.orders) {
        const row = node("div", "owner-order");
        const who = node("span", "", `${order.username} · ${order.telegram_id}`);
        const right = node("span", "");
        right.append(node("b", "", `${order.title} · ${order.price} 🐾`));
        if (order.kind === "voucher") {
          const mark = node("button", "owner-redeem", order.redeemed ? "Использован" : "Отметить использованным");
          mark.type = "button";
          mark.disabled = order.redeemed;
          mark.addEventListener("click", async () => {
            if (!window.confirm(`Отметить предмет «${order.title}» пользователя ${order.username} как использованный?`)) return;
            try { await request(`/api/black-market/owner/orders/${order.id}/redeem`, "POST"); await ownerOrders(); }
            catch (error) { info(error.message, true); }
          });
          right.append(mark);
        }
        row.append(who, right);
        box.append(row);
      }
      box.hidden = false;
    } catch (error) { info(error.message, true); }
  }

  $("refresh").addEventListener("click", () => void refresh());
  $("owner-open").addEventListener("click", () => void ownerAction("/api/black-market/owner/open", "Открыть Чёрный рынок ровно на 20 минут? Повторно запустить нельзя."));
  $("owner-close").addEventListener("click", () => void ownerAction("/api/black-market/owner/close", "Закрыть рынок досрочно? Возобновить продажу не получится."));
  $("owner-orders").addEventListener("click", () => void ownerOrders());
  $("modal-cancel").addEventListener("click", hideModal);
  $("modal").addEventListener("click", event => { if (event.target?.dataset?.close) hideModal(); });
  $("modal-buy").addEventListener("click", () => void purchase());
  document.addEventListener("keydown", event => { if (event.key === "Escape") hideModal(); });
  $("telegram-entry").hidden = authenticated();
  setInterval(tick, 250);
  setInterval(() => { if (!document.hidden) void refresh(true); }, 5000);
  (async () => { if (authenticated() && pending()) await retryPurchase(); await refresh(); })();
})();
