(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-153-76-175-145.sslip.io";
    const CODE_PATTERN = /^[A-Z0-9_-]{2,32}$/;
    const codeInput = document.getElementById("promo-code");
    const activateButton = document.getElementById("promo-activate");
    const walletButton = document.getElementById("promo-wallet");
    const status = document.getElementById("promo-status");
    const CHANNEL_URL = "https://t.me/NyanWallet";
    const bodyData = document.body?.dataset || {};
    const defaultCode = bodyData.defaultPromoCode || "NYANFLASH600";
    const lockPromoCode = bodyData.promoLockCode === "true";
    const configuredReward = Number.parseInt(bodyData.promoReward || "600", 10);
    const rewardAmount = Number.isInteger(configuredReward) && configuredReward > 0 ? configuredReward : 600;
    const configuredLimit = Number.parseInt(bodyData.promoLimit || "0", 10);
    const promoLimit = Number.isInteger(configuredLimit) && configuredLimit > 0 ? configuredLimit : null;

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
        if (lockPromoCode) return normalizeCode(defaultCode);
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

    function showSubscriptionRequired(message = "Вы не подписаны на канал.") {
        if (!status) return;
        status.className = "promo-status error";
        status.innerHTML = "";

        const text = document.createElement("div");
        text.textContent = message;

        const actions = document.createElement("div");
        actions.style.display = "grid";
        actions.style.gap = "8px";
        actions.style.marginTop = "12px";

        const subscribe = document.createElement("button");
        subscribe.type = "button";
        subscribe.className = "promo-activate";
        subscribe.textContent = "Подписаться";
        subscribe.addEventListener("click", () => {
            if (tg?.openTelegramLink) tg.openTelegramLink(CHANNEL_URL);
            else window.open(CHANNEL_URL, "_blank", "noopener,noreferrer");
        });

        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "promo-wallet";
        retry.textContent = "Попробовать снова";
        retry.addEventListener("click", () => {
            if (activateButton) {
                activateButton.disabled = false;
                activateButton.textContent = `Забрать ${rewardAmount} 🐾`;
            }
            void activate();
        });

        actions.append(subscribe, retry);
        status.append(text, actions);
    }

    function limitText() {
        if (promoLimit === 1) return "осталась 1 активация. кто успел, тот забрал.";
        if (promoLimit) return `осталось всего ${promoLimit} активаций. кто успел, тот забрал.`;
        return "промокод готов к активации.";
    }

    function setTelegramMainButton(enabled) {
        if (!tg?.MainButton) return;
        tg.MainButton.setText(enabled ? `Забрать ${rewardAmount} 🐾` : "Откройте в Telegram");
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
            activateButton.textContent = `Забрать ${rewardAmount} 🐾`;
        }
        setTelegramMainButton(true);
        setStatus(limitText());
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
                const rawDetail = data?.detail;
                const detailCode = typeof rawDetail === "object" ? rawDetail?.code : null;
                const detailMessage = typeof rawDetail === "object"
                    ? rawDetail?.message
                    : rawDetail;

                if (response.status === 403 && detailCode === "subscription_required") {
                    showSubscriptionRequired("Вы не подписаны на канал.");
                    if (activateButton) {
                        activateButton.disabled = false;
                        activateButton.textContent = `Забрать ${rewardAmount} 🐾`;
                    }
                    tg?.MainButton?.setText?.("Попробовать снова");
                    tg?.MainButton?.enable?.();
                    return;
                }

                throw new Error(detailMessage || "Не удалось активировать промокод");
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
        window.location.href = "./";
    });

    void warmUp();
})();
