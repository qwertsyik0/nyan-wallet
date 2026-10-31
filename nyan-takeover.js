(() => {
  "use strict";
  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const auth = Boolean(tg?.initData);
  const $ = id => document.getElementById(id);
  const LINK = "https://t.me/nyancash_bot?startapp=nyan_takeover";
  let state = null;
  let auctionState = {lots: []};
  let dropState = {items: []};
  let missionState = null;
  let groupState = null;
  let selected = null;
  let bidSelection = null;
  let busy = false;
  tg?.ready?.();
  tg?.expand?.();

  function element(tag, cls, value) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value !== undefined) node.textContent = String(value);
    return node;
  }
  function notice(value, type = "") {
    $("notice").textContent = value;
    $("notice").className = `notice ${type}`;
  }
  async function api(path, method = "GET", data) {
    if (!auth) throw new Error("Открой страницу через Telegram.");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 16000);
    try {
      const response = await fetch(`${API}${path}`, {
        method, cache: "no-store", signal: controller.signal,
        headers: {"X-Telegram-Init-Data": tg.initData, ...(data ? {"Content-Type": "application/json"} : {})},
        body: data ? JSON.stringify(data) : undefined,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || !body.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : `Ошибка сервера (${response.status})`);
      }
      return body;
    } catch (err) {
      if (err.name === "AbortError") throw new Error("Сервер долго не отвечает. Попробуй ещё раз.");
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }
  const format = value => `${Number(value).toLocaleString("ru-RU")} 🐾`;

  function renderGate() {
    const access = state?.access || "none";
    $("gate").hidden = false;
    $("event").hidden = true;
    $("owner-panel").hidden = true;
    $("apply").hidden = true;
    $("telegram-link").hidden = auth;
    $("telegram-link").href = LINK;
    if (!auth) {
      $("gate-copy").textContent = "Войти можно только из мини-приложения Nyan Wallet.";
      notice("Для проверки доступа открой страницу через Telegram.");
    } else {
      $("gate-copy").textContent = "Доступ есть только у действующих участников закрытого флуда.";
      notice("Бот проверяет участие автоматически. Если ты только что вступил, обнови страницу.");
    }
  }

  function itemArtwork(item) {
    const art = element("div", `item-art ${item.kind}`);
    const asset = item.kind === "badge" ?
      (item.asset === "economist" ? "badge-economist.png" : "badge-takeover-limited.png") :
      (item.kind === "skin" ? (item.asset === "resident" ? "skin-resident.png" : "skin-founding.png") : null);
    if (asset) {
      const img = element("img");
      img.src = `./assets/nyan-takeover/${asset}`;
      img.alt = `Предпросмотр: ${item.title}`;
      img.loading = "lazy";
      art.append(img);
    }
    return art;
  }

  function renderMarket() {
    $("market").replaceChildren();
    for (const item of state.items) {
      const card = element("article", "item");
      const head = element("div", "item-top");
      const title = element("h3", "", item.title);
      const stock = element("span", "item-stock", `осталось ${item.remaining}/${item.stock}`);
      head.append(title, stock);
      const description = element("p", "", item.description);
      const row = element("div", "item-bottom");
      const price = element("strong", "item-price", format(item.price));
      const button = element("button", "primary", item.purchased ? "✓ Куплено" : item.remaining < 1 ? "Раскуплено" : "Купить");
      button.type = "button";
      button.disabled = busy || !state.event_open || item.purchased || item.remaining <= 0 || state.balance < item.price;
      button.addEventListener("click", () => showBuy(item));
      row.append(price, button);
      card.append(head, description, itemArtwork(item), row);
      $("market").append(card);
    }
  }

  function renderOrders() {
    $("my-orders").hidden = !(state?.purchases?.length);
    $("orders").replaceChildren();
    for (const purchase of state.purchases || []) {
      const item = state.items.find(p => p.sku === purchase.sku);
      const line = element("div", "order");
      line.append(element("strong", "", item?.title || purchase.sku),
                  element("span", "", purchase.fulfillment === "done" ? "Получено" : "Ожидает выдачи"));
      $("orders").append(line);
    }
  }

  function renderEvent() {
    $("gate").hidden = true;
    $("event").hidden = false;
    $("owner-panel").hidden = !state.owner;
    $("flood-name").textContent = state.name;
    $("balance").textContent = state.balance == null ? "— 🐾" : format(state.balance);
    $("claim-panel").classList.toggle("is-claimed", state.claimed);
    $("claim").textContent = state.claimed ? "✓ Получено" : state.event_open ? "Забрать 500 🐾" : "Недоступно";
    $("claim").disabled = busy || state.claimed || !state.event_open || state.owner;
    renderMarket();
    renderAuction();
    renderDrops();
    renderMission();
    renderOrders();
    notice(state.event_open ? "Экономика флуда открыта!" :
           Date.now() < Date.parse(state.starts_at) ? "Событие откроется в 17:30 по МСК." : "Событие завершено.",
           state.event_open ? "good" : "");
  }

  function render() {
    if (state?.access === "approved" || state?.access === "owner") renderEvent();
    else renderGate();
  }

  async function refresh() {
    if (!auth) { renderGate(); return; }
    try {
      state = await api("/api/nyan-takeover/status");
      render();
      if (state.access === "approved" || state.owner) {
        await refreshAuction();
        await refreshDrops();
        if (!state.owner) await refreshMission();
        if (state.owner) await refreshOwner();
      }
    } catch (error) {
      $("gate").hidden = false;
      $("event").hidden = true;
      $("owner-panel").hidden = true;
      $("apply").hidden = true;
      $("gate-copy").textContent = "Проверка доступа пока недоступна.";
      notice(error.message, "bad");
    }
  }

  async function action(work, done) {
    if (busy) return;
    busy = true;
    try {
      const result = await work();
      tg?.HapticFeedback?.notificationOccurred?.("success");
      await refresh();
      notice(done || "Готово!", "good");
      return result;
    } catch (error) {
      notice(error.message, "bad");
      tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {busy = false;if (state) render();}
  }

  function showBuy(item) {
    selected = item;
    $("modal-title").textContent = item.title;
    $("modal-description").textContent = item.description;
    $("modal-price").textContent = `Спишется ${format(item.price)}`;
    $("modal-error").textContent = "";
    $("buy-modal").hidden = false;
  }
  function closeBuy() {if (!busy) {selected = null;$("buy-modal").hidden = true;}}

  function keyFor(sku) {
    const name = `nyan-takeover-purchase:${tg?.initDataUnsafe?.user?.id}:${sku}`;
    let value = sessionStorage.getItem(name);
    if (!value) {
      value = crypto.randomUUID().replaceAll("-", "");
      sessionStorage.setItem(name, value);
    }
    return {name, value};
  }

  async function buy() {
    if (!selected || busy) return;
    const item = selected;
    const key = keyFor(item.sku);
    busy = true;
    $("confirm").disabled = true;
    try {
      const result = await api("/api/nyan-takeover/buy", "POST", {sku: item.sku, request_key: key.value});
      sessionStorage.removeItem(key.name);
      $("buy-modal").hidden = true;
      selected = null;
      tg?.HapticFeedback?.notificationOccurred?.("success");
      await refresh();
      notice(result.fulfillment === "pending" ? "Покупка оплачена. Администрация выдаст привилегию." : "Покупка получена!", "good");
    } catch (error) {
      $("modal-error").textContent = error.message;
    } finally { busy = false;$("confirm").disabled = false;if (state) render(); }
  }

  function userLabel(row) {return `${row.first_name || "участник"} ${row.username ? `@${row.username}` : ""}`.trim();}

  function renderGroup() {
    if (!groupState) return;
    $("bind-form").hidden = groupState.bound;
    $("publish-form").hidden = !groupState.bound;
    $("group-status").textContent = groupState.bound ?
      `Привязана: ${groupState.title} · ID ${groupState.chat_id}. Бот проверяет участников и может отправлять сюда сообщения.` :
      "Группа ещё не привязана. Скопируй ссылку на любое сообщение из частного чата (t.me/c/…) и вставь ниже.";
    $("group-status").className = `notice ${groupState.bound ? "good" : ""}`;
  }

  async function refreshGroup() {
    if (!state?.owner) return;
    groupState = await api("/api/nyan-takeover/owner/group");
    renderGroup();
  }

  function renderAuction() {
    const container = $("auction-lots");
    container.replaceChildren();
    for (const lot of auctionState.lots) {
      const card = element("article", "auction-card");
      const statusText = {closed:"СКОРО",open:"ТОРГИ ОТКРЫТЫ",settled:"ЗАВЕРШЕНО",cancelled:"ОТМЕНЕНО"}[lot.status] || lot.status;
      card.append(element("span", "auction-status", statusText),element("h3", "", lot.title),element("p", "", lot.description));
      const value = element("div", "auction-value");
      value.append(element("span", "", lot.top_bid ? "Текущая ставка" : "Начальная ставка"),
                   element("strong", "", format(lot.top_bid || lot.starting)));
      card.append(value);
      if (lot.winner && lot.fulfillment === "pending") card.append(element("p", "", "Награда ожидает выдачи администрацией."));
      if (state.owner && lot.top_user_id) card.append(element("p", "", `Лидер / победитель · ID ${lot.top_user_id}`));
      if (!state.owner) {
        const bidButton = element("button", "primary", lot.winner ? "✓ Победа" : lot.is_leader ? "Ты лидируешь" : lot.status !== "open" ? "Недоступно" : "Сделать ставку");
        bidButton.disabled = busy || lot.status !== "open" || lot.is_leader || state.balance < lot.minimum_next;
        bidButton.addEventListener("click", () => openBid(lot));
        card.append(bidButton);
      } else {
        const controls = element("div", "auction-control");
        const operations = lot.status === "closed" ? [["open", "Открыть"]] : lot.status === "open" ? [["settle", "Завершить торги"],["cancel", "Отменить и вернуть"]] : lot.fulfillment === "pending" ? [["delivered", "Награда выдана"]] : [];
        for (const [operation,label] of operations) {
          const button = element("button", operation === "settle" ? "primary" : "secondary", label);
          button.type = "button";
          button.addEventListener("click", () => {
            if (!confirm(`Подтвердить: ${label.toLowerCase()} · ${lot.title}?`)) return;
            action(() => api("/api/nyan-takeover/owner/auction", "POST", {lot_key:lot.key, action:operation}), "Статус лота обновлён.");
          });
          controls.append(button);
        }
        card.append(controls);
      }
      container.append(card);
    }
  }

  async function refreshAuction() {
    auctionState = await api("/api/nyan-takeover/auction");
    if (!$("event").hidden) renderAuction();
  }

  function renderDrops() {
    const container = $("drop-list");
    container.replaceChildren();
    $("drops-panel").hidden = !dropState.items.length;
    for (const item of dropState.items) {
      const card = element("div", "drop-card");
      const left = element("div");
      left.append(element("strong", "", `+${format(item.amount)}`),
                  element("small", "", `Осталось ${item.remaining} · до ${new Date(item.expires_at).toLocaleTimeString("ru-RU", {hour:"2-digit", minute:"2-digit", timeZone:"Europe/Moscow"})} МСК`));
      const button = element("button", "primary", item.claimed ? "✓ Забрано" : state.owner ? "Закрыть" : "Забрать");
      button.disabled = busy || (!state.owner && (item.claimed || item.remaining <= 0 || !state.event_open));
      button.addEventListener("click", () => {
        if (state.owner) {
          if (!confirm("Закрыть раздачу досрочно?")) return;
          action(() => api("/api/nyan-takeover/owner/drops/close", "POST", {drop_id:item.id}), "Раздача закрыта.");
        } else {
          action(() => api("/api/nyan-takeover/drops/claim", "POST", {drop_id:item.id}), "Лапкоины начислены!");
        }
      });
      card.append(left,button);
      container.append(card);
    }
  }

  async function refreshDrops() {
    dropState = await api("/api/nyan-takeover/drops");
    if (!$("event").hidden) renderDrops();
  }

  function renderMission() {
    $("mission-panel").hidden = !missionState || state.owner;
    if (!missionState || state.owner) return;
    $("mission-progress").textContent = `${missionState.progress} / 3 · ${missionState.features.join(", ") || "функции ещё не использованы"}`;
    $("mission-claim").textContent = missionState.claimed ? "✓ Получено" : "Забрать +150 🐾";
    $("mission-claim").disabled = busy || missionState.claimed || missionState.progress < 3 || !state.event_open;
  }

  async function refreshMission() {
    missionState = await api("/api/nyan-takeover/mission");
    if (!$("event").hidden) renderMission();
  }

  function openBid(lot) {
    bidSelection = lot;
    $("bid-title").textContent = lot.title;
    $("bid-amount").min = String(lot.minimum_next);
    $("bid-amount").value = String(lot.minimum_next);
    $("bid-error").textContent = "";
    $("bid-modal").hidden = false;
  }
  function closeBid() {if (!busy) {$("bid-modal").hidden = true;bidSelection = null;}}
  async function submitBid() {
    if (!bidSelection || busy) return;
    const amount = Number($("bid-amount").value);
    if (!Number.isSafeInteger(amount) || amount < bidSelection.minimum_next || amount > 100000000) {
      $("bid-error").textContent = `Минимальная ставка ${format(bidSelection.minimum_next)}.`;
      return;
    }
    if (amount > state.balance) {$("bid-error").textContent = "Недостаточно лапкоинов.";return;}
    const name = `takeover-auction:${tg.initDataUnsafe?.user?.id}:${bidSelection.key}:${amount}`;
    let key = sessionStorage.getItem(name);
    if (!key) {key = crypto.randomUUID().replaceAll("-", "");sessionStorage.setItem(name,key);}
    busy = true;
    $("bid-confirm").disabled = true;
    try {
      await api("/api/nyan-takeover/auction/bid", "POST", {lot_key:bidSelection.key,amount,request_key:key});
      sessionStorage.removeItem(name);
      $("bid-modal").hidden = true;bidSelection = null;
      tg?.HapticFeedback?.notificationOccurred?.("success");
      await refresh();
      notice("Ставка принята. Если её перебьют, лапкоины вернутся автоматически.", "good");
    } catch (error) {
      $("bid-error").textContent = error.message;
    } finally {busy = false;$("bid-confirm").disabled = false;if (state) render();}
  }

  async function refreshOwner() {
    if (!state?.owner) return;
    await refreshGroup();
    const data = await api("/api/nyan-takeover/owner/requests");
    $("fulfillment").replaceChildren();
    if (!data.fulfillment.length) $("fulfillment").append(element("p", "empty", "Все заказы обработаны."));
    for (const row of data.fulfillment) {
      const card = element("div", "person");
      const left = element("div");
      left.append(element("strong", "", row.title), element("small", "", `${userLabel(row)} · ID ${row.telegram_id}`));
      const complete = element("button", "secondary", "Выдано");
      complete.addEventListener("click", () => {
        if (!confirm("Отметить привилегию как выданную?")) return;
        action(() => api("/api/nyan-takeover/owner/fulfilled", "POST", {purchase_id:row.id}), "Заказ отмечен как выданный.");
      });
      card.append(left, complete);$("fulfillment").append(card);
    }
  }

  $("bind-form").addEventListener("submit", event => {
    event.preventDefault();
    const chat_link_or_id = $("chat-link").value.trim();
    if (!chat_link_or_id || !confirm("Привязать именно эту группу к NYAN TAKEOVER? Проверь ссылку.")) return;
    action(() => api("/api/nyan-takeover/owner/group/bind", "POST", {chat_link_or_id}), "Группа проверена и привязана.");
  });
  $("publish-form").addEventListener("submit", event => {
    event.preventDefault();
    const content = $("publish-text").value.trim();
    if (!content || !groupState?.bound) return;
    if (!confirm(`Опубликовать сообщение от бота в «${groupState.title}»?`)) return;
    const storageKey = "takeover-post-pending:" + content;
    let request_key = sessionStorage.getItem(storageKey);
    if (!request_key) {request_key = crypto.randomUUID().replaceAll("-", "");sessionStorage.setItem(storageKey, request_key);}
    action(async () => {
      const result = await api("/api/nyan-takeover/owner/group/publish", "POST", {text:content,request_key});
      sessionStorage.removeItem(storageKey);
      return result;
    }, "Бот опубликовал сообщение в частном флуде.");
  });
  $("claim").addEventListener("click", () => action(() => api("/api/nyan-takeover/claim", "POST"), "+500 🐾 и достижения получены!"));
  $("mission-claim").addEventListener("click", () => action(() => api("/api/nyan-takeover/mission/claim", "POST"), "+150 🐾 и новый значок получены!"));
  $("refresh-owner").addEventListener("click", () => refreshOwner().catch(err => notice(err.message, "bad")));
  $("cancel").addEventListener("click", closeBuy);
  $("modal-shade").addEventListener("click", closeBuy);
  $("confirm").addEventListener("click", buy);
  $("bid-shade").addEventListener("click", closeBid);
  $("bid-cancel").addEventListener("click", closeBid);
  $("bid-confirm").addEventListener("click", submitBid);
  $("drop-form").addEventListener("submit", event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {amount:Number(form.get("amount")),capacity:Number(form.get("capacity")),minutes:Number(form.get("minutes"))};
    if (!Number.isSafeInteger(payload.amount) || !Number.isSafeInteger(payload.capacity) || !Number.isSafeInteger(payload.minutes)) return;
    action(() => api("/api/nyan-takeover/owner/drops", "POST", payload), "Раздача открыта.");
  });
  refresh();
  setInterval(() => {if (document.visibilityState === "visible" && $("buy-modal").hidden && $("bid-modal").hidden && !busy) refresh();}, 45000);
})();
