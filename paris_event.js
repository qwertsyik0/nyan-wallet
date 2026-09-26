(function () {
    "use strict";

    const API_BASE = "https://nyan-wallet-api.onrender.com";
    const tgApp = window.Telegram?.WebApp || null;
    const EVENT_ID = "le-nyan-paris";
    const STATUS_LABELS = {
        pending: "новая",
        accepted: "принята",
        rejected: "отклонена",
        needs_changes: "нужны правки",
    };
    const STATUS_TEXT = {
        pending: "Анкета уже отправлена. Владелец рассмотрит её и выдаст роль лично.",
        accepted: "Анкета принята. Роль будет выдана владельцем лично.",
        rejected: "Анкета отклонена. Повторная отправка сейчас недоступна.",
        needs_changes: "Владелец попросил правки. Исправь анкету и отправь её снова на рассмотрение.",
    };

    let myApplication = null;
    let ownerLoadedOnce = false;
    let selectedOwnerApplication = null;

    function telegramInitData() {
        return tgApp?.initData || "";
    }

    function authHeaders(json) {
        const headers = { "X-Telegram-Init-Data": telegramInitData() };
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

    function hideMainViews() {
        document.querySelectorAll(".view, .loading-view").forEach((view) => {
            view.classList.add("hidden");
        });
    }

    function showView(viewId) {
        const view = document.getElementById(viewId);
        if (!view) return;
        hideMainViews();
        view.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tgApp?.BackButton?.show?.();
    }

    function showWallet() {
        hideMainViews();
        document.getElementById("wallet-view")?.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tgApp?.BackButton?.hide?.();
    }

    function showEventInfo() {
        showView("paris-event-view");
    }

    function showApplicationForm() {
        renderApplicationForm();
        showView("paris-application-view");
    }

    function statusLabel(status) {
        return STATUS_LABELS[status] || "неизвестно";
    }

    function formatDate(value) {
        if (!value) return "";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "";
        return date.toLocaleString("ru-RU", {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    function safeUserLabel(application) {
        const applicant = application?.applicant;
        if (applicant?.label) return applicant.label;
        if (application?.telegram_username) return application.telegram_username;
        if (application?.telegram_id) return `ID ${application.telegram_id}`;
        return "пользователь";
    }

    function createLayout() {
        const appRoot = document.querySelector(".app");
        const walletCard = document.getElementById("wallet-card");
        if (!appRoot || !walletCard || document.getElementById("paris-event-banner")) return;

        const banner = document.createElement("button");
        banner.id = "paris-event-banner";
        banner.className = "paris-event-banner";
        banner.type = "button";
        banner.innerHTML = [
            '<span class="paris-event-kicker">сезонное событие</span>',
            '<span class="paris-event-title">ВСТУПИТЬ В ПАРИЖ</span>',
            '<span class="paris-event-subtitle" id="paris-event-subtitle">Le Nyan Paris · Франция эпохи Наполеона</span>',
            '<span class="paris-event-arrow" aria-hidden="true">→</span>',
        ].join("");
        banner.addEventListener("click", showEventInfo);
        walletCard.insertAdjacentElement("afterend", banner);

        appRoot.insertAdjacentHTML(
            "beforeend",
            '<main id="paris-event-view" class="view hidden">' +
                '<div class="subpage-header">' +
                    '<button id="paris-event-back" class="back-button" type="button" aria-label="Назад">‹</button>' +
                    '<div>' +
                        '<div class="page-title">Le Nyan Paris</div>' +
                        '<div class="page-subtitle">городской интерактив Нян во Франции эпохи Наполеона</div>' +
                    '</div>' +
                '</div>' +
                '<section class="paris-event-page-card">' +
                    '<div class="paris-lore-kicker">Париж открывает ворота.</div>' +
                    '<h1>Le Nyan Paris</h1>' +
                    '<p>Империя Нян переносится во Францию эпохи Наполеона. Здесь каждый участник становится частью живого города: кто-то окажется дворянином, кто-то торговцем, журналистом, солдатом, судьёй, врачом, артистом, преступником или обычным жителем Парижа.</p>' +
                    '<p>Это не просто ролка и не обычный чат. Это город, где действия участников влияют на происходящее.</p>' +
                    '<p>В Париже будут указы, суды, слухи, рынок, газета, полиция, тайные интриги, городские события и решения, которые меняют ход сезона. Одни будут строить репутацию, другие искать власть, третьи скрывать свои мотивы, а кто-то просто попробует выжить среди шума улиц, разговоров в кафе и приказов императора.</p>' +
                    '<p>Роль не выдаётся автоматически. После анкеты владелец рассмотрит заявку и подберёт место персонажа в городе.</p>' +
                    '<p>Заполни анкету, если хочешь стать частью Парижа.</p>' +
                    '<button id="paris-join-button" class="paris-join-button" type="button">ПРИНЯТЬ УЧАСТИЕ</button>' +
                    '<div id="paris-event-status" class="paris-event-status" aria-live="polite"></div>' +
                '</section>' +
            '</main>' +
            '<main id="paris-application-view" class="view hidden">' +
                '<div class="subpage-header">' +
                    '<button id="paris-form-back" class="back-button" type="button" aria-label="Назад">‹</button>' +
                    '<div>' +
                        '<div class="page-title">Анкета Le Nyan Paris</div>' +
                        '<div class="page-subtitle">один пользователь может отправить одну анкету</div>' +
                    '</div>' +
                '</div>' +
                '<section class="paris-form-card">' +
                    '<div id="paris-form-status" class="paris-form-status" aria-live="polite"></div>' +
                    '<form id="paris-application-form" class="paris-application-form">' +
                        '<label><span>Имя персонажа *</span><input id="paris-first-name" type="text" maxlength="40" autocomplete="off" required></label>' +
                        '<label><span>Фамилия персонажа *</span><input id="paris-last-name" type="text" maxlength="40" autocomplete="off" required></label>' +
                        '<label><span>Возраст персонажа *</span><input id="paris-age" type="number" min="1" max="120" inputmode="numeric" required></label>' +
                        '<label><span>Пол персонажа *</span><input id="paris-gender" type="text" maxlength="40" autocomplete="off" placeholder="например: мужчина, женщина, другое" required></label>' +
                        '<label><span>Ориентация персонажа *</span><input id="paris-orientation" type="text" maxlength="80" autocomplete="off" required></label>' +
                        '<label><span>Telegram username *</span><input id="paris-username" type="text" maxlength="80" autocomplete="off" placeholder="@username" required></label>' +
                        '<label><span>Желаемая роль <small>необязательно, финально выдаёт владелец</small></span><input id="paris-role" type="text" maxlength="80" autocomplete="off" placeholder="например: журналист, дворянин, солдат"></label>' +
                        '<label><span>Принадлежность <small>необязательно</small></span><select id="paris-affiliation"><option value="">Не выбрано</option><option value="двор">Двор</option><option value="армия">Армия</option><option value="город">Город</option><option value="пресса">Пресса</option><option value="суд">Суд</option><option value="полиция">Полиция</option><option value="рынок">Рынок</option><option value="подполье">Подполье</option><option value="другое">Другое</option></select></label>' +
                        '<label><span>Краткое описание персонажа <small>необязательно</small></span><textarea id="paris-description" maxlength="600" rows="4" placeholder="кто он, откуда, чем живёт"></textarea></label>' +
                        '<label><span>Характер <small>необязательно</small></span><textarea id="paris-personality" maxlength="300" rows="3" placeholder="спокойный, хитрый, вспыльчивый, мягкий и т.д."></textarea></label>' +
                        '<label><span>Опыт в ролках <small>необязательно</small></span><textarea id="paris-experience" maxlength="300" rows="3" placeholder="можно коротко: был/не был, какой формат знаком"></textarea></label>' +
                        '<label><span>Комментарий от себя <small>необязательно</small></span><textarea id="paris-comment" maxlength="400" rows="3" placeholder="что важно учесть владельцу"></textarea></label>' +
                        '<button id="paris-submit" class="paris-submit-button" type="submit">ОТПРАВИТЬ АНКЕТУ</button>' +
                    '</form>' +
                '</section>' +
            '</main>'
        );

        document.getElementById("paris-event-back")?.addEventListener("click", showWallet);
        document.getElementById("paris-form-back")?.addEventListener("click", showEventInfo);
        document.getElementById("paris-join-button")?.addEventListener("click", showApplicationForm);
        document.getElementById("paris-application-form")?.addEventListener("submit", submitApplication);

        if (tgApp?.BackButton?.onClick) {
            tgApp.BackButton.onClick(() => {
                const eventView = document.getElementById("paris-event-view");
                const applicationView = document.getElementById("paris-application-view");
                if (applicationView && !applicationView.classList.contains("hidden")) {
                    showEventInfo();
                } else if (eventView && !eventView.classList.contains("hidden")) {
                    showWallet();
                }
            });
        }

        createOwnerPanel();
    }

    function createOwnerPanel() {
        const ownerView = document.getElementById("owner-view");
        if (!ownerView || document.getElementById("paris-owner-section")) return;

        ownerView.insertAdjacentHTML(
            "beforeend",
            '<section id="paris-owner-section" class="admin-section paris-owner-section">' +
                '<div class="owner-title">Le Nyan Paris</div>' +
                '<div class="owner-subtitle">Заявки на участие в событии, роли выдаются владельцем лично.</div>' +
                '<div class="paris-owner-toolbar">' +
                    '<select id="paris-owner-filter" aria-label="Фильтр заявок">' +
                        '<option value="">Все заявки</option>' +
                        '<option value="pending">Новые</option>' +
                        '<option value="needs_changes">Нужны правки</option>' +
                        '<option value="accepted">Принятые</option>' +
                        '<option value="rejected">Отклонённые</option>' +
                    '</select>' +
                    '<button id="paris-owner-refresh" type="button">Обновить</button>' +
                '</div>' +
                '<div id="paris-owner-counts" class="paris-owner-counts"></div>' +
                '<div id="paris-owner-status" class="owner-status" aria-live="polite"></div>' +
                '<div id="paris-owner-list" class="owner-users-list"></div>' +
                '<div id="paris-owner-detail" class="paris-owner-detail" hidden></div>' +
            '</section>'
        );

        document.getElementById("paris-owner-filter")?.addEventListener("change", loadOwnerApplications);
        document.getElementById("paris-owner-refresh")?.addEventListener("click", loadOwnerApplications);

        const observer = new MutationObserver(() => {
            if (!ownerView.classList.contains("hidden") && !ownerLoadedOnce) {
                ownerLoadedOnce = true;
                loadOwnerApplications();
            }
        });
        observer.observe(ownerView, { attributes: true, attributeFilter: ["class"] });
    }

    async function loadMyApplication() {
        if (!telegramInitData()) {
            updateApplicationStatusCopy(null);
            return;
        }

        try {
            const response = await fetch(`${API_BASE}/api/paris/applications/me`, {
                headers: authHeaders(false),
            });
            const data = await readJson(response);
            if (response.status === 404) {
                myApplication = null;
                updateApplicationStatusCopy(null);
                return;
            }
            if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить заявку");
            myApplication = data.application || null;
            updateApplicationStatusCopy(myApplication);
        } catch (_) {
            updateApplicationStatusCopy(null);
        }
    }

    function updateApplicationStatusCopy(application) {
        const bannerSubtitle = document.getElementById("paris-event-subtitle");
        const eventStatus = document.getElementById("paris-event-status");

        if (!application) {
            if (bannerSubtitle) bannerSubtitle.textContent = "Le Nyan Paris · Франция эпохи Наполеона";
            if (eventStatus) eventStatus.textContent = "";
            return;
        }

        const label = statusLabel(application.status);
        if (bannerSubtitle) bannerSubtitle.textContent = `заявка: ${label}`;
        if (eventStatus) {
            eventStatus.textContent = STATUS_TEXT[application.status] || `Статус заявки: ${label}`;
        }
    }

    function formValue(id) {
        return document.getElementById(id)?.value.trim() || "";
    }

    function setFormValue(id, value) {
        const element = document.getElementById(id);
        if (element) element.value = value || "";
    }

    function getApplicationPayload() {
        return {
            character_first_name: formValue("paris-first-name"),
            character_last_name: formValue("paris-last-name"),
            character_age: Number(formValue("paris-age")),
            character_gender: formValue("paris-gender"),
            character_orientation: formValue("paris-orientation"),
            telegram_username: formValue("paris-username"),
            role_preference: formValue("paris-role") || null,
            character_description: formValue("paris-description") || null,
            character_personality: formValue("paris-personality") || null,
            affiliation: formValue("paris-affiliation") || null,
            roleplay_experience: formValue("paris-experience") || null,
            applicant_comment: formValue("paris-comment") || null,
        };
    }

    function prefillForm(application) {
        const user = tgApp?.initDataUnsafe?.user || {};
        const username = user.username ? `@${user.username}` : "";

        setFormValue("paris-first-name", application?.character_first_name || "");
        setFormValue("paris-last-name", application?.character_last_name || "");
        setFormValue("paris-age", application?.character_age ? String(application.character_age) : "");
        setFormValue("paris-gender", application?.character_gender || "");
        setFormValue("paris-orientation", application?.character_orientation || "");
        setFormValue("paris-username", application?.telegram_username || username);
        setFormValue("paris-role", application?.role_preference || "");
        setFormValue("paris-affiliation", application?.affiliation || "");
        setFormValue("paris-description", application?.character_description || "");
        setFormValue("paris-personality", application?.character_personality || "");
        setFormValue("paris-experience", application?.roleplay_experience || "");
        setFormValue("paris-comment", application?.applicant_comment || "");
    }

    function renderApplicationForm() {
        const form = document.getElementById("paris-application-form");
        const status = document.getElementById("paris-form-status");
        const submit = document.getElementById("paris-submit");
        if (!form || !status || !submit) return;

        status.textContent = "";
        form.hidden = false;

        if (!telegramInitData()) {
            form.hidden = true;
            status.textContent = "Открой Nyan Wallet через Telegram, чтобы отправить анкету.";
            return;
        }

        if (!myApplication) {
            prefillForm(null);
            submit.textContent = "ОТПРАВИТЬ АНКЕТУ";
            return;
        }

        if (myApplication.status === "needs_changes") {
            prefillForm(myApplication);
            submit.textContent = "ОТПРАВИТЬ ПРАВКИ";
            status.textContent = myApplication.owner_comment
                ? `Комментарий владельца: ${myApplication.owner_comment}`
                : STATUS_TEXT.needs_changes;
            return;
        }

        form.hidden = true;
        const label = statusLabel(myApplication.status);
        const reviewed = myApplication.reviewed_at ? ` · ${formatDate(myApplication.reviewed_at)}` : "";
        status.textContent = `${STATUS_TEXT[myApplication.status] || "Анкета уже отправлена."} Статус: ${label}${reviewed}`;
        if (myApplication.owner_comment) {
            status.textContent += ` Комментарий владельца: ${myApplication.owner_comment}`;
        }
    }

    function validatePayload(payload) {
        const required = [
            ["character_first_name", "укажи имя персонажа"],
            ["character_last_name", "укажи фамилию персонажа"],
            ["character_gender", "укажи пол персонажа"],
            ["character_orientation", "укажи ориентацию персонажа"],
            ["telegram_username", "укажи Telegram username"],
        ];
        for (const [key, message] of required) {
            if (!payload[key]) throw new Error(message);
        }
        if (!Number.isInteger(payload.character_age) || payload.character_age < 1 || payload.character_age > 120) {
            throw new Error("укажи корректный возраст персонажа");
        }
    }

    async function submitApplication(event) {
        event.preventDefault();
        const status = document.getElementById("paris-form-status");
        const submit = document.getElementById("paris-submit");
        if (!status || !submit) return;

        if (!telegramInitData()) {
            status.textContent = "Открой Nyan Wallet через Telegram.";
            return;
        }

        let payload;
        try {
            payload = getApplicationPayload();
            validatePayload(payload);
        } catch (error) {
            status.textContent = error.message || "Проверь анкету.";
            return;
        }

        submit.disabled = true;
        submit.textContent = myApplication?.status === "needs_changes" ? "ОТПРАВЛЯЕМ ПРАВКИ…" : "ОТПРАВЛЯЕМ…";
        status.textContent = "";

        try {
            const isEdit = myApplication?.status === "needs_changes";
            const response = await fetch(`${API_BASE}${isEdit ? "/api/paris/applications/me" : "/api/paris/applications"}`, {
                method: isEdit ? "PUT" : "POST",
                headers: authHeaders(true),
                body: JSON.stringify(payload),
            });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось отправить анкету");

            myApplication = data.application;
            updateApplicationStatusCopy(myApplication);
            tgApp?.HapticFeedback?.notificationOccurred?.("success");
            renderApplicationForm();
        } catch (error) {
            status.textContent = error.message || "Не удалось отправить анкету";
            tgApp?.HapticFeedback?.notificationOccurred?.("error");
        } finally {
            submit.disabled = false;
            submit.textContent = myApplication?.status === "needs_changes" ? "ОТПРАВИТЬ ПРАВКИ" : "ОТПРАВИТЬ АНКЕТУ";
        }
    }

    function renderCounts(counts) {
        const target = document.getElementById("paris-owner-counts");
        if (!target) return;
        const items = [
            ["pending", "новые"],
            ["needs_changes", "правки"],
            ["accepted", "приняты"],
            ["rejected", "отклонены"],
        ];
        target.textContent = items.map(([key, label]) => `${label}: ${counts?.[key] || 0}`).join(" · ");
    }

    async function loadOwnerApplications() {
        if (!telegramInitData()) return;

        const statusEl = document.getElementById("paris-owner-status");
        const list = document.getElementById("paris-owner-list");
        const detail = document.getElementById("paris-owner-detail");
        const filter = document.getElementById("paris-owner-filter");
        if (!statusEl || !list) return;

        statusEl.textContent = "Загружаем заявки…";
        list.innerHTML = "";
        if (detail) {
            detail.hidden = true;
            detail.innerHTML = "";
        }

        try {
            const params = new URLSearchParams();
            const status = filter?.value || "";
            if (status) params.set("status", status);

            const response = await fetch(`${API_BASE}/api/owner/paris/applications?${params.toString()}`, {
                headers: authHeaders(false),
            });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить заявки");

            renderCounts(data.counts);
            const applications = data.applications || [];
            statusEl.textContent = applications.length ? `Заявок: ${applications.length}` : "Заявок пока нет";

            applications.forEach((application) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "owner-user-row paris-owner-row";

                const left = document.createElement("div");
                left.className = "owner-user-row-main";

                const name = document.createElement("div");
                name.className = "owner-user-row-name";
                name.textContent = `${application.character_first_name} ${application.character_last_name}`;

                const meta = document.createElement("div");
                meta.className = "owner-user-row-meta";
                meta.textContent = `${safeUserLabel(application)} · ${statusLabel(application.status)} · ${formatDate(application.created_at)}`;

                const badge = document.createElement("div");
                badge.className = `paris-status-badge status-${application.status}`;
                badge.textContent = statusLabel(application.status);

                left.appendChild(name);
                left.appendChild(meta);
                button.appendChild(left);
                button.appendChild(badge);
                button.addEventListener("click", () => renderOwnerApplicationDetail(application));
                list.appendChild(button);
            });
        } catch (error) {
            statusEl.textContent = error.message || "Не удалось загрузить заявки";
        }
    }

    function addDetailRow(parent, label, value) {
        if (!value && value !== 0) return;
        const row = document.createElement("div");
        row.className = "paris-detail-row";

        const name = document.createElement("span");
        name.textContent = label;

        const text = document.createElement("b");
        text.textContent = String(value);

        row.appendChild(name);
        row.appendChild(text);
        parent.appendChild(row);
    }

    function renderOwnerApplicationDetail(application) {
        selectedOwnerApplication = application;
        const detail = document.getElementById("paris-owner-detail");
        if (!detail) return;

        detail.innerHTML = "";
        detail.hidden = false;

        const title = document.createElement("div");
        title.className = "paris-owner-detail-title";
        title.textContent = `${application.character_first_name} ${application.character_last_name}`;

        const meta = document.createElement("div");
        meta.className = "paris-owner-detail-meta";
        meta.textContent = `${safeUserLabel(application)} · статус: ${statusLabel(application.status)}`;

        const rows = document.createElement("div");
        rows.className = "paris-detail-grid";
        addDetailRow(rows, "Telegram ID", application.telegram_id);
        addDetailRow(rows, "Юз анкеты", application.telegram_username);
        addDetailRow(rows, "Возраст", application.character_age);
        addDetailRow(rows, "Пол", application.character_gender);
        addDetailRow(rows, "Ориентация", application.character_orientation);
        addDetailRow(rows, "Желаемая роль", application.role_preference);
        addDetailRow(rows, "Принадлежность", application.affiliation);
        addDetailRow(rows, "Описание", application.character_description);
        addDetailRow(rows, "Характер", application.character_personality);
        addDetailRow(rows, "Опыт в ролках", application.roleplay_experience);
        addDetailRow(rows, "Комментарий участника", application.applicant_comment);
        addDetailRow(rows, "Комментарий владельца", application.owner_comment);

        const commentLabel = document.createElement("label");
        commentLabel.className = "owner-field";
        commentLabel.innerHTML = '<span>Комментарий владельца <small>нужен для правок</small></span>';
        const comment = document.createElement("textarea");
        comment.id = "paris-owner-comment";
        comment.maxLength = 600;
        comment.rows = 3;
        comment.placeholder = "например: уточни возраст, роль и принадлежность";
        comment.value = application.owner_comment || "";
        commentLabel.appendChild(comment);

        const actions = document.createElement("div");
        actions.className = "paris-owner-actions";
        [
            ["accepted", "Принять"],
            ["needs_changes", "Нужны правки"],
            ["rejected", "Отклонить"],
        ].forEach(([status, label]) => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = label;
            button.className = `paris-owner-action status-${status}`;
            button.addEventListener("click", () => updateOwnerStatus(status));
            actions.appendChild(button);
        });

        const statusLine = document.createElement("div");
        statusLine.id = "paris-owner-detail-status";
        statusLine.className = "owner-status";

        detail.appendChild(title);
        detail.appendChild(meta);
        detail.appendChild(rows);
        detail.appendChild(commentLabel);
        detail.appendChild(actions);
        detail.appendChild(statusLine);
        detail.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    async function updateOwnerStatus(nextStatus) {
        if (!selectedOwnerApplication) return;

        const comment = document.getElementById("paris-owner-comment")?.value.trim() || "";
        const statusLine = document.getElementById("paris-owner-detail-status");
        if (nextStatus === "needs_changes" && !comment) {
            if (statusLine) statusLine.textContent = "Для правок нужен комментарий владельца.";
            return;
        }

        if (statusLine) statusLine.textContent = "Сохраняем…";

        try {
            const response = await fetch(`${API_BASE}/api/owner/paris/applications/${selectedOwnerApplication.id}/status`, {
                method: "POST",
                headers: authHeaders(true),
                body: JSON.stringify({
                    status: nextStatus,
                    owner_comment: comment || null,
                }),
            });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось обновить статус");

            selectedOwnerApplication = data.application;
            if (statusLine) statusLine.textContent = "Статус обновлён.";
            renderOwnerApplicationDetail(selectedOwnerApplication);
            loadOwnerApplications();
        } catch (error) {
            if (statusLine) statusLine.textContent = error.message || "Не удалось обновить статус";
        }
    }

    createLayout();
    loadMyApplication();
})();
