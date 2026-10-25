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
        // app.js already owns a 25s timeout and bounded retries. Restarting a
        // still pending call used to abort good connections at 8s / 20s.
        if (window.__nyanWalletLoadInFlight === true) {
            showRecovery();
            return;
        }
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

    // Show the recovery control early, but leave the active fetch alone.
    window.setTimeout(() => {
        if (isReady()) return;
        recover();
    }, 8000);

    // This only starts a fresh attempt if the ordinary boot loader is idle.
    window.setTimeout(() => {
        if (isReady()) return;
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
