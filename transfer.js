(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const MAX_AMOUNT = 100000;
    const CLIENT_VERSION = "20260920-4";

    let canonicalRecipient = null;
    let pendingIdempotencyKey = null;
    let qrObjectUrl = null;

    function headers(json = false) {
        const result = { "X-Telegram-Init-Data": tg?.initData || "" };
        if (json) result["Content-Type"] = "application/json";
        return result;
    }

    async function json(response) {
        try {
            return await response.json();
        } catch (_) {
            return {};
        }
    }

    async function api(path, options = {}, timeoutMs = 12000) {
        const method = String(options?.method || "GET").toUpperCase();
        const effectiveTimeout = ["GET", "HEAD", "OPTIONS"].includes(method)
            ? Math.max(timeoutMs, 40000)
            : timeoutMs;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), effectiveTimeout);
        try {
            const response = await fetch(API + path, { ...options, signal: controller.signal });
            const data = await json(response);
            if (!response.ok) {
                if (response.status === 503 && data?.detail === "maintenance") {
                    window.dispatchEvent(new CustomEvent("nyan-maintenance-required", {
                        detail: data.maintenance || {},
                    }));
                    const error = new Error("Сейчас идут технические работы.");
                    error.status = response.status;
                    throw error;
                }
                const detail = typeof data?.detail === "string"
                    ? data.detail
                    : "Операция не выполнена";
                const error = new Error(detail);
                error.status = response.status;
                throw error;
            }
            return data;
        } catch (error) {
            if (error?.name === "AbortError") {
                throw new Error("Сервер не ответил вовремя. Можно безопасно повторить операцию.");
            }
            throw error;
        } finally {
            clearTimeout(timeout);
        }
    }

    function createIdempotencyKey() {
        if (window.crypto?.randomUUID) {
            return window.crypto.randomUUID().replaceAll("-", "_");
        }
        if (!window.crypto?.getRandomValues) {
            throw new Error("Безопасный генератор случайных чисел недоступен. Обновите Telegram и повторите.");
        }
        const bytes = new Uint8Array(24);
        window.crypto.getRandomValues(bytes);
        return Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
    }

    function normalizePaymentStartParam(raw) {
        const value = String(raw || "").trim();
        if (!value) return null;

        const match = value.match(/^pay_(NW[A-F0-9]{20}|NYAN\d{12})$/i);
        if (match) return match[1].toUpperCase();

        if (/^(NW[A-F0-9]{20}|NYAN\d{12})$/i.test(value)) {
            return value.toUpperCase();
        }

        return null;
    }

    function pendingPaymentAddress() {
        const values = [];

        try {
            const url = new URL(window.location.href);
            values.push(url.searchParams.get("pay"));
            values.push(url.searchParams.get("tgWebAppStartParam"));
            values.push(url.searchParams.get("startapp"));

            const rawHash = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
            const hashParams = new URLSearchParams(rawHash);
            values.push(hashParams.get("pay"));
            values.push(hashParams.get("tgWebAppStartParam"));
            values.push(hashParams.get("startapp"));
        } catch (_) {}

        try {
            const initParams = new URLSearchParams(tg?.initData || "");
            values.push(initParams.get("start_param"));
        } catch (_) {}

        values.push(tg?.initDataUnsafe?.start_param || "");

        try {
            const stored = sessionStorage.getItem("nyan_pending_payment");
            if (stored) values.push(stored);
        } catch (_) {}

        for (const raw of values) {
            const normalized = normalizePaymentStartParam(raw);
            if (!normalized) continue;

            try {
                sessionStorage.setItem("nyan_pending_payment", normalized);
            } catch (_) {}

            return normalized;
        }

        return null;
    }

    const initialPendingPayment = pendingPaymentAddress();
    window.__nyanPaymentDeepLinkActive = Boolean(initialPendingPayment);

    async function reportLaunchDiagnostic() {
        if (!tg?.initData) return;

        const payload = {
            client_version: CLIENT_VERSION,
            detected_target: initialPendingPayment,
            unsafe_start_param: tg?.initDataUnsafe?.start_param || null,
            init_start_param: null,
            query_startapp: null,
            query_tg_start: null,
            hash_startapp: null,
            hash_tg_start: null,
        };

        try {
            const initParams = new URLSearchParams(tg.initData);
            payload.init_start_param = initParams.get("start_param");
        } catch (_) {}

        try {
            const url = new URL(window.location.href);
            payload.query_startapp = url.searchParams.get("startapp");
            payload.query_tg_start = url.searchParams.get("tgWebAppStartParam");
            const rawHash = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
            const hashParams = new URLSearchParams(rawHash);
            payload.hash_startapp = hashParams.get("startapp");
            payload.hash_tg_start = hashParams.get("tgWebAppStartParam");
        } catch (_) {}

        try {
            await fetch(API + "/api/client/launch", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify(payload),
                keepalive: true,
            });
        } catch (_) {}
    }

    void reportLaunchDiagnostic();

    function hideMainViews() {
        document.querySelectorAll(".app > main").forEach(node => node.classList.add("hidden"));
    }

    function showWallet() {
        document.getElementById("transfer-view")?.classList.add("hidden");
        document.getElementById("wallet-view")?.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tg?.BackButton?.hide?.();
    }

    function openTransfer(prefill = null) {
        hideMainViews();
        document.getElementById("transfer-view")?.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tg?.BackButton?.show?.();

        if (prefill) {
            const target = document.getElementById("transfer-target");
            if (target) target.value = prefill;
        }
        resetRecipient();
        tg?.HapticFeedback?.impactOccurred?.("light");
    }

    function resetRecipient() {
        canonicalRecipient = null;
        pendingIdempotencyKey = null;
        const preview = document.getElementById("transfer-recipient-preview");
        const send = document.getElementById("transfer-send");
        const resolve = document.getElementById("transfer-resolve");
        const change = document.getElementById("transfer-change");
        if (preview) preview.hidden = true;
        if (send) send.hidden = true;
        if (resolve) resolve.hidden = false;
        if (change) change.hidden = true;
    }

    function setStatus(message) {
        const status = document.getElementById("transfer-status");
        if (status) status.textContent = message || "";
    }

    function amountValue() {
        const raw = document.getElementById("transfer-amount")?.value || "";
        const amount = Number(raw);
        if (!Number.isSafeInteger(amount) || amount < 1 || amount > MAX_AMOUNT) {
            throw new Error("Укажите целое количество от 1 до 100 000 🐾.");
        }
        return amount;
    }

    async function resolveRecipient() {
        const targetInput = document.getElementById("transfer-target");
        const target = String(targetInput?.value || "").trim();
        if (!target) {
            setStatus("Укажите @username, Telegram ID или адрес кошелька.");
            targetInput?.focus();
            return;
        }
        if (!tg?.initData) {
            setStatus("Откройте Nyan Wallet через Telegram.");
            return;
        }

        const button = document.getElementById("transfer-resolve");
        button.disabled = true;
        button.textContent = "Проверяем…";
        setStatus("");

        try {
            const data = await api(
                "/api/transfers/recipient?target=" + encodeURIComponent(target),
                { headers: headers() },
            );
            canonicalRecipient = data.recipient;
            pendingIdempotencyKey = null;

            const preview = document.getElementById("transfer-recipient-preview");
            preview.querySelector("strong").textContent = canonicalRecipient.label;
            preview.querySelector("span").textContent =
                canonicalRecipient.wallet_address +
                (canonicalRecipient.username ? " · @" + canonicalRecipient.username : "");
            preview.hidden = false;
            document.getElementById("transfer-send").hidden = false;
            document.getElementById("transfer-change").hidden = false;
            button.hidden = true;
            tg?.HapticFeedback?.notificationOccurred?.("success");
        } catch (error) {
            setStatus(error.message || "Не удалось найти получателя");
            tg?.HapticFeedback?.notificationOccurred?.("error");
        } finally {
            button.disabled = false;
            button.textContent = "Продолжить";
        }
    }

    async function confirmTransferText(text) {
        if (tg?.showConfirm) {
            return await new Promise(resolve => tg.showConfirm(text, resolve));
        }
        return window.confirm(text);
    }

    async function sendTransfer() {
        if (!canonicalRecipient) {
            setStatus("Сначала подтвердите получателя.");
            return;
        }

        let amount;
        try {
            amount = amountValue();
        } catch (error) {
            setStatus(error.message);
            document.getElementById("transfer-amount")?.focus();
            return;
        }

        const note = String(document.getElementById("transfer-note")?.value || "").trim();
        if (note.length > 120) {
            setStatus("Комментарий должен быть не длиннее 120 символов.");
            return;
        }

        const confirmed = await confirmTransferText(
            "Перевести " + amount + " 🐾 пользователю " + canonicalRecipient.label + "?",
        );
        if (!confirmed) return;

        try {
            if (!pendingIdempotencyKey) pendingIdempotencyKey = createIdempotencyKey();
        } catch (error) {
            setStatus(error.message || "Не удалось подготовить безопасный перевод");
            return;
        }

        const button = document.getElementById("transfer-send");
        button.disabled = true;
        button.textContent = "Переводим…";
        setStatus("Не закрывайте окно до результата.");

        try {
            const data = await api("/api/transfers", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({
                    recipient: canonicalRecipient.wallet_address_compact || canonicalRecipient.wallet_address,
                    amount,
                    note: note || null,
                    idempotency_key: pendingIdempotencyKey,
                }),
            });

            const transfer = data.transfer;
            setStatus(
                "Готово. Переведено " + transfer.amount + " 🐾. Номер операции: " + transfer.id,
            );
            tg?.HapticFeedback?.notificationOccurred?.("success");

            document.getElementById("transfer-target").value = "";
            document.getElementById("transfer-amount").value = "";
            document.getElementById("transfer-note").value = "";
            pendingIdempotencyKey = null;
            canonicalRecipient = null;
            document.getElementById("transfer-recipient-preview").hidden = true;
            button.hidden = true;
            document.getElementById("transfer-resolve").hidden = false;

            if (typeof window.loadWallet === "function") {
                await window.loadWallet();
            } else if (!transfer.sender_unlimited_balance) {
                const balance = document.getElementById("balance");
                if (balance) balance.textContent = String(transfer.sender_balance);
            }
        } catch (error) {
            setStatus(error.message || "Перевод не выполнен");
            tg?.HapticFeedback?.notificationOccurred?.("error");
            // Keep the same idempotency key. A retry after a network failure is safe.
        } finally {
            button.disabled = false;
            button.textContent = "Перевести";
        }
    }

    function closeQr() {
        const overlay = document.getElementById("wallet-qr-overlay");
        if (overlay) overlay.hidden = true;
        document.body.style.overflow = "";
        const box = document.getElementById("wallet-qr-box");
        if (box) box.replaceChildren();
        if (qrObjectUrl) {
            URL.revokeObjectURL(qrObjectUrl);
            qrObjectUrl = null;
        }
    }

    async function openQr() {
        if (!tg?.initData) {
            window.alert("Откройте Nyan Wallet через Telegram.");
            return;
        }

        const overlay = document.getElementById("wallet-qr-overlay");
        const box = document.getElementById("wallet-qr-box");
        const addressNode = document.getElementById("wallet-qr-address");
        const linkButton = document.getElementById("wallet-qr-copy-link");

        overlay.hidden = false;
        document.body.style.overflow = "hidden";
        box.replaceChildren();
        box.textContent = "Загружаем QR…";
        addressNode.textContent = "Загружаем…";
        linkButton.dataset.link = "";
        linkButton.disabled = true;

        try {
            const qrController = new AbortController();
            const qrTimeout = setTimeout(() => qrController.abort(), 15000);
            let addressData;
            let qrResponse;

            try {
                [addressData, qrResponse] = await Promise.all([
                    api("/api/wallet/address", { headers: headers() }, 15000),
                    fetch(API + "/api/wallet/qr", {
                        headers: headers(),
                        signal: qrController.signal,
                    }),
                ]);
            } finally {
                clearTimeout(qrTimeout);
            }

            if (!qrResponse.ok) {
                let detail = "Не удалось загрузить QR-код";
                try {
                    const errorData = await qrResponse.json();
                    if (qrResponse.status === 503 && errorData?.detail === "maintenance") {
                        window.dispatchEvent(new CustomEvent("nyan-maintenance-required", {
                            detail: errorData.maintenance || {},
                        }));
                        detail = "Сейчас идут технические работы.";
                    } else if (typeof errorData?.detail === "string") {
                        detail = errorData.detail;
                    }
                } catch (_) {}
                throw new Error(detail);
            }

            const svgText = await qrResponse.text();
            const parsed = new DOMParser().parseFromString(svgText, "image/svg+xml");
            const svg = parsed.documentElement;

            if (!svg || svg.nodeName.toLowerCase() !== "svg" || parsed.querySelector("parsererror")) {
                throw new Error("Сервер вернул некорректный QR-код.");
            }

            svg.querySelectorAll("script, foreignObject").forEach(node => node.remove());
            svg.querySelectorAll("*").forEach(node => {
                for (const attribute of Array.from(node.attributes)) {
                    if (attribute.name.toLowerCase().startsWith("on")) {
                        node.removeAttribute(attribute.name);
                    }
                }
            });

            box.replaceChildren(document.importNode(svg, true));
            addressNode.textContent = addressData.wallet_address;
            linkButton.dataset.link = addressData.deep_link || "";
            linkButton.disabled = !linkButton.dataset.link;
        } catch (error) {
            box.textContent = "QR недоступен";
            addressNode.textContent = error?.name === "AbortError"
                ? "Сервер не ответил вовремя. Повторите попытку."
                : (error.message || "Ошибка загрузки QR-кода");
            linkButton.disabled = true;
        }
    }

    async function copyText(text) {
        if (navigator.clipboard?.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch (_) {}
        }

        const field = document.createElement("textarea");
        field.value = text;
        field.setAttribute("readonly", "");
        field.style.position = "fixed";
        field.style.left = "-9999px";
        field.style.opacity = "0";
        document.body.appendChild(field);

        try {
            field.focus();
            field.select();
            field.setSelectionRange(0, field.value.length);
            return Boolean(document.execCommand?.("copy"));
        } catch (_) {
            return false;
        } finally {
            field.remove();
        }
    }

    async function copyQrLink() {
        const button = document.getElementById("wallet-qr-copy-link");
        const link = button?.dataset.link || "";
        if (!button || !link) return;

        const copied = await copyText(link);
        if (copied) {
            tg?.HapticFeedback?.notificationOccurred?.("success");
            button.textContent = "Скопировано";
            setTimeout(() => {
                const current = document.getElementById("wallet-qr-copy-link");
                if (current) current.textContent = "Скопировать ссылку";
            }, 1600);
            return;
        }

        tg?.HapticFeedback?.notificationOccurred?.("error");
        button.textContent = "Не удалось скопировать";
        if (typeof window.prompt === "function") {
            window.prompt("Скопируйте ссылку вручную:", link);
        }
        setTimeout(() => {
            const current = document.getElementById("wallet-qr-copy-link");
            if (current) current.textContent = "Скопировать ссылку";
        }, 2000);
    }

    async function loadPublicWalletAddress() {
        if (!tg?.initData) return;
        try {
            const data = await api("/api/wallet/address", { headers: headers() });
            const number = document.getElementById("wallet-number");
            if (number && data?.wallet_address) number.textContent = data.wallet_address;
        } catch (error) {
            console.error("Nyan Wallet address load error:", error);
        }
    }

    function buildUi() {
        if (document.getElementById("transfer-view")) return;

        const app = document.querySelector(".app");
        const actions = document.querySelector("#wallet-view .actions");
        if (!app || !actions) return;

        const transferButton = document.createElement("button");
        transferButton.id = "transfer-button";
        transferButton.className = "primary-action";
        transferButton.type = "button";
        transferButton.textContent = "Перевести";

        const qrButton = document.createElement("button");
        qrButton.id = "wallet-qr-button";
        qrButton.className = "transfer-action-secondary";
        qrButton.type = "button";
        qrButton.textContent = "QR кошелька";

        const ownerButton = document.getElementById("owner-button");
        if (ownerButton) {
            actions.insertBefore(transferButton, ownerButton);
            actions.insertBefore(qrButton, ownerButton);
        } else {
            actions.appendChild(transferButton);
            actions.appendChild(qrButton);
        }

        const view = document.createElement("main");
        view.id = "transfer-view";
        view.className = "view hidden";
        view.innerHTML = `
            <div class="subpage-header">
                <button id="transfer-back" class="back-button" type="button" aria-label="Назад">‹</button>
                <div>
                    <div class="page-title">Перевод лапкоинов</div>
                    <div class="page-subtitle">безопасный перевод между кошельками</div>
                </div>
            </div>
            <section class="transfer-panel">
                <div class="transfer-title">Получатель</div>
                <div class="transfer-subtitle">Введите @username, Telegram ID или номер NYAN…</div>
                <div class="transfer-form">
                    <label>Получатель
                        <input id="transfer-target" type="text" maxlength="80" autocomplete="off" placeholder="@username, ID или NYAN…">
                    </label>
                    <label>Количество 🐾
                        <input id="transfer-amount" type="number" inputmode="numeric" min="1" max="100000" step="1" placeholder="Например, 100">
                    </label>
                    <label>Комментарий
                        <input id="transfer-note" type="text" maxlength="120" autocomplete="off" placeholder="Необязательно">
                    </label>
                    <button id="transfer-resolve" class="transfer-primary" type="button">Продолжить</button>
                </div>
                <div id="transfer-recipient-preview" class="transfer-recipient" hidden>
                    <strong></strong><span></span>
                </div>
                <div class="transfer-confirm-grid">
                    <button id="transfer-change" class="secondary" type="button" hidden>Изменить</button>
                    <button id="transfer-send" class="transfer-primary" type="button" hidden>Перевести</button>
                </div>
                <div id="transfer-status" class="transfer-status" aria-live="polite"></div>
            </section>`;
        app.appendChild(view);

        const overlay = document.createElement("div");
        overlay.id = "wallet-qr-overlay";
        overlay.className = "wallet-qr-overlay";
        overlay.hidden = true;
        overlay.innerHTML = `
            <section class="wallet-qr-sheet" role="dialog" aria-modal="true" aria-labelledby="wallet-qr-title">
                <button class="wallet-qr-close" type="button" aria-label="Закрыть">×</button>
                <h2 id="wallet-qr-title">Ваш Nyan Wallet</h2>
                <p>Другой пользователь может отсканировать QR и сразу открыть перевод на ваш кошелёк.</p>
                <div id="wallet-qr-box" class="wallet-qr-box" role="img" aria-label="QR-код Nyan Wallet"></div>
                <div id="wallet-qr-address" class="wallet-qr-address"></div>
                <div class="wallet-qr-actions">
                    <button id="wallet-qr-copy-link" type="button">Скопировать ссылку</button>
                    <button id="wallet-qr-close-bottom" class="secondary" type="button">Закрыть</button>
                </div>
            </section>`;
        document.body.appendChild(overlay);

        transferButton.addEventListener("click", () => openTransfer());
        qrButton.addEventListener("click", openQr);
        document.getElementById("transfer-back")?.addEventListener("click", showWallet);
        document.getElementById("transfer-resolve")?.addEventListener("click", resolveRecipient);
        document.getElementById("transfer-send")?.addEventListener("click", sendTransfer);
        document.getElementById("transfer-change")?.addEventListener("click", () => {
            resetRecipient();
            document.getElementById("transfer-change").hidden = true;
        });

        for (const id of ["transfer-target", "transfer-amount", "transfer-note"]) {
            document.getElementById(id)?.addEventListener("input", () => {
                if (canonicalRecipient) {
                    canonicalRecipient = null;
                    pendingIdempotencyKey = null;
                    document.getElementById("transfer-recipient-preview").hidden = true;
                    document.getElementById("transfer-send").hidden = true;
                    document.getElementById("transfer-resolve").hidden = false;
                }
                setStatus("");
            });
        }

        document.getElementById("wallet-qr-copy-link")?.addEventListener("click", copyQrLink);
        document.getElementById("wallet-qr-close-bottom")?.addEventListener("click", closeQr);
        overlay.querySelector(".wallet-qr-close")?.addEventListener("click", closeQr);
        overlay.addEventListener("click", event => {
            if (event.target === overlay) closeQr();
        });

        if (tg?.BackButton?.onClick) {
            tg.BackButton.onClick(() => {
                if (!view.classList.contains("hidden")) showWallet();
            });
        }

        void loadPublicWalletAddress();

        const pending = initialPendingPayment || pendingPaymentAddress();
        if (pending) {
            let attempts = 0;

            const start = () => {
                attempts += 1;

                if (window.__nyanMaintenanceBlocked) {
                    if (attempts < 100) setTimeout(start, 150);
                    return;
                }

                const wallet = document.getElementById("wallet-view");
                if (!wallet) {
                    if (attempts < 100) setTimeout(start, 120);
                    return;
                }

                // Deep-link launch owns initial navigation. Do not wait for
                // loading-view to disappear: app.js intentionally keeps the
                // wallet hidden while __nyanPaymentDeepLinkActive is true.
                document.getElementById("loading-view")?.classList.add("hidden");
                openTransfer(pending);
                window.__nyanPaymentDeepLinkActive = false;

                try {
                    sessionStorage.removeItem("nyan_pending_payment");
                } catch (_) {}

                void resolveRecipient();
            };

            setTimeout(start, 80);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", buildUi, { once: true });
    } else {
        buildUi();
    }
})();
