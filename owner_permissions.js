(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const OWNER_ADDON_SELECTOR = [
        "#nyg-owner-nav",
        "#owner-daily-tasks-panel",
        "#nyg-owner-list-view",
        "#nyg-owner-detail-view",
        "#nyg-purchases-view",
        "#adv-owner-catalog",
        "#adv-owner-events",
        "#adv-owner-rewards",
        "#owner-stats-section",
        "#owner-spend-requests",
        "#owner-promo-management",
        "#owner-audit-list"
    ].join(",");

    let ownerKnown = false;
    let isOwner = false;
    let scheduled = false;

    function headers() {
        return { "X-Telegram-Init-Data": tg?.initData || "" };
    }

    function ownerButton() {
        return document.getElementById("owner-button");
    }

    function walletView() {
        return document.getElementById("wallet-view");
    }

    function ownerView() {
        return document.getElementById("owner-view");
    }

    function setOwnerButtonState() {
        const button = ownerButton();
        if (!button) return;
        const allowed = ownerKnown && isOwner;
        button.hidden = !allowed;
        button.disabled = !allowed;
        button.setAttribute("aria-hidden", allowed ? "false" : "true");
        button.dataset.ownerAllowed = allowed ? "1" : "0";
    }

    function restoreWalletIfNeeded() {
        const owner = ownerView();
        const wallet = walletView();
        if (!owner || !wallet || isOwner) return;
        if (!owner.classList.contains("hidden")) {
            owner.classList.add("hidden");
            wallet.classList.remove("hidden");
            tg?.BackButton?.hide?.();
            window.scrollTo({ top: 0, behavior: "smooth" });
        }
    }

    function removeNonOwnerAdminAddons() {
        if (!ownerKnown || isOwner) return;
        document.querySelectorAll(OWNER_ADDON_SELECTOR).forEach((node) => node.remove());
        const owner = ownerView();
        if (owner) owner.setAttribute("aria-hidden", "true");
    }

    function placeDailyTasks() {
        const wallet = walletView();
        const card = document.getElementById("daily-tasks-card");
        const walletCard = document.getElementById("wallet-card");
        if (!wallet || !card || !walletCard || card.parentElement !== wallet || walletCard.parentElement !== wallet) return;
        if (walletCard.nextElementSibling !== card) walletCard.insertAdjacentElement("afterend", card);
    }

    function enforce() {
        scheduled = false;
        setOwnerButtonState();
        restoreWalletIfNeeded();
        removeNonOwnerAdminAddons();
        placeDailyTasks();
    }

    function scheduleEnforce() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(enforce);
    }

    async function resolveOwner() {
        if (!tg?.initData) {
            ownerKnown = true;
            isOwner = false;
            window.__nyanIsOwner = false;
            document.body.dataset.nyanRole = "guest";
            enforce();
            return;
        }

        try {
            const response = await fetch(`${API}/api/me`, { headers: headers(), cache: "no-store" });
            let data = {};
            try { data = await response.json(); } catch (_) {}
            if (!response.ok) throw new Error(data?.detail || "owner check failed");
            ownerKnown = true;
            isOwner = data?.user?.is_owner === true;
            window.__nyanIsOwner = isOwner;
            window.__nyanWalletUser = data.user || null;
            document.body.dataset.nyanRole = isOwner ? "owner" : "user";
            window.dispatchEvent(new CustomEvent("nyan-owner-state", { detail: { is_owner: isOwner, user: data.user || null } }));
        } catch (error) {
            console.warn("Nyan owner permission check failed:", error);
            ownerKnown = true;
            isOwner = false;
            window.__nyanIsOwner = false;
            document.body.dataset.nyanRole = "unknown";
        }
        enforce();
    }

    document.addEventListener("click", (event) => {
        const adminClick = event.target?.closest?.("#owner-button, #owner-view, #nyg-owner-nav, #nyg-owner-list-view, #nyg-owner-detail-view, #nyg-purchases-view");
        if (!adminClick || isOwner) return;
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        enforce();
    }, true);

    function start() {
        setOwnerButtonState();
        placeDailyTasks();
        const observer = new MutationObserver(scheduleEnforce);
        observer.observe(document.body, { childList: true, subtree: true });
        void resolveOwner();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }
})();
