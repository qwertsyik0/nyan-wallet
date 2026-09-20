(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    let hiddenByMaintenance = [];

    function headers() {
        return { "X-Telegram-Init-Data": tg?.initData || "" };
    }

    function ensureView() {
        let view = document.getElementById("maintenance-view");
        if (view) {
            // Self-heal stale Telegram WebView DOM left by an older cached bundle.
            const oldIcon = view.querySelector(".maintenance-icon");
            if (oldIcon) {
                const gear = document.createElement("div");
                gear.className = "maintenance-gear-wrap";
                gear.setAttribute("aria-hidden", "true");
                gear.innerHTML = '<div class="maintenance-gear">⚙</div><div class="maintenance-gear-dot"></div>';
                oldIcon.replaceWith(gear);
            }
            return view;
        }

        const app = document.querySelector(".app");
        if (!app) return null;

        view = document.createElement("main");
        view.id = "maintenance-view";
        view.className = "maintenance-view hidden";
        view.innerHTML = `
            <section class="maintenance-card" aria-live="polite">
                <div class="maintenance-gear-wrap" aria-hidden="true">
                    <div class="maintenance-gear">⚙</div>
                    <div class="maintenance-gear-dot"></div>
                </div>
                <div id="maintenance-title" class="maintenance-title">Nyan Wallet становится лучше</div>
                <div id="maintenance-message" class="maintenance-message">
                    Сейчас мы проводим технические работы: добавляем новые функции,
                    улучшаем стабильность и готовим обновления для вас.
                </div>
                <div class="maintenance-note">
                    Ваш баланс и история операций сохранены. Никаких действий с кошельком во время обслуживания не требуется.
                </div>
                <button id="maintenance-retry" class="maintenance-retry" type="button">Проверить снова</button>
            </section>
        `;
        app.appendChild(view);
        view.querySelector("#maintenance-retry")?.addEventListener("click", () => void checkMaintenance(true));
        return view;
    }

    function showMaintenance(state) {
        const view = ensureView();
        if (!view) return;

        // Ensure the current maintenance indicator is present even when Telegram
        // restores a previously cached page from its WebView snapshot.
        const staleIcon = view.querySelector(".maintenance-icon");
        if (staleIcon) {
            const gear = document.createElement("div");
            gear.className = "maintenance-gear-wrap";
            gear.setAttribute("aria-hidden", "true");
            gear.innerHTML = '<div class="maintenance-gear">⚙</div><div class="maintenance-gear-dot"></div>';
            staleIcon.replaceWith(gear);
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
            return;
        }

        const restorable = hiddenByMaintenance.filter(node => document.contains(node));
        hiddenByMaintenance = [];

        if (restorable.length) {
            restorable.forEach(node => node.classList.remove("hidden"));
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
        void checkMaintenance(false);
    });
})();
