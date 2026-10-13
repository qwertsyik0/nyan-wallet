const tg = window.Telegram?.WebApp;
const appealDeepLinkActive = (() => {
    const params = new URLSearchParams(window.location.search);
    return params.has("appeals") || params.has("appeal") || params.has("ownerAppeal");
})();
const API_BASE = "https://nyan-wallet-api.onrender.com";

if (tg) {
    tg.ready();
    tg.expand();
}

const loadingView = document.getElementById("loading-view");
const subscriptionView = document.getElementById("subscription-view");
const subscriptionOpen = document.getElementById("subscription-open");
const subscriptionCheck = document.getElementById("subscription-check");
const subscriptionStatus = document.getElementById("subscription-status");
const REQUIRED_CHANNEL_URL = "https://t.me/NyanWallet";
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
const ownerSurveyView = document.getElementById("owner-survey-view");
const ownerSurveyOpen = document.getElementById("owner-survey-open");
const ownerSurveyBack = document.getElementById("owner-survey-back");
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
const ownerBanToggle = document.getElementById("owner-ban-toggle");
const ownerBanStatus = document.getElementById("owner-ban-status");
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

const ownerSurveyStatus = document.getElementById("owner-survey-status");
const ownerSurveySummary = document.getElementById("owner-survey-summary");
const ownerSurveyComments = document.getElementById("owner-survey-comments");
const ownerSurveyParticipants = document.getElementById("owner-survey-participants");

let currentUser = null;
let selectedOwnerUserId = null;
let selectedOwnerUserBlocked = false;
let initialLoadFinished = false;
let walletLoadAttempt = 0;
let walletLoadController = null;
const WALLET_BOOT_TIMEOUT_MS = 9000;

function giveawayDeepLinkId() {
    const candidates = [];
    try {
        const url = new URL(window.location.href);
        candidates.push(url.searchParams.get("giveaway"));
        candidates.push(url.searchParams.get("tgWebAppStartParam"));
        candidates.push(url.searchParams.get("startapp"));
        const hash = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
        const hashParams = new URLSearchParams(hash);
        candidates.push(hashParams.get("tgWebAppStartParam"));
        candidates.push(hashParams.get("startapp"));
        candidates.push(hashParams.get("giveaway"));
    } catch (_) {}

    candidates.push(tg?.initDataUnsafe?.start_param || "");
    for (const raw of candidates) {
        const value = String(raw || "").trim();
        if (/^NYG-\d{6,}$/.test(value)) return value;
        const match = value.match(/^giveaway_(NYG-\d{6,})$/);
        if (match) return match[1];
    }
    return null;
}

const initialGiveawayDeepLink = giveawayDeepLinkId();
if (initialGiveawayDeepLink) {
    window.__nyanGiveawayDeepLink = initialGiveawayDeepLink;
    window.__nyanGiveawayDeepLinkActive = true;
}

const unsafeUser = tg?.initDataUnsafe?.user;
if (unsafeUser) {
    usernameEl.textContent = unsafeUser.first_name || unsafeUser.username || "пользователь";
    if (walletNumberEl) walletNumberEl.textContent = createWalletNumber(unsafeUser.id);
    if (walletHolderEl) walletHolderEl.textContent = walletHolderName(unsafeUser);
}

const OWNER_WALLET_NUMBER = "7777 7777 7777";

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

function ensureWalletLoadNotice() {
    let notice = document.getElementById("wallet-load-notice");
    if (notice) return notice;

    notice = document.createElement("section");
    notice.id = "wallet-load-notice";
    notice.className = "admin-section";
    notice.hidden = true;
    notice.innerHTML = `
        <div class="owner-title">Не удалось загрузить данные</div>
        <div id="wallet-load-notice-text" class="owner-subtitle">
            Сервер отвечает слишком долго. Сам кошелёк можно открыть, а данные попробовать загрузить ещё раз.
        </div>
        <button id="wallet-load-retry" class="owner-grant-button" type="button" style="width:100%;margin-top:12px">
            Попробовать снова
        </button>
    `;

    const history = walletView?.querySelector(".history");
    if (history?.parentNode) history.parentNode.insertBefore(notice, history);
    else walletView?.appendChild(notice);

    notice.querySelector("#wallet-load-retry")?.addEventListener("click", () => {
        void loadWallet();
    });
    return notice;
}

