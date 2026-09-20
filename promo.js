(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const codeInput = document.getElementById("promo-code");
    const activateButton = document.getElementById("promo-activate");
    const walletButton = document.getElementById("promo-wallet");
    const status = document.getElementById("promo-status");

    tg?.ready?.();
    tg?.expand?.();

    function headers(json = false) {
        const result = {
            "X-Telegram-Init-Data": tg?.initData || "",
        };
        if (json) result["Content-Type"] = "application/json";
        return result;
    }

    async function readJson(response) {
        try {
            return await response.json();
        } catch (_) {
            return {};
        }
    }

    function promoCode() {
        try {
            const raw = new URL(window.location.href).searchParams.get("code") || "";
            const value = raw.trim().toUpperCase();
            return /^[A-Z0-9_-]{2,32}$/.test(value) ? value : null;
        } catch (_) {
            return null;
        }
    }

    function setStatus(text, type = "") {
        status.textContent = text || "";
        status.className = "promo-status" + (type ? " " + type : "");
    }

    async function warmUp() {
        const code = promoCode();
        if (!code) {
            codeInput.value = "—";
            activateButton.disabled = true;
            activateButton.textContent = "Промокод недоступен";
            setStatus("Некорректная ссылка на промокод.", "error");
            return;
        }

        codeInput.value = code;

        if (!tg?.initData) {
            activateButton.disabled = true;
            activateButton.textContent = "Откройте через Telegram";
            setStatus("Эта страница должна быть открыта как Mini App в Telegram.", "error");
            return;
        }

        try {
            const response = await fetch(API + "/api/maintenance/status", {
                headers: headers(),
                cache: "no-store",
            });
            const data = await readJson(response);

            if (response.ok && data?.blocked) {
                activateButton.disabled = true;
                activateButton.textContent = "Технические работы";
                setStatus(data?.maintenance?.message || "Сейчас идут технические работы.", "error");
                return;
            }
        } catch (_) {
            // The global read retry layer handles cold starts. If it still fails,
            // allow manual activation so the user can retry without reopening.
        }

        activateButton.disabled = false;
        activateButton.textContent = "Активировать";
        setStatus("");
    }

    async function activate() {
        const code = promoCode();
        if (!code || !tg?.initData || activateButton.disabled) return;

        activateButton.disabled = true;
        activateButton.textContent = "Активируем…";
        setStatus("");

        try {
            const response = await fetch(API + "/api/promo/redeem", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({ code }),
            });
            const data = await readJson(response);

            if (!response.ok) {
                const detail = typeof data?.detail === "string"
                    ? data.detail
                    : "Не удалось активировать промокод";
                throw new Error(detail);
            }

            const reward = Number(data?.reward || 0);
            setStatus(
                reward > 0
                    ? `Готово. Начислено +${reward} 🐾`
                    : "Промокод успешно активирован.",
                "success",
            );
            activateButton.textContent = "Бонус получен";
            tg?.HapticFeedback?.notificationOccurred?.("success");
        } catch (error) {
            setStatus(error?.message || "Не удалось активировать промокод.", "error");
            activateButton.disabled = false;
            activateButton.textContent = "Повторить";
            tg?.HapticFeedback?.notificationOccurred?.("error");
        }
    }

    activateButton?.addEventListener("click", activate);

    walletButton?.addEventListener("click", () => {
        if (tg?.openTelegramLink) {
            tg.openTelegramLink("https://t.me/nyancash_bot?startapp=wallet");
            return;
        }
        window.location.href = "./";
    });

    void warmUp();
})();