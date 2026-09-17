const tg = window.Telegram?.WebApp;
const API_BASE = "https://nyan-wallet-api.onrender.com";

if (tg) {
    tg.ready();
    tg.expand();
}

const loadingView = document.getElementById("loading-view");
const usernameEl = document.getElementById("username");
const balanceEl = document.getElementById("balance");
const currencyNameEl = document.getElementById("currency-name");
const walletCardEl = document.getElementById("wallet-card");
const walletNumberEl = document.getElementById("wallet-number");
const walletStatusEl = document.getElementById("wallet-status");
const walletHolderEl = document.getElementById("wallet-holder");
const historyEl = document.querySelector(".history");
const walletView = document.getElementById("wallet-view");
const earnView = document.getElementById("earn-view");
const ownerView = document.getElementById("owner-view");
const earnButton = document.getElementById("earn-button");
const earnBack = document.getElementById("earn-back");
const ownerButton = document.getElementById("owner-button");
const ownerBack = document.getElementById("owner-back");
const promoCode = document.getElementById("promo-code");
const promoActivate = document.getElementById("promo-activate");
const promoStatus = document.getElementById("promo-status");

const ownerUserSearch = document.getElementById("owner-user-search");
const ownerUserSearchButton = document.getElementById("owner-user-search-button");
const ownerUsersStatus = document.getElementById("owner-users-status");
const ownerUsersList = document.getElementById("owner-users-list");
const ownerUserCard = document.getElementById("owner-user-card");
const selectedUserName = document.getElementById("selected-user-name");
const selectedUserMeta = document.getElementById("selected-user-meta");
const selectedUserBalance = document.getElementById("selected-user-balance");
const ownerAmount = document.getElementById("owner-amount");
const ownerReason = document.getElementById("owner-reason");
const ownerGrant = document.getElementById("owner-grant");
const ownerDebit = document.getElementById("owner-debit");
const ownerStatus = document.getElementById("owner-status");
const ownerUserHistory = document.getElementById("owner-user-history");

const ownerPromoCode = document.getElementById("owner-promo-code");
const ownerPromoReward = document.getElementById("owner-promo-reward");
const ownerPromoLimit = document.getElementById("owner-promo-limit");
const ownerPromoExpires = document.getElementById("owner-promo-expires");
const ownerPromoDescription = document.getElementById("owner-promo-description");
const ownerPromoCreate = document.getElementById("owner-promo-create");
const ownerPromoStatus = document.getElementById("owner-promo-status");
const ownerPromoList = document.getElementById("owner-promo-list");

let currentUser = null;
let selectedOwnerUserId = null;
let initialLoadFinished = false;

const unsafeUser = tg?.initDataUnsafe?.user;
if (unsafeUser) {
    usernameEl.textContent = unsafeUser.first_name || unsafeUser.username || "пользователь";
    if (walletNumberEl) walletNumberEl.textContent = createWalletNumber(unsafeUser.id);
    if (walletHolderEl) walletHolderEl.textContent = walletHolderName(unsafeUser);
}

function createWalletNumber(telegramId) {
    const input = `nyan-wallet:${telegramId || "guest"}`;
    let left = 0x811c9dc5;
    let right = 0x9e3779b9;

    for (let index = 0; index < input.length; index += 1) {
        const code = input.charCodeAt(index);
        left = Math.imul(left ^ code, 16777619) >>> 0;
        right = Math.imul(right ^ code, 2246822519) >>> 0;
    }

    const digits = `${String(left % 1000000).padStart(6, "0")}${String(right % 1000000).padStart(6, "0")}`;
    return `NYAN ${digits.slice(0, 4)} ${digits.slice(4, 8)} ${digits.slice(8, 12)}`;
}

function walletHolderName(user) {
    const fullName = [user?.first_name, user?.last_name].filter(Boolean).join(" ").trim();
    if (fullName) return fullName;
    if (user?.username) return `@${user.username}`;
    return "пользователь";
}

function authHeaders(json = false) {
    const headers = {
        "X-Telegram-Init-Data": tg?.initData || "",
    };
    if (json) headers["Content-Type"] = "application/json";
    return headers;
}

