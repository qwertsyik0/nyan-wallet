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
