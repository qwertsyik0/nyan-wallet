/* Restore Nyan Wallet first launch without closing Telegram WebView.
   This script is deliberately independent of optional wallet modules. */
(() => {
    "use strict";

    const loading = document.getElementById("loading-view");
    const status = document.getElementById("loading-status");
    const hint = document.getElementById("loading-hint");
    const retryButton = document.getElementById("loading-retry");
    if (!loading) return;

    const launchedAt = Date.now();
    let lastAttemptAt = 0;
    let scheduledAttempts = 0;
    const isReady = () => window.__nyanWalletReady === true ||
        loading.classList.contains("hidden");

    function showRecovery() {
        if (isReady()) return;
        if (status) status.textContent = "соединение задерживается";
        if (hint) hint.textContent =
            "Проверяем подключение ещё раз. Можно повторить сейчас, не закрывая кошелёк.";
        if (retryButton) retryButton.hidden = false;
        loading.classList.add("is-waiting");
    }

    function recover() {
        if (isReady() || document.hidden) return;
        const now = Date.now();
        if (now - lastAttemptAt < 4500) return;
        lastAttemptAt = now;
        showRecovery();
        if (typeof window.loadWallet === "function") {
            // loadWallet aborts its previous stale /api/me request itself.
            void Promise.resolve(window.loadWallet()).catch(() => {
                showRecovery();
            });
        }
    }

    // The ordinary boot loader still handles fast connections.
    // Retry once if the Telegram WebView left its first request suspended.
    window.setTimeout(() => {
        if (isReady()) return;
        scheduledAttempts += 1;
        recover();
    }, 8000);

    // A second bounded recovery prevents a single dead retry from
    // trapping the user until they close and reopen the Mini App.
    window.setTimeout(() => {
        if (isReady() || scheduledAttempts === 0) return;
        recover();
    }, 20000);

    function onReturn() {
        if (isReady()) return;
        if (Date.now() - launchedAt < 4500) return;
        recover();
    }

    document.addEventListener("visibilitychange", onReturn);
    window.addEventListener("pageshow", onReturn);
    window.addEventListener("focus", onReturn);
    window.addEventListener("online", onReturn);

    // If app.js itself failed to load, its retry handler does not exist.
    // Allow a manual page refresh as a last resort, never an automatic loop.
    retryButton?.addEventListener("click", () => {
        if (typeof window.loadWallet !== "function") {
            window.location.reload();
        }
    });
})();
