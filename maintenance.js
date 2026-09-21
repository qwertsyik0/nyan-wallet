(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    let hiddenByMaintenance = [];
    let bootstrapMaintenanceRecoveryNeeded = false;

    function headers() {
        return { "X-Telegram-Init-Data": tg?.initData || "" };
    }

    function isLoadingVisible() {
        const loading = document.getElementById("loading-view");
        return Boolean(loading && !loading.classList.contains("hidden"));
    }

    function anyAppViewVisible() {
        return Array.from(document.querySelectorAll(".app > main"))
            .some(node => node.id !== "loading-view" && !node.classList.contains("hidden"));
    }

    function revealWalletFallback(reason) {
        const loading = document.getElementById("loading-view");
        const wallet = document.getElementById("wallet-view");
        const currencyName = document.getElementById("currency-name");
        if (!isLoadingVisible() || anyAppViewVisible()) return false;
        if (loading) loading.classList.add("hidden");
        if (wallet) wallet.classList.remove("hidden");
        if (currencyName && currencyName.textContent === "лапкоинов") {
            currencyName.textContent = "данные временно недоступны";
        }
        bootstrapMaintenanceRecoveryNeeded = false;
        console.warn("Nyan maintenance bootstrap fallback:", reason);
        return true;
    }

    function recoverInitialBootstrap(reason) {
        return revealWalletFallback(reason);
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

        if (transfer && transfer.dataset.maintenanceRestore === "1") {
            transfer.classList.remove("hidden");
            delete transfer.dataset.maintenanceRestore;
        } else if (wallet) {
            wallet.classList.remove("hidden");
        }

        if (bootstrapMaintenanceRecoveryNeeded) {
            recoverInitialBootstrap("maintenance view had only loading screen to restore");
        }
    }

    async function refreshWalletDataWithoutReload() {
        try {
            if (typeof window.loadWallet === "function") {
                await window.loadWallet();
            }
            if (typeof window.__nyanLoadTasks === "function") {
                await window.__nyanLoadTasks();
            }
        } catch (error) {
            console.warn("Nyan maintenance soft refresh failed:", error);
        }
    }

    async function checkMaintenance(refreshWhenAvailable = false) {
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

            if (refreshWhenAvailable) {
                await refreshWalletDataWithoutReload();
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
        window.setTimeout(() => {
            if (!window.__nyanMaintenanceBlocked) {
                revealWalletFallback("initial bootstrap timed out without maintenance");
            }
        }, 12_000);
    }, { once: true });

    window.addEventListener("nyan-maintenance-required", () => {
        // A 503 can arrive after maintenance has already been switched off.
        // Re-check the authoritative status endpoint before changing the UI.
        bootstrapMaintenanceRecoveryNeeded = true;
        void checkMaintenance(false);
    });
})();
