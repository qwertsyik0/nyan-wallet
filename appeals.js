(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const STATUS_LABELS = {
        new: "Новое",
        viewed: "Просмотрено",
        in_progress: "В работе",
        approved: "Одобрено",
        completed: "Выполнено",
        rejected: "Отклонено",
    };
    const OPEN_STATUSES = new Set(["new", "viewed", "in_progress", "approved"]);
    const allowedImageTypes = new Set(["image/png", "image/jpeg", "image/webp"]);
    const skinObjectUrls = new Map();
    let currentAppealId = null;
    let currentOwnerAppealId = null;
    let activeSkinId = null;

    function headers(json = false) {
        const result = { "X-Telegram-Init-Data": tg?.initData || "" };
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

    function wait(ms) {
        return new Promise((resolve) => window.setTimeout(resolve, ms));
    }

    async function api(path, options = {}) {
        let lastError = null;

        for (let attempt = 0; attempt < 3; attempt += 1) {
            try {
                const response = await fetch(API + path, options);
                const data = await readJson(response);

                if (!response.ok) {
                    const error = new Error(data.detail || "Ошибка запроса");
                    error.status = response.status;
                    throw error;
                }

                return data;
            } catch (error) {
                lastError = error;

                const isNetworkError = error instanceof TypeError;
                const isRetryableHttp = [502, 504].includes(Number(error?.status));

                if (attempt < 2 && (isNetworkError || isRetryableHttp)) {
                    await wait(500 * (attempt + 1));
                    continue;
                }

                if (isNetworkError) {
                    const networkError = new Error("Не удалось связаться с сервером. Попробуйте ещё раз через несколько секунд.");
                    networkError.cause = error;
                    throw networkError;
                }

                throw error;
            }
        }

        throw lastError || new Error("Не удалось загрузить данные");
    }

    function esc(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function fmt(value) {
        if (!value) return "";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "";
        return date.toLocaleString("ru-RU", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    function statusClass(status) {
        if (status === "completed") return " done";
        if (status === "rejected") return " reject";
        return "";
    }

    function hideAppViews() {
        document.querySelectorAll(".app > .view").forEach((view) => view.classList.add("hidden"));
    }

    function showView(id) {
        hideAppViews();
        document.getElementById(id)?.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tg?.BackButton?.show?.();
    }

    function showWallet() {
        hideAppViews();
        document.getElementById("wallet-view")?.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tg?.BackButton?.hide?.();
    }

    function buildUi() {
        if (document.getElementById("appeals-button")) return;
        const app = document.querySelector(".app");
        const actions = document.querySelector("#wallet-view .actions");
        const ownerButton = document.getElementById("owner-button");

        const button = document.createElement("button");
        button.id = "appeals-button";
        button.className = "appeals-action";
        button.type = "button";
        button.textContent = "Обращения";
        if (ownerButton) actions?.insertBefore(button, ownerButton);
        else actions?.appendChild(button);

        const userView = document.createElement("main");
        userView.id = "appeals-view";
        userView.className = "view hidden appeal-view";
        userView.innerHTML =
            '<div class="subpage-header">' +
                '<button id="appeals-back" class="back-button" type="button" aria-label="Назад">‹</button>' +
                '<div><div class="page-title">Обращения</div><div class="page-subtitle">заявки и индивидуальные возможности Nyan Wallet</div></div>' +
            '</div>' +
            '<section class="appeal-panel">' +
                '<div class="appeal-section-title">Доступные обращения</div>' +
                '<div class="appeal-section-sub">Выберите тему и отправьте заявку владельцу Нян.</div>' +
                '<div id="appeal-topics" class="appeal-grid"></div>' +
            '</section>' +
            '<section id="appeal-compose" class="appeal-panel" hidden>' +
                '<div id="appeal-compose-title" class="appeal-section-title">Новое обращение</div>' +
                '<div id="appeal-compose-desc" class="appeal-section-sub"></div>' +
                '<form id="appeal-compose-form" class="appeal-form">' +
                    '<label>Пожелания / суть обращения<textarea id="appeal-message" maxlength="1500" required placeholder="Опишите, что вы хотите"></textarea></label>' +
                    '<div id="appeal-wallet-extra" hidden>' +
                        '<div class="appeal-form">' +
                            '<label>Любимые цвета <input id="appeal-colors" maxlength="300" placeholder="Например: бордовый, розовый, белый"></label>' +
                            '<label>Что точно не использовать <textarea id="appeal-avoid" maxlength="500" placeholder="Цвета, символы или детали, которые вам не нравятся"></textarea></label>' +
                            '<label>Дополнительный комментарий <textarea id="appeal-extra" maxlength="800" placeholder="Любые дополнительные пожелания"></textarea></label>' +
                        '</div>' +
                    '</div>' +
                    '<button id="appeal-submit" type="submit">Отправить обращение</button>' +
                    '<div id="appeal-submit-status" class="appeal-info" aria-live="polite"></div>' +
                '</form>' +
            '</section>' +
            '<section class="appeal-panel">' +
                '<div class="appeal-section-title">Мои обращения</div>' +
                '<div id="appeal-my-list" class="appeal-grid"></div>' +
            '</section>' +
            '<section class="appeal-panel">' +
                '<div class="appeal-section-title">Мои дизайны кошелька</div>' +
                '<div class="appeal-section-sub">Полученные оформления можно переключать в любой момент.</div>' +
                '<div id="appeal-my-skins" class="appeal-skin-grid"></div>' +
            '</section>';
        app?.appendChild(userView);

        const detailView = document.createElement("main");
        detailView.id = "appeal-detail-view";
        detailView.className = "view hidden appeal-view";
        detailView.innerHTML =
            '<div class="subpage-header">' +
                '<button id="appeal-detail-back" class="back-button" type="button" aria-label="Назад">‹</button>' +
                '<div><div class="page-title">Обращение</div><div id="appeal-detail-subtitle" class="page-subtitle"></div></div>' +
            '</div>' +
            '<section id="appeal-detail-card" class="appeal-panel"></section>';
        app?.appendChild(detailView);

        const ownerView = document.createElement("main");
        ownerView.id = "owner-appeals-view";
        ownerView.className = "view hidden appeal-view";
        ownerView.innerHTML =
            '<div class="subpage-header">' +
                '<button id="owner-appeals-back" class="back-button" type="button" aria-label="Назад">‹</button>' +
                '<div><div class="page-title">Обращения</div><div class="page-subtitle">очередь заявок Nyan Wallet</div></div>' +
            '</div>' +
            '<section class="appeal-panel">' +
                '<div class="appeal-section-title">Очередь</div>' +
                '<div class="appeal-owner-toolbar">' +
                    '<input id="owner-appeal-search" maxlength="80" placeholder="@username, ID или NWR-...">' +
                    '<select id="owner-appeal-filter">' +
                        '<option value="">Все статусы</option>' +
                        '<option value="new">Новые</option>' +
                        '<option value="viewed">Просмотренные</option>' +
                        '<option value="in_progress">В работе</option>' +
                        '<option value="approved">Одобренные</option>' +
                        '<option value="completed">Выполненные</option>' +
                        '<option value="rejected">Отклонённые</option>' +
                    '</select>' +
                '</div>' +
                '<div id="owner-appeal-list" class="appeal-grid"></div>' +
            '</section>' +
            '<section id="owner-appeal-detail" class="appeal-panel" hidden></section>' +
            '<section class="appeal-panel">' +
                '<div class="appeal-section-title">Готовые дизайны</div>' +
                '<div class="appeal-section-sub">Эти оформления можно выдавать нескольким пользователям.</div>' +
                '<form id="owner-template-form" class="appeal-form">' +
                    '<label>Название <input id="owner-template-title" maxlength="120" required placeholder="Например, Sakura"></label>' +
                    '<label>Текст на карточке <select id="owner-template-theme"><option value="dark">Тёмный</option><option value="light">Светлый</option></select></label>' +
                    '<label>Изображение PNG/JPEG/WEBP до 2 МБ <input id="owner-template-file" class="appeal-file" type="file" accept="image/png,image/jpeg,image/webp" required></label>' +
                    '<button type="submit">Добавить готовый дизайн</button>' +
                    '<div id="owner-template-status" class="appeal-info"></div>' +
                '</form>' +
                '<div id="owner-template-list" class="appeal-skin-grid"></div>' +
            '</section>' +
            '<section class="appeal-panel">' +
                '<div class="appeal-section-title">Темы обращений</div>' +
                '<div class="appeal-section-sub">Можно использовать систему и для других акций, не только для кошельков.</div>' +
                '<form id="owner-topic-form" class="appeal-form">' +
                    '<label>Код <input id="owner-topic-code" maxlength="64" required placeholder="NEW_ACTIVITY"></label>' +
                    '<label>Название <input id="owner-topic-title" maxlength="120" required></label>' +
                    '<label>Описание <textarea id="owner-topic-desc" maxlength="1200" required></textarea></label>' +
                    '<label>Форма <select id="owner-topic-type"><option value="general">Обычное обращение</option><option value="custom_wallet">Кастомный кошелёк</option></select></label>' +
                    '<label>Начало <small>необязательно</small><input id="owner-topic-start" type="datetime-local"></label>' +
                    '<label>Окончание <small>необязательно</small><input id="owner-topic-end" type="datetime-local"></label>' +
                    '<button type="submit">Создать тему</button>' +
                    '<div id="owner-topic-status" class="appeal-info"></div>' +
                '</form>' +
                '<div id="owner-topic-list" class="appeal-grid"></div>' +
            '</section>';
        app?.appendChild(ownerView);

        const mainOwnerView = document.getElementById("owner-view");
        if (mainOwnerView && !document.getElementById("owner-appeals-launch-section")) {
            const section = document.createElement("section");
            section.id = "owner-appeals-launch-section";
            section.className = "admin-section";
            section.innerHTML =
                '<div class="owner-title">Обращения</div>' +
                '<div class="owner-subtitle">заявки пользователей и кастомные кошельки</div>' +
                '<button id="owner-appeals-launch" class="owner-appeals-launch" type="button">Открыть обращения</button>';
            const header = mainOwnerView.querySelector(".subpage-header");
            header?.insertAdjacentElement("afterend", section);
        }

        button.addEventListener("click", openAppeals);
        document.getElementById("appeals-back")?.addEventListener("click", showWallet);
        document.getElementById("appeal-detail-back")?.addEventListener("click", openAppeals);
        document.getElementById("owner-appeals-back")?.addEventListener("click", () => showView("owner-view"));
        document.getElementById("owner-appeals-launch")?.addEventListener("click", openOwnerAppeals);
        document.getElementById("appeal-compose-form")?.addEventListener("submit", submitAppeal);
        document.getElementById("owner-template-form")?.addEventListener("submit", submitTemplate);
        document.getElementById("owner-topic-form")?.addEventListener("submit", submitTopic);
        document.getElementById("owner-appeal-search")?.addEventListener("input", debounce(loadOwnerAppeals, 280));
        document.getElementById("owner-appeal-filter")?.addEventListener("change", loadOwnerAppeals);

        if (tg?.BackButton?.onClick) {
            tg.BackButton.onClick(() => {
                const detail = document.getElementById("appeal-detail-view");
                const user = document.getElementById("appeals-view");
                const owner = document.getElementById("owner-appeals-view");
                if (detail && !detail.classList.contains("hidden")) {
                    openAppeals();
                } else if (owner && !owner.classList.contains("hidden")) {
                    showView("owner-view");
                } else if (user && !user.classList.contains("hidden")) {
                    showWallet();
                }
            });
        }
    }

    function debounce(fn, delay) {
        let timer = 0;
        return (...args) => {
            window.clearTimeout(timer);
            timer = window.setTimeout(() => fn(...args), delay);
        };
    }

    async function openAppeals() {
        showView("appeals-view");
        document.getElementById("appeal-compose").hidden = true;
        await Promise.all([loadTopics(), loadMyAppeals(), loadMySkins(true)]);
    }

    async function loadTopics() {
        const box = document.getElementById("appeal-topics");
        if (!box || !tg?.initData) return;
        box.innerHTML = '<div class="appeal-empty">Загружаем…</div>';
        try {
            const data = await api("/api/appeal-topics", { headers: headers() });
            if (!data.topics?.length) {
                box.innerHTML = '<div class="appeal-empty">Сейчас активных тем нет.</div>';
                return;
            }
            box.innerHTML = "";
            for (const topic of data.topics) {
                const card = document.createElement("article");
                card.className = "appeal-card";
                const existing = topic.my_appeal;
                card.innerHTML =
                    '<div class="appeal-card-head">' +
                        '<div><div class="appeal-title">' + esc(topic.title) + '</div>' +
                        '<div class="appeal-meta">' + esc(topic.description) + '</div></div>' +
                        (existing ? '<span class="appeal-status' + statusClass(existing.status) + '">' + esc(STATUS_LABELS[existing.status] || existing.status) + '</span>' : "") +
                    '</div>' +
                    '<div class="appeal-actions"><button class="appeal-button ' + (existing ? "secondary" : "") + '" type="button">' +
                        (existing ? "Открыть обращение" : "Оставить обращение") +
                    '</button></div>';
                card.querySelector("button")?.addEventListener("click", () => {
                    if (existing) openAppealDetail(existing.id);
                    else openCompose(topic);
                });
                box.appendChild(card);
            }
        } catch (error) {
            box.innerHTML = '<div class="appeal-error">' + esc(error.message) + '</div>';
        }
    }

    function openCompose(topic) {
        const panel = document.getElementById("appeal-compose");
        panel.hidden = false;
        panel.dataset.topicId = String(topic.id);
        panel.dataset.formType = topic.form_type || "general";
        document.getElementById("appeal-compose-title").textContent = topic.title;
        document.getElementById("appeal-compose-desc").textContent = topic.description;
        document.getElementById("appeal-wallet-extra").hidden = topic.form_type !== "custom_wallet";
        document.getElementById("appeal-message").value = "";
        document.getElementById("appeal-colors").value = "";
        document.getElementById("appeal-avoid").value = "";
        document.getElementById("appeal-extra").value = "";
        document.getElementById("appeal-submit-status").textContent = "";
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    async function submitAppeal(event) {
        event.preventDefault();
        const panel = document.getElementById("appeal-compose");
        const status = document.getElementById("appeal-submit-status");
        const button = document.getElementById("appeal-submit");
        const topicId = Number.parseInt(panel?.dataset.topicId || "", 10);
        const message = document.getElementById("appeal-message")?.value.trim() || "";
        if (!Number.isInteger(topicId) || topicId < 1) {
            status.textContent = "Тема обращения не выбрана.";
            status.className = "appeal-error";
            return;
        }
        if (!message) {
            status.textContent = "Напишите пожелания или суть обращения.";
            status.className = "appeal-error";
            return;
        }

        const payload = {
            topic_id: topicId,
            message,
            favorite_colors: document.getElementById("appeal-colors")?.value.trim() || null,
            avoid_text: document.getElementById("appeal-avoid")?.value.trim() || null,
            extra_comment: document.getElementById("appeal-extra")?.value.trim() || null,
        };

        button.disabled = true;
        status.textContent = "Отправляем…";
        status.className = "appeal-info";
        try {
            const data = await api("/api/appeals", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify(payload),
            });
            tg?.HapticFeedback?.notificationOccurred?.("success");
            status.textContent = "Обращение отправлено.";
            status.className = "appeal-success";
            panel.hidden = true;
            await Promise.all([loadTopics(), loadMyAppeals()]);
            await openAppealDetail(data.appeal.id);
        } catch (error) {
            status.textContent = error.message;
            status.className = "appeal-error";
            tg?.HapticFeedback?.notificationOccurred?.("error");
        } finally {
            button.disabled = false;
        }
    }

    async function loadMyAppeals() {
        const box = document.getElementById("appeal-my-list");
        if (!box || !tg?.initData) return;
        try {
            const data = await api("/api/appeals/me", { headers: headers() });
            if (!data.appeals?.length) {
                box.innerHTML = '<div class="appeal-empty">Вы ещё не отправляли обращений.</div>';
                return;
            }
            box.innerHTML = "";
            for (const item of data.appeals) {
                const card = document.createElement("article");
                card.className = "appeal-card clickable";
                card.innerHTML =
                    '<div class="appeal-card-head">' +
                        '<div><div class="appeal-title">' + esc(item.public_id) + ' · ' + esc(item.topic?.title || "Обращение") + '</div>' +
                        '<div class="appeal-meta">' + fmt(item.updated_at) + '<br>' + esc(item.message.slice(0, 180)) + '</div></div>' +
                        '<span class="appeal-status' + statusClass(item.status) + '">' + esc(STATUS_LABELS[item.status] || item.status) + '</span>' +
                    '</div>';
                card.addEventListener("click", () => openAppealDetail(item.id));
                box.appendChild(card);
            }
        } catch (error) {
            box.innerHTML = '<div class="appeal-error">' + esc(error.message) + '</div>';
        }
    }

    async function openAppealDetail(id) {
        if (!Number.isInteger(Number(id)) || Number(id) < 1) return;
        currentAppealId = Number(id);
        showView("appeal-detail-view");
        const box = document.getElementById("appeal-detail-card");
        box.innerHTML = '<div class="appeal-empty">Загружаем…</div>';
        try {
            const data = await api("/api/appeals/" + currentAppealId, { headers: headers() });
            renderUserAppeal(data.appeal);
        } catch (error) {
            box.innerHTML = '<div class="appeal-error">' + esc(error.message) + '</div>';
        }
    }

    function renderUserAppeal(item) {
        document.getElementById("appeal-detail-subtitle").textContent = item.public_id;
        const box = document.getElementById("appeal-detail-card");
        let details =
            '<div class="appeal-card-head"><div><div class="appeal-section-title">' + esc(item.topic?.title || "Обращение") + '</div>' +
            '<div class="appeal-section-sub">Создано ' + fmt(item.created_at) + '</div></div>' +
            '<span class="appeal-status' + statusClass(item.status) + '">' + esc(STATUS_LABELS[item.status] || item.status) + '</span></div>' +
            '<div class="appeal-divider"></div>' +
            '<div class="appeal-title">Пожелания</div><div class="appeal-meta">' + esc(item.message) + '</div>';
        if (item.favorite_colors) details += '<div class="appeal-title" style="margin-top:10px">Любимые цвета</div><div class="appeal-meta">' + esc(item.favorite_colors) + '</div>';
        if (item.avoid_text) details += '<div class="appeal-title" style="margin-top:10px">Не использовать</div><div class="appeal-meta">' + esc(item.avoid_text) + '</div>';
        if (item.extra_comment) details += '<div class="appeal-title" style="margin-top:10px">Комментарий</div><div class="appeal-meta">' + esc(item.extra_comment) + '</div>';

        details += '<div class="appeal-divider"></div><div class="appeal-title">Переписка</div><div class="appeal-thread">';
        if (!item.messages?.length) details += '<div class="appeal-empty">Дополнительных сообщений пока нет.</div>';
        for (const msg of item.messages || []) {
            details += '<div class="appeal-message ' + (msg.author_role === "owner" ? "owner" : "") + '">' +
                esc(msg.body) + '<div class="appeal-message-time">' + fmt(msg.created_at) + '</div></div>';
        }
        details += '</div>';

        if (OPEN_STATUSES.has(item.status)) {
            details +=
                '<form id="appeal-followup-form" class="appeal-form">' +
                    '<label>Дополнить обращение<textarea id="appeal-followup" maxlength="1500" required></textarea></label>' +
                    '<button type="submit">Отправить сообщение</button>' +
                    '<div id="appeal-followup-status" class="appeal-info"></div>' +
                '</form>';
        } else {
            details += '<div class="appeal-inline-note">Обращение закрыто. Новые сообщения в него отправить нельзя.</div>';
        }
        box.innerHTML = details;
        document.getElementById("appeal-followup-form")?.addEventListener("submit", submitFollowup);
    }

    async function submitFollowup(event) {
        event.preventDefault();
        const input = document.getElementById("appeal-followup");
        const status = document.getElementById("appeal-followup-status");
        const body = input?.value.trim() || "";
        if (!body) {
            status.textContent = "Сообщение пустое.";
            status.className = "appeal-error";
            return;
        }
        try {
            await api("/api/appeals/" + currentAppealId + "/messages", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({ body }),
            });
            input.value = "";
            await openAppealDetail(currentAppealId);
        } catch (error) {
            status.textContent = error.message;
            status.className = "appeal-error";
        }
    }

    async function skinUrl(skinId) {
        if (skinObjectUrls.has(skinId)) return skinObjectUrls.get(skinId);
        const response = await fetch(API + "/api/wallet-skins/" + skinId + "/image", { headers: headers() });
        if (!response.ok) {
            const data = await readJson(response);
            throw new Error(data.detail || "Не удалось загрузить дизайн");
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        skinObjectUrls.set(skinId, url);
        return url;
    }

    async function applySkin(skin) {
        const card = document.getElementById("wallet-card");
        if (!card) return;
        if (!skin) {
            card.classList.remove("has-custom-skin", "skin-text-light", "skin-text-dark");
            card.style.removeProperty("--custom-wallet-image");
            activeSkinId = null;
            return;
        }
        try {
            const url = await skinUrl(skin.id);
            card.style.setProperty("--custom-wallet-image", 'url("' + url + '")');
            card.classList.add("has-custom-skin");
            card.classList.toggle("skin-text-light", skin.text_theme === "light");
            card.classList.toggle("skin-text-dark", skin.text_theme !== "light");
            activeSkinId = skin.id;
        } catch (error) {
            console.error("Nyan Wallet skin apply failed:", error);
        }
    }

    async function loadMySkins(render = false) {
        if (!tg?.initData) return;
        const box = document.getElementById("appeal-my-skins");
        try {
            const data = await api("/api/wallet-skins/me", { headers: headers() });
            const active = (data.skins || []).find((skin) => skin.active) || null;
            await applySkin(active);
            if (!render || !box) return;
            if (!data.skins?.length) {
                box.innerHTML = '<div class="appeal-empty">У вас пока нет дополнительных дизайнов.</div>';
                return;
            }
            box.innerHTML = "";
            const defaultCard = document.createElement("article");
            defaultCard.className = "appeal-skin";
            defaultCard.innerHTML =
                '<div class="appeal-skin-preview" style="background:linear-gradient(145deg,#fffdfd,#fff0f6 52%,#f9dce9)"></div>' +
                '<div class="appeal-skin-body"><div class="appeal-skin-title">Стандартный Nyan Wallet</div>' +
                '<div class="appeal-skin-meta">' + (active ? "Можно вернуть в любой момент" : "Установлен сейчас") + '</div>' +
                '<button type="button" ' + (!active ? "disabled" : "") + '>' + (!active ? "Установлен" : "Вернуть") + '</button></div>';
            defaultCard.querySelector("button")?.addEventListener("click", activateDefaultSkin);
            box.appendChild(defaultCard);
            for (const skin of data.skins) {
                const card = document.createElement("article");
                card.className = "appeal-skin";
                card.innerHTML =
                    '<div class="appeal-skin-preview"></div>' +
                    '<div class="appeal-skin-body"><div class="appeal-skin-title">' + esc(skin.title) + '</div>' +
                    '<div class="appeal-skin-meta">' + (skin.active ? "Установлен сейчас" : "Доступен") + '</div>' +
                    '<button type="button" ' + (skin.active ? "disabled" : "") + '>' + (skin.active ? "Установлен" : "Установить") + '</button></div>';
                box.appendChild(card);
                skinUrl(skin.id).then((url) => {
                    const preview = card.querySelector(".appeal-skin-preview");
                    if (preview) preview.style.backgroundImage = 'url("' + url + '")';
                }).catch(() => {});
                card.querySelector("button")?.addEventListener("click", () => activateSkin(skin.id));
            }
        } catch (error) {
            if (render && box) box.innerHTML = '<div class="appeal-error">' + esc(error.message) + '</div>';
        }
    }

    async function activateSkin(skinId) {
        try {
            await api("/api/wallet-skins/" + skinId + "/activate", {
                method: "POST",
                headers: headers(true),
            });
            tg?.HapticFeedback?.notificationOccurred?.("success");
            await loadMySkins(true);
        } catch (error) {
            alert(error.message);
        }
    }

    async function activateDefaultSkin() {
        try {
            await api("/api/wallet-skins/activate-default", {
                method: "POST",
                headers: headers(true),
            });
            tg?.HapticFeedback?.notificationOccurred?.("success");
            await loadMySkins(true);
        } catch (error) {
            alert(error.message);
        }
    }

    async function openOwnerAppeals() {
        showView("owner-appeals-view");
        await Promise.all([loadOwnerAppeals(), loadOwnerTemplates(), loadOwnerTopics()]);
    }

    async function loadOwnerAppeals() {
        const box = document.getElementById("owner-appeal-list");
        if (!box || !tg?.initData) return;
        const status = document.getElementById("owner-appeal-filter")?.value || "";
        const q = document.getElementById("owner-appeal-search")?.value.trim() || "";
        const params = new URLSearchParams();
        if (status) params.set("status", status);
        if (q) params.set("q", q);
        box.innerHTML = '<div class="appeal-empty">Загружаем…</div>';
        try {
            const query = params.toString();
            const data = await api("/api/owner/appeals" + (query ? "?" + query : ""), { headers: headers() });
            if (!data.appeals?.length) {
                box.innerHTML = '<div class="appeal-empty">Обращений не найдено.</div>';
                return;
            }
            box.innerHTML = "";
            for (const item of data.appeals) {
                const card = document.createElement("article");
                card.className = "appeal-card clickable";
                card.innerHTML =
                    '<div class="appeal-card-head"><div><div class="appeal-title">' + esc(item.public_id) + ' · ' + esc(item.topic_title) + '</div>' +
                    '<div class="appeal-meta">' + esc(item.user?.label || "") + ' · ID ' + esc(item.user?.telegram_id) + '<br>' +
                    esc(item.message_preview) + '<br>' + fmt(item.updated_at) + '</div></div>' +
                    '<span class="appeal-status' + statusClass(item.status) + '">' + esc(STATUS_LABELS[item.status] || item.status) + '</span></div>';
                card.addEventListener("click", () => openOwnerAppeal(item.id));
                box.appendChild(card);
            }
        } catch (error) {
            box.innerHTML = '<div class="appeal-error">' + esc(error.message) + '</div>';
        }
    }

    async function openOwnerAppeal(id, fromDeepLink = false) {
        if (!Number.isInteger(Number(id)) || Number(id) < 1) return;
        currentOwnerAppealId = Number(id);
        if (fromDeepLink) showView("owner-appeals-view");
        const panel = document.getElementById("owner-appeal-detail");
        panel.hidden = false;
        panel.innerHTML = '<div class="appeal-empty">Загружаем…</div>';
        try {
            const data = await api("/api/owner/appeals/" + currentOwnerAppealId, { headers: headers() });
            await fetch(API + "/api/owner/appeals/" + currentOwnerAppealId + "/viewed", {
                method: "POST",
                headers: headers(true),
            }).catch(() => {});
            renderOwnerAppeal(data.appeal);
            if (fromDeepLink) {
                await Promise.all([loadOwnerAppeals(), loadOwnerTemplates(), loadOwnerTopics()]);
            } else {
                await loadOwnerAppeals();
            }
            panel.scrollIntoView({ behavior: "smooth", block: "start" });
        } catch (error) {
            panel.innerHTML = '<div class="appeal-error">' + esc(error.message) + '</div>';
            if (fromDeepLink && error.status === 403) showWallet();
        }
    }

    function renderOwnerAppeal(item) {
        const panel = document.getElementById("owner-appeal-detail");
        const user = item.user || {};
        let html =
            '<div class="appeal-card-head"><div><div class="appeal-section-title">' + esc(item.public_id) + ' · ' + esc(item.topic?.title || "Обращение") + '</div>' +
            '<div class="appeal-section-sub">' + fmt(item.created_at) + '</div></div>' +
            '<span class="appeal-status' + statusClass(item.status) + '">' + esc(STATUS_LABELS[item.status] || item.status) + '</span></div>' +
            '<div class="appeal-owner-user" style="margin-top:12px"><div class="appeal-title">' + esc(user.label || "Пользователь") + '</div>' +
            '<div class="appeal-meta">ID ' + esc(user.telegram_id) + (user.username ? ' · @' + esc(user.username) : "") +
            (user.rank ? '<br>Ранг: ' + esc(user.rank) : "") +
            (Number.isFinite(Number(user.balance)) ? ' · Баланс: ' + esc(user.balance) + ' 🐾' : "") + '</div></div>' +
            '<div class="appeal-divider"></div>' +
            '<div class="appeal-title">Пожелания</div><div class="appeal-meta">' + esc(item.message) + '</div>';
        if (item.favorite_colors) html += '<div class="appeal-title" style="margin-top:10px">Любимые цвета</div><div class="appeal-meta">' + esc(item.favorite_colors) + '</div>';
        if (item.avoid_text) html += '<div class="appeal-title" style="margin-top:10px">Не использовать</div><div class="appeal-meta">' + esc(item.avoid_text) + '</div>';
        if (item.extra_comment) html += '<div class="appeal-title" style="margin-top:10px">Комментарий</div><div class="appeal-meta">' + esc(item.extra_comment) + '</div>';

        html +=
            '<div class="appeal-divider"></div>' +
            '<div class="appeal-title">Статус</div>' +
            '<div class="appeal-actions">' +
                statusButtons(item.status) +
            '</div>' +
            '<div class="appeal-divider"></div>' +
            '<div class="appeal-title">Переписка</div><div class="appeal-thread">';
        if (!item.messages?.length) html += '<div class="appeal-empty">Сообщений пока нет.</div>';
        for (const msg of item.messages || []) {
            html += '<div class="appeal-message ' + (msg.author_role === "owner" ? "owner" : "") + '">' +
                esc(msg.body) + '<div class="appeal-message-time">' + fmt(msg.created_at) + '</div></div>';
        }
        html +=
            '</div>' +
            '<form id="owner-appeal-reply-form" class="appeal-form">' +
                '<label>Ответ пользователю<textarea id="owner-appeal-reply" maxlength="1500" required></textarea></label>' +
                '<button type="submit">Отправить ответ</button>' +
                '<div id="owner-appeal-reply-status" class="appeal-info"></div>' +
            '</form>';

        if (item.topic?.form_type === "custom_wallet") {
            html +=
                '<div class="appeal-divider"></div>' +
                '<div class="appeal-section-title">Кастомный кошелёк</div>' +
                '<div class="appeal-section-sub">Можно назначить готовый дизайн или загрузить индивидуальный по пожеланиям пользователя.</div>' +
                '<div class="appeal-form">' +
                    '<label>Готовый дизайн <select id="owner-appeal-template-select"><option value="">Выберите дизайн</option></select></label>' +
                    '<button id="owner-assign-template" type="button">Установить готовый дизайн</button>' +
                '</div>' +
                '<div class="appeal-inline-note" style="margin-top:12px">Индивидуальный дизайн</div>' +
                '<form id="owner-individual-skin-form" class="appeal-form">' +
                    '<label>Название <input id="owner-individual-title" maxlength="120" required placeholder="Например, Sakura для ' + esc(user.first_name || "пользователя") + '"></label>' +
                    '<label>Текст на карточке <select id="owner-individual-theme"><option value="dark">Тёмный</option><option value="light">Светлый</option></select></label>' +
                    '<label>Файл до 2 МБ <input id="owner-individual-file" class="appeal-file" type="file" accept="image/png,image/jpeg,image/webp" required></label>' +
                    '<button type="submit">Загрузить и установить</button>' +
                    '<div id="owner-individual-status" class="appeal-info"></div>' +
                '</form>';
        }

        panel.innerHTML = html;
        panel.querySelectorAll("[data-appeal-status]").forEach((button) => {
            button.addEventListener("click", () => setOwnerStatus(button.dataset.appealStatus));
        });
        document.getElementById("owner-appeal-reply-form")?.addEventListener("submit", submitOwnerReply);
        document.getElementById("owner-assign-template")?.addEventListener("click", assignSelectedTemplate);
        document.getElementById("owner-individual-skin-form")?.addEventListener("submit", uploadIndividualSkin);
        populateTemplateSelect();
    }

    function statusButtons(current) {
        return ["in_progress", "approved", "completed", "rejected"].map((status) => {
            const disabled = status === current ? " disabled" : "";
            const cls = status === "rejected" ? " appeal-button danger" : (status === "completed" ? " appeal-button secondary" : " appeal-button");
            return '<button class="' + cls.trim() + '" type="button" data-appeal-status="' + status + '"' + disabled + '>' + esc(STATUS_LABELS[status]) + '</button>';
        }).join("");
    }

    async function setOwnerStatus(status) {
        if (!currentOwnerAppealId) return;
        try {
            await api("/api/owner/appeals/" + currentOwnerAppealId + "/status", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({ status }),
            });
            await openOwnerAppeal(currentOwnerAppealId);
        } catch (error) {
            alert(error.message);
        }
    }

    async function submitOwnerReply(event) {
        event.preventDefault();
        const input = document.getElementById("owner-appeal-reply");
        const status = document.getElementById("owner-appeal-reply-status");
        const body = input?.value.trim() || "";
        if (!body) {
            status.textContent = "Ответ пустой.";
            status.className = "appeal-error";
            return;
        }
        try {
            await api("/api/owner/appeals/" + currentOwnerAppealId + "/reply", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({ body }),
            });
            input.value = "";
            await openOwnerAppeal(currentOwnerAppealId);
        } catch (error) {
            status.textContent = error.message;
            status.className = "appeal-error";
        }
    }

    function validateImageFile(file) {
        if (!file) throw new Error("Выберите изображение.");
        if (!allowedImageTypes.has(file.type)) throw new Error("Нужен PNG, JPEG или WEBP.");
        if (file.size <= 0) throw new Error("Файл пуст.");
        if (file.size > 2 * 1024 * 1024) throw new Error("Файл должен быть не больше 2 МБ.");
    }

    async function uploadSkin(file, title, theme, isTemplate, appealId = null) {
        validateImageFile(file);
        const params = new URLSearchParams({
            title,
            text_theme: theme,
            is_template: String(Boolean(isTemplate)),
        });
        if (appealId) params.set("appeal_id", String(appealId));
        const response = await fetch(API + "/api/owner/wallet-skins?" + params.toString(), {
            method: "POST",
            headers: {
                "X-Telegram-Init-Data": tg?.initData || "",
                "Content-Type": file.type,
            },
            body: file,
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data.detail || "Не удалось загрузить дизайн");
        return data.skin;
    }

    async function uploadIndividualSkin(event) {
        event.preventDefault();
        const title = document.getElementById("owner-individual-title")?.value.trim() || "";
        const theme = document.getElementById("owner-individual-theme")?.value || "dark";
        const file = document.getElementById("owner-individual-file")?.files?.[0];
        const status = document.getElementById("owner-individual-status");
        if (!title) {
            status.textContent = "Укажите название дизайна.";
            status.className = "appeal-error";
            return;
        }
        try {
            validateImageFile(file);
            status.textContent = "Загружаем и устанавливаем дизайн…";
            status.className = "appeal-info";
            const params = new URLSearchParams({
                title,
                text_theme: theme,
            });
            const response = await fetch(
                API + "/api/owner/appeals/" + currentOwnerAppealId + "/wallet-skin?" + params.toString(),
                {
                    method: "POST",
                    headers: {
                        "X-Telegram-Init-Data": tg?.initData || "",
                        "Content-Type": file.type,
                    },
                    body: file,
                },
            );
            const data = await readJson(response);
            if (!response.ok) throw new Error(data.detail || "Не удалось установить дизайн");
            tg?.HapticFeedback?.notificationOccurred?.("success");
            await openOwnerAppeal(currentOwnerAppealId);
        } catch (error) {
            status.textContent = error.message;
            status.className = "appeal-error";
        }
    }

    async function assignSelectedTemplate() {
        const select = document.getElementById("owner-appeal-template-select");
        const skinId = Number.parseInt(select?.value || "", 10);
        if (!Number.isInteger(skinId) || skinId < 1) {
            alert("Выберите готовый дизайн.");
            return;
        }
        try {
            await api("/api/owner/appeals/" + currentOwnerAppealId + "/assign-skin", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({ skin_id: skinId, complete_appeal: true }),
            });
            tg?.HapticFeedback?.notificationOccurred?.("success");
            await openOwnerAppeal(currentOwnerAppealId);
        } catch (error) {
            alert(error.message);
        }
    }

    async function submitTemplate(event) {
        event.preventDefault();
        const titleInput = document.getElementById("owner-template-title");
        const theme = document.getElementById("owner-template-theme")?.value || "dark";
        const fileInput = document.getElementById("owner-template-file");
        const status = document.getElementById("owner-template-status");
        const title = titleInput?.value.trim() || "";
        const file = fileInput?.files?.[0];
        if (!title) {
            status.textContent = "Укажите название.";
            status.className = "appeal-error";
            return;
        }
        try {
            validateImageFile(file);
            status.textContent = "Загружаем…";
            status.className = "appeal-info";
            await uploadSkin(file, title, theme, true);
            titleInput.value = "";
            fileInput.value = "";
            status.textContent = "Дизайн добавлен.";
            status.className = "appeal-success";
            await loadOwnerTemplates();
        } catch (error) {
            status.textContent = error.message;
            status.className = "appeal-error";
        }
    }

    async function loadOwnerTemplates() {
        const box = document.getElementById("owner-template-list");
        if (!box || !tg?.initData) return;
        try {
            const data = await api("/api/owner/wallet-skins", { headers: headers() });
            window.__nyanWalletTemplates = (data.skins || []).filter((skin) => skin.is_template && skin.is_active);
            const allTemplates = (data.skins || []).filter((skin) => skin.is_template);
            if (!allTemplates.length) {
                box.innerHTML = '<div class="appeal-empty">Готовых дизайнов пока нет.</div>';
                populateTemplateSelect();
                return;
            }
            box.innerHTML = "";
            for (const skin of allTemplates) {
                const card = document.createElement("article");
                card.className = "appeal-skin";
                card.innerHTML =
                    '<div class="appeal-skin-preview"></div>' +
                    '<div class="appeal-skin-body"><div class="appeal-skin-title">' + esc(skin.title) + '</div>' +
                    '<div class="appeal-skin-meta">' + (skin.is_active ? "Активен" : "Отключён") + '</div>' +
                    '<button type="button">' + (skin.is_active ? "Отключить" : "Включить") + '</button></div>';
                box.appendChild(card);
                skinUrl(skin.id).then((url) => {
                    const preview = card.querySelector(".appeal-skin-preview");
                    if (preview) preview.style.backgroundImage = 'url("' + url + '")';
                }).catch(() => {});
                card.querySelector("button")?.addEventListener("click", () => toggleTemplate(skin.id));
            }
            populateTemplateSelect();
        } catch (error) {
            box.innerHTML = '<div class="appeal-error">' + esc(error.message) + '</div>';
        }
    }

    function populateTemplateSelect() {
        const select = document.getElementById("owner-appeal-template-select");
        if (!select) return;
        const current = select.value;
        select.innerHTML = '<option value="">Выберите дизайн</option>';
        for (const skin of window.__nyanWalletTemplates || []) {
            const option = document.createElement("option");
            option.value = String(skin.id);
            option.textContent = skin.title;
            select.appendChild(option);
        }
        if ([...select.options].some((option) => option.value === current)) select.value = current;
    }

    async function toggleTemplate(id) {
        try {
            await api("/api/owner/wallet-skins/" + id + "/toggle", {
                method: "POST",
                headers: headers(true),
            });
            await loadOwnerTemplates();
        } catch (error) {
            alert(error.message);
        }
    }

    async function submitTopic(event) {
        event.preventDefault();
        const status = document.getElementById("owner-topic-status");
        const startRaw = document.getElementById("owner-topic-start")?.value || "";
        const endRaw = document.getElementById("owner-topic-end")?.value || "";
        const startDate = startRaw ? new Date(startRaw) : null;
        const endDate = endRaw ? new Date(endRaw) : null;
        if ((startDate && Number.isNaN(startDate.getTime())) || (endDate && Number.isNaN(endDate.getTime()))) {
            status.textContent = "Некорректная дата.";
            status.className = "appeal-error";
            return;
        }
        if (startDate && endDate && endDate <= startDate) {
            status.textContent = "Окончание должно быть позже начала.";
            status.className = "appeal-error";
            return;
        }
        const payload = {
            code: document.getElementById("owner-topic-code")?.value.trim() || "",
            title: document.getElementById("owner-topic-title")?.value.trim() || "",
            description: document.getElementById("owner-topic-desc")?.value.trim() || "",
            form_type: document.getElementById("owner-topic-type")?.value || "general",
            starts_at: startDate ? startDate.toISOString() : null,
            ends_at: endDate ? endDate.toISOString() : null,
        };
        if (!payload.code || !payload.title || !payload.description) {
            status.textContent = "Заполните код, название и описание.";
            status.className = "appeal-error";
            return;
        }
        try {
            await api("/api/owner/appeal-topics", {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify(payload),
            });
            document.getElementById("owner-topic-code").value = "";
            document.getElementById("owner-topic-title").value = "";
            document.getElementById("owner-topic-desc").value = "";
            document.getElementById("owner-topic-start").value = "";
            document.getElementById("owner-topic-end").value = "";
            status.textContent = "Тема создана.";
            status.className = "appeal-success";
            await loadOwnerTopics();
        } catch (error) {
            status.textContent = error.message;
            status.className = "appeal-error";
        }
    }

    async function loadOwnerTopics() {
        const box = document.getElementById("owner-topic-list");
        if (!box || !tg?.initData) return;
        try {
            const data = await api("/api/owner/appeal-topics", { headers: headers() });
            if (!data.topics?.length) {
                box.innerHTML = '<div class="appeal-empty">Тем пока нет.</div>';
                return;
            }
            box.innerHTML = "";
            for (const topic of data.topics) {
                const card = document.createElement("article");
                card.className = "appeal-card";
                card.innerHTML =
                    '<div class="appeal-card-head"><div><div class="appeal-title">' + esc(topic.title) + '</div>' +
                    '<div class="appeal-meta">' + esc(topic.code) + ' · ' + esc(topic.form_type) + '<br>' + esc(topic.description) +
                    (topic.starts_at ? '<br>Начало: ' + fmt(topic.starts_at) : "") +
                    (topic.ends_at ? '<br>Окончание: ' + fmt(topic.ends_at) : "") + '</div></div>' +
                    '<span class="appeal-status' + (topic.is_active ? "" : " reject") + '">' + (topic.is_active ? "Активна" : "Выключена") + '</span></div>' +
                    '<div class="appeal-actions"><button class="appeal-button secondary" type="button">' + (topic.is_active ? "Отключить" : "Включить") + '</button></div>';
                card.querySelector("button")?.addEventListener("click", () => toggleTopic(topic.id));
                box.appendChild(card);
            }
        } catch (error) {
            box.innerHTML = '<div class="appeal-error">' + esc(error.message) + '</div>';
        }
    }

    async function toggleTopic(id) {
        try {
            await api("/api/owner/appeal-topics/" + id + "/toggle", {
                method: "POST",
                headers: headers(true),
            });
            await loadOwnerTopics();
        } catch (error) {
            alert(error.message);
        }
    }

    function parsePositiveInt(value) {
        const parsed = Number.parseInt(value || "", 10);
        return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
    }

    async function handleDeepLinks() {
        const params = new URLSearchParams(window.location.search);
        const userAppeal = parsePositiveInt(params.get("appeal"));
        const ownerAppeal = parsePositiveInt(params.get("ownerAppeal"));
        if (ownerAppeal) {
            await openOwnerAppeal(ownerAppeal, true);
            return;
        }
        if (userAppeal) {
            await openAppealDetail(userAppeal);
        }
    }

    window.addEventListener("beforeunload", () => {
        for (const url of skinObjectUrls.values()) URL.revokeObjectURL(url);
        skinObjectUrls.clear();
    });

    buildUi();
    window.setTimeout(() => {
        loadMySkins(false);
        handleDeepLinks();
    }, 900);
})();