(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    let ownerLoaded = false;
    let editingTaskId = null;
    let recording = false;

    function headers(json = false) {
        const result = { "X-Telegram-Init-Data": tg?.initData || "" };
        if (json) result["Content-Type"] = "application/json";
        return result;
    }

    async function readJson(response) {
        try { return await response.json(); } catch (_) { return {}; }
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
        const d = new Date(value);
        if (Number.isNaN(d.getTime())) return "";
        return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    }

    async function confirmText(text) {
        if (tg?.showConfirm) return await new Promise(resolve => tg.showConfirm(text, resolve));
        return window.confirm(text);
    }

    async function postEvent(action_type, action_value = null, amount = 1) {
        if (!tg?.initData || recording) return null;
        recording = true;
        try {
            const response = await fetch(`${API}/api/tasks/events`, {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({ action_type, action_value, amount }),
                cache: "no-store",
            });
            const data = await readJson(response);
            if (response.ok && data?.balance != null) updateBalance(data.balance);
            if (response.ok) setTimeout(loadTasks, 150);
            return data;
        } catch (_) {
            return null;
        } finally {
            recording = false;
        }
    }

    function installFetchWatcher() {
        if (window.__nyanDailyTaskFetchWatcher) return;
        window.__nyanDailyTaskFetchWatcher = true;
        const originalFetch = window.fetch.bind(window);
        window.fetch = async (...args) => {
            const response = await originalFetch(...args);
            try {
                const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
                const method = String(args[1]?.method || "GET").toUpperCase();
                if (response.ok && url.includes(API) && !url.includes("/api/tasks/")) {
                    if (url.includes("/api/rewards") && method === "GET") setTimeout(() => postEvent("open_catalog"), 60);
                    if (url.includes("/api/promo/redeem") && method === "POST") setTimeout(() => postEvent("promo_redeem"), 60);
                    if (url.includes("/api/activity/check-in") && method === "POST") setTimeout(() => postEvent("activity_check_in"), 60);
                    if (url.includes("/api/referral") && method === "POST") setTimeout(() => postEvent("referral_completed"), 60);
                    if (url.includes("/api/giveaways") && method === "POST") setTimeout(() => postEvent("giveaway_join"), 60);
                }
            } catch (_) {}
            return response;
        };
    }

    function updateBalance(balance) {
        const box = document.getElementById("balance");
        if (box && box.textContent !== "∞") box.textContent = String(balance);
    }

    function ensureUserCard() {
        let card = document.getElementById("daily-tasks-card");
        if (card) return card;
        const wallet = document.getElementById("wallet-view");
        if (!wallet) return null;
        card = document.createElement("section");
        card.id = "daily-tasks-card";
        card.className = "daily-tasks-card";
        card.innerHTML = `<div class="daily-tasks-head"><div><div class="daily-tasks-title">Ежедневные задания</div><div class="daily-tasks-sub">выполняйте задания и получайте лапкоины</div></div><div id="daily-tasks-summary" class="daily-tasks-summary">0 из 0</div></div><div id="daily-task-list" class="daily-task-list"><div class="daily-empty">Загружаем задания…</div></div>`;
        const activity = document.getElementById("activity-streak-card");
        if (activity?.parentNode) activity.insertAdjacentElement("afterend", card);
        else document.getElementById("wallet-card")?.insertAdjacentElement("afterend", card) || wallet.appendChild(card);
        return card;
    }

    function statusLabel(status) {
        return {
            available: "доступно",
            in_progress: "в процессе",
            awaiting_confirmation: "ожидает подтверждения",
            reward_available: "награда доступна",
            reward_claimed: "награда получена",
            future: "скоро",
            expired: "истекло",
            disabled: "отключено",
        }[status] || status;
    }

    function actionText(task) {
        if (task.status === "reward_claimed") return "✓ Выполнено";
        if (task.status === "awaiting_confirmation") return "На проверке";
        if (task.task_type === "manual") return "Выполнил";
        if (task.task_type === "link") return "Перейти";
        if (task.action_type === "open_catalog") return "Перейти";
        if (task.action_type === "open_earn") return "Открыть";
        if (task.action_type === "open_profile") return "Открыть";
        if (task.action_type === "promo_redeem") return "К промокоду";
        return "Выполнить";
    }

    function renderTasks(data) {
        ensureUserCard();
        const list = document.getElementById("daily-task-list");
        const summary = document.getElementById("daily-tasks-summary");
        if (!list || !summary) return;
        const tasks = data?.tasks || [];
        const s = data?.summary || { completed: 0, total: 0 };
        summary.textContent = `${s.completed || 0} из ${s.total || tasks.length}`;
        if (data?.balance != null) updateBalance(data.balance);
        list.innerHTML = "";
        if (!tasks.length) {
            list.innerHTML = `<div class="daily-empty">Заданий пока нет. Владелец может создать их в управлении.</div>`;
            return;
        }
        for (const task of tasks) {
            const required = Math.max(1, Number(task.required_progress || 1));
            const progress = Math.min(required, Number(task.progress || 0));
            const pct = Math.round((progress / required) * 100);
            const disabled = ["reward_claimed", "awaiting_confirmation", "future", "expired", "disabled"].includes(task.status);
            const row = document.createElement("article");
            row.className = "daily-task-row";
            row.innerHTML = `
                <div class="daily-task-row-head">
                    <div>
                        <div class="daily-task-title">${esc(task.title)}</div>
                        <div class="daily-task-desc">${esc(task.description || "")}</div>
                    </div>
                    <div class="daily-task-reward">+${esc(task.reward_amount)} 🐾</div>
                </div>
                ${required > 1 ? `<div class="daily-progress"><span style="width:${pct}%"></span></div>` : ""}
                <div class="daily-task-footer">
                    <div class="daily-task-status ${task.status === "reward_claimed" ? "daily-task-done" : task.status === "awaiting_confirmation" ? "daily-task-wait" : ""}">${required > 1 ? `${progress}/${required} · ` : ""}${esc(statusLabel(task.status))}</div>
                    <button type="button" ${disabled ? "disabled" : ""}>${esc(actionText(task))}</button>
                </div>
            `;
            row.querySelector("button")?.addEventListener("click", () => handleTaskAction(task));
            list.appendChild(row);
        }
    }

    async function loadTasks() {
        if (!tg?.initData) return;
        ensureUserCard();
        try {
            const response = await fetch(`${API}/api/tasks`, { headers: headers(), cache: "no-store" });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить задания");
            renderTasks(data);
        } catch (error) {
            const list = document.getElementById("daily-task-list");
            if (list) list.innerHTML = `<div class="daily-empty">${esc(error.message || "Ошибка загрузки заданий")}</div>`;
        }
    }

    async function handleTaskAction(task) {
        if (task.task_type === "manual") return submitTask(task);
        if (task.task_type === "link") {
            if (task.action_value) {
                if (tg?.openLink) tg.openLink(task.action_value);
                else window.open(task.action_value, "_blank", "noopener");
            }
            return submitTask(task);
        }
        if (task.action_type === "open_catalog") {
            document.getElementById("spend-button")?.click();
            return;
        }
        if (task.action_type === "open_earn") {
            document.getElementById("earn-button")?.click();
            await postEvent("open_earn");
            return;
        }
        if (task.action_type === "open_profile") {
            document.getElementById("adv-profile-button")?.click();
            await postEvent("open_profile");
            return;
        }
        if (task.action_type === "promo_redeem") {
            document.getElementById("earn-button")?.click();
            document.getElementById("promo-code")?.focus();
            return;
        }
        await postEvent(task.action_type || "custom_event", task.action_value || null);
    }

    async function submitTask(task) {
        try {
            const response = await fetch(`${API}/api/tasks/${task.id}/submit`, {
                method: "POST",
                headers: headers(true),
                body: JSON.stringify({ note: null }),
            });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось отправить на проверку");
            tg?.HapticFeedback?.notificationOccurred?.("success");
            await loadTasks();
        } catch (error) {
            alert(error.message || "Не удалось отправить задание");
            tg?.HapticFeedback?.notificationOccurred?.("error");
        }
    }

    function ensureOwnerPanel() {
        const owner = document.getElementById("owner-view");
        if (!owner || document.getElementById("owner-daily-tasks-panel")) return;
        const panel = document.createElement("section");
        panel.id = "owner-daily-tasks-panel";
        panel.className = "owner-task-panel";
        panel.innerHTML = `
            <div class="owner-task-title">Ежедневные задания</div>
            <div class="owner-task-sub">конструктор заданий, наград и ручных подтверждений</div>
            <div class="owner-task-form">
                <input id="task-title" placeholder="Название задания">
                <textarea id="task-description" placeholder="Описание"></textarea>
                <div class="owner-task-two">
                    <select id="task-type"><option value="automatic">Автоматическое</option><option value="manual">Ручное</option><option value="link">Ссылка + подтверждение</option></select>
                    <select id="task-repeat"><option value="daily">Ежедневное</option><option value="once">Одноразовое</option></select>
                </div>
                <div class="owner-task-two">
                    <select id="task-action-type">
                        <option value="open_wallet">Зайти в кошелёк</option>
                        <option value="activity_check_in">Активировать серию</option>
                        <option value="open_catalog">Открыть каталог</option>
                        <option value="promo_redeem">Забрать промо</option>
                        <option value="referral_completed">Пригласить друга</option>
                        <option value="giveaway_join">Участвовать в розыгрыше</option>
                        <option value="open_earn">Открыть заработок</option>
                        <option value="open_profile">Открыть профиль</option>
                        <option value="custom_event">Другое событие</option>
                    </select>
                    <input id="task-action-value" placeholder="Ссылка или значение действия">
                </div>
                <div class="owner-task-two">
                    <input id="task-reward" type="number" min="0" max="10000000" placeholder="Награда 🐾">
                    <input id="task-progress" type="number" min="1" max="1000000" placeholder="Нужно прогресса, обычно 1">
                </div>
                <div class="owner-task-two">
                    <input id="task-max" type="number" min="1" max="1000000" placeholder="Лимит выполнений, пусто = нет">
                    <input id="task-order" type="number" placeholder="Порядок">
                </div>
                <div class="owner-task-two">
                    <input id="task-start" type="datetime-local">
                    <input id="task-end" type="datetime-local">
                </div>
                <label class="owner-task-sub"><input id="task-enabled" type="checkbox" checked> активно</label>
                <div class="owner-task-actions"><button id="task-save" type="button">Создать задание</button><button id="task-reset" class="secondary" type="button">Сбросить форму</button></div>
                <div id="task-owner-status" class="owner-task-status"></div>
            </div>
            <div class="owner-task-sub" style="margin-top:14px">Задания</div>
            <div id="owner-task-list" class="owner-task-list"></div>
            <div class="owner-task-sub" style="margin-top:14px">Ожидают подтверждения</div>
            <div id="owner-task-reviews" class="owner-task-list"></div>
        `;
        owner.appendChild(panel);
        document.getElementById("task-save")?.addEventListener("click", saveOwnerTask);
        document.getElementById("task-reset")?.addEventListener("click", resetTaskForm);
    }

    function formValue(id) { return document.getElementById(id)?.value?.trim() || ""; }
    function formNumber(id) { const raw = formValue(id); return raw ? Number.parseInt(raw, 10) : null; }
    function formIso(id) { const raw = formValue(id); if (!raw) return null; const d = new Date(raw); return Number.isNaN(d.getTime()) ? null : d.toISOString(); }

    function payloadFromForm() {
        return {
            title: formValue("task-title"),
            description: formValue("task-description") || null,
            task_type: formValue("task-type") || "automatic",
            action_type: formValue("task-action-type") || null,
            action_value: formValue("task-action-value") || null,
            reward_type: "lapcoins",
            reward_amount: formNumber("task-reward") ?? 0,
            required_progress: formNumber("task-progress") || 1,
            repeat_type: formValue("task-repeat") || "daily",
            start_at: formIso("task-start"),
            end_at: formIso("task-end"),
            max_completions: formNumber("task-max"),
            enabled: Boolean(document.getElementById("task-enabled")?.checked),
            sort_order: formNumber("task-order") ?? 100,
        };
    }

    async function saveOwnerTask() {
        const status = document.getElementById("task-owner-status");
        const save = document.getElementById("task-save");
        const payload = payloadFromForm();
        if (!payload.title) { if (status) status.textContent = "Введите название задания."; return; }
        if (!Number.isInteger(payload.reward_amount) || payload.reward_amount < 0) { if (status) status.textContent = "Награда должна быть числом от 0."; return; }
        save.disabled = true;
        if (status) status.textContent = editingTaskId ? "Сохраняем…" : "Создаём…";
        try {
            const url = editingTaskId ? `${API}/api/owner/tasks/${editingTaskId}` : `${API}/api/owner/tasks`;
            const response = await fetch(url, { method: "POST", headers: headers(true), body: JSON.stringify(payload) });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось сохранить задание");
            resetTaskForm();
            if (status) status.textContent = "Готово.";
            await Promise.all([loadOwnerTasks(), loadOwnerReviews(), loadTasks()]);
        } catch (error) {
            if (status) status.textContent = error.message || "Ошибка сохранения";
        } finally {
            save.disabled = false;
        }
    }

    function resetTaskForm() {
        editingTaskId = null;
        for (const id of ["task-title", "task-description", "task-action-value", "task-reward", "task-progress", "task-max", "task-order", "task-start", "task-end"]) {
            const el = document.getElementById(id);
            if (el) el.value = "";
        }
        const type = document.getElementById("task-type"); if (type) type.value = "automatic";
        const repeat = document.getElementById("task-repeat"); if (repeat) repeat.value = "daily";
        const action = document.getElementById("task-action-type"); if (action) action.value = "open_wallet";
        const enabled = document.getElementById("task-enabled"); if (enabled) enabled.checked = true;
        const save = document.getElementById("task-save"); if (save) save.textContent = "Создать задание";
    }

    async function loadOwnerTasks() {
        if (!tg?.initData) return;
        ensureOwnerPanel();
        const box = document.getElementById("owner-task-list");
        if (!box) return;
        box.innerHTML = `<div class="daily-empty">Загружаем…</div>`;
        try {
            const response = await fetch(`${API}/api/owner/tasks`, { headers: headers(), cache: "no-store" });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить задания");
            renderOwnerTasks(data.tasks || []);
        } catch (error) {
            box.innerHTML = `<div class="daily-empty">${esc(error.message || "Ошибка")}</div>`;
        }
    }

    function renderOwnerTasks(tasks) {
        const box = document.getElementById("owner-task-list");
        if (!box) return;
        box.innerHTML = "";
        if (!tasks.length) { box.innerHTML = `<div class="daily-empty">Заданий пока нет</div>`; return; }
        for (const task of tasks) {
            const row = document.createElement("div");
            row.className = "owner-task-row";
            const stats = task.stats || {};
            row.innerHTML = `
                <div class="owner-task-row-head">
                    <div><div class="owner-task-row-title">${esc(task.title)}</div><div class="owner-task-row-meta">${esc(task.task_type)} · ${esc(task.action_type || "без действия")} · +${task.reward_amount} 🐾 · выполнено ${stats.reward_claimed || 0}</div></div>
                    <div class="owner-task-pill ${task.enabled ? "" : "off"}">${task.enabled ? "активно" : "выключено"}</div>
                </div>
                <div class="owner-task-actions"></div>
            `;
            const actions = row.querySelector(".owner-task-actions");
            actions.append(
                smallButton("Редактировать", "secondary", () => fillTaskForm(task)),
                smallButton(task.enabled ? "Отключить" : "Включить", "secondary", () => toggleTask(task)),
                smallButton("Удалить", "danger", () => deleteTask(task)),
            );
            box.appendChild(row);
        }
    }

    function smallButton(text, className, handler) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = text;
        if (className) btn.className = className;
        btn.addEventListener("click", handler);
        return btn;
    }

    function localValue(value) {
        if (!value) return "";
        const d = new Date(value);
        if (Number.isNaN(d.getTime())) return "";
        const pad = (n) => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    function fillTaskForm(task) {
        editingTaskId = task.id;
        document.getElementById("task-title").value = task.title || "";
        document.getElementById("task-description").value = task.description || "";
        document.getElementById("task-type").value = task.task_type || "automatic";
        document.getElementById("task-repeat").value = task.repeat_type || "daily";
        document.getElementById("task-action-type").value = task.action_type || "custom_event";
        document.getElementById("task-action-value").value = task.action_value || "";
        document.getElementById("task-reward").value = task.reward_amount || 0;
        document.getElementById("task-progress").value = task.required_progress || 1;
        document.getElementById("task-max").value = task.max_completions || "";
        document.getElementById("task-order").value = task.sort_order || 100;
        document.getElementById("task-start").value = localValue(task.start_at);
        document.getElementById("task-end").value = localValue(task.end_at);
        document.getElementById("task-enabled").checked = Boolean(task.enabled);
        document.getElementById("task-save").textContent = "Сохранить изменения";
        document.getElementById("owner-daily-tasks-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    async function taskAction(path) {
        const response = await fetch(`${API}${path}`, { method: "POST", headers: headers(true) });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data?.detail || "Операция не выполнена");
        await Promise.all([loadOwnerTasks(), loadOwnerReviews(), loadTasks()]);
    }

    async function toggleTask(task) {
        try { await taskAction(`/api/owner/tasks/${task.id}/toggle`); } catch (error) { alert(error.message); }
    }

    async function deleteTask(task) {
        if (!await confirmText(`Удалить задание «${task.title}»? История пользователей сохранится.`)) return;
        try { await taskAction(`/api/owner/tasks/${task.id}/delete`); } catch (error) { alert(error.message); }
    }

    async function loadOwnerReviews() {
        if (!tg?.initData) return;
        ensureOwnerPanel();
        const box = document.getElementById("owner-task-reviews");
        if (!box) return;
        try {
            const response = await fetch(`${API}/api/owner/tasks/reviews`, { headers: headers(), cache: "no-store" });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось загрузить проверки");
            renderReviews(data.items || []);
        } catch (error) {
            box.innerHTML = `<div class="daily-empty">${esc(error.message || "Ошибка")}</div>`;
        }
    }

    function renderReviews(items) {
        const box = document.getElementById("owner-task-reviews");
        if (!box) return;
        box.innerHTML = "";
        if (!items.length) { box.innerHTML = `<div class="daily-empty">Заявок на проверку нет</div>`; return; }
        for (const item of items) {
            const who = item.username ? `@${item.username}` : (item.first_name || `ID ${item.telegram_id}`);
            const row = document.createElement("div");
            row.className = "task-review-row";
            row.innerHTML = `<div class="owner-task-row-title">${esc(item.task.title)}</div><div class="owner-task-row-meta">${esc(who)} · ID ${item.telegram_id} · ${fmt(item.updated_at)}</div>${item.note ? `<div class="task-review-note">${esc(item.note)}</div>` : ""}<div class="owner-task-actions"></div>`;
            const actions = row.querySelector(".owner-task-actions");
            actions.append(smallButton("Подтвердить", "", () => reviewAction(item.progress_id, "approve")), smallButton("Отклонить", "danger", () => reviewAction(item.progress_id, "reject")));
            box.appendChild(row);
        }
    }

    async function reviewAction(progressId, action) {
        try {
            const response = await fetch(`${API}/api/owner/tasks/reviews/${progressId}/${action}`, { method: "POST", headers: headers(true), body: JSON.stringify({ note: null }) });
            const data = await readJson(response);
            if (!response.ok) throw new Error(data?.detail || "Не удалось обработать заявку");
            tg?.HapticFeedback?.notificationOccurred?.("success");
            await Promise.all([loadOwnerReviews(), loadOwnerTasks(), loadTasks()]);
        } catch (error) {
            alert(error.message || "Ошибка обработки");
        }
    }

    function hookOwnerOpen() {
        document.getElementById("owner-button")?.addEventListener("click", () => {
            setTimeout(() => {
                ensureOwnerPanel();
                loadOwnerTasks();
                loadOwnerReviews();
                ownerLoaded = true;
            }, 180);
        });
    }

    function start() {
        installFetchWatcher();
        ensureUserCard();
        hookOwnerOpen();
        setTimeout(loadTasks, 900);
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
    else start();
})();
