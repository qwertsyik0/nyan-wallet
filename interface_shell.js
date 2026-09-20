(() => {
    "use strict";

    const STORE_PREFIX = "nyan-ui:";
    const COLLAPSIBLE_SELECTORS = [
        "#activity-streak-card",
        ".history",
        "#earn-view > .earn-list",
        "#earn-view > .promo-card",
        "#owner-view > .admin-section",
        "#owner-view > .feature-section",
        "#spend-view > .feature-section",
        "#transfer-view > .transfer-panel",
        "#promo-deeplink-view > .promo-card",
    ];
    const LIST_TARGETS = [
        ["owner-users-list", "Список пользователей"],
        ["owner-user-history", "История пользователя"],
        ["owner-promo-list", "Созданные промокоды"],
        ["owner-spend-requests", "Заявки на призы"],
        ["owner-promo-management", "Управление промокодами"],
        ["owner-audit-list", "Журнал действий"],
        ["reward-list", "Каталог наград"],
        ["my-spend-requests", "Мои заявки"],
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

    function viewId(node) {
        return node.closest("main")?.id || "page";
    }

    function keyFor(node, fallback) {
        if (node.id) return node.id;
        const view = viewId(node);
        const title = titleFor(node) || fallback || node.className || node.tagName;
        return `${view}:${String(title).toLowerCase().replace(/[^a-zа-я0-9]+/gi, "-").slice(0, 48)}`;
    }

    function titleFor(node) {
        if (!node) return "Раздел";
        if (node.id === "activity-streak-card") return "Серия активности";
        if (node.classList.contains("history")) return "Последние операции";
        if (node.classList.contains("earn-list")) return "Способы заработка";
        if (node.classList.contains("promo-card")) return textOf(node.querySelector(".promo-title")) || "Промокод";
        if (node.classList.contains("transfer-panel")) return textOf(node.querySelector(".transfer-title")) || "Перевод";
        if (node.id === "owner-user-card") return "Выбранный пользователь";

        const directTitle = node.querySelector(":scope > .feature-section-title, :scope > .owner-title, :scope > .selected-user-head .owner-title, :scope > h2, :scope > h3");
        if (directTitle) return textOf(directTitle);

        const nestedTitle = node.querySelector(".feature-section-title, .owner-title, .activity-streak-title, h2, h3");
        if (nestedTitle) return textOf(nestedTitle);

        return "Раздел";
    }

    function defaultCollapsed(node) {
        if (node.id === "activity-streak-card") return false;
        if (node.classList.contains("history")) return true;
        if (node.classList.contains("earn-list")) return false;
        if (node.classList.contains("promo-card")) return true;
        if (node.id === "owner-user-card") return true;
        if (node.matches("#owner-view > .admin-section")) {
            const sections = Array.from(document.querySelectorAll("#owner-view > .admin-section"));
            return sections.indexOf(node) > 0;
        }
        if (node.matches("#owner-view > .feature-section")) return true;
        if (node.matches("#spend-view > .feature-section")) return true;
        return false;
    }

    function setCollapsed(node, collapsed) {
        const body = node.querySelector(":scope > .nyan-collapse-body");
        const meta = node.querySelector(":scope > .nyan-collapse-toggle .nyan-collapse-state");
        if (!body) return;
        node.classList.toggle("nyan-collapsed", collapsed);
        body.hidden = collapsed;
        if (meta) meta.textContent = collapsed ? "развернуть" : "свернуть";
        node.querySelector(":scope > .nyan-collapse-toggle")?.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }

    function makeCollapsible(node) {
        if (!node) return;
        if (node.dataset.nyanCollapseReady === "1") {
            const stillWrapped = node.querySelector(":scope > .nyan-collapse-toggle")
                && node.querySelector(":scope > .nyan-collapse-body");
            if (stillWrapped) return;
            delete node.dataset.nyanCollapseReady;
        }
        if (node.closest(".privacy-overlay")) return;
        if (!node.closest(".app")) return;

        const title = titleFor(node);
        const key = keyFor(node, title);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "nyan-collapse-toggle";
        button.innerHTML = `
            <span class="nyan-collapse-title"><span>${escapeHtml(title)}</span></span>
            <span class="nyan-collapse-meta"><span class="nyan-collapse-state"></span><span class="nyan-collapse-chevron">▾</span></span>
        `;

        const body = document.createElement("div");
        body.className = "nyan-collapse-body";

        const children = Array.from(node.childNodes);
        for (const child of children) {
            body.appendChild(child);
        }

        node.appendChild(button);
        node.appendChild(body);
        node.classList.add("nyan-collapsible");
        node.dataset.nyanCollapseReady = "1";
        node.dataset.nyanCollapseKey = key;

        const stored = safeGet("collapse:" + key);
        const collapsed = stored === null ? defaultCollapsed(node) : stored === "1";
        setCollapsed(node, collapsed);

        button.addEventListener("click", () => {
            const next = !node.classList.contains("nyan-collapsed");
            setCollapsed(node, next);
            safeSet("collapse:" + key, next ? "1" : "0");
        });
    }

    function refreshCommandCenter() {
        const wallet = document.getElementById("wallet-view");
        const actions = wallet?.querySelector(".actions");
        if (!wallet || !actions) return;

        let center = document.getElementById("nyan-command-center");
        if (!center) {
            center = document.createElement("section");
            center.id = "nyan-command-center";
            center.className = "nyan-command-center";
            actions.insertAdjacentElement("afterend", center);
        }

        const specs = [
            ["earn-button", "＋", "Заработать", "все способы получить 🐾"],
            ["spend-button", "🐾", "Потратить", "каталог наград"],
            ["transfer-button", "↗", "Перевести", "другому пользователю"],
            ["wallet-qr-button", "▣", "QR кошелька", "адрес и ссылка"],
            ["owner-button", "⚙", "Управление", "панель владельца"],
        ];
        const available = specs.filter(([id]) => {
            const target = document.getElementById(id);
            return target && !target.hidden;
        });
        if (!available.length) {
            center.hidden = true;
            actions.classList.remove("nyan-actions-hidden");
            return;
        }

        center.hidden = false;
        center.innerHTML = `
            <div class="nyan-command-head">
                <div>
                    <div class="nyan-command-title">Быстрые действия</div>
                    <div class="nyan-command-subtitle">основные функции кошелька в одном месте</div>
                </div>
            </div>
            <div class="nyan-command-grid"></div>
        `;
        const grid = center.querySelector(".nyan-command-grid");
        for (const [id, icon, label, note] of available) {
            const tile = document.createElement("button");
            tile.type = "button";
            tile.className = "nyan-command-tile";
            tile.innerHTML = `
                <span class="nyan-command-icon">${escapeHtml(icon)}</span>
                <span class="nyan-command-label">${escapeHtml(label)}</span>
                <span class="nyan-command-note">${escapeHtml(note)}</span>
            `;
            tile.addEventListener("click", () => document.getElementById(id)?.click());
            grid?.appendChild(tile);
        }
        actions.classList.add("nyan-actions-hidden");
    }

    function ensureViewControls(view) {
        if (!view || view.id === "loading-view" || document.getElementById("nyan-controls-" + view.id)) return;
        const controls = document.createElement("div");
        controls.id = "nyan-controls-" + view.id;
        controls.className = "nyan-view-controls";
        controls.innerHTML = `
            <button class="nyan-view-control-button" type="button" data-mode="open">Развернуть всё</button>
            <button class="nyan-view-control-button" type="button" data-mode="close">Свернуть всё</button>
        `;

        const anchor = view.querySelector(":scope > .subpage-header, :scope > header");
        if (anchor) anchor.insertAdjacentElement("afterend", controls);
        else view.prepend(controls);

        controls.addEventListener("click", event => {
            const button = event.target.closest("button[data-mode]");
            if (!button) return;
            const shouldCollapse = button.dataset.mode === "close";
            view.querySelectorAll(":scope .nyan-collapsible").forEach(section => {
                setCollapsed(section, shouldCollapse);
                if (section.dataset.nyanCollapseKey) safeSet("collapse:" + section.dataset.nyanCollapseKey, shouldCollapse ? "1" : "0");
            });
        });
    }

    function refreshOwnerMap() {
        const owner = document.getElementById("owner-view");
        if (!owner) return;
        let map = document.getElementById("nyan-owner-map");
        if (!map) {
            map = document.createElement("section");
            map.id = "nyan-owner-map";
            map.className = "nyan-owner-map";
            const controls = document.getElementById("nyan-controls-owner-view");
            if (controls) controls.insertAdjacentElement("afterend", map);
            else owner.querySelector(":scope > .subpage-header")?.insertAdjacentElement("afterend", map);
        }

        const sections = Array.from(owner.querySelectorAll(":scope > .admin-section, :scope > .feature-section"))
            .filter(section => section.offsetParent !== null || !section.hidden);
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
                setCollapsed(section, false);
                if (section.dataset.nyanCollapseKey) safeSet("collapse:" + section.dataset.nyanCollapseKey, "0");
                section.scrollIntoView({ behavior: "smooth", block: "start" });
            });
            grid?.appendChild(button);
        }
    }

    function enhanceCollapsibles() {
        for (const selector of COLLAPSIBLE_SELECTORS) {
            document.querySelectorAll(selector).forEach(makeCollapsible);
        }
    }

    function enhanceLists() {
        for (const [id, label] of LIST_TARGETS) {
            const list = document.getElementById(id);
            if (!list || list.dataset.nyanListReady === "1") continue;
            const shell = document.createElement("div");
            shell.className = "nyan-list-shell";
            shell.dataset.nyanListKey = id;
            const toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "nyan-list-toggle";
            const targetParent = list.parentNode;
            if (!targetParent) continue;
            targetParent.insertBefore(shell, list);
            shell.appendChild(toggle);
            shell.appendChild(list);
            list.classList.add("nyan-list-target");
            list.dataset.nyanListReady = "1";

            const stored = safeGet("list:" + id);
            const collapsed = stored === "1";
            shell.classList.toggle("nyan-list-collapsed", collapsed);

            const refresh = () => {
                const count = list.children.length;
                toggle.textContent = `${label}${count ? ` · ${count}` : ""}`;
                toggle.setAttribute("aria-expanded", shell.classList.contains("nyan-list-collapsed") ? "false" : "true");
            };
            toggle.addEventListener("click", () => {
                const next = !shell.classList.contains("nyan-list-collapsed");
                shell.classList.toggle("nyan-list-collapsed", next);
                safeSet("list:" + id, next ? "1" : "0");
                refresh();
            });
            new MutationObserver(refresh).observe(list, { childList: true });
            refresh();
        }
    }

    function expandVisibleDynamicCards() {
        const ownerUser = document.getElementById("owner-user-card");
        if (ownerUser && !ownerUser.hidden && ownerUser.classList.contains("nyan-collapsed")) {
            setCollapsed(ownerUser, false);
        }
    }

    function install() {
        scheduled = false;
        refreshCommandCenter();
        document.querySelectorAll(".app > main.view").forEach(ensureViewControls);
        enhanceCollapsibles();
        enhanceLists();
        refreshOwnerMap();
        expandVisibleDynamicCards();
    }

    function scheduleInstall() {
        if (scheduled) return;
        scheduled = true;
        window.setTimeout(install, 80);
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function start() {
        install();
        const observer = new MutationObserver(scheduleInstall);
        observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
        window.addEventListener("nyan-wallet-loaded", scheduleInstall);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }
})();
