(() => {
    "use strict";

    const STORE_PREFIX = "nyan-owner-list:";
    const OWNER_LISTS = [
        ["owner-users-list", "Список пользователей", false],
        ["owner-user-history", "История пользователя", true],
        ["owner-promo-list", "Созданные промокоды", true],
        ["owner-spend-requests", "Заявки на призы", true],
        ["owner-promo-management", "Управление промокодами", true],
        ["owner-audit-list", "Журнал действий", true],
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

        const key = "collapse:" + id;
        const stored = safeGet(key);
        const collapsed = stored === null ? Boolean(collapsedByDefault) : stored === "1";
        setListCollapsed(list, button, collapsed);

        button.addEventListener("click", () => {
            const next = !list.hidden;
            setListCollapsed(list, button, next);
            safeSet(key, next ? "1" : "0");
        });
    }

    function apply() {
        scheduled = false;
        cleanupBrokenShell();
        OWNER_LISTS.forEach(([id, title, collapsedByDefault]) => {
            ensureOwnerListToggle(id, title, collapsedByDefault);
        });
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
    observer.observe(document.body, { childList: true, subtree: true });
})();
