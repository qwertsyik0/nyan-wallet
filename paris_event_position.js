(function () {
    "use strict";

    const WALLET_CARD_ID = "wallet-card";
    const BANNER_ID = "paris-event-banner";
    const SLOT_ID = "paris-event-slot";
    let scheduled = false;

    function positionParisBanner() {
        scheduled = false;

        const walletCard = document.getElementById(WALLET_CARD_ID);
        const banner = document.getElementById(BANNER_ID);
        if (!walletCard || !banner || !walletCard.parentElement) return;

        let slot = document.getElementById(SLOT_ID);
        if (!slot) {
            slot = document.createElement("section");
            slot.id = SLOT_ID;
            slot.className = "paris-event-slot";
            slot.setAttribute("aria-label", "Le Nyan Paris");
        }

        if (slot.parentElement !== walletCard.parentElement || walletCard.nextElementSibling !== slot) {
            walletCard.insertAdjacentElement("afterend", slot);
        }

        if (banner.parentElement !== slot) {
            slot.appendChild(banner);
        }

        banner.classList.add("paris-event-banner-pinned");
    }

    function schedulePosition() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(positionParisBanner);
    }

    function runSeveralPasses() {
        schedulePosition();
        window.setTimeout(schedulePosition, 80);
        window.setTimeout(schedulePosition, 300);
        window.setTimeout(schedulePosition, 900);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", runSeveralPasses, { once: true });
    } else {
        runSeveralPasses();
    }

    window.addEventListener("load", runSeveralPasses, { once: true });

    const walletView = document.getElementById("wallet-view");
    if (walletView && window.MutationObserver) {
        const observer = new MutationObserver(runSeveralPasses);
        observer.observe(walletView, { childList: true });
    }
})();

(function () {
    "use strict";

    if (window.__nyanParisAcceptRolePatched) return;
    window.__nyanParisAcceptRolePatched = true;

    const originalFetch = window.fetch.bind(window);

    function normalizeRole(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function requestUrl(input) {
        if (typeof input === "string") return input;
        if (input && typeof input.url === "string") return input.url;
        return "";
    }

    function requestMethod(input, init) {
        return String(init?.method || input?.method || "GET").toUpperCase();
    }

    function isParisStatusRequest(input, init) {
        const url = requestUrl(input);
        return requestMethod(input, init) === "POST"
            && url.includes("/api/owner/paris/applications/")
            && url.includes("/status");
    }

    function jsonError(detail, status) {
        return new Response(JSON.stringify({ detail }), {
            status,
            headers: { "Content-Type": "application/json" },
        });
    }

    window.fetch = function patchedFetch(input, init) {
        if (!isParisStatusRequest(input, init)) {
            return originalFetch(input, init);
        }

        const nextInit = init ? { ...init } : {};

        try {
            if (typeof nextInit.body !== "string") {
                return originalFetch(input, init);
            }

            const payload = JSON.parse(nextInit.body);
            if (!payload || payload.status !== "accepted" || payload.assigned_role) {
                return originalFetch(input, init);
            }

            const role = normalizeRole(window.prompt("Какую роль выдать участнику Le Nyan Paris?"));
            if (!role) {
                return Promise.resolve(jsonError("Для принятия анкеты нужно указать роль.", 400));
            }

            payload.assigned_role = role.slice(0, 120);
            if (!payload.owner_comment) {
                payload.owner_comment = payload.assigned_role;
            }
            nextInit.body = JSON.stringify(payload);
            return originalFetch(input, nextInit);
        } catch (_) {
            return originalFetch(input, init);
        }
    };
})();

(function () {
    "use strict";

    const PARIS_PARAMS = new Set([
        "paris",
        "nyan_paris",
        "le_nyan_paris",
        "le-nyan-paris",
        "le-nyan-paris-event",
    ]);
    let opened = false;

    function normalize(value) {
        return String(value || "").trim().toLowerCase().replace(/\s+/g, "_");
    }

    function valueWantsParis(value) {
        const normalized = normalize(value);
        return PARIS_PARAMS.has(normalized) || PARIS_PARAMS.has(normalized.replace(/_/g, "-"));
    }

    function urlWantsParis() {
        const params = new URLSearchParams(window.location.search || "");
        if (params.has("paris")) {
            const value = normalize(params.get("paris") || "1");
            if (!value || value === "1" || value === "true" || value === "open") return true;
        }
        for (const key of ["event", "page", "screen", "startapp", "start_param", "tgWebAppStartParam"]) {
            if (valueWantsParis(params.get(key))) return true;
        }
        if (valueWantsParis(window.location.hash.replace(/^#/, ""))) return true;
        return false;
    }

    function telegramWantsParis() {
        const tgApp = window.Telegram?.WebApp;
        const unsafe = tgApp?.initDataUnsafe || {};
        return valueWantsParis(unsafe.start_param)
            || valueWantsParis(unsafe.startapp)
            || valueWantsParis(unsafe.tgWebAppStartParam);
    }

    function shouldOpenParis() {
        return urlWantsParis() || telegramWantsParis();
    }

    function openParisEvent() {
        if (opened || !shouldOpenParis()) return;
        const banner = document.getElementById("paris-event-banner");
        const eventView = document.getElementById("paris-event-view");
        if (!banner || !eventView) return;
        opened = true;
        banner.click();
    }

    function runPasses() {
        openParisEvent();
        window.setTimeout(openParisEvent, 120);
        window.setTimeout(openParisEvent, 450);
        window.setTimeout(openParisEvent, 1000);
        window.setTimeout(openParisEvent, 1800);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", runPasses, { once: true });
    } else {
        runPasses();
    }
    window.addEventListener("load", runPasses, { once: true });

    const appRoot = document.querySelector(".app");
    if (appRoot && window.MutationObserver) {
        const observer = new MutationObserver(openParisEvent);
        observer.observe(appRoot, { childList: true, subtree: true });
        window.setTimeout(() => observer.disconnect(), 5000);
    }
})();
