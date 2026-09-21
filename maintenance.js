(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const BOOTSTRAP_RECOVERY_KEY = "nyan-maintenance-bootstrap-retry:20260921-7";
    let hiddenByMaintenance = [];
    let bootstrapMaintenanceRecoveryNeeded = false;

    function headers() {
        return { "X-Telegram-Init-Data": tg?.initData || "" };
    }

    function isLoadingVisible() {
        const loading = document.getElementById("loading-view");
        return Boolean(loading && !loading.classList.contains("hidden"));
    }

    function revealWalletFallback(reason) {
        const loading = document.getElementById("loading-view");
        const wallet = document.getElementById("wallet-view");
        const currencyName = document.getElementById("currency-name");
        if (loading) loading.classList.add("hidden");
        if (wallet) wallet.classList.remove("hidden");
        if (currencyName && currencyName.textContent === "лапкоинов") {
            currencyName.textContent = "данные временно недоступны";
        }
        console.warn("Nyan maintenance bootstrap fallback:", reason);
    }

    function recoverInitialBootstrap(reason) {
        const wallet = document.getElementById("wallet-view");
        if (!isLoadingVisible() || (wallet && !wallet.classList.contains("hidden"))) {
            return false;
        }

        try {
            if (sessionStorage.getItem(BOOTSTRAP_RECOVERY_KEY) === "1") {
                revealWalletFallback(reason);
                bootstrapMaintenanceRecoveryNeeded = false;
                return true;
            }
            sessionStorage.setItem(BOOTSTRAP_RECOVERY_KEY, "1");

            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set("_nyan_maintenance_retry", String(Date.now()));
            window.location.replace(currentUrl.toString());
            return true;
        } catch (error) {
            console.error("Maintenance bootstrap recovery failed:", error);
            revealWalletFallback(reason);
            bootstrapMaintenanceRecoveryNeeded = false;
            return true;
        }
    }

    function ensureView() {
        let view = document.getElementById("maintenance-view");
        if (view) return view;

        const app = document.querySelector(".app");
        if (!app) return null;

        view = document.createElement("main");
        view.id = "maintenance-view";
        view.className = "maintenance-view hidden";
        view.innerHTML = `
            <section class="maintenance-card" aria-live="polite">
                <div class="maintenance-background-gear" aria-hidden="true">⚙</div>
                <div class="maintenance-content">
                <div class="maintenance-icon" aria-hidden="true">🐾</div>
                <div id="maintenance-title" class="maintenance-title">Nyan Wallet становится лучше</div>
                <div id="maintenance-message" class="maintenance-message">
                    Сейчас мы проводим технические работы: добавляем новые функции,
                    улучшаем стабильность и готовим обновления для вас.
                </div>
                <div class="maintenance-note">
                    Ваш баланс и история операций сохранены. Никаких действий с кошельком во время обслуживания не требуется.
                </div>
                <button id="maintenance-retry" class="maintenance-retry" type="button">Проверить снова</button>
                </div>
            </section>
        `;
        app.appendChild(view);
        view.querySelector("#maintenance-retry")?.addEventListener("click", () => void checkMaintenance(true));
        return view;
    }

    function showMaintenance(state) {
        const view = ensureView();
        if (!view) return;

        if (isLoadingVisible()) {
            bootstrapMaintenanceRecoveryNeeded = true;
        }

        hiddenByMaintenance = Array.from(document.querySelectorAll(".app > main"))
            .filter(node => node !== view && !node.classList.contains("hidden"));

        document.querySelectorAll(".app > main").forEach(node => {
            if (node !== view) node.classList.add("hidden");
        });
        view.classList.remove("hidden");

        const title = view.querySelector("#maintenance-title");
        const message = view.querySelector("#maintenance-message");
        if (title) title.textContent = state?.title || "Nyan Wallet становится лучше";
        if (message) message.textContent = state?.message || "Сейчас ведутся технические работы.";

        tg?.BackButton?.hide?.();
        window.scrollTo({ top: 0, behavior: "smooth" });
        window.__nyanMaintenanceBlocked = true;
    }

    function clearMaintenance() {
        const view = document.getElementById("maintenance-view");
        const wasVisible = Boolean(view && !view.classList.contains("hidden"));

        if (view) view.classList.add("hidden");
        window.__nyanMaintenanceBlocked = false;

        if (!wasVisible) {
            hiddenByMaintenance = [];
            if (bootstrapMaintenanceRecoveryNeeded) {
                recoverInitialBootstrap("maintenance status cleared before maintenance view opened");
            }
            return;
        }

        const restorable = hiddenByMaintenance.filter(node => document.contains(node));
        hiddenByMaintenance = [];

        if (restorable.length) {
            restorable.forEach(node => node.classList.remove("hidden"));
            if (bootstrapMaintenanceRecoveryNeeded) {
                recoverInitialBootstrap("maintenance view restored loading screen");
            }
            return;
        }

        const transfer = document.getElementById("transfer-view");
        const wallet = document.getElementById("wallet-view");
        const loading = document.getElementById("loading-view");

        if (transfer && transfer.dataset.maintenanceRestore === "1") {
            transfer.classList.remove("hidden");
            delete transfer.dataset.maintenanceRestore;
        } else if (wallet) {
            wallet.classList.remove("hidden");
        } else if (loading) {
            loading.classList.remove("hidden");
            if (bootstrapMaintenanceRecoveryNeeded) {
                recoverInitialBootstrap("maintenance view had only loading screen to restore");
            }
        }
    }

    async function checkMaintenance(reloadWhenAvailable = false) {
        try {
            const response = await fetch(API + "/api/maintenance/status", {
                headers: headers(),
                cache: "no-store",
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data?.detail || "Не удалось проверить состояние сервиса");

            if (data.blocked) {
                showMaintenance(data.maintenance || {});
                return true;
            }

            clearMaintenance();

            if (reloadWhenAvailable) {
                const currentUrl = new URL(window.location.href);
                currentUrl.searchParams.set("_nyan_refresh", String(Date.now()));
                window.location.replace(currentUrl.toString());
            }
            return false;
        } catch (error) {
            console.error("Maintenance status check failed:", error);
            return false;
        }
    }

    window.__nyanCheckMaintenance = checkMaintenance;

    document.addEventListener("DOMContentLoaded", () => {
        ensureView();
        void checkMaintenance(false);
        window.setInterval(() => void checkMaintenance(false), 60_000);
    }, { once: true });

    window.addEventListener("nyan-maintenance-required", () => {
        // A 503 can arrive after maintenance has already been switched off.
        // Re-check the authoritative status endpoint before changing the UI.
        bootstrapMaintenanceRecoveryNeeded = true;
        void checkMaintenance(false);
    });
})();
