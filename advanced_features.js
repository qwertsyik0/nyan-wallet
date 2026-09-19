const tgAdv = window.Telegram?.WebApp;
const API_ADV = "https://nyan-wallet-api.onrender.com";
const ADV_EVENT_TARGET_ID = (() => {
    const raw = new URLSearchParams(window.location.search).get("event");
    const value = Number.parseInt(raw || "", 10);
    return Number.isInteger(value) && value > 0 ? value : null;
})();

function advHeaders(json = false) {
    const h = { "X-Telegram-Init-Data": tgAdv?.initData || "" };
    if (json) h["Content-Type"] = "application/json";
    return h;
}

async function advJson(response) {
    try { return await response.json(); } catch (_) { return {}; }
}

function advEsc(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function advDate(value) {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

async function advConfirm(text) {
    if (tgAdv?.showConfirm) return await new Promise(resolve => tgAdv.showConfirm(text, resolve));
    return window.confirm(text);
}

function addAdvStyles() {
    if (document.getElementById("advanced-wallet-styles")) return;
    const s = document.createElement("style");
    s.id = "advanced-wallet-styles";
    s.textContent = `
      .adv-mini-action{background:#fff;border:1px solid #efd8e2}.adv-badge{display:inline-flex;min-width:18px;height:18px;padding:0 5px;align-items:center;justify-content:center;border-radius:999px;background:#922954;color:#fff;font-size:10px;margin-left:6px}
      .adv-panel{margin-top:14px;padding:18px;border-radius:22px;border:1px solid #efd8e2;background:linear-gradient(145deg,#fff,#fff8fa)}
      .adv-title{font-size:17px;font-weight:700;color:#7e284c}.adv-sub{margin-top:5px;color:#a67589;font-size:12px;line-height:1.45}.adv-grid{display:grid;gap:10px;margin-top:13px}.adv-row{padding:13px;border-radius:15px;border:1px solid #f0dce5;background:#fff}.adv-row-title{font-size:13px;font-weight:700;color:#6d304a}.adv-row-meta{margin-top:5px;font-size:11px;color:#a67589;line-height:1.45}.adv-actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}.adv-actions button{width:auto;padding:9px 11px;border-radius:11px;font-size:11px}.adv-actions .secondary{background:#fff;color:#7e4059;border:1px solid #dfbbc9}
      .adv-form{display:grid;gap:9px;margin-top:12px}.adv-form input,.adv-form textarea,.adv-form select{width:100%;box-sizing:border-box;border:1px solid #efd8e2;border-radius:13px;padding:12px 13px;background:#fff;color:#6d304a;font:inherit}.adv-form textarea{min-height:80px;resize:vertical}.adv-form button{padding:12px 14px;border-radius:13px;background:#922954;color:#fff}.adv-two{display:grid;grid-template-columns:1fr 1fr;gap:8px}
      .adv-level{margin-top:14px;padding:16px;border-radius:20px;background:#fff7fa;border:1px solid #efd8e2}.adv-level-top{display:flex;align-items:center;justify-content:space-between;gap:12px}.adv-level-name{font-weight:800;color:#7e284c}.adv-level-progress{height:8px;border-radius:999px;background:#f2dfe8;overflow:hidden;margin-top:10px}.adv-level-progress>span{display:block;height:100%;background:#922954;border-radius:inherit}.adv-level-meta{margin-top:7px;font-size:11px;color:#9f7486}
      .adv-notification{padding:14px 0;border-bottom:1px solid #f2e2e9}.adv-notification:last-child{border-bottom:0}.adv-notification.unread .adv-row-title:before{content:'• ';color:#922954}.adv-event{padding:14px;border-radius:16px;background:#fff;border:1px solid #efd8e2}.adv-event.adv-event-target{border:2px solid #922954;box-shadow:0 0 0 4px rgba(146,41,84,.08)}.adv-event-badge{display:inline-block;margin-bottom:6px;padding:5px 8px;border-radius:999px;background:#fff0f6;color:#922954;font-size:10px;font-weight:700}
      .adv-reward{overflow:hidden}.adv-reward-img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:14px;margin-bottom:10px}.adv-stock{font-size:10px;color:#a67589;margin-top:5px}.adv-status{margin-top:9px;font-size:12px;color:#7e4059}.adv-ok{color:#4c7a5a}.adv-warn{color:#9a5c2f}
      @media(max-width:390px){.adv-two{grid-template-columns:1fr}.adv-actions{display:grid}.adv-actions button{width:100%}}
    `;
    document.head.appendChild(s);
}

function advShowView(id) {
    for (const viewId of ["wallet-view", "earn-view", "owner-view", "spend-view", "adv-profile-view", "adv-notifications-view"]) {
        document.getElementById(viewId)?.classList.add("hidden");
    }
    document.getElementById(id)?.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
    tgAdv?.BackButton?.show?.();
}

function advBackHome() {
    for (const id of ["adv-profile-view", "adv-notifications-view"]) document.getElementById(id)?.classList.add("hidden");
    document.getElementById("wallet-view")?.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
    tgAdv?.BackButton?.hide?.();
}

function buildAdvUI() {
    if (document.getElementById("adv-profile-button")) return;
    addAdvStyles();
    const app = document.querySelector(".app");
    const actions = document.querySelector("#wallet-view .actions");
    const ownerButton = document.getElementById("owner-button");

    const profileBtn = document.createElement("button");
    profileBtn.id = "adv-profile-button";
    profileBtn.className = "adv-mini-action";
    profileBtn.type = "button";
    profileBtn.textContent = "Профиль";

    const notifyBtn = document.createElement("button");
    notifyBtn.id = "adv-notifications-button";
    notifyBtn.className = "adv-mini-action";
    notifyBtn.type = "button";
    notifyBtn.innerHTML = `Уведомления <span id="adv-unread-badge" class="adv-badge" hidden>0</span>`;

    if (ownerButton) actions?.insertBefore(profileBtn, ownerButton); else actions?.appendChild(profileBtn);
    if (ownerButton) actions?.insertBefore(notifyBtn, ownerButton); else actions?.appendChild(notifyBtn);

    const levelCard = document.createElement("section");
    levelCard.id = "adv-level-card";
    levelCard.className = "adv-level";
    levelCard.innerHTML = `<div class="adv-level-top"><div><div class="adv-level-name">Уровень</div><div class="adv-sub">загружаем прогресс</div></div><div>🐾</div></div><div class="adv-level-progress"><span style="width:0%"></span></div><div class="adv-level-meta"></div>`;
    document.querySelector("#wallet-view .balance-card")?.insertAdjacentElement("afterend", levelCard);

    const profileView = document.createElement("main");
    profileView.id = "adv-profile-view";
    profileView.className = "view hidden";
    profileView.innerHTML = `
      <div class="subpage-header"><button class="back-button" id="adv-profile-back" type="button">‹</button><div><div class="page-title">Профиль</div><div class="page-subtitle">уровень и приглашения</div></div></div>
      <section class="adv-panel"><div class="adv-title">Ваш уровень</div><div id="adv-profile-level"></div></section>
      <section class="adv-panel"><div class="adv-title">Реферальная система</div><div class="adv-sub">Приглашайте пользователей. Код можно применить только один раз и в первые 7 дней до первого начисления.</div><div id="adv-referral-box" class="adv-grid"></div></section>
      <section class="adv-panel"><div class="adv-title">События</div><div class="adv-sub">активные лимитированные акции Nyan Wallet</div><div id="adv-events-user" class="adv-grid"></div></section>`;
    app?.appendChild(profileView);

    const notifView = document.createElement("main");
    notifView.id = "adv-notifications-view";
    notifView.className = "view hidden";
    notifView.innerHTML = `<div class="subpage-header"><button class="back-button" id="adv-notifications-back" type="button">‹</button><div><div class="page-title">Уведомления</div><div class="page-subtitle">все события Nyan Wallet</div></div></div><section class="adv-panel"><div id="adv-notification-list"></div></section>`;
    app?.appendChild(notifView);

    profileBtn.addEventListener("click", async () => { advShowView("adv-profile-view"); await Promise.all([loadAdvProfile(), loadAdvEvents()]); });
    notifyBtn.addEventListener("click", async () => { advShowView("adv-notifications-view"); await loadAdvNotifications(true); });
    document.getElementById("adv-profile-back")?.addEventListener("click", advBackHome);
    document.getElementById("adv-notifications-back")?.addEventListener("click", advBackHome);
    document.getElementById("spend-button")?.addEventListener("click", () => setTimeout(loadAdvancedCatalog, 250));
    document.getElementById("owner-button")?.addEventListener("click", () => setTimeout(loadAdvOwnerAll, 350));

    buildOwnerAdvancedSections();
}

function buildOwnerAdvancedSections() {
    const owner = document.getElementById("owner-view");
    if (!owner || document.getElementById("adv-owner-catalog")) return;
    owner.insertAdjacentHTML("beforeend", `
      <section id="adv-owner-catalog" class="adv-panel"><div class="adv-title">Каталог наград</div><div class="adv-sub">Добавление, изменение, лимиты и отключение наград</div><div class="adv-form"><input id="adv-r-title" placeholder="Название"><input id="adv-r-desc" placeholder="Описание"><div class="adv-two"><input id="adv-r-cost" type="number" placeholder="Цена 🐾"><input id="adv-r-stock" type="number" placeholder="Лимит, пусто = без лимита"></div><input id="adv-r-image" placeholder="Ссылка на изображение, необязательно"><input id="adv-r-until" type="datetime-local"><button id="adv-r-create" type="button">Добавить награду</button></div><div id="adv-owner-rewards" class="adv-grid"></div></section>
      <section class="adv-panel"><div class="adv-title">Массовое начисление</div><div class="adv-sub">До 100 пользователей за одну операцию</div><div class="adv-form"><textarea id="adv-mass-targets" placeholder="@username или Telegram ID, по одному в строке"></textarea><div class="adv-two"><input id="adv-mass-amount" type="number" placeholder="Количество 🐾"><input id="adv-mass-reason" placeholder="Причина"></div><button id="adv-mass-send" type="button">Начислить выбранным</button><div id="adv-mass-status" class="adv-status"></div></div></section>
      <section class="adv-panel"><div class="adv-title">Лимитированные события</div><div class="adv-form"><input id="adv-e-title" placeholder="Название события"><input id="adv-e-badge" placeholder="Плашка, например x2 🐾"><input id="adv-e-desc" placeholder="Описание"><div class="adv-two"><input id="adv-e-start" type="datetime-local"><input id="adv-e-end" type="datetime-local"></div><button id="adv-e-create" type="button">Создать событие</button></div><div id="adv-owner-events" class="adv-grid"></div></section>
      <section class="adv-panel"><div class="adv-title">Настройки экономики</div><div class="adv-sub">Все числа меняются без правки кода</div><div id="adv-economy-form" class="adv-form"></div></section>
      <section class="adv-panel"><div class="adv-title">Резервная копия и проверка</div><div class="adv-actions"><button id="adv-integrity" type="button">Проверить базу</button><button id="adv-export" type="button">Скачать резервную копию</button></div><div id="adv-integrity-status" class="adv-status"></div></section>`);

    document.getElementById("adv-r-create")?.addEventListener("click", createAdvReward);
    document.getElementById("adv-mass-send")?.addEventListener("click", sendMassGrant);
    document.getElementById("adv-e-create")?.addEventListener("click", createWalletEvent);
    document.getElementById("adv-integrity")?.addEventListener("click", checkIntegrity);
    document.getElementById("adv-export")?.addEventListener("click", downloadBackup);
}

async function loadAdvProfile() {
    if (!tgAdv?.initData) return;
    try {
        const r = await fetch(`${API_ADV}/api/profile`, { headers: advHeaders() });
        const d = await advJson(r);
        if (!r.ok) throw new Error(d.detail || "Ошибка профиля");
        renderLevel(d.level);
        const box = document.getElementById("adv-referral-box");
        if (box) {
            box.innerHTML = `<div class="adv-row"><div class="adv-row-title">Ваш код: ${advEsc(d.referral.code)}</div><div class="adv-row-meta">Приглашено: ${d.referral.invited_count}</div><div class="adv-actions"><button id="adv-copy-ref" type="button">Скопировать код</button></div></div>${d.referral.already_used_code ? `<div class="adv-row-meta">Вы уже использовали реферальный код.</div>` : `<div class="adv-form"><input id="adv-ref-input" placeholder="Введите код друга"><button id="adv-ref-apply" type="button">Применить код</button><div id="adv-ref-status" class="adv-status"></div></div>`}`;
            document.getElementById("adv-copy-ref")?.addEventListener("click", async () => { try { await navigator.clipboard.writeText(d.referral.code); tgAdv?.HapticFeedback?.notificationOccurred?.("success"); } catch (_) {} });
            document.getElementById("adv-ref-apply")?.addEventListener("click", applyReferral);
        }
    } catch (_) {}
}

function renderLevel(level) {
    const html = `<div class="adv-level"><div class="adv-level-top"><div><div class="adv-level-name">${advEsc(level.name)}</div><div class="adv-sub">Заработано всего: ${level.lifetime_earned} 🐾</div></div></div><div class="adv-level-progress"><span style="width:${level.progress}%"></span></div><div class="adv-level-meta">${level.next_name ? `До уровня «${advEsc(level.next_name)}» осталось ${level.remaining} 🐾` : "Максимальный уровень"}</div></div>`;
    const card = document.getElementById("adv-level-card");
    if (card) card.outerHTML = `<section id="adv-level-card">${html}</section>`;
    const p = document.getElementById("adv-profile-level");
    if (p) p.innerHTML = html;
}

async function applyReferral() {
    const code = document.getElementById("adv-ref-input")?.value.trim();
    const status = document.getElementById("adv-ref-status");
    if (!code) return;
    try {
        const r = await fetch(`${API_ADV}/api/referrals/apply`, { method: "POST", headers: advHeaders(true), body: JSON.stringify({ code }) });
        const d = await advJson(r);
        if (!r.ok) throw new Error(d.detail || "Не удалось применить код");
        if (status) status.textContent = `Готово. Начислено +${d.invited_bonus} 🐾`;
        const balance = document.getElementById("balance");
        if (balance && balance.textContent !== "∞") balance.textContent = String(d.balance);
        await loadAdvProfile();
    } catch (e) { if (status) status.textContent = e.message; }
}

async function loadAdvNotifications(markRead = false) {
    if (!tgAdv?.initData) return;
    try {
        const r = await fetch(`${API_ADV}/api/notifications`, { headers: advHeaders() });
        const d = await advJson(r);
        if (!r.ok) return;
        const badge = document.getElementById("adv-unread-badge");
        if (badge) { badge.hidden = !d.unread; badge.textContent = String(d.unread); }
        const box = document.getElementById("adv-notification-list");
        if (box) box.innerHTML = d.items?.length ? d.items.map(n => `<div class="adv-notification ${n.is_read ? "" : "unread"}"><div class="adv-row-title">${advEsc(n.title)}</div><div class="adv-row-meta">${advEsc(n.body).replaceAll("\n", "<br>")}<br>${advDate(n.created_at)}</div></div>`).join("") : `<div class="adv-sub">Уведомлений пока нет</div>`;
        if (markRead && d.unread) {
            await fetch(`${API_ADV}/api/notifications/read-all`, { method: "POST", headers: advHeaders(true) });
            if (badge) badge.hidden = true;
        }
    } catch (_) {}
}

async function loadAdvEvents(targetEventId = null) {
    const box = document.getElementById("adv-events-user");
    if (!box || !tgAdv?.initData) return;
    try {
        const r = await fetch(`${API_ADV}/api/events`, { headers: advHeaders() });
        const d = await advJson(r);
        if (!r.ok) throw new Error(d.detail || "Не удалось загрузить события");
        box.innerHTML = d.events?.length ? d.events.map(e => {
            const target = targetEventId && Number(e.id) === Number(targetEventId);
            return `<div class="adv-event${target ? " adv-event-target" : ""}" data-event-id="${e.id}">${e.badge ? `<div class="adv-event-badge">${advEsc(e.badge)}</div>` : ""}<div class="adv-row-title">${advEsc(e.title)}</div><div class="adv-row-meta">${advEsc(e.description || "")}<br>до ${advDate(e.ends_at)}</div></div>`;
        }).join("") : `<div class="adv-sub">Сейчас активных событий нет</div>`;
        if (targetEventId) {
            const card = box.querySelector(`[data-event-id="${Number(targetEventId)}"]`);
            if (card) setTimeout(() => card.scrollIntoView({ behavior: "smooth", block: "center" }), 80);
        }
    } catch (e) {
        box.innerHTML = `<div class="adv-sub">${advEsc(e.message)}</div>`;
    }
}

async function openAdvEventDeepLink() {
    if (!ADV_EVENT_TARGET_ID) return;
    advShowView("adv-profile-view");
    await Promise.all([loadAdvProfile(), loadAdvEvents(ADV_EVENT_TARGET_ID)]);
}

async function loadEconomyUser() {
    if (!tgAdv?.initData) return;
    try {
        const r = await fetch(`${API_ADV}/api/economy`, { headers: advHeaders() });
        const d = await advJson(r);
        if (!r.ok) return;
        const cards = document.querySelectorAll("#earn-view .earn-card .reward-badge");
        if (cards[0]) cards[0].textContent = `${d.settings.cashback_percent}%`;
        if (cards[1]) cards[1].textContent = `+${d.settings.first_purchase_bonus} 🐾`;
        if (cards[2]) cards[2].textContent = `+${d.settings.review_bonus} 🐾`;
        if (cards[3]) cards[3].textContent = `+${d.settings.activity_min}–${d.settings.activity_max} 🐾`;
    } catch (_) {}
}

async function loadAdvancedCatalog() {
    const list = document.getElementById("reward-list");
    if (!list || !tgAdv?.initData) return;
    try {
        const r = await fetch(`${API_ADV}/api/catalog`, { headers: advHeaders() });
        const d = await advJson(r);
        if (!r.ok) return;
        list.innerHTML = "";
        for (const reward of d.rewards || []) {
            const card = document.createElement("article");
            card.className = "feature-card adv-reward";
            card.innerHTML = `${reward.image_url ? `<img class="adv-reward-img" src="${advEsc(reward.image_url)}" alt="">` : ""}<div class="feature-card-head"><div><h3>${advEsc(reward.title)}</h3><p>${advEsc(reward.description || "")}</p>${reward.stock_remaining != null ? `<div class="adv-stock">Осталось: ${reward.stock_remaining}</div>` : ""}${reward.available_until ? `<div class="adv-stock">Доступно до ${advDate(reward.available_until)}</div>` : ""}</div><div class="feature-price">${reward.cost} 🐾</div></div><button type="button">Получить за ${reward.cost} 🐾</button>`;
            card.querySelector("button")?.addEventListener("click", () => buyAdvReward(reward));
            list.appendChild(card);
        }
    } catch (_) {}
}

async function buyAdvReward(reward) {
    if (!(await advConfirm(`Списать ${reward.cost} 🐾 и создать заявку на «${reward.title}»?`))) return;
    try {
        const r = await fetch(`${API_ADV}/api/rewards/${reward.id}/request`, { method: "POST", headers: advHeaders(true) });
        const d = await advJson(r);
        if (!r.ok) throw new Error(d.detail || "Не удалось создать заявку");
        const balance = document.getElementById("balance");
        if (balance && balance.textContent !== "∞") balance.textContent = String(d.balance);
        tgAdv?.HapticFeedback?.notificationOccurred?.("success");
        await Promise.all([loadAdvancedCatalog(), loadAdvNotifications(false)]);
    } catch (e) { alert(e.message); }
}

async function loadAdvOwnerAll() {
    await Promise.all([loadOwnerRewards(), loadAdvancedRequests(), loadOwnerEvents(), loadOwnerEconomy()]);
}

async function loadOwnerRewards() {
    const box = document.getElementById("adv-owner-rewards");
    if (!box || !tgAdv?.initData) return;
    try {
        const r = await fetch(`${API_ADV}/api/owner/catalog`, { headers: advHeaders() });
        const d = await advJson(r);
        if (!r.ok) throw new Error(d.detail || "Ошибка каталога");
        box.innerHTML = d.rewards?.length ? d.rewards.map(x => `<div class="adv-row" data-rid="${x.id}"><div class="adv-row-title">${advEsc(x.title)} · ${x.cost} 🐾</div><div class="adv-row-meta">${x.is_active ? "активна" : "отключена"}${x.stock_limit != null ? ` · ${x.stock_used}/${x.stock_limit}` : " · без лимита"}</div><div class="adv-actions"><button class="adv-r-edit" type="button">Изменить</button><button class="adv-r-toggle secondary" type="button">${x.is_active ? "Отключить" : "Включить"}</button></div></div>`).join("") : `<div class="adv-sub">Наград пока нет</div>`;
        for (const row of box.querySelectorAll("[data-rid]")) {
            const item = d.rewards.find(x => String(x.id) === row.dataset.rid);
            row.querySelector(".adv-r-edit")?.addEventListener("click", () => editAdvReward(item));
            row.querySelector(".adv-r-toggle")?.addEventListener("click", () => toggleAdvReward(item));
        }
    } catch (e) { box.innerHTML = `<div class="adv-sub">${advEsc(e.message)}</div>`; }
}

function rewardFormData(source = null) {
    const val = id => document.getElementById(id)?.value.trim() || "";
    const untilRaw = val("adv-r-until");
    return { title: val("adv-r-title"), description: val("adv-r-desc") || null, cost: Number.parseInt(val("adv-r-cost"), 10), stock_limit: val("adv-r-stock") ? Number.parseInt(val("adv-r-stock"), 10) : null, image_url: val("adv-r-image") || null, available_until: untilRaw ? new Date(untilRaw).toISOString() : null, sort_order: source?.sort_order || 0 };
}

async function createAdvReward() {
    const payload = rewardFormData();
    if (!payload.title || !Number.isInteger(payload.cost) || payload.cost < 1) return alert("Заполните название и цену");
    const r = await fetch(`${API_ADV}/api/owner/catalog`, { method: "POST", headers: advHeaders(true), body: JSON.stringify(payload) });
    const d = await advJson(r); if (!r.ok) return alert(d.detail || "Не удалось создать награду");
    for (const id of ["adv-r-title","adv-r-desc","adv-r-cost","adv-r-stock","adv-r-image","adv-r-until"]) { const el = document.getElementById(id); if (el) el.value = ""; }
    await loadOwnerRewards();
}

async function editAdvReward(item) {
    const title = prompt("Название", item.title); if (title === null) return;
    const costRaw = prompt("Цена в лапкоинах", String(item.cost)); if (costRaw === null) return;
    const desc = prompt("Описание", item.description || ""); if (desc === null) return;
    const stockRaw = prompt("Лимит количества, пусто = без лимита", item.stock_limit == null ? "" : String(item.stock_limit)); if (stockRaw === null) return;
    const payload = { title: title.trim(), description: desc.trim() || null, cost: Number.parseInt(costRaw, 10), stock_limit: stockRaw.trim() ? Number.parseInt(stockRaw, 10) : null, image_url: item.image_url || null, available_until: item.available_until || null, sort_order: item.sort_order || 0 };
    const r = await fetch(`${API_ADV}/api/owner/catalog/${item.id}/update`, { method: "POST", headers: advHeaders(true), body: JSON.stringify(payload) }); const d = await advJson(r); if (!r.ok) return alert(d.detail || "Ошибка"); await loadOwnerRewards();
}

async function toggleAdvReward(item) {
    if (!(await advConfirm(`${item.is_active ? "Отключить" : "Включить"} награду «${item.title}»?`))) return;
    const r = await fetch(`${API_ADV}/api/owner/catalog/${item.id}/toggle`, { method: "POST", headers: advHeaders(true) }); const d = await advJson(r); if (!r.ok) return alert(d.detail || "Ошибка"); await loadOwnerRewards();
}

async function loadAdvancedRequests() {
    const box = document.getElementById("owner-spend-requests");
    if (!box || !tgAdv?.initData) return;
    try {
        const r = await fetch(`${API_ADV}/api/owner/spend-requests-advanced`, { headers: advHeaders() }); const d = await advJson(r); if (!r.ok) throw new Error(d.detail || "Ошибка заявок");
        const labels = { pending: "создана", processing: "в работе", fulfilled: "выдано", cancelled: "отменена" };
        box.innerHTML = d.requests?.length ? d.requests.map(x => `<div class="adv-row" data-qid="${x.id}"><div class="adv-row-title">#${x.id} · ${advEsc(x.reward_title)}</div><div class="adv-row-meta">${x.username ? `@${advEsc(x.username)}` : advEsc(x.first_name || x.telegram_id)} · ${x.cost} 🐾 · ${labels[x.status] || x.status}${x.comment ? `<br>Комментарий: ${advEsc(x.comment)}` : ""}</div>${x.status !== "fulfilled" && x.status !== "cancelled" ? `<div class="adv-actions"><button data-status="processing" type="button">В работу</button><button data-status="fulfilled" type="button">Выдано</button><button data-status="cancelled" class="secondary" type="button">Отменить</button></div>` : ""}</div>`).join("") : `<div class="adv-sub">Заявок пока нет</div>`;
        for (const row of box.querySelectorAll("[data-qid]")) for (const b of row.querySelectorAll("[data-status]")) b.addEventListener("click", () => changeRequestStatus(row.dataset.qid, b.dataset.status));
    } catch (e) { box.innerHTML = `<div class="adv-sub">${advEsc(e.message)}</div>`; }
}

async function changeRequestStatus(id, status) {
    const comment = prompt("Комментарий пользователю, необязательно", ""); if (comment === null) return;
    if (!(await advConfirm(`Изменить статус заявки #${id}?`))) return;
    const r = await fetch(`${API_ADV}/api/owner/spend-requests/${id}/status`, { method: "POST", headers: advHeaders(true), body: JSON.stringify({ status, comment: comment || null }) }); const d = await advJson(r); if (!r.ok) return alert(d.detail || "Ошибка"); await loadAdvancedRequests();
}

async function sendMassGrant() {
    const targets = (document.getElementById("adv-mass-targets")?.value || "").split(/[\n,;]+/).map(x => x.trim()).filter(Boolean);
    const amount = Number.parseInt(document.getElementById("adv-mass-amount")?.value || "", 10);
    const reason = document.getElementById("adv-mass-reason")?.value.trim() || null;
    const status = document.getElementById("adv-mass-status");
    if (!targets.length || !Number.isInteger(amount) || amount < 1) return;
    if (!(await advConfirm(`Начислить ${amount} 🐾 для ${targets.length} пользователей?`))) return;
    const r = await fetch(`${API_ADV}/api/owner/mass-grant`, { method: "POST", headers: advHeaders(true), body: JSON.stringify({ targets, amount, reason }) }); const d = await advJson(r); if (!r.ok) return status.textContent = d.detail || "Ошибка"; status.textContent = `Начислено: ${d.granted.length}. Не найдено: ${d.missing.length}.`;
}

async function loadOwnerEvents() {
    const box = document.getElementById("adv-owner-events"); if (!box || !tgAdv?.initData) return;
    const r = await fetch(`${API_ADV}/api/owner/events`, { headers: advHeaders() }); const d = await advJson(r); if (!r.ok) return;
    box.innerHTML = d.events?.length ? d.events.map(x => {
        const delivery = Number(x.notification_total || 0) > 0
            ? `<br>ЛС: ${Number(x.notification_sent || 0)}/${Number(x.notification_total || 0)}${Number(x.notification_failed || 0) ? ` · ошибок ${Number(x.notification_failed || 0)}` : ""}`
            : "";
        return `<div class="adv-row" data-eid="${x.id}"><div class="adv-row-title">${advEsc(x.title)} ${x.badge ? `· ${advEsc(x.badge)}` : ""}</div><div class="adv-row-meta">${x.is_active ? "включено" : "выключено"} · до ${advDate(x.ends_at)}${delivery}</div><div class="adv-actions"><button type="button">${x.is_active ? "Отключить" : "Включить"}</button></div></div>`;
    }).join("") : `<div class="adv-sub">Событий пока нет</div>`;
    for (const row of box.querySelectorAll("[data-eid]")) row.querySelector("button")?.addEventListener("click", async () => { await fetch(`${API_ADV}/api/owner/events/${row.dataset.eid}/toggle`, { method: "POST", headers: advHeaders(true) }); await loadOwnerEvents(); });
}

async function createWalletEvent() {
    const title = document.getElementById("adv-e-title")?.value.trim(); const badge = document.getElementById("adv-e-badge")?.value.trim() || null; const description = document.getElementById("adv-e-desc")?.value.trim() || null; const s = document.getElementById("adv-e-start")?.value; const e = document.getElementById("adv-e-end")?.value;
    if (!title || !s || !e) return alert("Заполните название, начало и окончание");
    const r = await fetch(`${API_ADV}/api/owner/events`, { method: "POST", headers: advHeaders(true), body: JSON.stringify({ title, badge, description, starts_at: new Date(s).toISOString(), ends_at: new Date(e).toISOString() }) }); const d = await advJson(r); if (!r.ok) return alert(d.detail || "Ошибка"); await loadOwnerEvents();
}

const economyLabels = { cashback_percent: "Кешбэк Нян Шопа, %", first_purchase_bonus: "Первая покупка, 🐾", review_bonus: "Отзыв, 🐾", activity_min: "Активности минимум, 🐾", activity_max: "Активности максимум, 🐾", referral_inviter_bonus: "Бонус пригласившему, 🐾", referral_invitee_bonus: "Бонус приглашённому, 🐾", level_regular: "Порог Постоянника, 🐾", level_vip: "Порог VIP, 🐾", level_legend: "Порог Легенды, 🐾" };

async function loadOwnerEconomy() {
    const box = document.getElementById("adv-economy-form"); if (!box || !tgAdv?.initData) return;
    const r = await fetch(`${API_ADV}/api/owner/economy`, { headers: advHeaders() }); const d = await advJson(r); if (!r.ok) return;
    box.innerHTML = Object.entries(economyLabels).map(([key,label]) => `<label><div class="adv-row-meta">${label}</div><input data-setting="${key}" type="number" value="${d.settings[key]}"></label>`).join("") + `<button id="adv-economy-save" type="button">Сохранить настройки</button><div id="adv-economy-status" class="adv-status"></div>`;
    document.getElementById("adv-economy-save")?.addEventListener("click", saveOwnerEconomy);
}

async function saveOwnerEconomy() {
    const values = {}; for (const input of document.querySelectorAll("[data-setting]")) values[input.dataset.setting] = Number.parseInt(input.value, 10);
    const r = await fetch(`${API_ADV}/api/owner/economy`, { method: "POST", headers: advHeaders(true), body: JSON.stringify({ values }) }); const d = await advJson(r); const status = document.getElementById("adv-economy-status"); if (!r.ok) return status.textContent = d.detail || "Ошибка"; status.textContent = "Настройки сохранены"; await loadEconomyUser();
}

async function checkIntegrity() {
    const status = document.getElementById("adv-integrity-status"); status.textContent = "Проверяем…";
    const r = await fetch(`${API_ADV}/api/owner/integrity`, { headers: advHeaders() }); const d = await advJson(r); if (!r.ok) return status.textContent = d.detail || "Ошибка"; status.textContent = d.healthy ? `База в порядке. Пользователей: ${d.counts.users}, операций: ${d.counts.transactions}, заявок: ${d.counts.requests}.` : `Найдены проблемы: ${d.issues.join("; ")}`;
}

async function downloadBackup() {
    try {
        const r = await fetch(`${API_ADV}/api/owner/export`, { headers: advHeaders() }); if (!r.ok) throw new Error("Не удалось создать копию"); const blob = await r.blob(); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `nyan-wallet-backup-${new Date().toISOString().slice(0,10)}.zip`; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) { alert(e.message); }
}

buildAdvUI();
setTimeout(() => {
    if (ADV_EVENT_TARGET_ID) openAdvEventDeepLink();
    else loadAdvProfile();
    loadAdvNotifications(false);
    loadEconomyUser();
}, 1500);
