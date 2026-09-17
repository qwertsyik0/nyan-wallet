const tg = window.Telegram?.WebApp;
const API_BASE = "https://nyan-wallet-api.onrender.com";

if (tg) {
    tg.ready();
    tg.expand();
}

const usernameEl = document.getElementById("username");
const balanceEl = document.getElementById("balance");
const currencyNameEl = document.getElementById("currency-name");
const historyEl = document.querySelector(".history");
const walletView = document.getElementById("wallet-view");
const earnView = document.getElementById("earn-view");
const earnButton = document.getElementById("earn-button");
const earnBack = document.getElementById("earn-back");
const promoCode = document.getElementById("promo-code");
const promoActivate = document.getElementById("promo-activate");
const promoStatus = document.getElementById("promo-status");
const ownerPanel = document.getElementById("owner-panel");
const ownerTarget = document.getElementById("owner-target");
const ownerAmount = document.getElementById("owner-amount");
const ownerReason = document.getElementById("owner-reason");
const ownerGrant = document.getElementById("owner-grant");
const ownerStatus = document.getElementById("owner-status");

let currentUser = null;

const unsafeUser = tg?.initDataUnsafe?.user;
if (unsafeUser) {
    usernameEl.textContent = unsafeUser.first_name || unsafeUser.username || "пользователь";
}

function openEarnView() {
    walletView.classList.add("hidden");
    earnView.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });

    if (tg?.BackButton) {
        tg.BackButton.show();
    }

    tg?.HapticFeedback?.impactOccurred?.("light");
}

function closeEarnView() {
    earnView.classList.add("hidden");
    walletView.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });

    if (tg?.BackButton) {
        tg.BackButton.hide();
    }
}

earnButton?.addEventListener("click", openEarnView);
earnBack?.addEventListener("click", closeEarnView);

if (tg?.BackButton?.onClick) {
    tg.BackButton.onClick(() => {
        if (!earnView.classList.contains("hidden")) {
            closeEarnView();
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
            headers: {
                "Content-Type": "application/json",
                "X-Telegram-Init-Data": tg.initData,
            },
            body: JSON.stringify({ code }),
        });

        let data = {};
        try {
            data = await response.json();
        } catch (_) {
            data = {};
        }

        if (!response.ok) {
            throw new Error(data?.detail || "Не удалось активировать промокод");
        }

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
    if (event.key === "Enter") {
        activatePromo();
    }
});

promoCode?.addEventListener("input", () => {
    promoStatus.textContent = "";
});

async function grantLapcoins() {
    const target = ownerTarget.value.trim();
    const amount = Number.parseInt(ownerAmount.value, 10);
    const reason = ownerReason.value.trim();

    if (!target) {
        ownerStatus.textContent = "Укажите @username или Telegram ID.";
        ownerTarget.focus();
        return;
    }

    if (!Number.isInteger(amount) || amount < 1 || amount > 10000000) {
        ownerStatus.textContent = "Укажите количество от 1 до 10 000 000.";
        ownerAmount.focus();
        return;
    }

    if (!tg?.initData) {
        ownerStatus.textContent = "Откройте кошелёк через Telegram.";
        return;
    }

    ownerGrant.disabled = true;
    ownerGrant.textContent = "Начисляем…";
    ownerStatus.textContent = "";

    try {
        const response = await fetch(`${API_BASE}/api/owner/grant`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Telegram-Init-Data": tg.initData,
            },
            body: JSON.stringify({
                target,
                amount,
                reason: reason || null,
            }),
        });

        let data = {};
        try {
            data = await response.json();
        } catch (_) {
            data = {};
        }

        if (!response.ok) {
            throw new Error(data?.detail || "Не удалось начислить лапкоины");
        }

        const grant = data.grant;
        const recipient = grant.username
            ? `@${grant.username}`
            : grant.first_name || String(grant.telegram_id);

        ownerStatus.textContent = `Готово: ${recipient} получил +${grant.amount} 🐾. Баланс: ${grant.balance} 🐾`;
        ownerAmount.value = "";
        ownerReason.value = "";
        tg?.HapticFeedback?.notificationOccurred?.("success");

        if (currentUser && grant.telegram_id === currentUser.telegram_id) {
            await loadWallet();
        }
    } catch (error) {
        ownerStatus.textContent = error.message || "Не удалось начислить лапкоины";
        tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
        ownerGrant.disabled = false;
        ownerGrant.textContent = "Начислить";
    }
}

ownerGrant?.addEventListener("click", grantLapcoins);

ownerReason?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
        grantLapcoins();
    }
});

for (const input of [ownerTarget, ownerAmount, ownerReason]) {
    input?.addEventListener("input", () => {
        ownerStatus.textContent = "";
    });
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

    for (const tx of items) {
        const row = document.createElement("div");
        row.className = "transaction-row";

        const amount = document.createElement("div");
        amount.className = "transaction-amount";
        amount.textContent = `${tx.amount > 0 ? "+" : ""}${tx.amount} 🐾`;

        const text = document.createElement("div");
        text.className = "transaction-text";
        text.textContent = tx.description || tx.operation_type || "Операция";

        row.appendChild(text);
        row.appendChild(amount);
        list.appendChild(row);
    }
}

function applyUserState(user) {
    currentUser = user;
    usernameEl.textContent = user.first_name || user.username || "пользователь";

    if (user.unlimited_balance) {
        balanceEl.textContent = "∞";
        currencyNameEl.textContent = "лапкоинов · владелец";
        ownerPanel.hidden = false;
    } else {
        balanceEl.textContent = user.balance ?? 0;
        currencyNameEl.textContent = "лапкоинов";
        ownerPanel.hidden = true;
    }
}

async function loadWallet() {
    if (!tg?.initData) {
        balanceEl.textContent = "0";
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/me`, {
            headers: {
                "X-Telegram-Init-Data": tg.initData,
            },
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data?.detail || "Ошибка загрузки кошелька");
        }

        applyUserState(data.user);
        renderTransactions(data.transactions || []);
    } catch (error) {
        console.error("Nyan Wallet API error:", error);
        balanceEl.textContent = "0";
    }
}

loadWallet();
