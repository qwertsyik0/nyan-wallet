(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const activateButton = document.getElementById("promo-activate");
    const walletButton = document.getElementById("promo-wallet");
    const status = document.getElementById("promo-status");
    const limitLabel = document.getElementById("promo-limit");

    let promoAvailable = false;
    let requestInFlight = false;

    tg?.ready?.();
    tg?.expand?.();

    function headers() {
        return { "X-Telegram-Init-Data": tg?.initData || "" };
    }

    async function readJson(response) {
        try { return await response.json(); } catch (_) { return {}; }
    }

    function setStatus(text, type = "") {
        status.textContent = text || "";
        status.className = "promo-status" + (type ? " " + type : "");
    }

    function setButton(text, enabled) {
        activateButton.textContent = text;
        activateButton.disabled = !enabled;

        if (!tg?.MainButton) return;
        tg.MainButton.setText(text);
        if (enabled) tg.MainButton.enable?.();
        else tg.MainButton.disable?.();
        tg.MainButton.show?.();
    }

    function lockAsUsed() {
        promoAvailable = false;
        setButton("Бонус уже получен", false);
        tg?.MainButton?.hide?.();
    }

    function lockAsExhausted() {
        promoAvailable = false;
        setButton("Лимит исчерпан", false);
        tg?.MainButton?.hide?.();
    }

    async function warmUp() {
        if (!tg?.initData) {
            setStatus("Откройте эту страницу через Telegram Mini App.", "error");
            setButton("Откройте через Telegram", false);
            return;
        }

        try {
            const response = await fetch(API + "/api/limited-promos/nyan200", {
                headers: headers(),
                cache: "no-store",
            });
            const data = await readJson(response);
            if (!response.ok) {
                throw new Error(data?.detail || "Не удалось проверить промокод");
            }

            const promo = data?.promo || {};
            const remaining = Math.max(0, Number(promo.remaining || 0));
            limitLabel.textContent = remaining + " из 10";

            if (promo.already_used) {
                setStatus("Вы уже активировали этот промокод и получили +200 🐾.", "success");
                lockAsUsed();
                return;
            }

            if (promo.status !== "active" || remaining <= 0) {
                setStatus("Все 10 активаций уже забраны.", "error");
                lockAsExhausted();
                return;
            }

            promoAvailable = true;
            setStatus("Осталось активаций: " + remaining + " из 10.");
            setButton("Забрать 200 🐾", true);
        } catch (error) {
            promoAvailable = false;
            setStatus(error?.message || "Не удалось проверить промокод.", "error");
            setButton("Повторить проверку", true);
        }
    }

    async function activate() {
        if (!tg?.initData || requestInFlight) return;
        if (!promoAvailable) {
            await warmUp();
            return;
        }

        requestInFlight = true;
        setButton("Активируем…", false);
        tg?.MainButton?.showProgress?.();
        setStatus("");

        try {
            const response = await fetch(API + "/api/limited-promos/nyan200/activate", {
                method: "POST",
                headers: headers(),
            });
            const data = await readJson(response);

            if (!response.ok) {
                const detail = typeof data?.detail === "string"
                    ? data.detail
                    : "Не удалось активировать промокод";
                if (response.status === 409) {
                    setStatus("Вы уже активировали этот промокод.", "success");
                    lockAsUsed();
                    return;
                }
                if (response.status === 410) {
                    setStatus("Все 10 активаций уже забраны.", "error");
                    lockAsExhausted();
                    return;
                }
                throw new Error(detail);
            }

            const remaining = Math.max(0, Number(data?.promo?.remaining || 0));
            limitLabel.textContent = remaining + " из 10";
            setStatus("Готово! На баланс начислено +200 🐾.", "success");
            lockAsUsed();
            tg?.HapticFeedback?.notificationOccurred?.("success");
        } catch (error) {
            promoAvailable = true;
            setStatus(error?.message || "Не удалось активировать промокод.", "error");
            setButton("Повторить", true);
            tg?.HapticFeedback?.notificationOccurred?.("error");
        } finally {
            requestInFlight = false;
            tg?.MainButton?.hideProgress?.();
        }
    }

    activateButton?.addEventListener("click", activate);
    tg?.MainButton?.onClick?.(activate);

    walletButton?.addEventListener("click", () => {
        window.location.href = "https://qwertsyik0.github.io/nyan-wallet/";
    });

    void warmUp();
})();
