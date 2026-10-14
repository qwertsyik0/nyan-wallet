(() => {
    "use strict";

    const API = "https://nyan-wallet-api.onrender.com";
    const tg = window.Telegram?.WebApp;
    const root = document.getElementById("owner-view");
    if (!root) return;

    let cases = [];
    let loadedOnce = false;
    let loading = false;
    let detailToken = 0;

    function el(tag, className, textValue) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (textValue !== undefined && textValue !== null) node.textContent = String(textValue);
        return node;
    }

    function title(user, fallback) {
        if (user?.username) return "@" + user.username;
        return user?.first_name || "ID " + fallback;
    }

    function fmtDate(input) {
        if (!input) return "нет даты";
        const date = new Date(input);
        if (!Number.isFinite(date.getTime())) return "нет даты";
        return date.toLocaleString("ru-RU", { timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) + " МСК";
    }

    function createUI() {
        const section = el("section", "admin-section nyan-antifraud");
        section.id = "nyan-antifraud-section";
        section.innerHTML =
            '<div class="owner-title">Антифрод-центр</div>' +
            '<div class="owner-subtitle">Поиск подозрительных цепочек · только для владельца</div>' +
            '<div class="nyan-af-tools">' +
                '<input id="nyan-af-search" type="search" placeholder="@username или Telegram ID" aria-label="Поиск аккаунтов">' +
                '<select id="nyan-af-filter" aria-label="Фильтр уровня риска">' +
                    '<option value="all">Все сигналы</option>' +
                    '<option value="high">Высокий риск</option>' +
                    '<option value="medium">Средний риск</option>' +
                '</select>' +
                '<button id="nyan-af-refresh" type="button">Сканировать</button>' +
            '</div>' +
            '<div id="nyan-af-status" class="nyan-af-status" role="status">Загрузка по запросу владельца</div>' +
            '<div id="nyan-af-totals" class="nyan-af-totals"></div>' +
            '<div id="nyan-af-cases" class="nyan-af-list"></div>' +
            '<div id="nyan-af-detail" class="nyan-af-detail" hidden></div>' +
            '<p class="nyan-af-disclaimer">Сигнал не доказывает мультиаккаунтинг. Совпадения IP/устройства здесь не определяются. Никаких автоматических блокировок или списаний.</p>';
        const anchor = root.querySelector("#owner-user-card");
        root.insertBefore(section, anchor || root.firstChild);

        section.querySelector("#nyan-af-refresh").addEventListener("click", refresh);
        section.querySelector("#nyan-af-search").addEventListener("input", renderList);
        section.querySelector("#nyan-af-filter").addEventListener("change", renderList);
        return section;
    }

    const section = createUI();
    const status = section.querySelector("#nyan-af-status");
    const totals = section.querySelector("#nyan-af-totals");
    const list = section.querySelector("#nyan-af-cases");
    const detail = section.querySelector("#nyan-af-detail");

    async function fetchOwner(route) {
        if (!tg?.initData) throw new Error("Откройте приложение через Telegram.");
        const response = await fetch(API + route, {
            headers: { "X-Telegram-Init-Data": tg.initData },
            cache: "no-store",
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const reason = typeof data?.detail === "string" ? data.detail : data?.detail?.message;
            throw new Error(reason || "Не удалось получить данные антифрода");
        }
        return data;
    }

    function riskLabel(level) {
        return level === "high" ? "высокий" : level === "medium" ? "средний" : "низкий";
    }

    function renderList() {
        list.replaceChildren();
        const phrase = section.querySelector("#nyan-af-search").value.trim().toLowerCase().replace(/^@/, "");
        const level = section.querySelector("#nyan-af-filter").value;
        const matched = cases.filter(item => {
            if (level !== "all" && item.risk_level !== level) return false;
            if (!phrase) return true;
            return [item.sender_id, item.recipient_id,
                item.sender?.username, item.recipient?.username,
                item.sender?.first_name, item.recipient?.first_name]
                .some(value => String(value || "").toLowerCase().includes(phrase));
        });
        if (!matched.length) {
            list.appendChild(el("p", "nyan-af-empty", cases.length ? "Нет совпадений по фильтру." : "Подозрительных цепочек в просмотренных переводах нет."));
            return;
        }
        for (const item of matched) {
            const card = el("article", "nyan-af-case");
            const heading = el("div", "nyan-af-case-top");
            const names = el("strong", "", title(item.sender, item.sender_id) + " → " + title(item.recipient, item.recipient_id));
            const badge = el("span", "nyan-af-risk nyan-af-risk-" + item.risk_level, riskLabel(item.risk_level) + " риск");
            heading.append(names, badge);
            card.append(heading);
            card.appendChild(el("div", "nyan-af-meta",
                item.transfer_total + " 🐾 · " + item.transfer_count + " перевод(ов) · " +
                item.promo_count + " промокод(ов)"));
            for (const reason of item.reasons || []) {
                card.appendChild(el("p", "nyan-af-reason", "• " + reason));
            }
            if (item.sender_banned || item.recipient_banned) {
                card.appendChild(el("p", "nyan-af-banned", "Блокировка уже есть: " +
                    [item.sender_banned ? title(item.sender, item.sender_id) : null,
                     item.recipient_banned ? title(item.recipient, item.recipient_id) : null]
                    .filter(Boolean).join(", ")));
            }
            const button = el("button", "nyan-af-open", "Посмотреть доказательства");
            button.type = "button";
            button.addEventListener("click", () => openDetails(item));
            card.appendChild(button);
            list.appendChild(card);
        }
    }

    function makeLine(label, value) {
        const row = el("div", "nyan-af-line");
        row.append(el("span", "", label), el("strong", "", value));
        return row;
    }

    function buildTableHeading(textValue) {
        return el("h4", "nyan-af-heading", textValue);
    }

    function renderDetail(data) {
        detail.replaceChildren();
        detail.hidden = false;
        const back = el("button", "nyan-af-back", "← Вернуться к списку");
        back.type = "button";
        back.addEventListener("click", () => {
            detail.hidden = true;
            detail.replaceChildren();
        });
        detail.appendChild(back);
        detail.appendChild(buildTableHeading(
            title(data.sender, data.sender?.telegram_id) + " → " +
            title(data.recipient, data.recipient?.telegram_id)
        ));
        detail.appendChild(el("p", "nyan-af-caution", data.note || "Решение принимает администрация."));

        detail.appendChild(makeLine("Отправитель", String(data.sender.telegram_id)));
        detail.appendChild(makeLine("Получатель", String(data.recipient.telegram_id)));
        detail.appendChild(makeLine("Баланс отправителя", data.sender.balance + " 🐾"));
        detail.appendChild(makeLine("Баланс получателя", data.recipient.balance + " 🐾"));
        detail.appendChild(makeLine("Реферальная связь", data.referral
            ? "подтверждена · " + fmtDate(data.referral.created_at)
            : "не найдена"));
        detail.appendChild(makeLine("Прямые переводы", data.transfers.length + " шт. · " + data.transfer_total_in_history + " 🐾" +
            (data.transfers_truncated ? " · показаны последние 100" : "")));
        detail.appendChild(makeLine("Отправитель", data.sender_ban ? "заблокирован" : "нет блокировки"));
        detail.appendChild(makeLine("Получатель", data.recipient_ban ? "заблокирован" : "нет блокировки"));

        detail.appendChild(buildTableHeading("Переводы между аккаунтами"));
        if (!data.transfers.length) detail.appendChild(el("p", "nyan-af-empty", "Прямых переводов не найдено."));
        for (const item of data.transfers || []) {
            const row = el("div", "nyan-af-event");
            row.appendChild(el("strong", "", item.amount + " 🐾 · " + fmtDate(item.created_at)));
            if (item.note) row.appendChild(el("div", "", "Комментарий: " + item.note));
            detail.appendChild(row);
        }

        detail.appendChild(buildTableHeading("Активированные промокоды отправителя"));
        if (!data.promos.length) detail.appendChild(el("p", "nyan-af-empty", "Промокоды не найдены."));
        for (const promo of data.promos || []) {
            detail.appendChild(el("div", "nyan-af-event", promo.code + " · +" + promo.amount + " 🐾 · " + fmtDate(promo.created_at)));
        }
        if (data.promos_truncated) detail.appendChild(el("p", "nyan-af-empty", "Показаны последние 50 промокодов."));

        detail.appendChild(buildTableHeading("История важных операций"));
        for (const op of data.operations || []) {
            const item = el("div", "nyan-af-event");
            item.appendChild(el("strong", "", (op.amount > 0 ? "+" : "") + op.amount + " 🐾 · " + op.type));
            item.appendChild(el("div", "", "ID " + op.telegram_id + " · " + fmtDate(op.created_at)));
            if (op.description) item.appendChild(el("div", "", op.description));
            detail.appendChild(item);
        }
        if (data.operations_truncated) detail.appendChild(el("p", "nyan-af-empty", "Показаны последние 80 операций."));

        const actions = el("div", "nyan-af-actions");
        for (const user of [data.sender, data.recipient]) {
            const button = el("button", "nyan-af-owner-open", "Открыть " + title(user, user.telegram_id));
            button.type = "button";
            button.addEventListener("click", () => {
                if (typeof window.selectOwnerUser === "function") {
                    void window.selectOwnerUser(user.telegram_id).then(() => {
                        document.getElementById("owner-user-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
                    });
                } else {
                    section.querySelector("#nyan-af-search").value = String(user.telegram_id);
                    renderList();
                    detail.hidden = true;
                }
            });
            actions.appendChild(button);
        }
        detail.appendChild(actions);
        detail.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    async function openDetails(item) {
        if (window.__nyanIsOwner !== true) return;
        const token = ++detailToken;
        detail.hidden = false;
        detail.replaceChildren(el("p", "nyan-af-status", "Проверяем историю переводов и бонусов…"));
        try {
            const data = await fetchOwner("/api/owner/antifraud/pair/" +
                encodeURIComponent(item.sender_id) + "/" + encodeURIComponent(item.recipient_id));
            if (token !== detailToken) return;
            renderDetail(data);
        } catch (error) {
            if (token !== detailToken) return;
            detail.replaceChildren(el("p", "nyan-af-error", error?.message || "Не удалось загрузить историю."));
        }
    }

    async function refresh() {
        if (window.__nyanIsOwner !== true || loading) return;
        loading = true;
        section.querySelector("#nyan-af-refresh").disabled = true;
        status.textContent = "Анализируем переводы, рефералов и промокоды…";
        try {
            const data = await fetchOwner("/api/owner/antifraud/cases");
            cases = Array.isArray(data.cases) ? data.cases : [];
            loadedOnce = true;
            const high = cases.filter(x => x.risk_level === "high").length;
            totals.replaceChildren(
                makeLine("Сигналов", String(data.total_candidates)),
                makeLine("Высокий риск", String(high)),
                makeLine("Переводов изучено", String(data.scanned_transfers)),
            );
            status.textContent = "Готово · проверены последние " + data.scanned_transfers +
                " переводов" + (data.truncated ? " · выборка ограничена, не вся история" : "") +
                ". Это сигналы для проверки, не доказанные нарушения.";
            renderList();
        } catch (error) {
            status.textContent = "Ошибка: " + (error?.message || "не удалось провести проверку");
        } finally {
            loading = false;
            section.querySelector("#nyan-af-refresh").disabled = false;
        }
    }

    const ownerButton = document.getElementById("owner-button");
    ownerButton?.addEventListener("click", () => {
        if (window.__nyanIsOwner === true && !loadedOnce) void refresh();
    });
    window.addEventListener("nyan-owner-state", event => {
        const isOwner = event.detail?.is_owner === true;
        section.hidden = !isOwner;
        if (!isOwner) {
            ++detailToken;
            cases = [];
            loadedOnce = false;
            list.replaceChildren();
            totals.replaceChildren();
            detail.hidden = true;
        }
    });
    section.hidden = window.__nyanIsOwner !== true;
})();
