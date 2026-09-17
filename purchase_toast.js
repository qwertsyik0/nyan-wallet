(() => {
    const originalFetch = window.fetch.bind(window);
    const shownRequests = new Set();

    function ensureStyles() {
        if (document.getElementById("nyan-purchase-toast-styles")) return;

        const style = document.createElement("style");
        style.id = "nyan-purchase-toast-styles";
        style.textContent = `
            .nyan-purchase-toast {
                position: fixed;
                top: max(18px, env(safe-area-inset-top));
                left: 50%;
                transform: translateX(-50%);
                z-index: 99999;
                width: min(calc(100vw - 28px), 460px);
                padding: 18px 48px 18px 18px;
                border: 1px solid #efd5e1;
                border-radius: 22px;
                background: rgba(255, 250, 252, 0.98);
                box-shadow: 0 18px 48px rgba(137, 41, 82, 0.16);
                color: #6d304a;
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                animation: nyanPurchaseToastIn .22s ease-out;
            }

            .nyan-purchase-toast-title {
                padding-right: 6px;
                font-size: 16px;
                font-weight: 700;
                color: #8f2955;
            }

            .nyan-purchase-toast-text {
                margin-top: 7px;
                font-size: 13px;
                line-height: 1.5;
                color: #83536a;
            }

            .nyan-purchase-toast-meta {
                margin-top: 8px;
                font-size: 11px;
                color: #b08498;
            }

            .nyan-purchase-toast-close {
                position: absolute;
                top: 11px;
                right: 11px;
                display: grid;
                place-items: center;
                width: 32px;
                height: 32px;
                padding: 0;
                border: 0;
                border-radius: 50%;
                background: #fff0f6;
                color: #922954;
                font-size: 22px;
                font-weight: 400;
                line-height: 1;
                cursor: pointer;
            }

            .nyan-purchase-toast-close:active {
                transform: scale(.96);
            }

            .nyan-purchase-toast.closing {
                animation: nyanPurchaseToastOut .16s ease-in forwards;
            }

            @keyframes nyanPurchaseToastIn {
                from { opacity: 0; transform: translate(-50%, -12px) scale(.98); }
                to { opacity: 1; transform: translate(-50%, 0) scale(1); }
            }

            @keyframes nyanPurchaseToastOut {
                from { opacity: 1; transform: translate(-50%, 0) scale(1); }
                to { opacity: 0; transform: translate(-50%, -8px) scale(.985); }
            }
        `;
        document.head.appendChild(style);
    }

    function closeToast(toast) {
        if (!toast || toast.classList.contains("closing")) return;
        toast.classList.add("closing");
        window.setTimeout(() => toast.remove(), 170);
    }

    function showPurchaseToast(request) {
        if (!request?.id || shownRequests.has(request.id)) return;
        shownRequests.add(request.id);
        ensureStyles();

        document.querySelector(".nyan-purchase-toast")?.remove();

        const toast = document.createElement("div");
        toast.className = "nyan-purchase-toast";
        toast.setAttribute("role", "status");
        toast.setAttribute("aria-live", "polite");

        const close = document.createElement("button");
        close.type = "button";
        close.className = "nyan-purchase-toast-close";
        close.setAttribute("aria-label", "Закрыть");
        close.textContent = "×";
        close.addEventListener("click", () => closeToast(toast));

        const title = document.createElement("div");
        title.className = "nyan-purchase-toast-title";
        title.textContent = "Покупка оформлена";

        const text = document.createElement("div");
        text.className = "nyan-purchase-toast-text";
        text.textContent = `Вы приобрели «${request.reward_title}». Выдадим приз в ближайшее время. Спасибо, что пользуетесь Nyan Wallet.`;

        const meta = document.createElement("div");
        meta.className = "nyan-purchase-toast-meta";
        meta.textContent = `Заявка #${request.id}`;

        toast.append(close, title, text, meta);
        document.body.appendChild(toast);
        window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred?.("success");
    }

    window.fetch = async (...args) => {
        const response = await originalFetch(...args);

        try {
            const request = args[0];
            const url = typeof request === "string" ? request : request?.url || "";
            const options = args[1] || {};
            const method = String(options.method || request?.method || "GET").toUpperCase();

            if (
                method === "POST" &&
                response.ok &&
                /\/api\/rewards\/\d+\/request(?:\?|$)/.test(url)
            ) {
                const data = await response.clone().json();
                if (data?.request) {
                    window.setTimeout(() => showPurchaseToast(data.request), 0);
                }
            }
        } catch (_) {
            // Визуальное уведомление не должно влиять на саму покупку.
        }

        return response;
    };
})();