(() => {
    "use strict";

    const STORE_PREFIX = "nyan-ui-collapse-v3:";
    const ACTION_ORDER = [
        "earn-button",
        "spend-button",
        "transfer-button",
        "wallet-qr-button",
        "appeals-button",
        "adv-profile-button",
        "adv-notifications-button",
        "nyg-my-button",
        "nyg-my-purchases-button",
        "owner-button",
    ];
    const ACTION_LABELS = {
        "earn-button": ["＋", "Заработать"],
        "spend-button": ["🐾", "Потратить"],
        "transfer-button": ["↗", "Перевести"],
        "wallet-qr-button": ["▣", "QR"],
        "appeals-button": ["✉", "Обращения"],
        "adv-profile-button": ["♡", "Профиль"],
        "adv-notifications-button": ["•", "Уведомления"],
        "nyg-my-button": ["🎁", "Розыгрыши"],
        "nyg-my-purchases-button": ["🧾", "Покупки"],
        "owner-button": ["⚙", "Управление"],
    };
    const OWNER_SECTION_SELECTOR = "#owner-view > section";
    const OWNER_LISTS = [
        ["owner-users-list", "Список пользователей", false],
        ["owner-user-history", "История пользователя", true],
        ["owner-promo-list", "Созданные промокоды", true],
        ["owner-spend-requests", "Заявки на призы", true],
        ["owner-promo-management", "Управление промокодами", true],
        ["owner-audit-list", "Журнал действий", true],
        ["adv-owner-rewards", "Каталог наград", true],
        ["adv-owner-events", "События", true],
    ];

    let scheduled = false;
    let delegated = false;

    function safeGet(key) {
        try { return localStorage.getItem(STORE_PREFIX + key); } catch (_) { return null; }
    }

    function safeSet(key, value) {
        try { localStorage.setItem(STORE_PREFIX + key, value); } catch (_) {}
    }

    function isOwnerAllowed() {
        return window.__nyanIsOwner === true || document.body?.dataset?.nyanRole === "owner";
    }

    function enforceOwnerButton() {
        const button = document.getElementById("owner-button");
        if (!button) return;
        const allowed = isOwnerAllowed();
        button.hidden = !allowed;
        button.disabled = !allowed;
        button.dataset.ownerAllowed = allowed ? "1" : "0";
        button.setAttribute("aria-hidden", allowed ? "false" : "true");
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function textOf(node) {
        return String(node?.textContent || "").replace(/\s+/g, " ").trim();
    }

    function unwrapLegacySection(node, bodySelector, toggleSelector, classNames = []) {
        const body = node.querySelector(`:scope > ${bodySelector}`);
        const toggle = node.querySelector(`:scope > ${toggleSelector}`);
        if (body) {
            body.hidden = false;
            while (body.firstChild) node.appendChild(body.firstChild);
            body.remove();
        }
        toggle?.remove();
        for (const name of classNames) node.classList.remove(name);
    }

    function cleanupLegacyShell() {
        document.getElementById("nyan-command-center")?.remove();
        document.getElementById("nyan-owner-map")?.remove();
        document.getElementById("nyan-owner-controls")?.remove();
        document.querySelectorAll(".nyan-view-controls").forEach(node => node.remove());
        document.querySelector("#wallet-view .actions")?.classList.remove("nyan-actions-hidden");

        document.querySelectorAll(".nyan-collapsible").forEach(node => {
            unwrapLegacySection(node, ".nyan-collapse-body", ".nyan-collapse-toggle", ["nyan-collapsible", "nyan-collapsed"]);
            delete node.dataset.nyanCollapseReady;
            delete node.dataset.nyanCollapseKey;
        });

        document.querySelectorAll(".nyan-owner-collapsible").forEach(node => {
            unwrapLegacySection(node, ".nyan-owner-collapse-body", ".nyan-owner-collapse-toggle", ["nyan-owner-collapsible", "nyan-owner-collapsed"]);
            delete node.dataset.nyanOwnerCollapseReady;
            delete node.dataset.nyanOwnerCollapseKey;
        });
    }

    function titleForSection(section) {
        if (section.id === "owner-user-card") return "Выбранный пользователь";
        if (section.id === "owner-stats-section") return "Статистика";
        if (section.id === "nyg-owner-nav") return "Быстрый доступ";
        const direct = section.querySelector(":scope > .owner-title, :scope > .feature-section-title, :scope > .adv-title, :scope > .appeal-section-title, :scope > h2, :scope > h3");
        if (direct) return textOf(direct);
        const nested = section.querySelector(".owner-title, .feature-section-title, .adv-title, .appeal-section-title, h2, h3");
        if (nested) return textOf(nested);
        return "Раздел";
    }

    function keyForSection(section, title) {
        if (section.id) return "section:" + section.id;
        return "section:" + String(title || "section").toLowerCase().replace(/[^a-zа-я0-9]+/gi, "-").slice(0, 64);
    }

    function defaultSectionCollapsed(section) {
        if (section.id === "owner-user-card") return true;
        const sections = Array.from(document.querySelectorAll(OWNER_SECTION_SELECTOR));
        return sections.indexOf(section) > 0;
    }

    function resetButton(button) {
        if (!button) return null;
        if (button.dataset.nyanCollapseVersion === "3") return button;
        const clone = button.cloneNode(true);
        button.replaceWith(clone);
        return clone;
    }

    function setSectionCollapsed(section, collapsed, persist = false) {
        const body = section.querySelector(":scope > .nyan-admin-body");
        const toggle = section.querySelector(":scope > .nyan-admin-toggle");
        const state = toggle?.querySelector(".nyan-admin-state");
        if (!body || !toggle) return;
        body.hidden = Boolean(collapsed);
        section.classList.toggle("nyan-admin-collapsed", Boolean(collapsed));
        section.dataset.nyanCollapsed = collapsed ? "1" : "0";
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        if (state) state.textContent = collapsed ? "развернуть" : "свернуть";
        if (persist && section.dataset.nyanAdminKey) safeSet(section.dataset.nyanAdminKey, collapsed ? "1" : "0");
    }

    function ensureSectionBody(section) {
        let toggle = section.querySelector(":scope > .nyan-admin-toggle");
        let body = section.querySelector(":scope > .nyan-admin-body");
        if (!body) {
            body = document.createElement("div");
            body.className = "nyan-admin-body";
            for (const child of Array.from(section.childNodes)) {
                if (child !== toggle) body.appendChild(child);
            }
            section.appendChild(body);
        } else {
            for (const child of Array.from(section.childNodes)) {
                if (child !== toggle && child !== body) body.appendChild(child);
            }
        }
        return body;
    }

    function ensureOwnerSection(section) {
        if (!isOwnerAllowed()) return;
        if (!section || !section.closest("#owner-view")) return;
        if (section.closest(".nyan-admin-body")) return;

        const title = titleForSection(section);
        const key = keyForSection(section, title);
        let toggle = section.querySelector(":scope > .nyan-admin-toggle");
        const body = ensureSectionBody(section);

        if (!toggle) {
            toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "nyan-admin-toggle";
            section.insertBefore(toggle, body);
        } else if (toggle.nextElementSibling !== body) {
            section.insertBefore(toggle, body);
        }

        toggle = resetButton(toggle);
        toggle.type = "button";
        toggle.className = "nyan-admin-toggle";
        toggle.dataset.nyanCollapseToggle = "section";
        toggle.dataset.nyanCollapseVersion = "3";
        toggle.innerHTML = `
            <span class="nyan-admin-title">${escapeHtml(title)}</span>
            <span class="nyan-admin-meta"><span class="nyan-admin-state"></span><span class="nyan-admin-arrow">▾</span></span>
        `;

        section.classList.add("nyan-admin-section");
        section.dataset.nyanAdminReady = "1";
        section.dataset.nyanAdminKey = key;
        body.dataset.nyanCollapseBody = "section";

        const stored = safeGet(key);
        const collapsed = stored === null ? defaultSectionCollapsed(section) : stored === "1";
        setSectionCollapsed(section, collapsed, false);
    }

    function setListCollapsed(list, collapsed, persist = false) {
        const button = list.previousElementSibling?.dataset?.nyanCollapseTarget === list.id
            ? list.previousElementSibling
            : null;
        const state = button?.querySelector(".nyan-owner-list-state");
        list.hidden = Boolean(collapsed);
        list.classList.toggle("nyan-list-collapsed", Boolean(collapsed));
        list.dataset.nyanCollapsed = collapsed ? "1" : "0";
        button?.setAttribute("aria-expanded", collapsed ? "false" : "true");
        if (state) state.textContent = collapsed ? "развернуть" : "свернуть";
        if (persist && list.id) safeSet("list:" + list.id, collapsed ? "1" : "0");
    }

    function ensureOwnerListToggle(id, title, collapsedByDefault) {
        if (!isOwnerAllowed()) return;
        const list = document.getElementById(id);
        if (!list || !list.closest("#owner-view")) return;

        let button = list.previousElementSibling?.classList?.contains("nyan-owner-list-toggle")
            ? list.previousElementSibling
            : null;
        if (!button) {
            button = document.createElement("button");
            button.type = "button";
            button.className = "nyan-owner-list-toggle";
            list.insertAdjacentElement("beforebegin", button);
        }
        button = resetButton(button);
        button.type = "button";
        button.className = "nyan-owner-list-toggle";
        button.dataset.nyanCollapseToggle = "list";
        button.dataset.nyanCollapseTarget = id;
        button.dataset.nyanCollapseVersion = "3";
        button.innerHTML = `
            <span>${escapeHtml(title)}</span>
            <span class="nyan-owner-list-state"></span>
        `;

        list.classList.add("nyan-owner-list-body");
        list.dataset.nyanOwnerListReady = "1";
        const stored = safeGet("list:" + id);
        const collapsed = stored === null ? Boolean(collapsedByDefault) : stored === "1";
        setListCollapsed(list, collapsed, false);
    }

    function handleCollapseClick(event) {
        const control = event.target.closest("[data-nyan-collapse-toggle]");
        if (!control || !control.closest("#owner-view")) return;
        event.preventDefault();
        event.stopPropagation();

        if (control.dataset.nyanCollapseToggle === "section") {
            const section = control.closest(".nyan-admin-section");
            if (!section) return;
            setSectionCollapsed(section, !section.classList.contains("nyan-admin-collapsed"), true);
            return;
        }

        if (control.dataset.nyanCollapseToggle === "list") {
            const list = document.getElementById(control.dataset.nyanCollapseTarget || "");
            if (!list) return;
            setListCollapsed(list, !list.hidden, true);
        }
    }

    function ensureDelegatedCollapseHandler() {
        if (delegated) return;
        delegated = true;
        document.addEventListener("click", handleCollapseClick, true);
    }

    function labelAction(button) {
        if (!button?.id || !ACTION_LABELS[button.id]) return;
        if (button.dataset.nyanRelabelled === "1") return;
        const [icon, label] = ACTION_LABELS[button.id];
        if (button.id === "adv-notifications-button") {
            const badge = document.getElementById("adv-unread-badge");
            button.innerHTML = `<span class="nyan-action-icon">${escapeHtml(icon)}</span><span>${escapeHtml(label)}</span>`;
            if (badge) button.appendChild(badge);
        } else {
            button.innerHTML = `<span class="nyan-action-icon">${escapeHtml(icon)}</span><span>${escapeHtml(label)}</span>`;
        }
        button.dataset.nyanRelabelled = "1";
    }

    function moveAfter(anchor, node) {
        if (!anchor || !node || anchor.parentNode !== node.parentNode) return;
        if (anchor.nextElementSibling !== node) anchor.insertAdjacentElement("afterend", node);
    }

    function organizeActions() {
        const wallet = document.getElementById("wallet-view");
        const actions = wallet?.querySelector(":scope > .actions");
        if (!wallet || !actions) return;

        enforceOwnerButton();
        actions.classList.add("nyan-actions-grid");
        const orderedButtons = ACTION_ORDER
            .map(id => document.getElementById(id))
            .filter(button => button && button.parentElement === actions && !button.hidden);
        for (const button of orderedButtons) labelAction(button);

        const currentButtons = Array.from(actions.children).filter(node => orderedButtons.includes(node));
        const isAlreadyOrdered = currentButtons.length === orderedButtons.length
            && currentButtons.every((node, index) => node === orderedButtons[index]);
        if (!isAlreadyOrdered) {
            for (const button of orderedButtons) actions.appendChild(button);
        }

        const walletCard = document.getElementById("wallet-card") || wallet.querySelector(".balance-card");
        const tasks = document.getElementById("daily-tasks-card");
        const streak = document.getElementById("activity-streak-card");
        const level = document.getElementById("adv-level-card");
        const home = document.getElementById("ny-home");
        const history = wallet.querySelector(":scope > .history");

        if (walletCard && tasks?.parentNode === wallet) moveAfter(walletCard, tasks);
        if (walletCard && streak?.parentNode === wallet) {
            if (tasks?.parentNode === wallet) moveAfter(tasks, streak);
            else moveAfter(walletCard, streak);
        }
        if (actions.parentNode === wallet) {
            if (streak?.parentNode === wallet) moveAfter(streak, actions);
            else if (tasks?.parentNode === wallet) moveAfter(tasks, actions);
            else if (walletCard) moveAfter(walletCard, actions);
        }
        if (level?.parentNode === wallet && actions.parentNode === wallet) moveAfter(actions, level);
        if (home?.parentNode === wallet) {
            if (level?.parentNode === wallet) moveAfter(level, home);
            else if (actions.parentNode === wallet) moveAfter(actions, home);
        }
        if (history?.parentNode === wallet && home?.parentNode === wallet) moveAfter(home, history);
    }

    function apply() {
        scheduled = false;
        cleanupLegacyShell();
        organizeActions();
        ensureDelegatedCollapseHandler();
        if (isOwnerAllowed()) {
            document.querySelectorAll(OWNER_SECTION_SELECTOR).forEach(ensureOwnerSection);
            OWNER_LISTS.forEach(([id, title, collapsedByDefault]) => ensureOwnerListToggle(id, title, collapsedByDefault));
        }
    }

    function scheduleApply() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(apply);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", scheduleApply, { once: true });
    } else {
        scheduleApply();
    }

    window.addEventListener("nyan-owner-state", scheduleApply);

    const observer = new MutationObserver(scheduleApply);
    observer.observe(document.body, { childList: true, subtree: true });
})();
