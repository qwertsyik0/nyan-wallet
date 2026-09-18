(() => {
  const API = "https://nyan-wallet-api.onrender.com";
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const app = document.querySelector(".app");
  if (!app) return;

  const state = { ownerItems: [], ownerFilter: "all", currentId: null, purchaseCount: 1 };
  const labels = {
    draft: "Черновик", scheduled: "Запланирован", active: "Активен",
    paused: "На паузе", awaiting_results: "Ожидает итогов",
    completed: "Завершён", cancelled: "Отменён"
  };

  function esc(v) {
    return String(v == null ? "" : v)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  function headers(withJson) {
    const h = { "X-Telegram-Init-Data": tg && tg.initData ? tg.initData : "" };
    if (withJson) h["Content-Type"] = "application/json";
    return h;
  }

  async function api(path, options) {
    const init = Object.assign({}, options || {});
    init.headers = Object.assign({}, headers(Boolean(init.body)), init.headers || {});
    const response = await fetch(API + path, init);
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      const d = data && data.detail;
      if (d && typeof d === "object") {
        const errors = Array.isArray(d.errors) ? d.errors.join("\n") : "";
        throw new Error([d.message || "Ошибка", errors].filter(Boolean).join("\n"));
      }
      throw new Error(d || "Не удалось выполнить запрос");
    }
    return data;
  }

  function badge(status) {
    return '<span class="nyg-status ' + esc(status) + '">' + esc(labels[status] || status) + '</span>';
  }

  function hideViews() {
    app.querySelectorAll(":scope > main").forEach(function (v) { v.classList.add("hidden"); });
  }

  function show(id) {
    hideViews();
    const v = document.getElementById(id);
    if (v) v.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (tg && tg.BackButton) tg.BackButton.show();
  }

  function showWallet() {
    window.__nyanGiveawayDeepLinkActive = false;
    hideViews();
    const wallet = document.getElementById("wallet-view");
    if (wallet) wallet.classList.remove("hidden");
    if (tg && tg.BackButton) tg.BackButton.hide();
  }

  function visibleCustom() {
    const ids = ["nyg-list-view","nyg-detail-view","nyg-my-purchases-view","nyg-owner-list-view","nyg-owner-detail-view","nyg-purchases-view"];
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el && !el.classList.contains("hidden")) return el;
    }
    return null;
  }

  function ask(message) {
    return new Promise(function (resolve) {
      if (tg && tg.showConfirm) tg.showConfirm(message, function (v) { resolve(Boolean(v)); });
      else resolve(window.confirm(message));
    });
  }

  function promptText(message, def) {
    const v = window.prompt(message, def || "");
    return v == null ? null : v.trim();
  }

  function head(title, sub, back) {
    return '<div class="subpage-header">' +
      '<button class="back-button" type="button" data-nyg-back="' + esc(back) + '" aria-label="Назад">‹</button>' +
      '<div><div class="page-title">' + esc(title) + '</div><div class="page-subtitle">' + esc(sub || "") + '</div></div></div>';
  }

  function ensureViews() {
    if (!document.getElementById("nyg-list-view")) {
      const v = document.createElement("main");
      v.id = "nyg-list-view"; v.className = "view hidden nyg-view";
      v.innerHTML = head("Мои розыгрыши", "ваши участия и выигрыши", "wallet-view") +
        '<div id="nyg-my-list" class="nyg-stack"><div class="nyg-empty">Загружаем…</div></div>';
      app.appendChild(v);
    }
    if (!document.getElementById("nyg-detail-view")) {
      const v = document.createElement("main");
      v.id = "nyg-detail-view"; v.className = "view hidden nyg-view";
      v.innerHTML = head("Розыгрыш", "Nyan Cash", "nyg-list-view") +
        '<div id="nyg-detail-content" class="nyg-stack"><div class="nyg-empty">Загружаем…</div></div>';
      app.appendChild(v);
    }
    if (!document.getElementById("nyg-my-purchases-view")) {
      const v = document.createElement("main");
      v.id = "nyg-my-purchases-view"; v.className = "view hidden nyg-view";
      v.innerHTML = head("Мои покупки", "покупки, учтённые в Нян Шопе", "wallet-view") +
        '<section class="nyg-card"><div class="nyg-title">История покупок</div>' +
        '<div id="nyg-my-purchases-summary" class="nyg-message">Загружаем…</div>' +
        '<div id="nyg-my-purchases-list"></div></section>';
      app.appendChild(v);
    }
    if (!document.getElementById("nyg-owner-list-view")) {
      const v = document.createElement("main");
      v.id = "nyg-owner-list-view"; v.className = "view hidden nyg-view";
      v.innerHTML = head("Розыгрыши", "управление владельца", "owner-view") +
        '<div class="nyg-toolbar" id="nyg-owner-filters">' +
        '<button class="nyg-filter active" data-status="all">Все</button>' +
        '<button class="nyg-filter" data-status="draft">Черновики</button>' +
        '<button class="nyg-filter" data-status="scheduled">Запланированные</button>' +
        '<button class="nyg-filter" data-status="active">Активные</button>' +
        '<button class="nyg-filter" data-status="awaiting_results">Ожидают итогов</button>' +
        '<button class="nyg-filter" data-status="completed">Завершённые</button>' +
        '<button class="nyg-filter" data-status="cancelled">Отменённые</button></div>' +
        '<div id="nyg-owner-list" class="nyg-stack"><div class="nyg-empty">Загружаем…</div></div>';
      app.appendChild(v);
    }
    if (!document.getElementById("nyg-owner-detail-view")) {
      const v = document.createElement("main");
      v.id = "nyg-owner-detail-view"; v.className = "view hidden nyg-view";
      v.innerHTML = head("Управление розыгрышем", "статистика и участники", "nyg-owner-list-view") +
        '<div id="nyg-owner-detail" class="nyg-stack"><div class="nyg-empty">Загружаем…</div></div>';
      app.appendChild(v);
    }
    if (!document.getElementById("nyg-purchases-view")) {
      const v = document.createElement("main");
      v.id = "nyg-purchases-view"; v.className = "view hidden nyg-view";
      v.innerHTML = head("Покупки Нян Шопа", "ручной реестр для условий", "owner-view") +
        '<section class="nyg-card"><div class="nyg-title">Импорт списком</div>' +
        '<div class="nyg-import-help">Формат: Telegram ID | что купил | сумма | дата<br>Пример: 6289461565 | США | 100 | 12.09.2026</div>' +
        '<div class="nyg-form"><textarea id="nyg-purchase-import" placeholder="6289461565 | США | 100 | 12.09.2026"></textarea>' +
        '<button id="nyg-purchase-import-btn" class="nyg-primary" type="button">Импортировать</button></div>' +
        '<div id="nyg-purchase-import-status" class="nyg-message"></div></section>' +
        '<section class="nyg-card"><div class="nyg-title">Добавить вручную</div><div class="nyg-form">' +
        '<input id="nyg-purchase-target" placeholder="Telegram ID или @username">' +
        '<input id="nyg-purchase-item" placeholder="Что купил"><input id="nyg-purchase-amount" inputmode="decimal" placeholder="Сумма, ₽">' +
        '<input id="nyg-purchase-date" placeholder="Дата, например 12.09.2026">' +
        '<button id="nyg-purchase-add-btn" class="nyg-secondary" type="button">Добавить покупку</button></div>' +
        '<div id="nyg-purchase-add-status" class="nyg-message"></div></section>' +
        '<section class="nyg-card"><div class="nyg-title">История покупок</div><div class="nyg-search">' +
        '<input id="nyg-purchase-search" placeholder="Telegram ID или @username"><button id="nyg-purchase-search-btn" type="button">Найти</button></div>' +
        '<div id="nyg-purchase-summary" class="nyg-message"></div><div id="nyg-purchase-list"></div></section>';
      app.appendChild(v);
    }
  }

  function ensureButtons() {
    const actions = document.querySelector("#wallet-view .actions");
    if (actions && !document.getElementById("nyg-my-button")) {
      const b = document.createElement("button");
      b.id = "nyg-my-button"; b.className = "nyg-action"; b.type = "button"; b.textContent = "Розыгрыши";
      actions.appendChild(b); b.addEventListener("click", openMine);
    }
    if (actions && !document.getElementById("nyg-my-purchases-button")) {
      const b = document.createElement("button");
      b.id = "nyg-my-purchases-button"; b.className = "nyg-action"; b.type = "button"; b.textContent = "Мои покупки";
      actions.appendChild(b); b.addEventListener("click", openMyPurchases);
    }
    const owner = document.getElementById("owner-view");
    if (owner && !document.getElementById("nyg-owner-nav")) {
      const nav = document.createElement("section");
      nav.id = "nyg-owner-nav"; nav.className = "nyg-owner-nav";
      nav.innerHTML = '<button id="nyg-owner-giveaways-btn" type="button">Розыгрыши</button>' +
        '<button id="nyg-owner-purchases-btn" type="button">Покупки Нян Шопа</button>';
      const h = owner.querySelector(".subpage-header");
      if (h) h.insertAdjacentElement("afterend", nav);
      const gb = nav.querySelector("#nyg-owner-giveaways-btn");
      const pb = nav.querySelector("#nyg-owner-purchases-btn");
      if (gb) gb.addEventListener("click", openOwnerList);
      if (pb) pb.addEventListener("click", openPurchases);
    }
  }

  function card(g, tickets, wins, owner) {
    let meta = '<span class="nyg-pill">' + (g.kind === "free" ? "Бесплатный" : "Платный") + '</span>';
    if (tickets != null) meta += '<span class="nyg-pill">Билетов: ' + esc(tickets) + '</span>';
    if (wins && wins.length) meta += '<span class="nyg-pill">Выигрыш: ' + esc(wins.map(function (x) { return x.position + " место"; }).join(", ")) + '</span>';
    return '<article class="nyg-card" role="button" tabindex="0" data-nyg-id="' + esc(g.public_id) + '" data-owner="' + (owner ? "1" : "0") + '">' +
      '<div class="nyg-top"><div><div class="nyg-title">' + esc(g.title) + '</div><div class="nyg-id">' + esc(g.public_id) + '</div></div>' +
      badge(g.status) + '</div><div class="nyg-meta">' + meta + '</div></article>';
  }

  async function openMine() {
    show("nyg-list-view");
    const box = document.getElementById("nyg-my-list");
    box.innerHTML = '<div class="nyg-empty">Загружаем…</div>';
    try {
      const d = await api("/api/my-giveaways");
      box.innerHTML = d.items && d.items.length
        ? d.items.map(function (item) { return card(item.giveaway, item.tickets, item.wins || [], false); }).join("")
        : '<div class="nyg-empty">Вы пока не участвуете в розыгрышах</div>';
    } catch (e) { box.innerHTML = '<div class="nyg-empty">' + esc(e.message) + '</div>'; }
  }

  function availableTickets(d) { return Math.max(0, Number(d.me.limit || 0) - Number(d.me.tickets || 0)); }

  function renderDetail(d) {
    const g = d.giveaway, me = d.me, avail = availableTickets(d), price = Number(me.ticket_price || 0);
    let prizes = (g.prizes || []).map(function (p) {
      return '<div class="nyg-prize"><span class="nyg-place">' + esc(p.position) + '</span><span>' + esc(p.text) + '</span></div>';
    }).join("");
    if (!prizes) prizes = '<div class="nyg-message">Призы не указаны</div>';
    let wins = (me.wins || []).map(function (w) {
      return '<div class="nyg-result"><b>' + esc(w.position) + ' место</b> · ' + esc(w.prize_text) +
        '<div class="nyg-result-meta">Билет #' + String(w.ticket_number).padStart(6, "0") + '</div></div>';
    }).join("");
    let join = g.status === "active" && !me.is_participating ? '<button id="nyg-join-btn" class="nyg-secondary" type="button">Участвовать</button>' : "";
    let buy = "";
    if (g.status === "active" && avail > 0 && (g.kind === "paid" || g.allow_extra_tickets)) {
      const values = [1,3,5].filter(function (n) { return n <= avail; });
      let chips = values.map(function (n) {
        return '<button type="button" class="nyg-ticket-chip ' + (n === 1 ? "active" : "") + '" data-count="' + n + '">+' + n + '</button>';
      }).join("");
      if (avail > 1) chips += '<button type="button" class="nyg-ticket-chip" data-count="' + avail + '">максимум</button>';
      buy = '<div class="nyg-section-title">Купить билеты</div><div class="nyg-ticket-controls" id="nyg-ticket-controls">' + chips + '</div>' +
        '<button id="nyg-buy-btn" class="nyg-primary" type="button" style="margin-top:10px">Купить</button>';
    }
    const paused = g.status === "paused" ? '<div class="nyg-message">Розыгрыш временно приостановлен</div>' : "";
    return '<section class="nyg-card"><div class="nyg-top"><div><div class="nyg-title">' + esc(g.title) + '</div><div class="nyg-id">' + esc(g.public_id) + '</div></div>' +
      badge(g.status) + '</div><div class="nyg-meta"><span class="nyg-pill">' + (g.kind === "free" ? "Бесплатный розыгрыш" : "Платный розыгрыш") +
      '</span><span class="nyg-pill">Ваш ранг: ' + esc(me.rank) + '</span></div><div class="nyg-section-title">Призы</div><div class="nyg-prizes">' + prizes + '</div></section>' +
      '<section class="nyg-card"><div class="nyg-title">Ваше участие</div><div class="nyg-info"><div class="nyg-info-grid">' +
      '<div class="nyg-stat"><b>' + esc(me.tickets) + '</b><span>билетов</span></div><div class="nyg-stat"><b>' + esc(me.limit) + '</b><span>ваш лимит</span></div>' +
      '<div class="nyg-stat"><b>' + (me.unlimited_balance ? "∞" : esc(me.balance == null ? 0 : me.balance)) + ' 🐾</b><span>баланс</span></div>' +
      '<div class="nyg-stat"><b>' + esc(price) + ' 🐾</b><span>цена билета</span></div></div></div>' + paused +
      '<div class="nyg-actions">' + join + '</div>' + buy + '<div id="nyg-detail-status" class="nyg-message"></div></section>' +
      (wins ? '<section class="nyg-card"><div class="nyg-title">Ваши выигрыши</div><div class="nyg-results">' + wins + '</div></section>' : "");
  }

  async function openDetail(id, returnView) {
    state.currentId = id; state.purchaseCount = 1;
    const back = document.querySelector("#nyg-detail-view [data-nyg-back]");
    if (back) back.dataset.nygBack = returnView || "nyg-list-view";
    show("nyg-detail-view");
    const box = document.getElementById("nyg-detail-content");
    box.innerHTML = '<div class="nyg-empty">Загружаем розыгрыш…</div>';
    try {
      const d = await api("/api/giveaways/" + encodeURIComponent(id));
      box.innerHTML = renderDetail(d);
      bindDetail(d);
    } catch (e) { box.innerHTML = '<div class="nyg-empty">' + esc(e.message) + '</div>'; }
  }

  function bindDetail(d) {
    const status = document.getElementById("nyg-detail-status");
    const join = document.getElementById("nyg-join-btn");
    if (join) join.addEventListener("click", async function () {
      join.disabled = true;
      try {
        const r = await api("/api/giveaways/" + encodeURIComponent(d.giveaway.public_id) + "/join", { method: "POST" });
        if (r.purchase_required) {
          status.textContent = r.message; status.className = "nyg-message";
        } else {
          if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
          await openDetail(d.giveaway.public_id, document.querySelector("#nyg-detail-view [data-nyg-back]").dataset.nygBack);
        }
      } catch (e) { status.textContent = e.message; status.className = "nyg-message error"; }
      finally { join.disabled = false; }
    });

    const controls = document.getElementById("nyg-ticket-controls");
    if (controls) controls.addEventListener("click", function (event) {
      const b = event.target.closest("[data-count]"); if (!b) return;
      state.purchaseCount = Number(b.dataset.count || 1);
      controls.querySelectorAll(".nyg-ticket-chip").forEach(function (x) { x.classList.toggle("active", x === b); });
    });

    const buy = document.getElementById("nyg-buy-btn");
    if (buy) buy.addEventListener("click", async function () {
      const count = Math.max(1, Math.min(availableTickets(d), state.purchaseCount || 1));
      const total = Number(d.me.ticket_price || 0) * count;
      if (!(await ask("К списанию: " + total + " 🐾 · получите " + count + " бил."))) return;
      buy.disabled = true; status.textContent = "Покупаем…";
      const requestKey = window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : "nyg-" + Date.now() + "-" + Math.random().toString(16).slice(2);
      try {
        await api("/api/giveaways/" + encodeURIComponent(d.giveaway.public_id) + "/tickets/purchase", {
          method: "POST", body: JSON.stringify({ count: count, request_key: requestKey })
        });
        if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
        if (typeof window.loadWallet === "function") { try { await window.loadWallet(); } catch (_) {} }
        await openDetail(d.giveaway.public_id, document.querySelector("#nyg-detail-view [data-nyg-back]").dataset.nygBack);
      } catch (e) { status.textContent = e.message; status.className = "nyg-message error"; }
      finally { buy.disabled = false; }
    });
  }

  function renderOwnerList() {
    const box = document.getElementById("nyg-owner-list");
    const items = state.ownerItems.filter(function (x) { return state.ownerFilter === "all" || x.status === state.ownerFilter; });
    box.innerHTML = items.length ? items.map(function (x) { return card(x, null, [], true); }).join("") :
      '<div class="nyg-empty">В этой категории пока нет розыгрышей</div>';
  }

  async function openOwnerList() {
    show("nyg-owner-list-view");
    const box = document.getElementById("nyg-owner-list");
    box.innerHTML = '<div class="nyg-empty">Загружаем…</div>';
    try { const d = await api("/api/owner/giveaways"); state.ownerItems = d.items || []; renderOwnerList(); }
    catch (e) { box.innerHTML = '<div class="nyg-empty">' + esc(e.message) + '</div>'; }
  }

  function participantHtml(p) {
    const name = p.username ? "@" + p.username : (p.first_name || "Пользователь");
    const search = (name + " " + p.telegram_id).toLowerCase();
    const serials = Array.isArray(p.ticket_numbers) && p.ticket_numbers.length
      ? '<br>Билеты: ' + p.ticket_numbers.map(function (n) { return '#' + String(n).padStart(6, "0"); }).join(', ')
      : '';
    return '<div class="nyg-participant" data-search="' + esc(search) + '"><div><div class="nyg-person-name">' + esc(name) + '</div>' +
      '<div class="nyg-person-meta">ID ' + esc(p.telegram_id) + ' · ' + esc(p.rank) + ' · билетов ' + esc(p.tickets) + ' · потрачено ' + esc(p.paid_lapcoins) +
      ' 🐾<br>Статус: ' + esc(p.status) + (p.exclusion_reason ? " · " + esc(p.exclusion_reason) : "") + serials + '</div></div>' +
      '<div class="nyg-mini-actions"><button type="button" data-pa="plus" data-target="' + esc(p.telegram_id) + '">+1</button>' +
      '<button type="button" data-pa="minus" data-target="' + esc(p.telegram_id) + '">−1</button>' +
      '<button type="button" data-pa="exclude" data-target="' + esc(p.telegram_id) + '">Исключить</button>' +
      '<button type="button" data-pa="refund" data-target="' + esc(p.telegram_id) + '">Возврат</button></div></div>';
  }

  function renderOwnerDetail(d) {
    const g = d.giveaway, s = d.stats || {};
    let results = (d.results || []).map(function (r) {
      const who = r.username ? "@" + r.username : (r.first_name || "ID " + r.telegram_id);
      return '<div class="nyg-result ' + (r.status === "active" ? "" : "old") + '"><b>' + esc(r.position) + ' место</b> · ' + esc(who) +
        '<div class="nyg-result-meta">' + esc(r.prize_text) + ' · билет #' + String(r.ticket_number).padStart(6,"0") + ' · ' + esc(r.status) + '</div>' +
        (r.status === "active" ? '<button type="button" class="nyg-secondary" data-replace="' + esc(r.position) + '" style="margin-top:8px">Перевыбрать это место</button>' : "") + '</div>';
    }).join("");
    let controls = "";
    if (g.status === "active") controls += '<button class="nyg-secondary" data-oa="pause">Поставить на паузу</button>';
    if (g.status === "paused") controls += '<button class="nyg-success" data-oa="resume">Продолжить</button>';
    if (["active","paused","scheduled"].includes(g.status)) controls += '<button class="nyg-secondary" data-oa="close">Завершить сейчас</button>';
    if (g.status === "awaiting_results" && !(d.results || []).some(function (x) { return x.status === "active"; })) controls += '<button class="nyg-primary" data-oa="draw">Выбрать победителей</button>';
    if ((d.results || []).some(function (x) { return x.status === "active"; })) controls += '<button class="nyg-secondary" data-oa="annul">Аннулировать результаты</button>';
    const activeResults = (d.results || []).filter(function (x) { return x.status === "active"; }).length;
    const publishedResults = (d.result_posts || []).some(function (x) { return x.status === "published"; });
    const staleResults = (d.result_posts || []).some(function (x) { return x.status === "stale"; });
    if (activeResults === (g.prizes || []).length && activeResults > 0 && ["awaiting_results","completed"].includes(g.status)) {
      controls += '<button class="nyg-success" data-oa="publish-results">' +
        (publishedResults || staleResults ? 'Обновить итоги в каналах' : 'Опубликовать итоги во все каналы') +
        '</button>';
    }
    if (!["completed","cancelled"].includes(g.status)) controls += '<button class="nyg-danger" data-oa="cancel">Отменить розыгрыш</button>';

    const ranks = Object.entries(s.rank_distribution || {}).map(function (x) {
      return '<span class="nyg-pill">' + esc(x[0]) + ': ' + esc(x[1]) + '</span>';
    }).join("");

    return '<section class="nyg-card"><div class="nyg-top"><div><div class="nyg-title">' + esc(g.title) + '</div><div class="nyg-id">' + esc(g.public_id) +
      '</div></div>' + badge(g.status) + '</div><div class="nyg-info"><div class="nyg-info-grid">' +
      '<div class="nyg-stat"><b>' + esc(s.unique_participants || 0) + '</b><span>участников</span></div>' +
      '<div class="nyg-stat"><b>' + esc(s.tickets || 0) + '</b><span>билетов</span></div>' +
      '<div class="nyg-stat"><b>' + esc(s.paid_lapcoins || 0) + ' 🐾</b><span>потрачено</span></div>' +
      '<div class="nyg-stat"><b>' + esc((g.prizes || []).length) + '</b><span>призовых мест</span></div></div></div>' +
      '<div class="nyg-meta">' + ranks + '</div><div class="nyg-actions">' + controls + '</div><div id="nyg-owner-status" class="nyg-message"></div></section>' +
      (results ? '<section class="nyg-card"><div class="nyg-title">Результаты</div><div class="nyg-results">' + results + '</div></section>' : "") +
      '<section class="nyg-card"><div class="nyg-title">Ручное управление</div><div class="nyg-search"><input id="nyg-manual-target" placeholder="Telegram ID или @username">' +
      '<button type="button" id="nyg-manual-add">+1 билет</button></div><div class="nyg-message">Ручные билеты не списывают лапкоины.</div></section>' +
      '<section class="nyg-card"><div class="nyg-title">Участники</div><div class="nyg-search"><input id="nyg-participant-search" placeholder="Поиск по username или Telegram ID"></div>' +
      '<div id="nyg-participant-list">' + ((d.participants || []).map(participantHtml).join("") || '<div class="nyg-message">Пока нет участников</div>') + '</div></section>';
  }

  async function openOwnerDetail(id) {
    show("nyg-owner-detail-view");
    const box = document.getElementById("nyg-owner-detail");
    box.innerHTML = '<div class="nyg-empty">Загружаем…</div>';
    try { const d = await api("/api/owner/giveaways/" + encodeURIComponent(id)); box.innerHTML = renderOwnerDetail(d); bindOwnerDetail(d); }
    catch (e) { box.innerHTML = '<div class="nyg-empty">' + esc(e.message) + '</div>'; }
  }

  async function ownerAction(id, action, body) {
    const o = { method: "POST" }; if (body) o.body = JSON.stringify(body);
    return api("/api/owner/giveaways/" + encodeURIComponent(id) + "/" + action, o);
  }

  function bindOwnerDetail(d) {
    const id = d.giveaway.public_id, status = document.getElementById("nyg-owner-status");
    document.querySelectorAll("#nyg-owner-detail [data-oa]").forEach(function (b) {
      b.addEventListener("click", async function () {
        const a = b.dataset.oa; let body = null;
        if (a === "cancel") {
          if (!(await ask("Отменить розыгрыш? Все потраченные лапкоины будут возвращены."))) return;
          if (!(await ask("Точно отменить розыгрыш? Это действие закроет участие."))) return;
        }
        if (a === "annul") { const r = promptText("Причина аннулирования результатов"); if (!r) return; body = { reason: r }; }
        if (a === "publish-results") {
          const channels = (d.giveaway.channels || []).filter(function (x) { return x.publish_enabled; });
          const names = channels.map(function (x) { return x.username ? "@" + x.username : x.title; }).join(", ");
          if (!channels.length) { status.textContent = "Нет каналов для публикации итогов"; status.className = "nyg-message error"; return; }
          if (!(await ask("Опубликовать итоги в каналы: " + names + "?"))) return;
          body = { channel_ids: channels.map(function (x) { return x.chat_id; }) };
        }
        b.disabled = true; status.textContent = "Выполняем…";
        try {
          if (a === "publish-results") {
            await api("/api/owner/giveaways/" + encodeURIComponent(id) + "/results/publish", {
              method: "POST", body: JSON.stringify(body)
            });
          } else {
            await ownerAction(id, a === "annul" ? "results/annul" : a, body);
          }
          await openOwnerDetail(id);
        }
        catch (e) { status.textContent = e.message; status.className = "nyg-message error"; }
        finally { b.disabled = false; }
      });
    });

    document.querySelectorAll("#nyg-owner-detail [data-replace]").forEach(function (b) {
      b.addEventListener("click", async function () {
        const r = promptText("Причина перевыбора победителя"); if (!r) return;
        b.disabled = true;
        try {
          const response = await api("/api/owner/giveaways/" + encodeURIComponent(id) + "/results/" + encodeURIComponent(b.dataset.replace) + "/replace", {
            method: "POST", body: JSON.stringify({ reason: r })
          });
          if (response.publication_refreshed && tg && tg.showAlert) tg.showAlert("Победитель перевыбран. Опубликованные итоги обновлены.");
          await openOwnerDetail(id);
        } catch (e) { status.textContent = e.message; status.className = "nyg-message error"; }
        finally { b.disabled = false; }
      });
    });

    const search = document.getElementById("nyg-participant-search");
    if (search) search.addEventListener("input", function () {
      const q = search.value.trim().toLowerCase();
      document.querySelectorAll("#nyg-participant-list .nyg-participant").forEach(function (row) {
        row.classList.toggle("nyg-hidden", Boolean(q) && !(row.dataset.search || "").includes(q));
      });
    });

    const add = document.getElementById("nyg-manual-add");
    if (add) add.addEventListener("click", async function () {
      const t = document.getElementById("nyg-manual-target").value.trim(); if (!t) return;
      add.disabled = true;
      try { await api("/api/owner/giveaways/" + encodeURIComponent(id) + "/participants/adjust", { method:"POST", body:JSON.stringify({target:t,delta:1,refund_removed:false}) }); await openOwnerDetail(id); }
      catch (e) { status.textContent = e.message; status.className = "nyg-message error"; }
      finally { add.disabled = false; }
    });

    document.querySelectorAll("#nyg-participant-list [data-pa]").forEach(function (b) {
      b.addEventListener("click", async function () {
        const a = b.dataset.pa, target = b.dataset.target; b.disabled = true;
        try {
          if (a === "plus" || a === "minus") {
            const refund = a === "minus" ? await ask("Если билет был платным, вернуть его стоимость?") : false;
            await api("/api/owner/giveaways/" + encodeURIComponent(id) + "/participants/adjust", {
              method:"POST", body:JSON.stringify({target:target,delta:a==="plus"?1:-1,reason:a==="minus"?"Удалено владельцем":null,refund_removed:Boolean(refund)})
            });
          } else if (a === "exclude") {
            const r = promptText("Причина исключения"); if (!r) return;
            const refund = await ask("Вернуть стоимость всех платных билетов этому пользователю?");
            await api("/api/owner/giveaways/" + encodeURIComponent(id) + "/participants/remove", {
              method:"POST", body:JSON.stringify({target:target,reason:r,refund_paid:Boolean(refund)})
            });
          } else if (a === "refund") {
            const raw = promptText("Сколько лапкоинов вернуть?"); if (!raw) return;
            const amount = Number(raw); if (!Number.isInteger(amount) || amount <= 0) throw new Error("Введите целое количество лапкоинов");
            const r = promptText("Причина возврата", "Ручной возврат"); if (!r) return;
            await api("/api/owner/giveaways/" + encodeURIComponent(id) + "/participants/refund", {
              method:"POST", body:JSON.stringify({target:target,amount:amount,reason:r})
            });
          }
          await openOwnerDetail(id);
        } catch (e) { status.textContent = e.message; status.className = "nyg-message error"; }
        finally { b.disabled = false; }
      });
    });
  }

  async function openMyPurchases() {
    show("nyg-my-purchases-view");
    const list = document.getElementById("nyg-my-purchases-list");
    const summary = document.getElementById("nyg-my-purchases-summary");
    list.innerHTML = '<div class="nyg-message">Загружаем…</div>';
    summary.textContent = "Загружаем покупки…";
    summary.className = "nyg-message";
    try {
      const d = await api("/api/my-purchases");
      summary.textContent = "Покупок: " + d.count + " · общая сумма: " + (Number(d.total_kopecks || 0) / 100).toFixed(2) + " ₽";
      list.innerHTML = d.items && d.items.length ? d.items.map(function (x) {
        return '<div class="nyg-purchase-row">' +
          '<div class="nyg-purchase-top"><div class="nyg-purchase-name">' + esc(x.item_name) + '</div>' +
          '<div class="nyg-purchase-amount">' + esc(x.amount_rub) + ' ₽</div></div>' +
          '<div class="nyg-purchase-meta">' + esc(x.purchase_id) + ' · ' + esc(x.purchased_on) + '</div>' +
          '</div>';
      }).join("") : '<div class="nyg-message">У вас пока нет учтённых покупок</div>';
    } catch (e) {
      summary.textContent = e.message;
      summary.className = "nyg-message error";
      list.innerHTML = "";
    }
  }


  async function loadPurchases(q) {
    const list = document.getElementById("nyg-purchase-list"), sum = document.getElementById("nyg-purchase-summary");
    list.innerHTML = '<div class="nyg-message">Загружаем…</div>';
    try {
      const d = await api("/api/owner/purchases?q=" + encodeURIComponent(q || ""));
      sum.textContent = "Покупок: " + d.count + " · сумма: " + (Number(d.total_kopecks || 0) / 100).toFixed(2) + " ₽";
      list.innerHTML = d.items && d.items.length ? d.items.map(function (x) {
        const who = x.username ? "@" + x.username : (x.first_name || "ID " + x.telegram_id);
        return '<div class="nyg-purchase-row"><div class="nyg-purchase-top"><div class="nyg-purchase-name">' + esc(who) + ' · ' + esc(x.item_name) +
          '</div><div class="nyg-purchase-amount">' + esc(x.amount_rub) + ' ₽</div></div><div class="nyg-purchase-meta">' + esc(x.purchase_id) + ' · ' + esc(x.purchased_on) +
          ' · ID ' + esc(x.telegram_id) + '</div><button type="button" class="nyg-danger" data-del-purchase="' + esc(x.id) + '">Удалить</button></div>';
      }).join("") : '<div class="nyg-message">Покупок не найдено</div>';
      list.querySelectorAll("[data-del-purchase]").forEach(function (b) {
        b.addEventListener("click", async function () {
          if (!(await ask("Удалить эту покупку из реестра?"))) return;
          b.disabled = true;
          try { await api("/api/owner/purchases/" + encodeURIComponent(b.dataset.delPurchase) + "/delete", {method:"POST"}); await loadPurchases(document.getElementById("nyg-purchase-search").value.trim()); }
          catch (e) { sum.textContent = e.message; } finally { b.disabled = false; }
        });
      });
    } catch (e) { list.innerHTML = '<div class="nyg-message error">' + esc(e.message) + '</div>'; }
  }

  async function openPurchases() { show("nyg-purchases-view"); await loadPurchases(""); }

  function bindPurchaseAdmin() {
    const sb = document.getElementById("nyg-purchase-search-btn");
    if (sb) sb.addEventListener("click", function () { loadPurchases(document.getElementById("nyg-purchase-search").value.trim()); });
    const si = document.getElementById("nyg-purchase-search");
    if (si) si.addEventListener("keydown", function (e) { if (e.key === "Enter") loadPurchases(si.value.trim()); });

    const ib = document.getElementById("nyg-purchase-import-btn");
    if (ib) ib.addEventListener("click", async function () {
      const ta = document.getElementById("nyg-purchase-import"), st = document.getElementById("nyg-purchase-import-status");
      if (!ta.value.trim()) return; ib.disabled = true; st.textContent = "Проверяем список…";
      try {
        const d = await api("/api/owner/purchases/import", {method:"POST",body:JSON.stringify({text:ta.value})});
        st.textContent = "Добавлено: " + d.imported + ". Дубликатов пропущено: " + d.duplicates_skipped + ".";
        st.className = "nyg-message ok"; ta.value = ""; await loadPurchases("");
      } catch (e) { st.textContent = e.message; st.className = "nyg-message error"; }
      finally { ib.disabled = false; }
    });

    const ab = document.getElementById("nyg-purchase-add-btn");
    if (ab) ab.addEventListener("click", async function () {
      const st = document.getElementById("nyg-purchase-add-status");
      const body = {
        target:document.getElementById("nyg-purchase-target").value.trim(),
        item_name:document.getElementById("nyg-purchase-item").value.trim(),
        amount_rub:document.getElementById("nyg-purchase-amount").value.trim(),
        purchased_on:document.getElementById("nyg-purchase-date").value.trim()
      };
      if (!body.target || !body.item_name || !body.amount_rub || !body.purchased_on) { st.textContent = "Заполните все четыре поля"; return; }
      ab.disabled = true;
      try {
        const d = await api("/api/owner/purchases/add", {method:"POST",body:JSON.stringify(body)});
        st.textContent = "Добавлено: " + d.purchase.purchase_id; st.className = "nyg-message ok"; await loadPurchases(body.target);
      } catch (e) { st.textContent = e.message; st.className = "nyg-message error"; }
      finally { ab.disabled = false; }
    });
  }

  function bindGlobal() {
    app.addEventListener("click", function (event) {
      const back = event.target.closest("[data-nyg-back]");
      if (back) {
        const t = back.dataset.nygBack;
        if (t === "wallet-view") showWallet();
        else if (t === "nyg-list-view") openMine();
        else if (t === "nyg-owner-list-view") openOwnerList();
        else show(t);
        return;
      }
      const c = event.target.closest("[data-nyg-id]");
      if (c) {
        if (c.dataset.owner === "1") openOwnerDetail(c.dataset.nygId);
        else openDetail(c.dataset.nygId, "nyg-list-view");
      }
    });

    const filters = document.getElementById("nyg-owner-filters");
    if (filters) filters.addEventListener("click", function (e) {
      const b = e.target.closest("[data-status]"); if (!b) return;
      state.ownerFilter = b.dataset.status;
      filters.querySelectorAll(".nyg-filter").forEach(function (x) { x.classList.toggle("active", x === b); });
      renderOwnerList();
    });

    if (tg && tg.BackButton && tg.BackButton.onClick) tg.BackButton.onClick(function () {
      const v = visibleCustom(); if (!v) return;
      if (v.id === "nyg-detail-view") {
        const t = document.querySelector("#nyg-detail-view [data-nyg-back]").dataset.nygBack || "nyg-list-view";
        if (t === "nyg-list-view") openMine(); else show(t);
      } else if (v.id === "nyg-owner-detail-view") openOwnerList();
      else if (v.id === "nyg-owner-list-view" || v.id === "nyg-purchases-view") show("owner-view");
      else showWallet();
    });
  }

  function deepId() {
    if (window.__nyanGiveawayDeepLink && /^NYG-\d{6,}$/.test(window.__nyanGiveawayDeepLink)) {
      return window.__nyanGiveawayDeepLink;
    }
    const candidates = [];
    try {
      const url = new URL(window.location.href);
      candidates.push(url.searchParams.get("giveaway"));
      candidates.push(url.searchParams.get("tgWebAppStartParam"));
      candidates.push(url.searchParams.get("startapp"));
      const hash = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
      const hp = new URLSearchParams(hash);
      candidates.push(hp.get("giveaway"));
      candidates.push(hp.get("tgWebAppStartParam"));
      candidates.push(hp.get("startapp"));
    } catch (_) {}
    candidates.push(tg && tg.initDataUnsafe ? (tg.initDataUnsafe.start_param || "") : "");

    for (const raw of candidates) {
      const value = String(raw || "").trim();
      if (/^NYG-\d{6,}$/.test(value)) return value;
      const match = value.match(/^giveaway_(NYG-\d{6,})$/);
      if (match) return match[1];
    }
    return null;
  }

  function start() {
    ensureViews(); ensureButtons(); bindPurchaseAdmin(); bindGlobal();
    const id = deepId();
    if (id && tg && tg.initData) {
      window.__nyanGiveawayDeepLink = id;
      window.__nyanGiveawayDeepLinkActive = true;
      openDetail(id, "wallet-view");
      setTimeout(function () {
        if (window.__nyanGiveawayDeepLinkActive && state.currentId === id) {
          const detail = document.getElementById("nyg-detail-view");
          if (detail && detail.classList.contains("hidden")) openDetail(id, "wallet-view");
        }
      }, 800);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
