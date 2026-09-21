(() => {
    "use strict";

    const STORE_PREFIX = "nyan-owner-ui:";
    const OWNER_SECTION_SELECTOR = "#owner-view > .admin-section, #owner-view > .feature-section";
    const OWNER_LISTS = [
        ["owner-users-list", "Список пользователей"],
        ["owner-user-history", "История пользователя"],
        ["owner-promo-list", "Созданные промокоды"],
        ["owner-spend-requests", "Заявки на призы"],
        ["owner-promo-management", "Управление промокодами"],
        ["owner-audit-list", "Журнал действий"],
    ];

    let scheduled = false;

    function safeGet(key) {
        try { return localStorage.getItem(STORE_PREFIX + key); } catch (_) { return null; }
    }

    function safeSet(key, value) {
        try { localStorage.setItem(STORE_PREFIX + key, value); } catch (_) {}
    }

    function textOf(node) {
        return String(node?.textContent || "").replace(/\s+/g, " ").trim();
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function titleFor(node) {
        if (!node) return "Раздел";
        if (node.id === "owner-user-card") return "Выбранный пользователь";

        const directTitle = node.querySelector(
            ":scope > .feature-section-title, :scope > .owner-title, :scope > .selected-user-head .owner-title, :scope > h2, :scope > h3",
        );
        if (directTitle) return textOf(directTitle);

        const nestedTitle = node.querySelector(".feature-section-title, .owner-title, h2, h3");
        if (nestedTitle) return textOf(nestedTitle);

        return "Раздел";
    }

    function ownerSectionKey(node, title) {
        if (node.id) return node.id;
        return "section:" + String(title || "section")
            .toLowerCase()
            .replace(/[^a-zа-я0-9]+/gi, "-")
            .slice(0, 48);
    }

    function defaultSectionCollapsed(node) {
        if (node.id === "owner-user-card") return true;
        if (node.matches("#owner-view > .feature-section")) return true;
        const sections = Array.from(document.querySelectorAll("#owner-view > .admin-section"));
        return sections.indexOf(node) > 0;
    }

    function setSectionCollapsed(node, collapsed) {
        const body = node.querySelector(":scope > .nyan-owner-collapse-body");
        const state = node.querySelector(":scope > .nyan-owner-collapse-toggle .nyan-owner-collapse-state");
        const toggle = node.querySelector(":scope > .nyan-owner-collapse-toggle");
        if (!body || !toggle) return;

        node.classList.toggle("nyan-owner-collapsed", collapsed);
        body.hidden = collapsed;
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        if (state) state.textContent = collapsed ? "развернуть" : "свернуть";
    }

    function unwrapOldGlobalCollapsible(node) {
        const body = node.querySelector(":scope > .nyan-collapse-body");
        const toggle = node.querySelector(":scope > .nyan-collapse-toggle");
        if (!body && !toggle) return;

        if (body) {
            body.hidden = false;
            while (body.firstChild) node.appendChild(body.firstChild);
            body.remove();
        }
        toggle?.remove();
        node.classList.remove("nyan-collapsible", "nyan-collapsed");
        delete node.dataset.nyanCollapseReady;
        delete node.dataset.nyanCollapseKey;
    }

    function cleanupOldGlobalShell() {
        // Previous iteration added collapse controls everywhere. Keep collapses only in owner panel.
        document.getElementById("nyan-command-center")?.remove();
        document.querySelector("#wallet-view .actions")?.classList.remove("nyan-actions-hidden");

        document.querySelectorAll(".nyan-view-controls").forEach(node => {
            if (!node.closest("#owner-view")) node.remove();
        });

        document.querySelectorAll(".nyan-collapsible").forEach(node => {
            if (!node.closest("#owner-view")) unwrapOldGlobalCollapsible(node);
        });
    }

    function makeOwnerSectionCollapsible(node) {
        if (!node || node.dataset.nyanOwnerCollapseReady === "1") return;
        if (!node.closest("#owner-view")) return;

        const title = titleFor(node);
        const key = ownerSectionKey(node, title);
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "nyan-owner-collapse-toggle";
        toggle.innerHTML = `
            <span class="nyan-owner-collapse-title">${escapeHtml(title)}</span>
            <span class="nyan-owner-collapse-meta"><span class="nyan-owner-collapse-state"></span><span class="nyan-owner-collapse-chevron">▾</span></span>
        `;

        const body = document.createElement("div");
        body.className = "nyan-owner-collapse-body";
        for (const child of Array.from(node.childNodes)) body.appendChild(child);
        node.appendChild(toggle);
        node.appendChild(body);

        node.classList.add("nyan-owner-collapsible");
        node.dataset.nyanOwnerCollapseReady = "1";
        node.dataset.nyanOwnerCollapseKey = key;

        const stored = safeGet("collapse:" + key);
        const collapsed = stored === null ? defaultSectionCollapsed(node) : stored === "1";
        setSectionCollapsed(node, collapsed);

        toggle.addEventListener("click", () => {
            const next = !node.classList.contains("nyan-owner-collapsed");
            setSectionCollapsed(node, next);
            safeSet("collapse:" + key, next ? "1" : "0");
        });
    }

    function setListCollapsed(list, button, collapsed) {
        list.hidden = collapsed;
        button.setAttribute("aria-expanded", collapsed ? "false" : "true");
        const state = button.querySelector(".nyan-owner-list-state");
        if (state) state.textContent = collapsed ? "развернуть список" : "свернуть список";
    }

    function ensureOwnerListToggle(id, title) {
        const list = document.getElementById(id);
        if (!list || !list.closest("#owner-view") || list.dataset.nyanOwnerListReady === "1") return;

        const key = "list:" + id;
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

        const stored = safeGet("collapse:" + key);
        const collapsed = stored === null ? id !== "owner-users-list" : stored === "1";
        setListCollapsed(list, button, collapsed);

        button.addEventListener("click", () => {
            const next = !list.hidden;
            setListCollapsed(list, button, next);
            safeSet("collapse:" + key, next ? "1" : "0");
        });
    }

    function ensureOwnerControls() {
        const owner = document.getElementById("owner-view");
        if (!owner || document.getElementById("nyan-owner-controls")) return;

        const controls = document.createElement("div");
        controls.id = "nyan-owner-controls";
        controls.className = "nyan-owner-controls";
        controls.innerHTML = `
            <button class="nyan-owner-control-button" type="button" data-mode="open">Развернуть управление</button>
            <button class="nyan-owner-control-button" type="button" data-mode="close">Свернуть управление</button>
        `;

        const header = owner.querySelector(":scope > .subpage-header");
        if (header) header.insertAdjacentElement("afterend", controls);
        else owner.prepend(controls);

        controls.addEventListener("click", event => {
            const button = event.target.closest("button[data-mode]");
            if (!button) return;
            const shouldCollapse = button.dataset.mode === "close";
            owner.querySelectorAll(":scope > .nyan-owner-collapsible").forEach(section => {
                setSectionCollapsed(section, shouldCollapse);
                if (section.dataset.nyanOwnerCollapseKey) {
                    safeSet("collapse:" + section.dataset.nyanOwnerCollapseKey, shouldCollapse ? "1" : "0");
                }
            });
            OWNER_LISTS.forEach(([id]) => {
                const list = document.getElementById(id);
                const toggle = list?.previousElementSibling?.classList?.contains("nyan-owner-list-toggle")
                    ? list.previousElementSibling
                    : null;
                if (list && toggle) {
                    setListCollapsed(list, toggle, shouldCollapse);
                    safeSet("collapse:list:" + id, shouldCollapse ? "1" : "0");
                }
            });
        });
    }

    function ensureOwnerMap() {
        const owner = document.getElementById("owner-view");
        if (!owner) return;

        let map = document.getElementById("nyan-owner-map");
        if (!map) {
            map = document.createElement("section");
            map.id = "nyan-owner-map";
            map.className = "nyan-owner-map";
            const controls = document.getElementById("nyan-owner-controls");
            if (controls) controls.insertAdjacentElement("afterend", map);
            else owner.querySelector(":scope > .subpage-header")?.insertAdjacentElement("afterend", map);
        }

        const sections = Array.from(owner.querySelectorAll(OWNER_SECTION_SELECTOR));
        if (!sections.length) {
            map.hidden = true;
            return;
        }

        map.hidden = false;
        map.innerHTML = `
            <div class="nyan-owner-map-head">
                <div>
                    <div class="nyan-owner-map-title">Карта управления</div>
                    <div class="nyan-owner-map-subtitle">быстрый переход к нужному блоку</div>
                </div>
            </div>
            <div class="nyan-owner-map-grid"></div>
        `;

        const grid = map.querySelector(".nyan-owner-map-grid");
        for (const section of sections) {
            const title = titleFor(section);
            const button = document.createElement("button");
            button.type = "button";
            button.className = "nyan-owner-map-button";
            button.textContent = title;
            button.addEventListener("click", () => {
                setSectionCollapsed(section, false);
                if (section.dataset.nyanOwnerCollapseKey) safeSet("collapse:" + section.dataset.nyanOwnerCollapseKey, "0");
                section.scrollIntoView({ behavior: "smooth", block: "start" });
            });
            grid?.appendChild(button);
        }
    }

    function applyOwnerShell() {
        scheduled = false;
        cleanupOldGlobalShell();

        const owner = document.getElementById("owner-view");
        if (!owner) return;

        ensureOwnerControls();
        document.querySelectorAll(OWNER_SECTION_SELECTOR).forEach(makeOwnerSectionCollapsible);
        OWNER_LISTS.forEach(([id, title]) => ensureOwnerListToggle(id, title));
        ensureOwnerMap();
    }

    function scheduleApply() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(applyOwnerShell);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", scheduleApply, { once: true });
    } else {
        scheduleApply();
    }

    const observer = new MutationObserver(scheduleApply);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "class"] });
})();
