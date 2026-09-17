const tg = window.Telegram?.WebApp;
const API_BASE = "https://nyan-wallet-api.onrender.com";

if (tg) {
    tg.ready();
    tg.expand();
}

const usernameEl = document.getElementById("username");
const balanceEl = document.getElementById("balance");
const historyEl = document.querySelector(".history");

const unsafeUser = tg?.initDataUnsafe?.user;
if (unsafeUser) {
    usernameEl.textContent = unsafeUser.first_name || unsafeUser.username || "пользователь";
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
