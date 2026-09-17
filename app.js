const tg = window.Telegram?.WebApp;
const API_BASE = "https://nyan-wallet-api.onrender.com";

if (tg) {
    tg.ready();
    tg.expand();
}

const usernameEl = document.getElementById("username");
const balanceEl = document.getElementById("balance");
const historyEl = document.querySelector(".history");
const walletView = document.getElementById("wallet-view");
const earnView = document.getElementById("earn-view");
const earnButton = document.getElementById("earn-button");
const earnBack = document.getElementById("earn-back");
const promoCode = document.getElementById("promo-code");
const promoActivate = document.getElementById("promo-activate");
const promoStatus = document.getElementById("promo-status");

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

promoActivate?.addEventListener("click", () => {
    const code = promoCode.value.trim();

    if (!code) {
        promoStatus.textContent = "Введите промокод.";
        promoCode.focus();
        return;
    }

    promoStatus.textContent = "Проверку промокодов подключим следующим этапом.";
    tg?.HapticFeedback?.notificationOccurred?.("warning");
});

promoCode?.addEventListener("input", () => {
    promoStatus.textContent = "";
});

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

        const user = data.user;
        balanceEl.textContent = user.balance ?? 0;
        usernameEl.textContent = user.first_name || user.username || "пользователь";
        renderTransactions(data.transactions || []);
    } catch (error) {
        console.error("Nyan Wallet API error:", error);
        balanceEl.textContent = "0";
    }
}

loadWallet();
