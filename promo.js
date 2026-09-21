(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const CODE_PATTERN = /^[A-Z0-9_-]{2,32}$/;
    const codeInput = document.getElementById("promo-code");
    const activateButton = document.getElementById("promo-activate");
    const walletButton = document.getElementById("promo-wallet");
    const status = document.getElementById("promo-status");
    const defaultCode = document.body?.dataset?.defaultPromoCode || "NYANFLASH600";

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

    function normalizeCode(value) {
        const code = String(value || "").trim().toUpperCase();
        return CODE_PATTERN.test(code) ? code : null;
    }

    function promoCode() {
        try {
            const url = new URL(window.location.href);
            const fromQuery = url.searchParams.get("code");
            return normalizeCode(fromQuery) || normalizeCode(defaultCode);
        } catch (_) {
            return normalizeCode(defaultCode);
        }
    }

    function setStatus(text, type = "") {
        if (!status) return;
        status.textContent = text || "";
        status.className = "promo-status" + (type ? " " + type : "");
    }

    function setTelegramMainButton(enabled) {
        if (!tg?.MainButton) return;
        tg.MainButton.setText(enabled ? "Забрать 600 🐾" : "Откройте в Telegram");
        if (enabled) tg.MainButton.enable?.();
        else tg.MainButton.disable?.();
        tg.MainButton.show?.();
    }

    async function warmUp() {
        const code = promoCode();
        if (!code) {
            if (codeInput) codeInput.value = "—";
            if (activateButton) {
                activateButton.disabled = true;
                activateButton.textContent = "Промокод недоступен";
            }
            setTelegramMainButton(false);
            setStatus("Некорректная ссылка на промокод.", "error");
            return;
        }

        if (codeInput) codeInput.value = code;

        if (!tg?.initData) {
            if (activateButton) {
                activateButton.disabled = true;
                activateButton.textContent = "Откройте через Telegram";
            }
            setTelegramMainButton(false);
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
                if (activateButton) {
                    activateButton.disabled = true;
                    activateButton.textContent = "Технические работы";
                }
                setTelegramMainButton(false);
                setStatus(data?.maintenance?.message || "Сейчас идут технические работы.", "error");
                return;
            }
        } catch (_) {
            // If Render is waking up, activation below can still retry through the global fetch layer.
        }

        if (activateButton) {
            activateButton.disabled = false;
            activateButton.textContent = "Забрать 600 🐾";
        }
        setTelegramMainButton(true);
        setStatus("осталось всего 5 мест. кто успел, тот забрал.");
    }

    async function activate() {
        const code = promoCode();
        if (!code || !tg?.initData || activateButton?.disabled) return;

        if (activateButton) {
            activateButton.disabled = true;
            activateButton.textContent = "Активируем…";
        }
        tg?.MainButton?.showProgress?.();
        tg?.MainButton?.disable?.();
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
            if (activateButton) activateButton.textContent = "Бонус получен";
            tg?.MainButton?.setText?.("Бонус получен");
            tg?.HapticFeedback?.notificationOccurred?.("success");
        } catch (error) {
            setStatus(error?.message || "Не удалось активировать промокод.", "error");
            if (activateButton) {
                activateButton.disabled = false;
                activateButton.textContent = "Повторить";
            }
            tg?.MainButton?.setText?.("Повторить");
            tg?.MainButton?.enable?.();
            tg?.HapticFeedback?.notificationOccurred?.("error");
        } finally {
            tg?.MainButton?.hideProgress?.();
        }
    }

    activateButton?.addEventListener("click", activate);
    tg?.MainButton?.onClick?.(activate);

    walletButton?.addEventListener("click", () => {
        window.location.href = "./?ui_v=20260921-7";
    });

    void warmUp();
})();
