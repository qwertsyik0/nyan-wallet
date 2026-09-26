(function () {
    "use strict";

    const API_BASE = "https://nyan-wallet-api.onrender.com";
    const tgApp = window.Telegram?.WebApp || null;

    function initData() {
        return tgApp?.initData || "";
    }

    function authHeaders(json) {
        const headers = { "X-Telegram-Init-Data": initData() };
        if (json) headers["Content-Type"] = "application/json";
        return headers;
    }

    async function readJson(response) {
        try {
            return await response.json();
        } catch (_) {
            return {};
        }
    }

    function value(id) {
        return document.getElementById(id)?.value.trim() || "";
    }

    function payloadFromForm() {
        return {
            character_first_name: value("paris-first-name"),
            character_last_name: value("paris-last-name"),
            character_age: Number(value("paris-age")),
            character_gender: value("paris-gender"),
            character_orientation: value("paris-orientation"),
            telegram_username: value("paris-username"),
            role_preference: value("paris-role") || null,
            character_description: value("paris-description") || null,
            character_personality: value("paris-personality") || null,
            affiliation: value("paris-affiliation") || null,
            roleplay_experience: value("paris-experience") || null,
            applicant_comment: value("paris-comment") || null,
        };
    }

    function validate(payload) {
        if (!payload.character_first_name) throw new Error("укажи имя персонажа");
        if (!payload.character_last_name) throw new Error("укажи фамилию персонажа");
        if (!Number.isInteger(payload.character_age) || payload.character_age < 1 || payload.character_age > 120) {
            throw new Error("укажи корректный возраст персонажа");
        }
        if (!payload.character_gender) throw new Error("укажи пол персонажа");
        if (!payload.character_orientation) throw new Error("укажи ориентацию персонажа");
        if (!payload.telegram_username) throw new Error("укажи Telegram username");
    }

    async function currentApplication() {
        const response = await fetch(`${API_BASE}/api/paris/applications/me`, {
            headers: authHeaders(false),
        });
        if (response.status === 404) return null;
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Не удалось проверить заявку");
        return data.application || null;
    }

    async function handleSubmitCapture(event) {
        const form = event.target;
        if (!form || form.id !== "paris-application-form") return;
        if (!initData()) return;

        let application;
        try {
            application = await currentApplication();
        } catch (_) {
            return;
        }

        if (!application || application.status !== "needs_changes") return;

        event.preventDefault();
        event.stopImmediatePropagation();

        const status = document.getElementById("paris-form-status");
        const submit = document.getElementById("paris-submit");

        let payload;
        try {
            payload = payloadFromForm();
            validate(payload);
        } catch (error) {
            if (status) status.textContent = error.message || "Проверь анкету.";
            return;
        }

        if (submit) {
            submit.disabled = true;
            submit.textContent = "ОТПРАВЛЯЕМ ПРАВКИ…";
        }
        if (status) status.textContent = "";

        try {
            const response = await fetch(`${API_BASE}/api/paris/applications/me`, {
                method: "POST",
                headers: authHeaders(true),
                body: JSON.stringify(payload),
            });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось отправить правки");

            form.hidden = true;
            if (status) {
                status.textContent = "Правки отправлены. Заявка снова на рассмотрении у владельца.";
            }
            tgApp?.HapticFeedback?.notificationOccurred?.("success");
        } catch (error) {
            if (status) status.textContent = error.message || "Не удалось отправить правки";
            tgApp?.HapticFeedback?.notificationOccurred?.("error");
        } finally {
            if (submit) {
                submit.disabled = false;
                submit.textContent = "ОТПРАВИТЬ ПРАВКИ";
            }
        }
    }

    document.addEventListener("submit", handleSubmitCapture, true);
})();
