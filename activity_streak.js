(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    let loaded = false;

    function headers() {
        return { "X-Telegram-Init-Data": tg?.initData || "" };
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function addStyles() {
        if (document.getElementById("activity-streak-style")) return;
        const style = document.createElement("style");
        style.id = "activity-streak-style";
        style.textContent = `
            .activity-streak-card {
                position: relative;
                overflow: hidden;
                margin: 18px 0;
                padding: 18px;
                border: 1px solid rgba(222,165,188,.55);
                border-radius: 24px;
                background:
                    radial-gradient(circle at 100% 0%, rgba(255,255,255,.94) 0 16%, transparent 38%),
                    linear-gradient(145deg, rgba(255,255,255,.92), rgba(255,239,247,.88));
                box-shadow: 0 14px 34px rgba(137, 41, 82, .10);
            }
            .activity-streak-card::after {
                content: "";
                position: absolute;
                right: -44px;
                top: -48px;
                width: 144px;
                height: 144px;
                border-radius: 999px;
                background: rgba(255, 222, 236, .72);
                pointer-events: none;
            }
            .activity-streak-top {
                position: relative;
                z-index: 1;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
            }
            .activity-streak-title {
                color: #84264d;
                font-weight: 800;
                font-size: 18px;
                line-height: 1.15;
            }
            .activity-streak-subtitle {
                margin-top: 4px;
                color: #9d6d80;
                font-size: 12px;
                line-height: 1.35;
            }
            .activity-streak-flame {
                width: 54px;
                height: 54px;
                display: grid;
                place-items: center;
                border-radius: 18px;
                background: rgba(255,255,255,.72);
                color: #a22958;
                font-size: 26px;
                box-shadow: inset 0 0 0 1px rgba(222,165,188,.45);
            }
            .activity-streak-main {
                position: relative;
                z-index: 1;
                margin-top: 16px;
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 10px;
            }
            .activity-streak-stat {
                padding: 12px;
                border-radius: 16px;
                background: rgba(255,255,255,.62);
                border: 1px solid rgba(222,165,188,.38);
            }
            .activity-streak-number {
                color: #84264d;
                font-size: 24px;
                line-height: 1;
                font-weight: 900;
            }
            .activity-streak-label {
                margin-top: 5px;
                color: #a67589;
                font-size: 11px;
            }
            .activity-streak-week {
                position: relative;
                z-index: 1;
                margin-top: 14px;
                display: grid;
                grid-template-columns: repeat(7, 1fr);
                gap: 6px;
            }
            .activity-streak-dot {
                height: 8px;
                border-radius: 999px;
                background: rgba(166,117,137,.20);
            }
            .activity-streak-dot.active {
                background: #a22958;
                box-shadow: 0 0 0 3px rgba(162,41,88,.10);
            }
            .activity-streak-status {
                position: relative;
                z-index: 1;
                margin-top: 13px;
                padding: 10px 12px;
                border-radius: 14px;
                background: rgba(255,255,255,.58);
                color: #9a5f78;
                font-size: 12px;
                line-height: 1.4;
            }
            .activity-streak-refresh {
                width: 100%;
                margin-top: 12px;
                background: #922954;
                color: #fff;
            }
        `;
        document.head.appendChild(style);
    }

    function ensureCard() {
        addStyles();
        let card = document.getElementById("activity-streak-card");
        if (card) return card;

        const wallet = document.getElementById("wallet-view");
        if (!wallet) return null;

        card = document.createElement("section");
        card.id = "activity-streak-card";
        card.className = "activity-streak-card";
        card.setAttribute("aria-live", "polite");

        const history = wallet.querySelector(".history");
        if (history?.parentNode) history.parentNode.insertBefore(card, history);
        else wallet.appendChild(card);
        return card;
    }

    function weekDots(streak) {
        const position = streak <= 0 ? 0 : ((streak - 1) % 7) + 1;
        return Array.from({ length: 7 }, (_, index) => {
            const active = index < position;
            return `<span class="activity-streak-dot ${active ? "active" : ""}"></span>`;
        }).join("");
    }

    function renderLoading() {
        const card = ensureCard();
        if (!card) return;
        card.innerHTML = `
            <div class="activity-streak-top">
                <div>
                    <div class="activity-streak-title">Серия активности</div>
                    <div class="activity-streak-subtitle">проверяем сегодняшний вход</div>
                </div>
                <div class="activity-streak-flame">🔥</div>
            </div>
            <div class="activity-streak-status">Загружаем серию…</div>
        `;
    }

    function render(data) {
        const card = ensureCard();
        if (!card) return;
        const activity = data?.activity || {};
        const streak = Number(activity.current_streak || 0);
        const best = Number(activity.best_streak || 0);
        const total = Number(activity.total_checkins || 0);
        const credited = Number(data?.credited_now || 0);
        const already = Boolean(data?.already_checked_today || activity.checked_today);
        const lastReward = Number(activity.last_reward_amount || 0);
        const nextReward = Number(activity.next_reward_amount || 0);

        let status;
        if (credited > 0) {
            status = `Сегодняшний вход засчитан. Начислено +${credited} 🐾.`;
        } else if (already && lastReward > 0) {
            status = `Сегодня вход уже засчитан. Награда за день была +${lastReward} 🐾.`;
        } else if (already) {
            status = "Сегодня вход уже засчитан.";
        } else {
            status = "Открой кошелёк завтра, чтобы продолжить серию.";
        }
        if (nextReward > 0) status += ` Следующая награда: +${nextReward} 🐾.`;

        card.innerHTML = `
            <div class="activity-streak-top">
                <div>
                    <div class="activity-streak-title">Серия активности</div>
                    <div class="activity-streak-subtitle">заходи каждый день и получай лапкоины</div>
                </div>
                <div class="activity-streak-flame">🔥</div>
            </div>
            <div class="activity-streak-main">
                <div class="activity-streak-stat">
                    <div class="activity-streak-number">${escapeHtml(streak)}</div>
                    <div class="activity-streak-label">дней подряд</div>
                </div>
                <div class="activity-streak-stat">
                    <div class="activity-streak-number">${escapeHtml(best)}</div>
                    <div class="activity-streak-label">лучший рекорд</div>
                </div>
            </div>
            <div class="activity-streak-week">${weekDots(streak)}</div>
            <div class="activity-streak-status">${escapeHtml(status)} Всего входов: ${escapeHtml(total)}.</div>
            <button id="activity-streak-refresh" class="activity-streak-refresh" type="button">Обновить серию</button>
        `;

        const balance = document.getElementById("balance");
        if (balance && !activity.unlimited_balance && activity.balance != null) {
            balance.textContent = String(activity.balance);
        }
        if (credited > 0) tg?.HapticFeedback?.notificationOccurred?.("success");
        card.querySelector("#activity-streak-refresh")?.addEventListener("click", () => void load(true));
    }

    function renderError(message) {
        const card = ensureCard();
        if (!card) return;
        card.innerHTML = `
            <div class="activity-streak-top">
                <div>
                    <div class="activity-streak-title">Серия активности</div>
                    <div class="activity-streak-subtitle">не удалось обновить сейчас</div>
                </div>
                <div class="activity-streak-flame">🔥</div>
            </div>
            <div class="activity-streak-status">${escapeHtml(message || "Ошибка загрузки серии")}</div>
            <button id="activity-streak-refresh" class="activity-streak-refresh" type="button">Попробовать снова</button>
        `;
        card.querySelector("#activity-streak-refresh")?.addEventListener("click", () => void load(true));
    }

    async function load(force = false) {
        if (loaded && !force) return;
        if (!tg?.initData) return;
        loaded = true;
        renderLoading();
        try {
            const response = await fetch(`${API}/api/activity/check-in`, {
                method: "POST",
                headers: headers(),
                cache: "no-store",
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data?.detail || "Не удалось засчитать вход");
            render(data);
        } catch (error) {
            renderError(error.message || "Не удалось загрузить серию активности");
            tg?.HapticFeedback?.notificationOccurred?.("error");
        }
    }

    function start() {
        ensureCard();
        window.setTimeout(() => void load(false), 450);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }
})();
