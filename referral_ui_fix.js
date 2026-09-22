(() => {
    "use strict";

    const NEXT_TEXT = "Приглашайте пользователей. Код можно применить один раз. Системные награды, задания, серии и промокоды не блокируют ввод реферального кода.";
    const API_BASE = "https://nyan-wallet-api.onrender.com";
    const tg = window.Telegram?.WebApp;

    function patchReferralText() {
        document.querySelectorAll("#adv-profile-view .adv-panel").forEach((panel) => {
            const title = panel.querySelector(".adv-title")?.textContent?.trim();
            if (title !== "Реферальная система") return;
            const sub = panel.querySelector(".adv-sub");
            if (sub && sub.textContent !== NEXT_TEXT) sub.textContent = NEXT_TEXT;
        });
    }

    function readStartParam() {
        const values = [];
        try {
            const url = new URL(window.location.href);
            values.push(url.searchParams.get("promo"));
            values.push(url.searchParams.get("slug"));
            values.push(url.searchParams.get("startapp"));
            values.push(url.searchParams.get("start_param"));
            values.push(url.searchParams.get("tgWebAppStartParam"));
            const pathMatch = url.pathname.match(/\/promo\/([a-z0-9_-]{2,48})/i);
            if (pathMatch) values.push(pathMatch[1]);
            const hash = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
            const hashParams = new URLSearchParams(hash);
            values.push(hashParams.get("promo"));
            values.push(hashParams.get("startapp"));
            values.push(hashParams.get("tgWebAppStartParam"));
        } catch (_) {}
        values.push(tg?.initDataUnsafe?.start_param || "");

        for (const raw of values) {
            const value = String(raw || "").trim();
            if (!value) continue;
            const direct = value.match(/^[a-z0-9_-]{2,48}$/i);
            const prefixed = value.match(/^promo[_-]([a-z0-9_-]{2,48})$/i);
            const slug = prefixed ? prefixed[1] : (direct ? value : "");
            if (slug) return slug.toLowerCase().replaceAll("_", "-");
        }
        return null;
    }

    function headers(json = false) {
        const result = { "X-Telegram-Init-Data": tg?.initData || "" };
        if (json) result["Content-Type"] = "application/json";
        return result;
    }

    async function readJson(response) {
        try { return await response.json(); } catch (_) { return {}; }
    }

    function injectPromoStyles() {
        if (document.getElementById("limited-promo-styles")) return;
        const style = document.createElement("style");
        style.id = "limited-promo-styles";
        style.textContent = `
            .limited-promo-card{margin-top:18px;padding:22px;border-radius:28px;border:1px solid rgba(146,41,84,.18);background:radial-gradient(circle at 18% 12%,rgba(255,255,255,.95),rgba(255,245,249,.98) 44%,rgba(250,228,238,.96));box-shadow:0 18px 45px rgba(127,39,76,.13);overflow:hidden;position:relative}
            .limited-promo-card:before{content:"";position:absolute;inset:-80px -80px auto auto;width:180px;height:180px;border-radius:50%;background:rgba(146,41,84,.08);filter:blur(12px)}
            .limited-promo-kicker{position:relative;display:inline-flex;padding:7px 11px;border-radius:999px;background:#fff;color:#922954;font-size:11px;font-weight:800;border:1px solid #efd8e2}
            .limited-promo-title{position:relative;margin-top:14px;font-size:24px;line-height:1.08;font-weight:900;color:#7e284c;letter-spacing:-.03em}
            .limited-promo-reward{position:relative;margin-top:12px;font-size:48px;line-height:1;font-weight:900;color:#922954;letter-spacing:-.05em}
            .limited-promo-description{position:relative;margin-top:12px;color:#9b6d80;font-size:14px;line-height:1.45}
            .limited-promo-stats{position:relative;display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:17px}
            .limited-promo-stat{padding:13px;border-radius:17px;background:rgba(255,255,255,.82);border:1px solid #efd8e2}
            .limited-promo-stat-label{font-size:10px;color:#a67589;text-transform:uppercase;letter-spacing:.08em}.limited-promo-stat-value{margin-top:4px;font-size:18px;font-weight:900;color:#7e284c}
            .limited-promo-action{position:relative;margin-top:18px;width:100%;border:0;border-radius:17px;padding:15px 18px;background:#922954;color:#fff;font-weight:900;font-size:15px;box-shadow:0 13px 30px rgba(146,41,84,.22)}
            .limited-promo-action:disabled{opacity:.55;box-shadow:none}.limited-promo-status{position:relative;margin-top:13px;padding:12px 13px;border-radius:15px;background:#fff;color:#7e4059;border:1px solid #efd8e2;font-size:13px;line-height:1.4}.limited-promo-status.success{background:#f4fff6;color:#3d724b;border-color:#cdeed5}.limited-promo-status.error{background:#fff6f7;color:#9a3852;border-color:#f0cbd5}
            .limited-promo-footnote{position:relative;margin-top:12px;color:#a67589;font-size:11px;line-height:1.4;text-align:center}
            @media(max-width:390px){.limited-promo-reward{font-size:40px}.limited-promo-stats{grid-template-columns:1fr}}
        `;
        document.head.appendChild(style);
    }

    function promoView() {
        let view = document.getElementById("limited-promo-view");
        if (view) return view;
        injectPromoStyles();
        view = document.createElement("main");
        view.id = "limited-promo-view";
        view.className = "view hidden";
        view.innerHTML = `
            <div class="subpage-header">
                <button id="limited-promo-back" class="back-button" type="button" aria-label="Назад">‹</button>
                <div>
                    <div class="page-title">Промо Nyan Wallet</div>
                    <div class="page-subtitle">лимитированный бонус</div>
                </div>
            </div>
            <section class="limited-promo-card">
                <div class="limited-promo-kicker">только первые активации</div>
                <div id="limited-promo-title" class="limited-promo-title">Загружаем промо</div>
                <div id="limited-promo-reward" class="limited-promo-reward">109 🐾</div>
                <div id="limited-promo-description" class="limited-promo-description">Проверяем доступность бонуса.</div>
                <div class="limited-promo-stats">
                    <div class="limited-promo-stat"><div class="limited-promo-stat-label">лимит</div><div id="limited-promo-limit" class="limited-promo-stat-value">10</div></div>
                    <div class="limited-promo-stat"><div class="limited-promo-stat-label">осталось</div><div id="limited-promo-left" class="limited-promo-stat-value">—</div></div>
                </div>
                <button id="limited-promo-activate" class="limited-promo-action" type="button" disabled>Загрузка…</button>
                <div id="limited-promo-status" class="limited-promo-status" aria-live="polite">Подождите пару секунд.</div>
                <div class="limited-promo-footnote">Сумма начисления и лимит проверяются сервером.</div>
            </section>
        `;
        document.querySelector(".app")?.appendChild(view);
        document.getElementById("limited-promo-back")?.addEventListener("click", showWalletFromPromo);
        return view;
    }

    function hideMainViews() {
        ["loading-view", "wallet-view", "earn-view", "owner-view", "spend-view", "adv-profile-view", "adv-notifications-view", "appeals-view", "privacy-view", "about-view"].forEach((id) => {
            document.getElementById(id)?.classList.add("hidden");
        });
    }

    function showPromoView() {
        const view = promoView();
        hideMainViews();
        view.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tg?.BackButton?.show?.();
    }

    function showWalletFromPromo() {
        window.__nyanPromoDeepLinkActive = false;
        document.getElementById("limited-promo-view")?.classList.add("hidden");
        document.getElementById("wallet-view")?.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tg?.BackButton?.hide?.();
    }

    function setPromoStatus(text, type = "") {
        const node = document.getElementById("limited-promo-status");
        if (!node) return;
        node.textContent = text;
        node.className = "limited-promo-status" + (type ? " " + type : "");
    }

    function renderPromo(promo) {
        document.getElementById("limited-promo-title").textContent = promo.title || "Лимитированный бонус";
        document.getElementById("limited-promo-reward").textContent = `+${promo.reward_amount} 🐾`;
        document.getElementById("limited-promo-description").textContent = promo.description || "Бонус Nyan Wallet";
        document.getElementById("limited-promo-limit").textContent = String(promo.max_uses ?? "—");
        document.getElementById("limited-promo-left").textContent = String(promo.remaining ?? 0);

        const button = document.getElementById("limited-promo-activate");
        if (!button) return;
        button.disabled = false;
        button.textContent = `Забрать ${promo.reward_amount} 🐾`;

        if (promo.already_used) {
            button.disabled = true;
            button.textContent = "Уже активировано";
            setPromoStatus("Вы уже активировали это промо", "success");
        } else if (promo.status === "exhausted") {
            button.disabled = true;
            button.textContent = "Активации закончились";
            setPromoStatus("Все активации уже забраны", "error");
        } else if (promo.status !== "active") {
            button.disabled = true;
            button.textContent = "Промо недоступно";
            setPromoStatus("Промо больше недоступно", "error");
        } else {
            setPromoStatus(`Доступно только ${promo.max_uses} активаций. Осталось: ${promo.remaining}`);
        }
    }

    async function loadLimitedPromo(slug) {
        showPromoView();
        const button = document.getElementById("limited-promo-activate");
        if (!tg?.initData) {
            if (button) {
                button.disabled = true;
                button.textContent = "Откройте через Telegram";
            }
            setPromoStatus("Эта страница работает только внутри Telegram Mini App.", "error");
            return;
        }
        try {
            const response = await fetch(`${API_BASE}/api/limited-promos/${encodeURIComponent(slug)}`, { headers: headers(), cache: "no-store" });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Промо не найдено");
            renderPromo(data.promo);
            button?.addEventListener("click", () => activateLimitedPromo(slug), { once: false });
        } catch (error) {
            if (button) {
                button.disabled = true;
                button.textContent = "Промо недоступно";
            }
            setPromoStatus(error?.message || "Не удалось загрузить промо", "error");
        }
    }

    async function activateLimitedPromo(slug) {
        const button = document.getElementById("limited-promo-activate");
        if (!button || button.disabled) return;
        button.disabled = true;
        button.textContent = "Активируем…";
        setPromoStatus("Отправляем запрос на сервер.");
        try {
            const response = await fetch(`${API_BASE}/api/limited-promos/${encodeURIComponent(slug)}/activate`, {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({}),
            });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось активировать промо");
            const balance = document.getElementById("balance");
            if (balance && balance.textContent !== "∞") balance.textContent = String(data.balance);
            renderPromo(data.promo);
            button.disabled = true;
            button.textContent = "Бонус получен";
            setPromoStatus(`Промо активировано. +${data.reward} 🐾 начислено`, "success");
            tg?.HapticFeedback?.notificationOccurred?.("success");
        } catch (error) {
            setPromoStatus(error?.message || "Не удалось активировать промо", "error");
            button.disabled = false;
            button.textContent = "Повторить";
            tg?.HapticFeedback?.notificationOccurred?.("error");
        }
    }

    function start() {
        patchReferralText();
        const observer = new MutationObserver(patchReferralText);
        observer.observe(document.body, { childList: true, subtree: true });

        const slug = readStartParam();
        if (slug) {
            window.__nyanPromoDeepLinkActive = true;
            void loadLimitedPromo(slug);
            tg?.BackButton?.onClick?.(() => {
                if (!document.getElementById("limited-promo-view")?.classList.contains("hidden")) {
                    showWalletFromPromo();
                }
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }
})();