async function readJson(response) {
    try {
        return await response.json();
    } catch (_) {
        return {};
    }
}

function finishInitialLoad() {
    if (initialLoadFinished) return;
    initialLoadFinished = true;
    loadingView?.classList.add("hidden");
    walletView.classList.remove("hidden");
}

function showWalletView() {
    loadingView?.classList.add("hidden");
    earnView.classList.add("hidden");
    ownerView.classList.add("hidden");
    walletView.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });

    if (tg?.BackButton) tg.BackButton.hide();
}

function openEarnView() {
    walletView.classList.add("hidden");
    ownerView.classList.add("hidden");
    earnView.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });

    if (tg?.BackButton) tg.BackButton.show();
    tg?.HapticFeedback?.impactOccurred?.("light");
}

function openOwnerView() {
    if (!currentUser?.is_owner) return;

    walletView.classList.add("hidden");
    earnView.classList.add("hidden");
    ownerView.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });

    if (tg?.BackButton) tg.BackButton.show();
    tg?.HapticFeedback?.impactOccurred?.("light");

    loadOwnerUsers();
    loadOwnerPromos();
}

earnButton?.addEventListener("click", openEarnView);
earnBack?.addEventListener("click", showWalletView);
ownerButton?.addEventListener("click", openOwnerView);
ownerBack?.addEventListener("click", showWalletView);

if (tg?.BackButton?.onClick) {
    tg.BackButton.onClick(() => {
        if (!earnView.classList.contains("hidden") || !ownerView.classList.contains("hidden")) {
            showWalletView();
        }
    });
}

async function activatePromo() {
    const code = promoCode.value.trim();

    if (!code) {
        promoStatus.textContent = "Введите промокод.";
        promoCode.focus();
        return;
    }

    if (!tg?.initData) {
        promoStatus.textContent = "Откройте кошелёк через Telegram.";
        return;
    }

    promoActivate.disabled = true;
    promoActivate.textContent = "Проверяем…";
    promoStatus.textContent = "";

    try {
        const response = await fetch(`${API_BASE}/api/promo/redeem`, {
            method: "POST",
            headers: authHeaders(true),
            body: JSON.stringify({ code }),
        });
        const data = await readJson(response);

        if (!response.ok) throw new Error(data?.detail || "Не удалось активировать промокод");

        if (!currentUser?.unlimited_balance) {
            balanceEl.textContent = data.balance ?? balanceEl.textContent;
        }

        promoCode.value = "";
        promoStatus.textContent = currentUser?.unlimited_balance
            ? `Готово: +${data.reward} 🐾`
            : `Готово: +${data.reward} 🐾. Баланс: ${data.balance} 🐾`;
        tg?.HapticFeedback?.notificationOccurred?.("success");
        await loadWallet();
    } catch (error) {
        promoStatus.textContent = error.message || "Не удалось активировать промокод";
        tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
        promoActivate.disabled = false;
        promoActivate.textContent = "Активировать";
    }
}

promoActivate?.addEventListener("click", activatePromo);
promoCode?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") activatePromo();
});
promoCode?.addEventListener("input", () => {
    promoStatus.textContent = "";
});

