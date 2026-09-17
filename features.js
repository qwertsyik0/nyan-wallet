const tgExt = window.Telegram?.WebApp;
const API_EXT = "https://nyan-wallet-api.onrender.com";

function extHeaders(json = false) {
    const headers = { "X-Telegram-Init-Data": tgExt?.initData || "" };
    if (json) headers["Content-Type"] = "application/json";
    return headers;
}

async function extJson(response) {
    try { return await response.json(); } catch (_) { return {}; }
}

async function extConfirm(text) {
    if (tgExt?.showConfirm) {
        return await new Promise((resolve) => tgExt.showConfirm(text, resolve));
    }
    return window.confirm(text);
}

function extFormatDate(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function injectFeatureStyles() {
    if (document.getElementById("nyan-feature-styles")) return;
    const style = document.createElement("style");
    style.id = "nyan-feature-styles";
    style.textContent = `
        .request-banner{margin-top:16px;padding:15px 16px;border:1px solid #efd8e2;border-radius:18px;background:#fff7fa;color:#7e4059;font-size:13px;line-height:1.45}
        .spend-action{background:#fff;border:1px solid #efd8e2}
        .feature-list{display:grid;gap:12px}
        .feature-card{background:#fff;border:1px solid #f0dce5;border-radius:20px;padding:16px;box-shadow:0 8px 24px rgba(137,41,82,.05)}
        .feature-card h3{margin:0;font-size:16px;color:#6d304a}
        .feature-card p{margin:7px 0 0;font-size:12px;line-height:1.45;color:#9d7487}
        .feature-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
        .feature-price{flex:0 0 auto;padding:7px 10px;border-radius:12px;background:#fff0f6;color:#922954;font-size:12px;font-weight:700}
        .feature-card button{margin-top:13px;padding:13px 14px;border-radius:14px;background:#922954;color:#fff}
        .feature-status{margin:0 0 14px;padding:14px 16px;border-radius:17px;background:#fff7fa;border:1px solid #efd8e2;color:#7e4059;font-size:13px;line-height:1.45}
        .feature-request-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 14px;border:1px solid #f0dce5;border-radius:16px;background:#fff}
        .feature-request-main{min-width:0}.feature-request-title{font-size:13px;font-weight:700;color:#6d304a}.feature-request-meta{margin-top:4px;font-size:11px;color:#aa8092}
        .feature-status-pill{flex:0 0 auto;padding:6px 9px;border-radius:999px;background:#fff0f6;color:#922954;font-size:11px;font-weight:700}
        .feature-status-pill.done{background:#f7f2f4;color:#806271}
        .feature-section{margin-top:14px;padding:20px;background:linear-gradient(145deg,#fff,#fff8fa);border:1px solid #efd5e1;border-radius:24px;box-shadow:0 12px 32px rgba(137,41,82,.06)}
        .feature-section-title{font-size:18px;font-weight:700;color:#7e284c}.feature-section-subtitle{margin-top:5px;margin-bottom:14px;font-size:13px;color:#a67589}
        .stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.stat-card{padding:14px;border-radius:16px;background:#fff;border:1px solid #f0dce5}.stat-value{font-size:20px;font-weight:700;color:#8f2955}.stat-label{margin-top:4px;font-size:11px;color:#aa8092}
        .owner-extra-row{padding:13px 14px;border-radius:16px;background:#fff;border:1px solid #f0dce5;margin-top:9px}.owner-extra-top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.owner-extra-title{font-size:14px;font-weight:700;color:#6d304a}.owner-extra-meta{margin-top:5px;font-size:11px;line-height:1.4;color:#aa8092}.owner-extra-actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.owner-extra-actions button{width:auto;padding:9px 11px;border-radius:11px;font-size:11px}.owner-extra-actions .danger{background:#fff;border:1px solid #dfbbc9;color:#7e4059}.owner-extra-actions .primary{background:#922954;color:#fff}
        .feature-inline-list{margin-top:8px;padding:10px 12px;border-radius:13px;background:#fff8fa;font-size:11px;line-height:1.5;color:#8a6072}
        .audit-item{padding:11px 0;border-bottom:1px solid #f3e4ea}.audit-item:last-child{border-bottom:0}.audit-title{font-size:12px;font-weight:700;color:#6d304a}.audit-meta{margin-top:4px;font-size:11px;color:#aa8092}
        @media(max-width:380px){.stats-grid{grid-template-columns:1fr}.owner-extra-actions{display:grid}.owner-extra-actions button{width:100%}}
    `;
    document.head.appendChild(style);
}

function buildFeatureUI() {
    if (document.getElementById("spend-button")) return;
    injectFeatureStyles();

    const walletView = document.getElementById("wallet-view");
    const actions = walletView?.querySelector(".actions");
    const ownerButton = document.getElementById("owner-button");
    const balanceCard = walletView?.querySelector(".balance-card");
    const app = document.querySelector(".app");

    const banner = document.createElement("div");
    banner.id = "request-banner";
    banner.className = "request-banner";
    banner.hidden = true;
    banner.textContent = "Заявка создана. Мы выдадим приз вам в ближайшее время.";
    balanceCard?.insertAdjacentElement("afterend", banner);

    const spendButton = document.createElement("button");
    spendButton.id = "spend-button";
    spendButton.className = "spend-action";
    spendButton.type = "button";
    spendButton.innerHTML = "<span>🐾</span> Потратить";
    if (ownerButton) actions?.insertBefore(spendButton, ownerButton);
    else actions?.appendChild(spendButton);

    const spendView = document.createElement("main");
    spendView.id = "spend-view";
    spendView.className = "view hidden";
    spendView.innerHTML = `
        <div class="subpage-header">
            <button id="spend-back" class="back-button" type="button" aria-label="Назад">‹</button>
            <div>
                <div class="page-title">Потратить лапкоины</div>
                <div class="page-subtitle">выберите награду и создайте заявку</div>
            </div>
        </div>
        <div id="spend-status"></div>
        <section id="reward-list" class="feature-list"></section>
        <section class="feature-section">
            <div class="feature-section-title">Ваши заявки</div>
            <div class="feature-section-subtitle">статус последних заявок на выдачу</div>
            <div id="my-spend-requests" class="feature-list"></div>
        </section>
    `;
    app?.appendChild(spendView);

    const ownerView = document.getElementById("owner-view");
    if (ownerView) {
        const header = ownerView.querySelector(".subpage-header");

        const stats = document.createElement("section");
        stats.id = "owner-stats-section";
        stats.className = "feature-section";
        stats.innerHTML = `<div class="feature-section-title">Статистика</div><div class="feature-section-subtitle">сводка Nyan Wallet</div><div id="owner-stats-grid" class="stats-grid"></div>`;
        header?.insertAdjacentElement("afterend", stats);

        const requestSection = document.createElement("section");
        requestSection.className = "feature-section";
        requestSection.innerHTML = `<div class="feature-section-title">Заявки на призы</div><div class="feature-section-subtitle">лапкоины уже списаны у пользователя</div><div id="owner-spend-requests"></div>`;
        ownerView.appendChild(requestSection);

        const promoManage = document.createElement("section");
        promoManage.className = "feature-section";
        promoManage.innerHTML = `<div class="feature-section-title">Управление промокодами</div><div class="feature-section-subtitle">включение, лимиты, активации и удаление</div><div id="owner-promo-management"></div>`;
        ownerView.appendChild(promoManage);

        const audit = document.createElement("section");
        audit.className = "feature-section";
        audit.innerHTML = `<div class="feature-section-title">Журнал действий</div><div class="feature-section-subtitle">последние действия владельца</div><div id="owner-audit-list"></div>`;
        ownerView.appendChild(audit);
    }

    spendButton.addEventListener("click", openSpendView);
    document.getElementById("spend-back")?.addEventListener("click", closeSpendView);

    document.getElementById("owner-button")?.addEventListener("click", () => {
        setTimeout(loadOwnerExtras, 50);
    });

    tgExt?.BackButton?.onClick?.(() => {
        const view = document.getElementById("spend-view");
        if (view && !view.classList.contains("hidden")) closeSpendView();
    });
}

function openSpendView() {
    for (const id of ["wallet-view", "earn-view", "owner-view"]) {
        document.getElementById(id)?.classList.add("hidden");
    }
    document.getElementById("spend-view")?.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
    tgExt?.BackButton?.show?.();
    tgExt?.HapticFeedback?.impactOccurred?.("light");
    loadSpendData();
}

function closeSpendView() {
    document.getElementById("spend-view")?.classList.add("hidden");
    document.getElementById("wallet-view")?.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
    tgExt?.BackButton?.hide?.();
}

function updatePendingBanner(requests) {
    const banner = document.getElementById("request-banner");
    if (!banner) return;
    const pending = (requests || []).find((item) => item.status === "pending");
    banner.hidden = !pending;
    if (pending) {
        banner.textContent = `Заявка #${pending.id} создана. Мы выдадим приз вам в ближайшее время.`;
    }
}

function renderMyRequests(items) {
    const box = document.getElementById("my-spend-requests");
    if (!box) return;
    box.innerHTML = "";
    if (!items?.length) {
        box.innerHTML = `<div class="feature-inline-list">Заявок пока нет</div>`;
        return;
    }
    for (const item of items) {
        const row = document.createElement("div");
        row.className = "feature-request-row";
        const done = item.status === "fulfilled";
        row.innerHTML = `
            <div class="feature-request-main">
                <div class="feature-request-title">${escapeHtml(item.reward_title)}</div>
                <div class="feature-request-meta">#${item.id} · ${item.cost} 🐾 · ${extFormatDate(item.created_at)}</div>
            </div>
            <div class="feature-status-pill ${done ? "done" : ""}">${done ? "выдано" : "в обработке"}</div>
        `;
        box.appendChild(row);
    }
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

async function loadSpendData() {
    if (!tgExt?.initData) return;
    const status = document.getElementById("spend-status");
    const list = document.getElementById("reward-list");
    if (status) status.innerHTML = "";
    if (list) list.innerHTML = `<div class="feature-inline-list">Загружаем награды…</div>`;
    try {
        const response = await fetch(`${API_EXT}/api/rewards`, { headers: extHeaders() });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить награды");
        renderRewards(data.rewards || []);
        renderMyRequests(data.requests || []);
        updatePendingBanner(data.requests || []);
    } catch (error) {
        if (status) status.innerHTML = `<div class="feature-status">${escapeHtml(error.message || "Ошибка загрузки")}</div>`;
    }
}

function renderRewards(items) {
    const list = document.getElementById("reward-list");
    if (!list) return;
    list.innerHTML = "";
    if (!items.length) {
        list.innerHTML = `<div class="feature-inline-list">Награды временно недоступны</div>`;
        return;
    }
    for (const reward of items) {
        const card = document.createElement("article");
        card.className = "feature-card";
        card.innerHTML = `
            <div class="feature-card-head">
                <div><h3>${escapeHtml(reward.title)}</h3><p>${escapeHtml(reward.description || "")}</p></div>
                <div class="feature-price">${reward.cost} 🐾</div>
            </div>
            <button type="button">Получить за ${reward.cost} 🐾</button>
        `;
        card.querySelector("button")?.addEventListener("click", () => createRewardRequest(reward));
        list.appendChild(card);
    }
}

async function createRewardRequest(reward) {
    const ok = await extConfirm(`Списать ${reward.cost} 🐾 и создать заявку на «${reward.title}»?`);
    if (!ok) return;
    const status = document.getElementById("spend-status");
    if (status) status.innerHTML = `<div class="feature-status">Создаём заявку…</div>`;
    try {
        const response = await fetch(`${API_EXT}/api/rewards/${reward.id}/request`, {
            method: "POST",
            headers: extHeaders(true),
        });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось создать заявку");
        if (status) status.innerHTML = `<div class="feature-status">Заявка создана. Мы выдадим приз вам в ближайшее время.</div>`;
        const balance = document.getElementById("balance");
        if (balance && balance.textContent !== "∞") balance.textContent = String(data.balance);
        tgExt?.HapticFeedback?.notificationOccurred?.("success");
        await loadSpendData();
    } catch (error) {
        if (status) status.innerHTML = `<div class="feature-status">${escapeHtml(error.message || "Не удалось создать заявку")}</div>`;
        tgExt?.HapticFeedback?.notificationOccurred?.("error");
    }
}

async function loadOwnerExtras() {
    await Promise.all([
        loadOwnerStats(),
        loadOwnerRequests(),
        loadPromoManagement(),
        loadOwnerAudit(),
    ]);
}

async function loadOwnerStats() {
    const grid = document.getElementById("owner-stats-grid");
    if (!grid || !tgExt?.initData) return;
    grid.innerHTML = `<div class="feature-inline-list">Загружаем…</div>`;
    try {
        const response = await fetch(`${API_EXT}/api/owner/stats`, { headers: extHeaders() });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Ошибка статистики");
        const s = data.stats;
        const items = [
            [s.total_users, "пользователей"],
            [`${s.circulation} 🐾`, "в обращении"],
            [`+${s.granted_today} 🐾`, "начислено сегодня"],
            [`${s.spent_today} 🐾`, "списано сегодня"],
            [s.promo_uses, "активаций промокодов"],
            [s.pending_requests, "заявок ждут выдачи"],
        ];
        grid.innerHTML = items.map(([value, label]) => `<div class="stat-card"><div class="stat-value">${escapeHtml(value)}</div><div class="stat-label">${escapeHtml(label)}</div></div>`).join("");
    } catch (error) {
        grid.innerHTML = `<div class="feature-inline-list">${escapeHtml(error.message)}</div>`;
    }
}

async function loadOwnerRequests() {
    const box = document.getElementById("owner-spend-requests");
    if (!box || !tgExt?.initData) return;
    box.innerHTML = `<div class="feature-inline-list">Загружаем…</div>`;
    try {
        const response = await fetch(`${API_EXT}/api/owner/spend-requests`, { headers: extHeaders() });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить заявки");
        box.innerHTML = "";
        if (!data.requests?.length) {
            box.innerHTML = `<div class="feature-inline-list">Заявок пока нет</div>`;
            return;
        }
        for (const item of data.requests) {
            const row = document.createElement("div");
            row.className = "owner-extra-row";
            const who = item.username ? `@${item.username}` : (item.first_name || `ID ${item.telegram_id}`);
            row.innerHTML = `
                <div class="owner-extra-top"><div><div class="owner-extra-title">#${item.id} · ${escapeHtml(item.reward_title)}</div><div class="owner-extra-meta">${escapeHtml(who)} · ID ${item.telegram_id} · ${item.cost} 🐾 · ${extFormatDate(item.created_at)}</div></div><div class="feature-status-pill ${item.status === "fulfilled" ? "done" : ""}">${item.status === "fulfilled" ? "выдано" : "ожидает"}</div></div>
            `;
            if (item.status === "pending") {
                const actions = document.createElement("div");
                actions.className = "owner-extra-actions";
                const button = document.createElement("button");
                button.type = "button";
                button.className = "primary";
                button.textContent = "Отметить выданным";
                button.addEventListener("click", () => completeOwnerRequest(item));
                actions.appendChild(button);
                row.appendChild(actions);
            }
            box.appendChild(row);
        }
    } catch (error) {
        box.innerHTML = `<div class="feature-inline-list">${escapeHtml(error.message)}</div>`;
    }
}

async function completeOwnerRequest(item) {
    const ok = await extConfirm(`Подтвердить выдачу «${item.reward_title}» пользователю?`);
    if (!ok) return;
    try {
        const response = await fetch(`${API_EXT}/api/owner/spend-requests/${item.id}/complete`, {
            method: "POST",
            headers: extHeaders(true),
        });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось завершить заявку");
        tgExt?.HapticFeedback?.notificationOccurred?.("success");
        await Promise.all([loadOwnerRequests(), loadOwnerStats(), loadOwnerAudit()]);
    } catch (error) {
        alert(error.message || "Не удалось завершить заявку");
    }
}

async function loadPromoManagement() {
    const box = document.getElementById("owner-promo-management");
    if (!box || !tgExt?.initData) return;
    box.innerHTML = `<div class="feature-inline-list">Загружаем…</div>`;
    try {
        const response = await fetch(`${API_EXT}/api/owner/promos`, { headers: extHeaders() });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить промокоды");
        box.innerHTML = "";
        if (!data.promos?.length) {
            box.innerHTML = `<div class="feature-inline-list">Промокодов пока нет</div>`;
            return;
        }
        for (const promo of data.promos) {
            const row = document.createElement("div");
            row.className = "owner-extra-row";
            const limit = promo.max_uses == null ? "без лимита" : `${promo.uses_count}/${promo.max_uses}`;
            row.innerHTML = `
                <div class="owner-extra-top"><div><div class="owner-extra-title">${escapeHtml(promo.code)}</div><div class="owner-extra-meta">+${promo.reward_amount} 🐾 · ${limit}${promo.expires_at ? ` · до ${extFormatDate(promo.expires_at)}` : ""}</div></div><div class="feature-status-pill ${promo.is_active ? "" : "done"}">${promo.is_active ? "активен" : "выключен"}</div></div>
                <div class="owner-extra-actions"></div>
                <div class="feature-inline-list" hidden></div>
            `;
            const actions = row.querySelector(".owner-extra-actions");
            const toggle = makeSmallButton(promo.is_active ? "Отключить" : "Включить", "", () => togglePromo(promo));
            const limitButton = makeSmallButton("Лимит", "", () => changePromoLimit(promo));
            const usersButton = makeSmallButton("Активации", "", () => showPromoRedemptions(promo, row));
            const del = makeSmallButton("Удалить", "danger", () => deletePromo(promo));
            actions.append(toggle, limitButton, usersButton, del);
            box.appendChild(row);
        }
    } catch (error) {
        box.innerHTML = `<div class="feature-inline-list">${escapeHtml(error.message)}</div>`;
    }
}

function makeSmallButton(text, className, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    if (className) button.className = className;
    button.addEventListener("click", handler);
    return button;
}

async function togglePromo(promo) {
    const ok = await extConfirm(`${promo.is_active ? "Отключить" : "Включить"} промокод ${promo.code}?`);
    if (!ok) return;
    await promoAction(`/api/owner/promos/${promo.id}/toggle`, null);
}

async function changePromoLimit(promo) {
    const current = promo.max_uses == null ? "" : String(promo.max_uses);
    const raw = prompt("Новый лимит активаций. Оставьте пустым, чтобы убрать лимит.", current);
    if (raw === null) return;
    const trimmed = raw.trim();
    let maxUses = null;
    if (trimmed) {
        maxUses = Number.parseInt(trimmed, 10);
        if (!Number.isInteger(maxUses) || maxUses < 1 || maxUses > 1000000) {
            alert("Лимит должен быть от 1 до 1 000 000.");
            return;
        }
    }
    await promoAction(`/api/owner/promos/${promo.id}/limit`, { max_uses: maxUses });
}

async function showPromoRedemptions(promo, row) {
    const details = row.querySelector(".feature-inline-list");
    details.hidden = false;
    details.textContent = "Загружаем активации…";
    try {
        const response = await fetch(`${API_EXT}/api/owner/promos/${promo.id}/redemptions`, { headers: extHeaders() });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Ошибка загрузки");
        if (!data.items?.length) {
            details.textContent = "Активаций пока нет";
            return;
        }
        details.innerHTML = data.items.map((item) => {
            const who = item.username ? `@${item.username}` : (item.first_name || `ID ${item.telegram_id}`);
            return `${escapeHtml(who)} · ID ${item.telegram_id} · +${item.reward_amount} 🐾 · ${extFormatDate(item.created_at)}`;
        }).join("<br>");
    } catch (error) {
        details.textContent = error.message || "Ошибка загрузки";
    }
}

async function deletePromo(promo) {
    const ok = await extConfirm(`Удалить промокод ${promo.code}? Это действие нельзя отменить.`);
    if (!ok) return;
    await promoAction(`/api/owner/promos/${promo.id}/delete`, null);
}

async function promoAction(path, body) {
    try {
        const response = await fetch(`${API_EXT}${path}`, {
            method: "POST",
            headers: extHeaders(true),
            body: body === null ? undefined : JSON.stringify(body),
        });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Операция не выполнена");
        tgExt?.HapticFeedback?.notificationOccurred?.("success");
        await Promise.all([loadPromoManagement(), loadOwnerAudit()]);
    } catch (error) {
        alert(error.message || "Операция не выполнена");
    }
}

async function loadOwnerAudit() {
    const box = document.getElementById("owner-audit-list");
    if (!box || !tgExt?.initData) return;
    box.innerHTML = `<div class="feature-inline-list">Загружаем…</div>`;
    try {
        const response = await fetch(`${API_EXT}/api/owner/audit`, { headers: extHeaders() });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить журнал");
        box.innerHTML = "";
        if (!data.items?.length) {
            box.innerHTML = `<div class="feature-inline-list">Действий пока нет</div>`;
            return;
        }
        const labels = {
            owner_grant: "Начисление",
            owner_debit: "Списание",
            promo_created: "Создан промокод",
            promo_toggled: "Изменён статус промокода",
            promo_limit_changed: "Изменён лимит промокода",
            promo_deleted: "Удалён промокод",
            reward_fulfilled: "Выдан приз",
        };
        for (const item of data.items.slice(0, 40)) {
            const row = document.createElement("div");
            row.className = "audit-item";
            row.innerHTML = `<div class="audit-title">${escapeHtml(labels[item.action] || item.action)}</div><div class="audit-meta">${escapeHtml(item.details || "")}${item.target_telegram_id ? ` · ID ${item.target_telegram_id}` : ""} · ${extFormatDate(item.created_at)}</div>`;
            box.appendChild(row);
        }
    } catch (error) {
        box.innerHTML = `<div class="feature-inline-list">${escapeHtml(error.message)}</div>`;
    }
}

function selectedUserIdFromDom() {
    const text = document.getElementById("selected-user-meta")?.textContent || "";
    const match = text.match(/Telegram ID\s+(\d+)/i);
    return match ? match[1] : null;
}

async function performOwnerAdjustment(action) {
    const id = selectedUserIdFromDom();
    const amountInput = document.getElementById("owner-amount");
    const reasonInput = document.getElementById("owner-reason");
    const status = document.getElementById("owner-status");
    const grant = document.getElementById("owner-grant");
    const debit = document.getElementById("owner-debit");
    if (!id) {
        if (status) status.textContent = "Сначала выберите пользователя.";
        return;
    }
    const amount = Number.parseInt(amountInput?.value || "", 10);
    const reason = reasonInput?.value.trim() || "";
    if (!Number.isInteger(amount) || amount < 1 || amount > 10000000) {
        if (status) status.textContent = "Укажите количество от 1 до 10 000 000.";
        amountInput?.focus();
        return;
    }
    if (action === "debit" || amount >= 1000) {
        const ok = await extConfirm(`${action === "debit" ? "Списать" : "Начислить"} ${amount} 🐾 пользователю ID ${id}?`);
        if (!ok) return;
    }
    if (grant) grant.disabled = true;
    if (debit) debit.disabled = true;
    if (status) status.textContent = action === "grant" ? "Начисляем…" : "Списываем…";
    try {
        const response = await fetch(`${API_EXT}/api/owner/action/${action}`, {
            method: "POST",
            headers: extHeaders(true),
            body: JSON.stringify({ target: id, amount, reason: reason || null }),
        });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Операция не выполнена");
        const result = action === "grant" ? data.grant : data.debit;
        if (status) status.textContent = action === "grant"
            ? `Начислено +${result.amount} 🐾. Баланс: ${result.balance} 🐾`
            : `Списано ${result.amount} 🐾. Баланс: ${result.balance} 🐾`;
        if (amountInput) amountInput.value = "";
        if (reasonInput) reasonInput.value = "";
        document.getElementById("selected-user-balance").textContent = `${result.balance} 🐾`;
        tgExt?.HapticFeedback?.notificationOccurred?.("success");
        document.querySelector(`.owner-user-row[data-user-id="${id}"]`)?.click();
        document.getElementById("owner-user-search-button")?.click();
        await Promise.all([loadOwnerStats(), loadOwnerAudit()]);
    } catch (error) {
        if (status) status.textContent = error.message || "Операция не выполнена";
        tgExt?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
        if (grant) grant.disabled = false;
        if (debit) debit.disabled = false;
    }
}

async function performPromoCreate() {
    const codeInput = document.getElementById("owner-promo-code");
    const rewardInput = document.getElementById("owner-promo-reward");
    const limitInput = document.getElementById("owner-promo-limit");
    const expiresInput = document.getElementById("owner-promo-expires");
    const descriptionInput = document.getElementById("owner-promo-description");
    const status = document.getElementById("owner-promo-status");
    const button = document.getElementById("owner-promo-create");

    const code = codeInput?.value.trim().toUpperCase() || "";
    const rewardAmount = Number.parseInt(rewardInput?.value || "", 10);
    const limitRaw = limitInput?.value.trim() || "";
    const maxUses = limitRaw ? Number.parseInt(limitRaw, 10) : null;
    const expiresRaw = expiresInput?.value || "";
    const description = descriptionInput?.value.trim() || "";

    if (!/^[A-Z0-9_-]{2,32}$/.test(code)) {
        if (status) status.textContent = "Код: 2–32 символа, латиница, цифры, _ или -.";
        return;
    }
    if (!Number.isInteger(rewardAmount) || rewardAmount < 1 || rewardAmount > 10000000) {
        if (status) status.textContent = "Укажите награду от 1 до 10 000 000 🐾.";
        return;
    }
    let expiresAt = null;
    if (expiresRaw) {
        const date = new Date(expiresRaw);
        if (Number.isNaN(date.getTime()) || date.getTime() <= Date.now()) {
            if (status) status.textContent = "Укажите будущую дату окончания.";
            return;
        }
        expiresAt = date.toISOString();
    }
    if (button) button.disabled = true;
    if (status) status.textContent = "Создаём…";
    try {
        const response = await fetch(`${API_EXT}/api/owner/manage/promos`, {
            method: "POST",
            headers: extHeaders(true),
            body: JSON.stringify({ code, reward_amount: rewardAmount, max_uses: maxUses, expires_at: expiresAt, description: description || null }),
        });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось создать промокод");
        if (status) status.textContent = `Промокод ${data.promo.code} создан: +${data.promo.reward_amount} 🐾`;
        for (const input of [codeInput, rewardInput, limitInput, expiresInput, descriptionInput]) if (input) input.value = "";
        tgExt?.HapticFeedback?.notificationOccurred?.("success");
        await Promise.all([loadPromoManagement(), loadOwnerAudit()]);
    } catch (error) {
        if (status) status.textContent = error.message || "Не удалось создать промокод";
    } finally {
        if (button) button.disabled = false;
    }
}

async function performPromoRedeem() {
    const input = document.getElementById("promo-code");
    const button = document.getElementById("promo-activate");
    const status = document.getElementById("promo-status");
    const code = input?.value.trim() || "";
    if (!code) {
        if (status) status.textContent = "Введите промокод.";
        return;
    }
    if (button) {
        button.disabled = true;
        button.textContent = "Проверяем…";
    }
    if (status) status.textContent = "";
    try {
        const response = await fetch(`${API_EXT}/api/promo/redeem-notify`, {
            method: "POST",
            headers: extHeaders(true),
            body: JSON.stringify({ code }),
        });
        const data = await extJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось активировать промокод");
        if (input) input.value = "";
        if (status) status.textContent = `Готово: +${data.reward} 🐾. Баланс: ${data.balance} 🐾`;
        const balance = document.getElementById("balance");
        if (balance && balance.textContent !== "∞") balance.textContent = String(data.balance);
        tgExt?.HapticFeedback?.notificationOccurred?.("success");
    } catch (error) {
        if (status) status.textContent = error.message || "Не удалось активировать промокод";
        tgExt?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "Активировать";
        }
    }
}

document.addEventListener("click", (event) => {
    const grant = event.target.closest?.("#owner-grant");
    const debit = event.target.closest?.("#owner-debit");
    const promoCreate = event.target.closest?.("#owner-promo-create");
    const promoActivate = event.target.closest?.("#promo-activate");
    if (!grant && !debit && !promoCreate && !promoActivate) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    if (grant) void performOwnerAdjustment("grant");
    else if (debit) void performOwnerAdjustment("debit");
    else if (promoCreate) void performPromoCreate();
    else if (promoActivate) void performPromoRedeem();
}, true);

document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.target?.id !== "promo-code") return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    void performPromoRedeem();
}, true);

buildFeatureUI();

setTimeout(() => {
    if (tgExt?.initData) loadSpendData();
}, 1200);