function showWalletLoadNotice(message) {
    const notice = ensureWalletLoadNotice();
    const text = notice?.querySelector("#wallet-load-notice-text");
    if (text && message) text.textContent = message;
    if (notice) notice.hidden = false;
}

function clearWalletLoadNotice() {
    const notice = document.getElementById("wallet-load-notice");
    if (notice) notice.hidden = true;
}

function finishInitialLoad() {
    if (initialLoadFinished) return;
    initialLoadFinished = true;
    loadingView?.classList.add("hidden");
    if (
        !window.__nyanMaintenanceBlocked &&
        !window.__nyanSubscriptionBlocked &&
        !window.__nyanGiveawayDeepLinkActive &&
        !window.__nyanPaymentDeepLinkActive &&
        !window.__nyanPromoDeepLinkActive &&
        !appealDeepLinkActive
    ) {
        walletView.classList.remove("hidden");
    }
}

// wallet-ready startup guard: if data loaded successfully but another startup
// module left only the loading screen visible, never trap the user there.
window.addEventListener("nyan-wallet-ready", () => {
    window.setTimeout(() => {
        if (window.__nyanMaintenanceBlocked || window.__nyanSubscriptionBlocked) return;

        const loadingVisible = loadingView && !loadingView.classList.contains("hidden");
        if (!loadingVisible) return;

        const anotherViewVisible = Array.from(document.querySelectorAll(".app > main"))
            .some((node) => node !== loadingView && !node.classList.contains("hidden"));
        if (anotherViewVisible) {
            loadingView.classList.add("hidden");
            return;
        }

        console.warn("Nyan Wallet startup guard: forcing wallet view after successful /api/me");
        window.__nyanGiveawayDeepLinkActive = false;
        window.__nyanPaymentDeepLinkActive = false;
        window.__nyanPromoDeepLinkActive = false;
        loadingView.classList.add("hidden");
        walletView?.classList.remove("hidden");
    }, 1200);
});

function hideAllAppViewsForSubscription() {
    document.querySelectorAll(".app > main").forEach((node) => {
        if (node !== subscriptionView) node.classList.add("hidden");
    });
}

function showSubscriptionGate(message = "Для продолжения необходимо подписаться на информационный канал.") {
    window.__nyanSubscriptionBlocked = true;
    window.__nyanWalletReady = false;
    hideAllAppViewsForSubscription();
    loadingView?.classList.add("hidden");
    subscriptionView?.classList.remove("hidden");
    if (subscriptionStatus) subscriptionStatus.textContent = message;
    if (tg?.BackButton) tg.BackButton.hide();
}

async function checkRequiredSubscription() {
    if (!tg?.initData) return false;

    if (subscriptionCheck) {
        subscriptionCheck.disabled = true;
        subscriptionCheck.textContent = "Проверяем…";
    }
    if (subscriptionStatus) subscriptionStatus.textContent = "";

    try {
        const response = await fetch(`${API_BASE}/api/subscription/status`, {
            headers: authHeaders(),
            cache: "no-store",
        });
        const data = await readJson(response);
        if (!response.ok) {
            const detail = data?.detail;
            const message = typeof detail === "object"
                ? detail?.message
                : detail;
            throw new Error(message || "Не удалось проверить подписку");
        }

        if (!data?.subscribed) {
            showSubscriptionGate("Подписка пока не найдена. Подпишитесь на канал и нажмите «Проверить подписку».");
            return false;
        }

        window.__nyanSubscriptionBlocked = false;
        subscriptionView?.classList.add("hidden");
        if (subscriptionStatus) subscriptionStatus.textContent = "";
        initialLoadFinished = false;
        await loadWallet();
        return true;
    } catch (error) {
        showSubscriptionGate(error?.message || "Не удалось проверить подписку. Попробуйте ещё раз.");
        return false;
    } finally {
        if (subscriptionCheck) {
            subscriptionCheck.disabled = false;
            subscriptionCheck.textContent = "Проверить подписку";
        }
    }
}

