(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const activateButton = document.getElementById("promo-activate");
    const walletButton = document.getElementById("promo-wallet");
    const terms = document.getElementById("promo-terms");
    const status = document.getElementById("promo-status");

    tg?.ready?.();
    tg?.expand?.();

    function headers(json = false) {
        const out = { "X-Telegram-Init-Data": tg?.initData || "" };
        if (json) out["Content-Type"] = "application/json";
        return out;
    }

    async function readJson(response) {
        try { return await response.json(); } catch (_) { return {}; }
    }

    function setStatus(text, type = "") {
        status.textContent = text || "";
        status.className = "promo-status" + (type ? " " + type : "");
    }

    function syncButton() {
        const accepted = Boolean(terms?.checked);
        activateButton.disabled = !accepted || !tg?.initData;
        activateButton.textContent = !tg?.initData
            ? "Откройте через Telegram"
            : accepted
                ? "Забрать 300 🐾"
                : "Подтвердите условие";

        if (tg?.MainButton) {
            tg.MainButton.setText(accepted ? "Забрать 300 🐾" : "Подтвердите условие");
            if (accepted && tg.initData) tg.MainButton.enable?.();
            else tg.MainButton.disable?.();
            tg.MainButton.show?.();
        }
    }

    async function warmUp() {
        if (!tg?.initData) {
            setStatus("Эта страница должна быть открыта как Mini App в Telegram.", "error");
            syncButton();
            return;
        }

        try {
            const response = await fetch(API + "/api/promo/nyan300/status", {
                headers: headers(),
                cache: "no-store",
            });
            const data = await readJson(response);

            if (!response.ok) {
                throw new Error(data?.detail || "Не удалось проверить промокод");
            }

            if (data?.fee?.processed_at) {
                setStatus(
                    `Промокод уже использован. Через час было списано ${data.fee.applied_amount || 0} 🐾.`,
                    "success",
                );
                activateButton.disabled = true;
                activateButton.textContent = "Промокод использован";
                tg?.MainButton?.hide?.();
                return;
            }

            if (data?.fee?.due_at) {
                const due = new Date(data.fee.due_at);
                setStatus(
                    `Промокод уже активирован. Списание 10% запланировано на ${due.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})}.`,
                    "success",
                );
                activateButton.disabled = true;
                activateButton.textContent = "Бонус получен";
                tg?.MainButton?.hide?.();
                return;
            }

            if (!data.available) {
                setStatus("Лимит из 30 активаций уже исчерпан.", "error");
                activateButton.disabled = true;
                activateButton.textContent = "Лимит исчерпан";
                tg?.MainButton?.hide?.();
                return;
            }

            const remaining = Math.max(0, Number(data.max_uses || 30) - Number(data.uses_count || 0));
            setStatus(`Доступно активаций: ${remaining} из 30.`);
            syncButton();
        } catch (error) {
            setStatus(error?.message || "Не удалось проверить промокод.", "error");
            syncButton();
        }
    }

    async function activate() {
        if (!tg?.initData || !terms?.checked || activateButton.disabled) return;

        activateButton.disabled = true;
        activateButton.textContent = "Активируем…";
        tg?.MainButton?.showProgress?.();
        tg?.MainButton?.disable?.();
        setStatus("");

        try {
            const response = await fetch(API + "/api/promo/nyan300/redeem", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({ accepted_terms: true }),
            });
            const data = await readJson(response);

            if (!response.ok) {
                throw new Error(
                    typeof data?.detail === "string"
                        ? data.detail
                        : "Не удалось активировать промокод"
                );
            }

            setStatus(
                "Готово: +300 🐾. Через 1 час будет списано 10% от вашего текущего баланса.",
                "success",
            );
            activateButton.textContent = "Бонус получен";
            tg?.MainButton?.hide?.();
            tg?.HapticFeedback?.notificationOccurred?.("success");
        } catch (error) {
            setStatus(error?.message || "Не удалось активировать промокод.", "error");
            activateButton.disabled = false;
            activateButton.textContent = "Повторить";
            tg?.MainButton?.setText?.("Повторить");
            tg?.MainButton?.enable?.();
            tg?.HapticFeedback?.notificationOccurred?.("error");
        } finally {
            tg?.MainButton?.hideProgress?.();
        }
    }

    terms?.addEventListener("change", syncButton);
    activateButton?.addEventListener("click", activate);
    tg?.MainButton?.onClick?.(activate);

    walletButton?.addEventListener("click", () => {
        window.location.href = "https://qwertsyik0.github.io/nyan-wallet/";
    });

    void warmUp();
})();
