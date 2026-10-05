(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const OWNER_TELEGRAM_ID = 6289461565;

    let shown = false;

    function headers() {
        return { "X-Telegram-Init-Data": tg?.initData || "" };
    }

    function ensureStyles() {
        if (document.getElementById("nyan-ban-style")) return;
        const style = document.createElement("style");
        style.id = "nyan-ban-style";
        style.textContent = `
            #nyan-ban-overlay{
                position:fixed;
                inset:0;
                z-index:2147483647;
                display:flex;
                align-items:center;
                justify-content:center;
                padding:24px 18px max(18px, env(safe-area-inset-bottom));
                background:
                    radial-gradient(circle at 50% 0%, rgba(255,235,244,.96), rgba(255,255,255,.985) 48%, #fff 100%);
                color:#6d304a;
                font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
            }
            #nyan-ban-overlay[hidden]{display:none}
            .nyan-ban-card{
                width:min(100%,430px);
                padding:26px 20px 20px;
                border:1px solid #efd8e2;
                border-radius:28px;
                background:rgba(255,250,252,.98);
                box-shadow:0 22px 60px rgba(92,27,57,.13);
                text-align:center;
            }
            .nyan-ban-icon{
                display:grid;
                place-items:center;
                width:62px;
                height:62px;
                margin:0 auto 16px;
                border-radius:21px;
                background:#fff0f6;
                font-size:29px;
            }
            .nyan-ban-title{
                color:#842b50;
                font-size:27px;
                line-height:1.05;
                font-weight:900;
                letter-spacing:-.035em;
            }
            .nyan-ban-text{
                margin-top:10px;
                color:#98667b;
                font-size:13px;
                line-height:1.5;
            }
            .nyan-ban-reason{
                margin-top:16px;
                padding:13px 14px;
                border:1px solid #efd9e3;
                border-radius:17px;
                background:#fff;
                color:#7b3b57;
                font-size:12px;
                line-height:1.45;
                text-align:left;
            }
            .nyan-ban-reason strong{
                display:block;
                margin-bottom:4px;
                color:#9a2c59;
                font-size:10px;
                text-transform:uppercase;
                letter-spacing:.05em;
            }
            .nyan-ban-appeal{
                display:inline-block;
                margin-top:22px;
                border:0;
                padding:0;
                background:none;
                color:#b18397;
                font:inherit;
                font-size:10px;
                text-decoration:underline;
                text-underline-offset:3px;
                cursor:pointer;
            }
        `;
        document.head.appendChild(style);
    }

    function ensureOverlay() {
        ensureStyles();
        let overlay = document.getElementById("nyan-ban-overlay");
        if (overlay) return overlay;

        overlay = document.createElement("div");
        overlay.id = "nyan-ban-overlay";
        overlay.hidden = true;
        overlay.innerHTML = `
            <section class="nyan-ban-card" role="alert" aria-live="assertive">
                <div class="nyan-ban-icon" aria-hidden="true">🚫</div>
                <div class="nyan-ban-title">Аккаунт заблокирован</div>
                <div class="nyan-ban-text">
                    Доступ к Nyan Wallet для этого аккаунта ограничен.
                </div>
                <div id="nyan-ban-reason" class="nyan-ban-reason" hidden></div>
                <button id="nyan-ban-appeal" class="nyan-ban-appeal" type="button">
                    Обжаловать решение
                </button>
            </section>
        `;
        document.body.appendChild(overlay);

        overlay.querySelector("#nyan-ban-appeal")?.addEventListener("click", () => {
            const deepLink = `tg://user?id=${OWNER_TELEGRAM_ID}`;
            try {
                window.location.href = deepLink;
            } catch (_) {
                try { tg?.openLink?.(deepLink); } catch (_) {}
            }
        });

        return overlay;
    }

    function showBlocked(reason) {
        const overlay = ensureOverlay();
        const reasonBox = overlay.querySelector("#nyan-ban-reason");

        if (reason) {
            reasonBox.innerHTML = "";
            const title = document.createElement("strong");
            title.textContent = "Причина";
            const text = document.createElement("span");
            text.textContent = reason;
            reasonBox.append(title, text);
            reasonBox.hidden = false;
        } else {
            reasonBox.hidden = true;
            reasonBox.textContent = "";
        }

        overlay.hidden = false;
        document.documentElement.style.overflow = "hidden";
        document.body.style.overflow = "hidden";
        window.__nyanAccountBlocked = true;
        shown = true;

        tg?.BackButton?.hide?.();
        tg?.MainButton?.hide?.();
        tg?.SecondaryButton?.hide?.();
    }

    async function checkBanStatus() {
        if (!tg?.initData) return false;

        try {
            const response = await fetch(API + "/api/ban/status", {
                headers: headers(),
                cache: "no-store",
            });
            const data = await response.json().catch(() => ({}));

            if (!response.ok) {
                throw new Error(data?.detail || "ban status check failed");
            }

            if (data.blocked === true) {
                showBlocked(data.reason || null);
                return true;
            }

            window.__nyanAccountBlocked = false;
            return false;
        } catch (error) {
            console.warn("Nyan ban status check failed:", error);
            return false;
        }
    }

    window.__nyanCheckBanStatus = checkBanStatus;

    function start() {
        ensureOverlay();
        void checkBanStatus();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }

    window.addEventListener("pageshow", () => {
        if (!shown) void checkBanStatus();
    });
})();