function formatDate(value) {
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

function operationLabel(type) {
    const labels = {
        promo: "Промокод",
        owner_grant: "Начисление",
        owner_debit: "Списание",
    };
    return labels[type] || "Операция";
}

function createTransactionRow(tx, compact = false) {
    const row = document.createElement("div");
    row.className = compact ? "transaction-row compact" : "transaction-row";

    const info = document.createElement("div");
    info.className = "transaction-info";

    const text = document.createElement("div");
    text.className = "transaction-text";
    text.textContent = tx.description || operationLabel(tx.operation_type);

    const meta = document.createElement("div");
    meta.className = "transaction-meta";
    const parts = [operationLabel(tx.operation_type), formatDate(tx.created_at)].filter(Boolean);
    meta.textContent = parts.join(" · ");

    const amount = document.createElement("div");
    amount.className = `transaction-amount ${tx.amount < 0 ? "negative" : "positive"}`;
    amount.textContent = `${tx.amount > 0 ? "+" : ""}${tx.amount} 🐾`;

    info.appendChild(text);
    info.appendChild(meta);
    row.appendChild(info);
    row.appendChild(amount);
    return row;
}

function renderTransactions(items) {
    const old = document.querySelector(".history .empty");
    if (old) old.remove();

    let list = document.querySelector(".transactions-list");
    if (!list) {
        list = document.createElement("div");
        list.className = "transactions-list";
        historyEl.appendChild(list);
    }

    list.innerHTML = "";

    if (!items || items.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Здесь появится история ваших операций";
        historyEl.appendChild(empty);
        return;
    }

    for (const tx of items) list.appendChild(createTransactionRow(tx));
}

function displayUserName(user) {
    if (user.username) return `@${user.username}`;
    const fullName = [user.first_name, user.last_name].filter(Boolean).join(" ").trim();
    return fullName || `ID ${user.telegram_id}`;
}

async function loadOwnerUsers(query = ownerUserSearch?.value.trim() || "") {
    if (!currentUser?.is_owner || !tg?.initData) return;

    ownerUsersStatus.textContent = "Загружаем…";
    ownerUsersList.innerHTML = "";

    try {
        const response = await fetch(`${API_BASE}/api/owner/users?q=${encodeURIComponent(query)}`, {
            headers: authHeaders(),
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить пользователей");

        ownerUsersStatus.textContent = data.users.length ? `Найдено: ${data.users.length}` : "Ничего не найдено";

        for (const user of data.users) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "owner-user-row";
            button.dataset.userId = String(user.telegram_id);

            const left = document.createElement("div");
            left.className = "owner-user-row-main";

            const name = document.createElement("div");
            name.className = "owner-user-row-name";
            name.textContent = displayUserName(user);

            const meta = document.createElement("div");
            meta.className = "owner-user-row-meta";
            meta.textContent = `ID ${user.telegram_id} · ${formatDate(user.last_seen_at) || "нет активности"}`;

            const balance = document.createElement("div");
            balance.className = "owner-user-row-balance";
            balance.textContent = user.unlimited_balance ? "∞ 🐾" : `${user.balance} 🐾`;

            left.appendChild(name);
            left.appendChild(meta);
            button.appendChild(left);
            button.appendChild(balance);
            button.addEventListener("click", () => selectOwnerUser(user.telegram_id));
            ownerUsersList.appendChild(button);
        }
    } catch (error) {
        ownerUsersStatus.textContent = error.message || "Не удалось загрузить пользователей";
    }
}

async function selectOwnerUser(telegramId) {
    if (!currentUser?.is_owner || !tg?.initData) return;

    ownerStatus.textContent = "";
    ownerUserHistory.innerHTML = "";

    try {
        const response = await fetch(`${API_BASE}/api/owner/users/${telegramId}`, {
            headers: authHeaders(),
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось открыть пользователя");

        const user = data.user;
        selectedOwnerUserId = user.telegram_id;
        selectedUserName.textContent = displayUserName(user);
        selectedUserMeta.textContent = `Telegram ID ${user.telegram_id}${user.last_seen_at ? ` · был в кошельке ${formatDate(user.last_seen_at)}` : ""}`;
        selectedUserBalance.textContent = user.unlimited_balance ? "∞ 🐾" : `${user.balance} 🐾`;
        ownerUserCard.hidden = false;

        if (!data.transactions.length) {
            const empty = document.createElement("div");
            empty.className = "admin-empty";
            empty.textContent = "Операций пока нет";
            ownerUserHistory.appendChild(empty);
        } else {
            for (const tx of data.transactions) {
                ownerUserHistory.appendChild(createTransactionRow(tx, true));
            }
        }

        ownerUserCard.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
        ownerStatus.textContent = error.message || "Не удалось открыть пользователя";
    }
}

ownerUserSearchButton?.addEventListener("click", () => loadOwnerUsers());
ownerUserSearch?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadOwnerUsers();
});

async function adjustSelectedUser(action) {
    if (!selectedOwnerUserId) {
        ownerStatus.textContent = "Сначала выберите пользователя.";
        return;
    }

    const amount = Number.parseInt(ownerAmount.value, 10);
    const reason = ownerReason.value.trim();

    if (!Number.isInteger(amount) || amount < 1 || amount > 10000000) {
        ownerStatus.textContent = "Укажите количество от 1 до 10 000 000.";
        ownerAmount.focus();
        return;
    }

    ownerGrant.disabled = true;
    ownerDebit.disabled = true;
    ownerStatus.textContent = action === "grant" ? "Начисляем…" : "Списываем…";

    try {
        const response = await fetch(`${API_BASE}/api/owner/${action}`, {
            method: "POST",
            headers: authHeaders(true),
            body: JSON.stringify({
                target: String(selectedOwnerUserId),
                amount,
                reason: reason || null,
            }),
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Операция не выполнена");

        const result = action === "grant" ? data.grant : data.debit;
        ownerStatus.textContent = action === "grant"
            ? `Начислено +${result.amount} 🐾. Баланс: ${result.balance} 🐾`
            : `Списано ${result.amount} 🐾. Баланс: ${result.balance} 🐾`;

        ownerAmount.value = "";
        ownerReason.value = "";
        tg?.HapticFeedback?.notificationOccurred?.("success");

        await selectOwnerUser(selectedOwnerUserId);
        await loadOwnerUsers();
    } catch (error) {
        ownerStatus.textContent = error.message || "Операция не выполнена";
        tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
        ownerGrant.disabled = false;
        ownerDebit.disabled = false;
    }
}

ownerGrant?.addEventListener("click", () => adjustSelectedUser("grant"));
ownerDebit?.addEventListener("click", () => adjustSelectedUser("debit"));

for (const input of [ownerAmount, ownerReason]) {
    input?.addEventListener("input", () => {
        ownerStatus.textContent = "";
    });
}

function renderPromoList(items) {
    ownerPromoList.innerHTML = "";

    if (!items || !items.length) {
        const empty = document.createElement("div");
        empty.className = "admin-empty";
        empty.textContent = "Промокодов пока нет";
        ownerPromoList.appendChild(empty);
        return;
    }

    for (const promo of items) {
        const row = document.createElement("div");
        row.className = "owner-promo-row";

        const main = document.createElement("div");
        main.className = "owner-promo-main";

        const code = document.createElement("div");
        code.className = "owner-promo-code";
        code.textContent = promo.code;

        const meta = document.createElement("div");
        meta.className = "owner-promo-meta";
        const limit = promo.max_uses == null ? "без лимита" : `${promo.uses_count}/${promo.max_uses}`;
        const expiry = promo.expires_at ? ` · до ${formatDate(promo.expires_at)}` : "";
        meta.textContent = `${promo.uses_count} активаций · ${limit}${expiry}`;

        const reward = document.createElement("div");
        reward.className = "owner-promo-reward";
        reward.textContent = `+${promo.reward_amount} 🐾`;

        main.appendChild(code);
        main.appendChild(meta);
        row.appendChild(main);
        row.appendChild(reward);
        ownerPromoList.appendChild(row);
    }
}

async function loadOwnerPromos() {
    if (!currentUser?.is_owner || !tg?.initData) return;

    try {
        const response = await fetch(`${API_BASE}/api/owner/promos`, {
            headers: authHeaders(),
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить промокоды");
        renderPromoList(data.promos || []);
    } catch (error) {
        ownerPromoStatus.textContent = error.message || "Не удалось загрузить промокоды";
    }
}

async function createOwnerPromo() {
    const code = ownerPromoCode.value.trim().toUpperCase();
    const rewardAmount = Number.parseInt(ownerPromoReward.value, 10);
    const limitRaw = ownerPromoLimit.value.trim();
    const maxUses = limitRaw ? Number.parseInt(limitRaw, 10) : null;
    const expiresRaw = ownerPromoExpires.value;
    const description = ownerPromoDescription.value.trim();

    if (!/^[A-Z0-9_-]{2,32}$/.test(code)) {
        ownerPromoStatus.textContent = "Код: 2–32 символа, латиница, цифры, _ или -.";
        ownerPromoCode.focus();
        return;
    }

    if (!Number.isInteger(rewardAmount) || rewardAmount < 1 || rewardAmount > 10000000) {
        ownerPromoStatus.textContent = "Укажите награду от 1 до 10 000 000 🐾.";
        ownerPromoReward.focus();
        return;
    }

    if (maxUses !== null && (!Number.isInteger(maxUses) || maxUses < 1 || maxUses > 1000000)) {
        ownerPromoStatus.textContent = "Лимит активаций должен быть от 1 до 1 000 000.";
        ownerPromoLimit.focus();
        return;
    }

    let expiresAt = null;
    if (expiresRaw) {
        const date = new Date(expiresRaw);
        if (Number.isNaN(date.getTime()) || date.getTime() <= Date.now()) {
            ownerPromoStatus.textContent = "Укажите будущую дату окончания.";
            ownerPromoExpires.focus();
            return;
        }
        expiresAt = date.toISOString();
    }

    ownerPromoCreate.disabled = true;
    ownerPromoCreate.textContent = "Создаём…";
    ownerPromoStatus.textContent = "";

    try {
        const response = await fetch(`${API_BASE}/api/owner/promos`, {
            method: "POST",
            headers: authHeaders(true),
            body: JSON.stringify({
                code,
                reward_amount: rewardAmount,
                max_uses: maxUses,
                expires_at: expiresAt,
                description: description || null,
            }),
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось создать промокод");

        ownerPromoStatus.textContent = `Промокод ${data.promo.code} создан: +${data.promo.reward_amount} 🐾`;
        ownerPromoCode.value = "";
        ownerPromoReward.value = "";
        ownerPromoLimit.value = "";
        ownerPromoExpires.value = "";
        ownerPromoDescription.value = "";
        tg?.HapticFeedback?.notificationOccurred?.("success");
        await loadOwnerPromos();
    } catch (error) {
        ownerPromoStatus.textContent = error.message || "Не удалось создать промокод";
        tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
        ownerPromoCreate.disabled = false;
        ownerPromoCreate.textContent = "Создать промокод";
    }
}

ownerPromoCreate?.addEventListener("click", createOwnerPromo);

for (const input of [ownerPromoCode, ownerPromoReward, ownerPromoLimit, ownerPromoExpires, ownerPromoDescription]) {
    input?.addEventListener("input", () => {
        ownerPromoStatus.textContent = "";
    });
}

function applyUserState(user) {
    currentUser = user;
    usernameEl.textContent = user.first_name || user.username || "пользователь";
    if (walletNumberEl) walletNumberEl.textContent = createWalletNumber(user.telegram_id);
    if (walletHolderEl) walletHolderEl.textContent = walletHolderName(user);
    if (walletStatusEl) walletStatusEl.textContent = user.is_owner ? "Владелец" : "Участник Нян";
    walletCardEl?.classList.toggle("is-owner", Boolean(user.is_owner));

    if (user.unlimited_balance) {
        balanceEl.textContent = "∞";
        currencyNameEl.textContent = "лапкоинов · владелец";
        ownerButton.hidden = false;
    } else {
        balanceEl.textContent = user.balance ?? 0;
        currencyNameEl.textContent = "лапкоинов";
        ownerButton.hidden = true;
    }
}

async function loadWallet() {
    if (!tg?.initData) {
        balanceEl.textContent = "0";
        finishInitialLoad();
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/me`, {
            headers: authHeaders(),
        });
        const data = await readJson(response);

        if (!response.ok) throw new Error(data?.detail || "Ошибка загрузки кошелька");

        applyUserState(data.user);
        renderTransactions(data.transactions || []);
    } catch (error) {
        console.error("Nyan Wallet API error:", error);
        balanceEl.textContent = "0";
    } finally {
        finishInitialLoad();
    }
}

loadWallet();
