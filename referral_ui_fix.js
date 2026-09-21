(() => {
    "use strict";

    const NEXT_TEXT = "Приглашайте пользователей. Код можно применить один раз. Системные награды, задания, серии и промокоды не блокируют ввод реферального кода.";

    function patchReferralText() {
        document.querySelectorAll("#adv-profile-view .adv-panel").forEach((panel) => {
            const title = panel.querySelector(".adv-title")?.textContent?.trim();
            if (title !== "Реферальная система") return;
            const sub = panel.querySelector(".adv-sub");
            if (sub && sub.textContent !== NEXT_TEXT) sub.textContent = NEXT_TEXT;
        });
    }

    function start() {
        patchReferralText();
        const observer = new MutationObserver(patchReferralText);
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }
})();
