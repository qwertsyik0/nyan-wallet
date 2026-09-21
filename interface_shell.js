(() => {
    "use strict";

    const STORE_PREFIX = "nyan-ui-v2:";
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
    const OWNER_SECTION_SELECTOR = "#owner-view > .admin-section, #owner-view > .feature-section, #owner-view > .adv-panel, #owner-view > .appeal-panel";
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

    function safeGet(key) {
        try { return localStorage.getItem(STORE_PREFIX + key); } catch (_) { return null; }
    }

    function safeSet(key, value) {
        try { localStorage.setItem(STORE_PREFIX + key, value); } catch (_) {}
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

    function unwrapSection(node, bodySelector, toggleSelector, classNames = []) {
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

    function cleanupBrokenShell() {
        document.getElementById("nyan-command-center")?.remove();
        document.getElementById("nyan-owner-map")?.remove();
        document.getElementById("nyan-owner-controls")?.remove();
        document.querySelectorAll(".nyan-view-controls").forEach(node => node.remove());
        document.querySelector("#wallet-view .actions")?.classList.remove("nyan-actions-hidden");

        document.querySelectorAll(".nyan-collapsible").forEach(node => {
            unwrapSection(node, ".nyan-collapse-body", ".nyan-collapse-toggle", ["nyan-collapsible", "nyan-collapsed"]);
            delete node.dataset.nyanCollapseReady;
            delete node.dataset.nyanCollapseKey;
        });

        document.querySelectorAll(".nyan-owner-collapsible").forEach(node => {
            unwrapSection(node, ".nyan-owner-collapse-body", ".nyan-owner-collapse-toggle", ["nyan-owner-collapsible", "nyan-owner-collapsed"]);
            delete node.dataset.nyanOwnerCollapseReady;
            delete node.dataset.nyanOwnerCollapseKey;
        });
    }

    function titleForSection(section) {
        if (section.id === "owner-user-card") return "Выбранный пользователь";
        const direct = section.querySelector(":scope > .owner-title, :scope > .feature-section-title, :scope > .adv-title, :scope > .appeal-section-title, :scope > h2, :scope > h3");
        if (direct) return textOf(direct);
        const nested = section.querySelector(".owner-title, .feature-section-title, .adv-title, .appeal-section-title, h2, h3");
        if (nested) return textOf(nested);
        return "Раздел";
    }

    function keyForSection(section, title) {
        if (section.id) return "section:" + section.id;
        return "section:" + String(title || "section").toLowerCase().replace(/[^a-zа-я0-9]+/gi, "-").slice(0, 48);
    }

    function defaultSectionCollapsed(section) {
        if (section.id === "owner-user-card") return true;
        const sections = Array.from(document.querySelectorAll(OWNER_SECTION_SELECTOR));
        return sections.indexOf(section) > 0;
    }

    function setSectionCollapsed(section, collapsed) {
        const body = section.querySelector(":scope > .nyan-admin-body");
        const toggle = section.querySelector(":scope > .nyan-admin-toggle");
        const state = section.querySelector(":scope > .nyan-admin-toggle .nyan-admin-state");
        if (!body || !toggle) return;
        body.hidden = collapsed;
        section.classList.toggle("nyan-admin-collapsed", collapsed);
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        if (state) state.textContent = collapsed ? "развернуть" : "свернуть";
    }

    function makeOwnerSectionCollapsible(section) {
        if (!section || !section.closest("#owner-view")) return;
        if (section.dataset.nyanAdminReady === "1") return;
        if (section.closest(".nyan-admin-body")) return;

        const title = titleForSection(section);
        const key = keyForSection(section, title);
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "nyan-admin-toggle";
        toggle.innerHTML = `
            <span class="nyan-admin-title">${escapeHtml(title)}</span>
            <span class="nyan-admin-meta"><span class="nyan-admin-state"></span><span class="nyan-admin-arrow">▾</span></span>
        `;

        const body = document.createElement("div");
        body.className = "nyan-admin-body";
        for (const child of Array.from(section.childNodes)) body.appendChild(child);
        section.appendChild(toggle);
        section.appendChild(body);
        section.classList.add("nyan-admin-section");
        section.dataset.nyanAdminReady = "1";
        section.dataset.nyanAdminKey = key;

        const stored = safeGet(key);
        const collapsed = stored === null ? defaultSectionCollapsed(section) : stored === "1";
        setSectionCollapsed(section, collapsed);

        toggle.addEventListener("click", () => {
            const next = !section.classList.contains("nyan-admin-collapsed");
            setSectionCollapsed(section, next);
            safeSet(key, next ? "1" : "0");
        });
    }

    function setListCollapsed(list, button, collapsed) {
        list.hidden = collapsed;
        button.setAttribute("aria-expanded", collapsed ? "false" : "true");
        const state = button.querySelector(".nyan-owner-list-state");
        if (state) state.textContent = collapsed ? "развернуть" : "свернуть";
    }

    function ensureOwnerListToggle(id, title, collapsedByDefault) {
        const list = document.getElementById(id);
        if (!list || !list.closest("#owner-view")) return;
        if (list.dataset.nyanOwnerListReady === "1") return;

        const oldToggle = list.previousElementSibling;
        if (oldToggle?.classList?.contains("nyan-owner-list-toggle")) oldToggle.remove();

        const button = document.createElement("button");
        button.type = "button";
        button.className = "nyan-owner-list-toggle";
        button.innerHTML = `
            <span>${escapeHtml(title)}</span>
            <span class="nyan-owner-list-state"></span>
        `;

        list.insertAdjacentElement("beforebegin", button);
        list.classList.add("nyan-owner-list-body");
        list.dataset.nyanOwnerListReady = "1";

        const key = "list:" + id;
        const stored = safeGet(key);
        const collapsed = stored === null ? Boolean(collapsedByDefault) : stored === "1";
        setListCollapsed(list, button, collapsed);

        button.addEventListener("click", () => {
            const next = !list.hidden;
            setListCollapsed(list, button, next);
            safeSet(key, next ? "1" : "0");
        });
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
        const streak = document.getElementById("activity-streak-card");
        const level = document.getElementById("adv-level-card");
        const home = document.getElementById("ny-home");
        const history = wallet.querySelector(":scope > .history");

        if (walletCard && streak?.parentNode === wallet) moveAfter(walletCard, streak);
        if (actions.parentNode === wallet) {
            if (streak?.parentNode === wallet) moveAfter(streak, actions);
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
        cleanupBrokenShell();
        organizeActions();
        document.querySelectorAll(OWNER_SECTION_SELECTOR).forEach(makeOwnerSectionCollapsible);
        OWNER_LISTS.forEach(([id, title, collapsedByDefault]) => ensureOwnerListToggle(id, title, collapsedByDefault));
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

    const observer = new MutationObserver(scheduleApply);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "class"] });
})();
