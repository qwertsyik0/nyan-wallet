(() => {
  "use strict";

  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  let auth = tg?.initData || "";
  const state = { rounds: [], owner: false, editId: null, busy: false, adminTab: "form" };
  const labels = {draft:"черновик",active:"продажа билетов",closed:"приём закрыт",drawn:"результаты",cancelled:"отменено"};

  tg?.ready?.();
  tg?.expand?.();
  try { if (!auth) auth = "browser:" + (sessionStorage.getItem("nyan_ideas_browser_auth") || ""); } catch (_) {}
  if (auth === "browser:") auth = "";

  function el(tag, cls, content) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (content !== undefined) n.textContent = String(content);
    return n;
  }
  function button(text, handler, cls = "") {
    const b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", handler);
    return b;
  }
  function date(value) {
    if (!value) return "без срока";
    const d = new Date(value);
    return Number.isFinite(d.getTime()) ? d.toLocaleString("ru-RU", { dateStyle:"short", timeStyle:"short" }) : "—";
  }
  function price(amount) { return `${Number(amount).toLocaleString("ru-RU")} 🐾`; }
  function status(message, owner = false) {
    $(owner ? "lottery-editor-status" : "lottery-status").textContent = message || "";
  }
  async function api(path, method = "GET", data = null) {
    if (!auth) throw Error("Открой страницу через Telegram");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), method === "GET" ? 16000 : 30000);
    try {
      const resp = await fetch(API + path, {
        method, headers: { "X-Telegram-Init-Data": auth, ...(data === null ? {} : {"Content-Type":"application/json"}) },
        body: data === null ? undefined : JSON.stringify(data),
        cache: "no-store", signal: controller.signal,
      });
      const json = await resp.json().catch(() => null);
      if (!resp.ok) {
        const detail = json?.detail;
        throw Error(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map(e => e.msg || e).join("; ") : `HTTP ${resp.status}`);
      }
      if (!json?.ok) throw Error("Некорректный ответ сервера");
      return json;
    } catch (error) {
      if (controller.signal.aborted) throw Error("Сервер долго отвечает. Повтори запрос.");
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function confirmText(text) {
    return new Promise(resolve => {
      if (tg?.showConfirm) tg.showConfirm(text, yes => resolve(Boolean(yes)));
      else resolve(window.confirm(text));
    });
  }
  async function safeAction(action, ask = null) {
    if (state.busy) return;
    if (ask && !await confirmText(ask)) return;
    state.busy = true;
    try { await action(); } catch (error) {
      status(error.message);
      if (state.owner && state.adminTab === "form") status(error.message, true);
    }
    finally { state.busy = false; }
  }

  function card(round) {
    const box = el("article", "lottery-round");
    const head = el("div", "lottery-round-top");
    head.append(el("h3", "", round.title), el("span", "lottery-tag", labels[round.status] || round.status));
    box.append(head, el("p", "", round.description));
    const stats = el("div", "lottery-stats");
    stats.append(el("span", "", `🎫 куплено: ${round.total_tickets}`),
                 el("span", "", `моих билетов: ${round.my_tickets}`),
                 el("span", "", `⏱ ${date(round.ends_at)}`));
    box.append(stats);
    box.append(el("div", "lottery-subhead", "Призовой фонд"));
    const prizes = el("div", "lottery-prize-list");
    for (const prize of round.prizes) prizes.append(el("span", "lottery-prize", `${prize.title} · ${price(prize.amount)} × ${prize.quantity}`));
    box.append(prizes);
    box.append(el("div", "lottery-subhead", "Выбери билет"));
    const tickets = el("div", "lottery-tickets");
    for (const tier of round.tiers) {
      const tile = el("div", "lottery-ticket");
      tile.append(el("strong", "", tier.name), el("span", "lottery-price", price(tier.price)));
      if (round.status === "active" && !state.owner && (!round.ends_at || new Date(round.ends_at) > new Date())) {
        const amount = document.createElement("select");
        amount.setAttribute("aria-label", `Количество билетов ${tier.name}`);
        const limit = Math.min(25, Math.max(0, round.max_per_user - round.my_tickets));
        for (let i = 1; i <= limit; i++) {
          const option = el("option", "", `${i} шт. · ${price(i * tier.price)}`);
          option.value = String(i);
          amount.append(option);
        }
        if (limit) {
          tile.append(amount, button("купить билет", () => buy(round, tier, Number(amount.value)), "lottery-buy"));
        } else tile.append(el("small", "", "Лимит билетов достигнут"));
      } else if (round.status !== "active") {
        tile.setAttribute("aria-disabled", "true");
        tile.append(el("small", "", "Приём билетов закрыт"));
      }
      tickets.append(tile);
    }
    box.append(tickets);
    const rule = el("p", "lottery-note", "Билет подтверждает участие, но не гарантирует выигрыш. Итоги появятся после закрытия тиража.");
    box.append(rule);
    if (round.status === "drawn") {
      const results = el("div", "lottery-winning");
      results.append(el("strong", "", "Победители"));
      if (!round.winners.length) results.append(el("div", "", "В этом тираже не было участников."));
      for (const winner of round.winners) {
        results.append(el("div", winner.is_me ? "lottery-own-win" : "",
                          `${winner.is_me ? "★ " : ""}${winner.name} · +${price(winner.amount)}`));
      }
      box.append(results);
    }
    if (state.owner) box.append(ownerActions(round));
    return box;
  }

  async function buy(round, tier, count) {
    await safeAction(async () => {
      const cost = tier.price * count;
      if (!await confirmText(`Купить ${count} бил. «${tier.name}» за ${price(cost)}? Покупка не возвращается, если тираж состоялся.`)) return;
      // Retain the same key after a timeout. A retry must never debit twice.
      const pendingKey = `nyan-lottery-pending-${round.id}-${tier.id}-${count}`;
      let key = "";
      try { key = sessionStorage.getItem(pendingKey) || ""; } catch (_) {}
      if (!key) {
        key = (window.crypto?.randomUUID?.() || `${Date.now()}-${Math.floor(Math.random() * 1e9)}`).replaceAll("-", "");
        try { sessionStorage.setItem(pendingKey, key); } catch (_) {}
      }
      const response = await api(`/api/lottery/${round.id}/purchase`, "POST", {
        tier_id: tier.id, count, request_key: key,
      });
      try { sessionStorage.removeItem(pendingKey); } catch (_) {}
      status(`${response.duplicate ? "Повторная покупка найдена" : "Билеты куплены"}. Списано ${price(response.cost)}. Остаток: ${price(response.balance)}.`);
      await load(true);
    });
  }

  function ownerActions(round) {
    const actions = el("div", "lottery-admin-actions");
    if (round.status === "draft" || (round.status === "active" && !round.total_tickets)) {
      actions.append(button("✎ изменить условия", () => edit(round)));
    }
    if (round.status === "draft") actions.append(button("запустить продажи", () => ownerAct(round, "activate", "Начать продажу билетов?"), "lottery-confirm"));
    if (round.status === "active") actions.append(button("закрыть приём", () => ownerAct(round, "close", "Закрыть приём билетов? В автоматическом режиме призы будут начислены сразу.")));
    if (round.status === "closed" && round.mode === "manual") actions.append(button("выбрать победителей", () => review(round), "lottery-confirm"));
    if (["draft", "active", "closed"].includes(round.status) && !round.reserved_winners.length) {
      actions.append(button("отменить и вернуть 🐾", () => ownerAct(round, "cancel", "Отменить тираж? Все потраченные на билеты лапкоины вернутся участникам."), "lottery-danger"));
    }
    if (round.status === "drawn") actions.append(el("span", "lottery-note", `${round.reserved_winners.length} победителей · продажи ${price(round.gross_sales)}`));
    if (["drawn", "cancelled"].includes(round.status)) {
      actions.append(button("убрать в архив", () => ownerAct(round, "archive",
        "Скрыть тираж из мини-приложения? История покупок, списания и награды сохранятся.")));
    }
    return actions;
  }

  async function ownerAct(round, action, question) {
    await safeAction(async () => {
      const answer = await api(`/api/owner/lottery/rounds/${round.id}/${action}`, "POST");
      status(action === "cancel" ? `Тираж отменён, возвратов: ${answer.refunds}` : `Тираж #${round.id}: ${labels[answer.status] || answer.status}`);
      await load(true);
    }, question);
  }

  function render() {
    $("lottery-owner").hidden = !state.owner;
    const publicRounds = state.rounds.filter(r => r.status !== "draft" && r.status !== "cancelled");
    const wrapper = $("lottery-rounds");
    wrapper.replaceChildren();
    if (!publicRounds.length) wrapper.append(el("div", "studio-placeholder", "пока нет открытых лотерей"));
    for (const round of publicRounds) wrapper.append(card(round));
    const admin = $("lottery-admin-rounds");
    admin.replaceChildren();
    if (!state.rounds.length) admin.append(el("div", "studio-placeholder", "создай первый тираж"));
    for (const round of state.rounds) {
      const row = el("div", "lottery-round");
      const head = el("div", "lottery-round-top");
      head.append(el("h3", "", `#${round.id} · ${round.title}`), el("span", "lottery-tag", labels[round.status] || round.status));
      row.append(head, el("p", "", `Билетов: ${round.total_tickets} · Продажи: ${price(round.gross_sales)} · призов: ${round.prizes.reduce((a,p) => a + p.quantity, 0)} · ${round.mode === "manual" ? "ручной" : "автоматический"}`), ownerActions(round));
      if (round.audit?.length) {
        const history = document.createElement("details");
        history.append(el("summary", "lottery-note", "журнал управления"));
        for (const item of round.audit) history.append(el("p", "lottery-note", `${date(item.at)} · ${item.details}`));
        row.append(history);
      }
      admin.append(row);
    }
  }

  async function load(quiet = false) {
    if (!auth) {
      $("lottery-login").hidden = false;
      $("lottery-rounds").replaceChildren(el("div", "studio-placeholder", "открой через Telegram"));
      return;
    }
    if (!quiet) status("Получаем лотереи…");
    try {
      const data = await api("/api/lottery");
      state.rounds = data.rounds;
      state.owner = Boolean(data.is_owner);
      render();
      if (!quiet) status("");
    } catch (error) {
      status("Не удалось открыть лотерею: " + error.message);
      if (/Telegram|вход|сессия/i.test(error.message)) $("lottery-login").hidden = false;
    }
  }

  function numberField(label, value, min, max) {
    const wrap = el("label", "", label);
    const input = document.createElement("input");
    input.type = "number"; input.min = String(min); input.max = String(max); input.required = true;
    input.value = String(value);
    wrap.append(input);
    return {wrap, input};
  }
  function textField(label, value, max) {
    const wrap = el("label", "", label);
    const input = document.createElement("input");
    input.type = "text"; input.maxLength = max; input.required = true; input.value = value;
    wrap.append(input);
    return {wrap, input};
  }
  function editorRow(type, values) {
    const holder = $(type === "tier" ? "lottery-tier-fields" : "lottery-prize-fields");
    if (holder.children.length >= (type === "tier" ? 6 : 10)) return;
    const row = el("div", "lottery-editor-row");
    const fields = type === "tier" ? [
      textField("название", values?.name || "", 50), numberField("цена 🐾", values?.price || 50, 1, 100000),
      numberField("вес", values?.weight || 1, 1, 1000),
    ] : [
      textField("приз", values?.title || "", 90), numberField("награда 🐾", values?.amount || 100, 1, 100000),
      numberField("кол-во", values?.quantity || 1, 1, 30),
    ];
    row._fields = fields.map(x => x.input);
    row.append(...fields.map(x => x.wrap), button("×", () => {
      if (holder.children.length > 1) row.remove();
    }, "lottery-remove"));
    holder.append(row);
  }
  function reset() {
    state.editId = null;
    $("lottery-form-title").textContent = "Новый тираж";
    $("lottery-save").textContent = "сохранить черновик";
    $("lottery-form").reset();
    $("lottery-title").value = "Счастливый билет Няника";
    $("lottery-description").value = "Купи билет и попробуй выиграть лапкоины!";
    $("lottery-limit").value = "20";
    $("lottery-tier-fields").replaceChildren();
    $("lottery-prize-fields").replaceChildren();
    editorRow("tier", {name:"обычный",price:50,weight:1});
    editorRow("tier", {name:"серебряный",price:150,weight:4});
    editorRow("tier", {name:"золотой",price:300,weight:10});
    editorRow("prize", {title:"малый приз",amount:100,quantity:3});
    editorRow("prize", {title:"большой приз",amount:500,quantity:1});
    status("", true);
  }
  function setTab(tab) {
    state.adminTab = tab;
    $("lottery-form").hidden = tab !== "form";
    $("lottery-admin-panel").hidden = tab !== "list";
    $("lottery-new-tab").classList.toggle("lottery-selected", tab === "form");
    $("lottery-admin-list-tab").classList.toggle("lottery-selected", tab === "list");
  }
  function edit(round) {
    state.editId = round.id;
    setTab("form");
    $("lottery-form-title").textContent = `Изменить тираж #${round.id}`;
    $("lottery-save").textContent = "сохранить изменения";
    $("lottery-title").value = round.title;
    $("lottery-description").value = round.description;
    $("lottery-mode").value = round.mode;
    $("lottery-limit").value = String(round.max_per_user);
    if (round.ends_at) {
      const d = new Date(round.ends_at);
      $("lottery-ends").value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}T${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
    } else $("lottery-ends").value = "";
    $("lottery-tier-fields").replaceChildren();
    $("lottery-prize-fields").replaceChildren();
    round.tiers.forEach(t => editorRow("tier", t));
    round.prizes.forEach(p => editorRow("prize", p));
    status("", true);
    $("lottery-owner").scrollIntoView({behavior:"smooth",block:"start"});
  }
  function serializeRows(id, type) {
    return [...$(id).children].map(row => {
      const [a,b,c] = row._fields;
      if (type === "tier") return {name:a.value.trim(),price:Number(b.value),weight:Number(c.value)};
      return {title:a.value.trim(),amount:Number(b.value),quantity:Number(c.value)};
    });
  }
  async function save(event) {
    event.preventDefault();
    await safeAction(async () => {
      const ends = $("lottery-ends").value;
      const payload = {
        title:$("lottery-title").value.trim(), description:$("lottery-description").value.trim(),
        mode:$("lottery-mode").value, max_per_user:Number($("lottery-limit").value),
        ends_at:ends ? new Date(ends).toISOString() : null,
        tiers:serializeRows("lottery-tier-fields", "tier"), prizes:serializeRows("lottery-prize-fields", "prize"),
      };
      const response = state.editId
        ? await api(`/api/owner/lottery/rounds/${state.editId}/update`, "POST", payload)
        : await api("/api/owner/lottery/rounds", "POST", payload);
      reset();
      status(`Тираж #${response.round.id} сохранён. Пока он в черновиках.`, true);
      await load(true);
      setTab("list");
    });
  }

  async function review(round) {
    await safeAction(async () => {
      const r = (await api(`/api/lottery/${round.id}`)).round;
      $("lottery-review-title").textContent = `Победители · тираж #${round.id}`;
      $("lottery-review").hidden = false;
      $("lottery-review-content").replaceChildren();
      const area = $("lottery-review-content");
      const participants = r.participants || [];
      if (!participants.length) area.append(el("p", "lottery-note", "Билетов нет. Можно завершить тираж без победителей."));
      const picked = new Set(r.reserved_winners.map(w => w.telegram_id));
      for (const prize of r.prizes) {
        for (let slot = 1; slot <= prize.quantity; slot++) {
          const selected = r.reserved_winners.find(w => w.prize_id === prize.id && w.slot === slot);
          const row = el("div", "lottery-slot");
          row.append(el("strong", "", `${prize.title} #${slot} · ${price(prize.amount)}`));
          if (selected) {
            row.append(el("span", "lottery-rule", `Победитель: ${selected.telegram_id}`));
            row.append(button("убрать", () => assign(r.id, selected.prize_id, slot, selected.telegram_id, "unassign"), "lottery-danger"));
          } else {
            const select = document.createElement("select");
            select.append(new Option("выбери участника", ""));
            for (const user of participants.filter(p => !picked.has(p.telegram_id))) {
              select.append(new Option(`${user.username ? "@" + user.username : "участник"} · ${user.telegram_id} · ${user.tickets} бил.`, user.telegram_id));
            }
            row.append(select, button("назначить", () => {
              if (select.value) assign(r.id, prize.id, slot, Number(select.value), "assign");
            }, "lottery-confirm"));
          }
          area.append(row);
        }
      }
      const actions = el("div", "lottery-review-actions");
      actions.append(button("подтвердить и выдать призы", () => ownerAct(r, "finalize",
        "Начислить лапкоины назначенным победителям? После подтверждения выбор изменить нельзя."), "lottery-confirm"));
      area.append(actions);
      $("lottery-review").scrollIntoView({behavior:"smooth",block:"start"});
    });
  }
  async function assign(roundId, prizeId, slot, telegramId, action) {
    await safeAction(async () => {
      await api(`/api/owner/lottery/rounds/${roundId}/${action}`, "POST",
                {prize_id:prizeId,slot,telegram_id:telegramId});
      status(action === "assign" ? "Победитель назначен, пока без начисления." : "Назначение убрано.");
      await load(true);
      const r = state.rounds.find(x => x.id === roundId);
      if (r) setTimeout(() => review(r), 0);
    });
  }

  $("lottery-form").addEventListener("submit", save);
  $("lottery-add-tier").addEventListener("click", () => editorRow("tier"));
  $("lottery-add-prize").addEventListener("click", () => editorRow("prize"));
  $("lottery-reset").addEventListener("click", reset);
  $("lottery-new-tab").addEventListener("click", () => { reset(); setTab("form"); });
  $("lottery-admin-list-tab").addEventListener("click", () => setTab("list"));
  $("lottery-reload").addEventListener("click", () => load());
  $("lottery-review-close").addEventListener("click", () => { $("lottery-review").hidden = true; });
  reset();
  load();
})();