subscriptionOpen?.addEventListener("click", () => {
    if (tg?.openTelegramLink) tg.openTelegramLink(REQUIRED_CHANNEL_URL);
    else window.open(REQUIRED_CHANNEL_URL, "_blank", "noopener,noreferrer");
});

subscriptionCheck?.addEventListener("click", () => {
    void checkRequiredSubscription();
});


function showWalletView() {
    loadingView?.classList.add("hidden");
    earnView.classList.add("hidden");
    ownerView.classList.add("hidden");
    ownerSurveyView?.classList.add("hidden");
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

function openOwnerSurveyView() {
    if (!currentUser?.is_owner) return;
    walletView.classList.add("hidden");
    earnView.classList.add("hidden");
    ownerView.classList.add("hidden");
    ownerSurveyView?.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
    tg?.BackButton?.show?.();
    tg?.HapticFeedback?.impactOccurred?.("light");
    loadOwnerSurveyResults();
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
    loadOwnerSurveyResults();
}

earnButton?.addEventListener("click", openEarnView);
earnBack?.addEventListener("click", showWalletView);
ownerButton?.addEventListener("click", openOwnerView);
ownerBack?.addEventListener("click", showWalletView);
ownerSurveyOpen?.addEventListener("click", openOwnerSurveyView);
ownerSurveyBack?.addEventListener("click", openOwnerView);

if (tg?.BackButton?.onClick) {
    tg.BackButton.onClick(() => {
        if (ownerSurveyView && !ownerSurveyView.classList.contains("hidden")) {
            openOwnerView();
        } else if (!earnView.classList.contains("hidden") || !ownerView.classList.contains("hidden")) {
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
        transfer_out: "Перевод",
        transfer_in: "Перевод",
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
        await refreshSelectedBanStatus();

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

async function refreshSelectedBanStatus() {
    if (!selectedOwnerUserId || !ownerBanToggle) return;

    ownerBanToggle.disabled = true;
    if (ownerBanStatus) ownerBanStatus.textContent = "Проверяем блокировку…";

    try {
        const response = await fetch(`${API_BASE}/api/owner/bans/status/${selectedOwnerUserId}`, {
            headers: authHeaders(),
            cache: "no-store",
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось проверить блокировку");

        selectedOwnerUserBlocked = data.blocked === true;
        ownerBanToggle.textContent = selectedOwnerUserBlocked ? "Разблокировать" : "Заблокировать";

        if (ownerBanStatus) {
            if (selectedOwnerUserBlocked) {
                const reason = data?.ban?.reason ? ` · ${data.ban.reason}` : "";
                ownerBanStatus.textContent = `Пользователь заблокирован${reason}`;
            } else {
                ownerBanStatus.textContent = "Пользователь не заблокирован";
            }
        }
    } catch (error) {
        if (ownerBanStatus) ownerBanStatus.textContent = error.message || "Не удалось проверить блокировку";
    } finally {
        ownerBanToggle.disabled = false;
    }
}

function confirmOwnerAction(message) {
    return new Promise((resolve) => {
        if (typeof tg?.showConfirm === "function") {
            tg.showConfirm(message, (ok) => resolve(Boolean(ok)));
            return;
        }
        resolve(window.confirm(message));
    });
}

async function toggleSelectedUserBan() {
    if (!selectedOwnerUserId || !ownerBanToggle) {
        if (ownerBanStatus) ownerBanStatus.textContent = "Сначала выберите пользователя.";
        return;
    }

    const action = selectedOwnerUserBlocked ? "unban" : "ban";
    const reason = ownerReason?.value.trim() || "";
    const prompt = selectedOwnerUserBlocked
        ? "Разблокировать этого пользователя?"
        : "Заблокировать пользователя в Nyan Wallet?";

    if (!(await confirmOwnerAction(prompt))) return;

    ownerBanToggle.disabled = true;
    if (ownerBanStatus) {
        ownerBanStatus.textContent = action === "ban" ? "Блокируем…" : "Разблокируем…";
    }

    try {
        const response = await fetch(`${API_BASE}/api/owner/bans/${action}`, {
            method: "POST",
            headers: authHeaders(true),
            body: JSON.stringify({
                target: String(selectedOwnerUserId),
                reason: action === "ban" && reason ? reason : null,
            }),
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Операция не выполнена");

        selectedOwnerUserBlocked = action === "ban";
        ownerBanToggle.textContent = selectedOwnerUserBlocked ? "Разблокировать" : "Заблокировать";
        if (ownerBanStatus) {
            ownerBanStatus.textContent = selectedOwnerUserBlocked
                ? `Пользователь заблокирован${reason ? `: ${reason}` : ""}`
                : "Пользователь разблокирован";
        }
        tg?.HapticFeedback?.notificationOccurred?.("success");
        await loadOwnerUsers();
    } catch (error) {
        if (ownerBanStatus) ownerBanStatus.textContent = error.message || "Операция не выполнена";
        tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
        ownerBanToggle.disabled = false;
    }
}

ownerBanToggle?.addEventListener("click", () => void toggleSelectedUserBan());

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
    if (walletNumberEl) {
        walletNumberEl.textContent = user.is_owner
            ? OWNER_WALLET_NUMBER
            : createWalletNumber(user.telegram_id);
    }
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
        balanceEl.textContent = "—";
        currencyNameEl.textContent = "откройте через Telegram";
        finishInitialLoad();
        return;
    }

    const attempt = ++walletLoadAttempt;
    walletLoadController?.abort();
    const controller = new AbortController();
    walletLoadController = controller;
    const timeout = window.setTimeout(() => controller.abort(), WALLET_BOOT_TIMEOUT_MS);
    let blockedByMaintenance = false;

    try {
        const response = await fetch(`${API_BASE}/api/me`, {
            headers: authHeaders(),
            cache: "no-store",
            signal: controller.signal,
        });
        const data = await readJson(response);

        if (attempt !== walletLoadAttempt) return;

        if (response.status === 503 && data?.detail === "maintenance") {
            blockedByMaintenance = true;
            window.dispatchEvent(new CustomEvent("nyan-maintenance-required", {
                detail: data.maintenance || {},
            }));
            return;
        }

        const apiDetail = data?.detail;
        const apiCode = typeof apiDetail === "object" ? apiDetail?.code : null;
        if (response.status === 403 && apiCode === "subscription_required") {
            showSubscriptionGate(
                apiDetail?.message || "Для продолжения необходимо подписаться на информационный канал."
            );
            return;
        }

        if (response.status === 503 && apiCode === "subscription_check_unavailable") {
            showSubscriptionGate(
                apiDetail?.message || "Не удалось проверить подписку. Попробуйте ещё раз."
            );
            return;
        }

        if (!response.ok) {
            const message = typeof apiDetail === "object" ? apiDetail?.message : apiDetail;
            throw new Error(message || "Ошибка загрузки кошелька");
        }

        applyUserState(data.user);
        renderTransactions(data.transactions || []);
        clearWalletLoadNotice();

        window.__nyanWalletReady = true;
        window.dispatchEvent(new CustomEvent("nyan-wallet-ready", {
            detail: { user: data.user },
        }));
    } catch (error) {
        if (attempt !== walletLoadAttempt) return;

        console.error("Nyan Wallet API error:", error);
        balanceEl.textContent = "—";
        currencyNameEl.textContent = "данные временно недоступны";
        const timedOut = error?.name === "AbortError";
        showWalletLoadNotice(
            timedOut
                ? "Сервер отвечает слишком долго. Кошелёк открыт без данных — нажмите «Попробовать снова»."
                : "Не удалось получить данные кошелька. Проверьте соединение и попробуйте снова."
        );
    } finally {
        window.clearTimeout(timeout);
        if (walletLoadController === controller) walletLoadController = null;
        if (!blockedByMaintenance && !window.__nyanSubscriptionBlocked && attempt === walletLoadAttempt) {
            finishInitialLoad();
        }
    }
}


const SURVEY_TITLES = {
    useful: "Насколько полезен Nyan Wallet?",
    most_used: "Чем пользуются чаще всего?",
    missing: "Чего больше всего не хватает?",
    separate_channel: "Нужен ли отдельный канал Nyan Wallet?",
    updates: "Что интереснее видеть в новостях?",
};

function surveyPercentBar(option) {
    const row = document.createElement("div");
    row.className = "owner-survey-option";

    const top = document.createElement("div");
    top.className = "owner-survey-option-top";

    const label = document.createElement("span");
    label.textContent = option.label;

    const value = document.createElement("strong");
    value.textContent = `${option.count} · ${option.percent}%`;

    const track = document.createElement("div");
    track.className = "owner-survey-track";

    const fill = document.createElement("div");
    fill.className = "owner-survey-fill";
    fill.style.width = `${Math.max(0, Math.min(100, Number(option.percent) || 0))}%`;

    top.append(label, value);
    track.appendChild(fill);
    row.append(top, track);
    return row;
}

async function loadOwnerSurveyResults() {
    if (!currentUser?.is_owner || !tg?.initData || !ownerSurveyStatus) return;

    ownerSurveyStatus.textContent = "Загружаем результаты…";
    ownerSurveySummary.innerHTML = "";
    ownerSurveyComments.innerHTML = "";
    ownerSurveyParticipants.innerHTML = "";

    try {
        const response = await fetch(`${API_BASE}/api/owner/wallet-survey/results`, {
            headers: authHeaders(),
            cache: "no-store",
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить результаты опроса");

        ownerSurveyStatus.textContent = data.total
            ? `Прошли: ${data.total} · выдано: ${data.total_rewards} 🐾`
            : "Пока никто не прошёл опрос";

        const stats = document.createElement("div");
        stats.className = "owner-survey-stats";

        const totalCard = document.createElement("div");
        totalCard.className = "owner-survey-stat";
        totalCard.innerHTML = `<span>участников</span><strong>${data.total}</strong>`;

        const rewardCard = document.createElement("div");
        rewardCard.className = "owner-survey-stat";
        rewardCard.innerHTML = `<span>выдано</span><strong>${data.total_rewards} 🐾</strong>`;

        stats.append(totalCard, rewardCard);
        ownerSurveySummary.appendChild(stats);

        for (const [field, options] of Object.entries(data.questions || {})) {
            const block = document.createElement("div");
            block.className = "owner-survey-block";

            const title = document.createElement("div");
            title.className = "owner-survey-question";
            title.textContent = SURVEY_TITLES[field] || field;
            block.appendChild(title);

            for (const option of options) block.appendChild(surveyPercentBar(option));
            ownerSurveySummary.appendChild(block);
        }

        const commentsTitle = document.createElement("div");
        commentsTitle.className = "owner-survey-section-title";
        commentsTitle.textContent = `Комментарии (${(data.comments || []).length})`;
        ownerSurveyComments.appendChild(commentsTitle);

        if (!(data.comments || []).length) {
            const empty = document.createElement("div");
            empty.className = "owner-survey-empty";
            empty.textContent = "Комментариев пока нет";
            ownerSurveyComments.appendChild(empty);
        } else {
            for (const item of data.comments) {
                const card = document.createElement("div");
                card.className = "owner-survey-comment";

                const head = document.createElement("div");
                head.className = "owner-survey-comment-head";
                head.textContent = `${item.name} · ${formatDate(item.created_at)}`;

                const text = document.createElement("div");
                text.className = "owner-survey-comment-text";
                text.textContent = item.comment;

                card.append(head, text);
                ownerSurveyComments.appendChild(card);
            }
        }

        const participantsTitle = document.createElement("div");
        participantsTitle.className = "owner-survey-section-title";
        participantsTitle.textContent = `Участники (${(data.participants || []).length})`;
        ownerSurveyParticipants.appendChild(participantsTitle);

        for (const item of data.participants || []) {
            const row = document.createElement("div");
            row.className = "owner-survey-participant";

            const left = document.createElement("div");
            left.innerHTML = `<strong></strong><span></span>`;
            left.querySelector("strong").textContent = item.name;
            left.querySelector("span").textContent = `${formatDate(item.created_at)} · +${item.reward_amount} 🐾`;

            const channel = document.createElement("div");
            channel.className = "owner-survey-participant-answer";
            const answer = item.answers?.separate_channel;
            channel.textContent = answer === "yes" ? "канал: да" : answer === "no" ? "канал: нет" : "канал: не уверен";

            row.append(left, channel);
            ownerSurveyParticipants.appendChild(row);
        }
    } catch (error) {
        ownerSurveyStatus.textContent = error.message || "Не удалось загрузить результаты опроса";
    }
}

loadWallet();
