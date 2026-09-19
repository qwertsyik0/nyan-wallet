(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";

    function headers() {
        return { "X-Telegram-Init-Data": tg?.initData || "" };
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
            </section>
        `;
        app.appendChild(view);
        view.querySelector("#maintenance-retry")?.addEventListener("click", () => void checkMaintenance(true));
        return view;
    }

    function showMaintenance(state) {
        const view = ensureView();
        if (!view) return;

        document.querySelectorAll(".app > main").forEach(node => node.classList.add("hidden"));
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
        if (view) view.classList.add("hidden");
        window.__nyanMaintenanceBlocked = false;
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
            if (reloadWhenAvailable) window.location.reload();
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
    }, { once: true });

    window.addEventListener("nyan-maintenance-required", event => {
        showMaintenance(event.detail || {});
    });
})();
