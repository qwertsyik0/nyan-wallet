(() => {
    "use strict";

    const TASK_TITLES = {
        activity: "Активируй серию",
        referrals: "Пригласи 3 друзей",
        review: "Напиши отзыв",
    };

    function rowTitle(row) {
        return (row?.querySelector(".daily-task-title")?.textContent || "").trim();
    }

    function rowStatus(row) {
        return (row?.querySelector(".daily-task-status")?.textContent || "").trim().toLowerCase();
    }

    function isTerminal(row) {
        const status = rowStatus(row);
        return status.includes("награда получена") || status.includes("ожидает") || status.includes("выполнено");
    }

    function patchLabels() {
        document.querySelectorAll(".daily-task-status").forEach((status) => {
            const current = status.textContent || "";
            if (current.includes("ожидает подтверждения")) {
                status.textContent = current.replace("ожидает подтверждения", "ожидает проверки");
            }
            if (current.includes("reward_claimed")) {
                status.textContent = current.replace("reward_claimed", "награда получена");
            }
        });

        document.querySelectorAll("#daily-task-list .daily-task-row").forEach((row) => {
            const title = rowTitle(row);
            const button = row.querySelector("button");
            if (!button || button.disabled || isTerminal(row)) return;

            if (title === TASK_TITLES.activity) {
                button.textContent = "Активировать";
            } else if (title === TASK_TITLES.referrals) {
                button.textContent = "Пригласить";
            } else if (title === TASK_TITLES.review) {
                button.textContent = "Отправить на проверку";
            }
        });

        document.querySelectorAll("#owner-daily-tasks-panel .owner-task-sub").forEach((node) => {
            if ((node.textContent || "").trim() === "Ожидают подтверждения") {
                node.textContent = "Заявки на проверку заданий";
            }
        });

        document.querySelectorAll("#owner-task-reviews .task-review-row").forEach((row) => {
            if (row.dataset.nyanReviewHardened === "1") return;
            row.dataset.nyanReviewHardened = "1";
            const meta = row.querySelector(".owner-task-row-meta");
            const title = row.querySelector(".owner-task-row-title")?.textContent || "";
            if (meta && !meta.textContent.includes("статус:")) {
                meta.textContent = `${meta.textContent} · статус: ожидает проверки`;
            }
            const reward = document.createElement("div");
            reward.className = "owner-task-row-meta";
            reward.textContent = title === TASK_TITLES.review ? "награда: +50 🐾" : title === TASK_TITLES.referrals ? "награда: +170 🐾" : "";
            if (reward.textContent) row.insertBefore(reward, row.querySelector(".owner-task-actions"));
        });
    }

    function openActivity() {
        const refresh = document.getElementById("activity-streak-refresh");
        if (refresh && !refresh.disabled) {
            refresh.click();
            return;
        }
        const card = document.getElementById("activity-streak-card");
        if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function openReferralProfile() {
        const profile = document.getElementById("adv-profile-button");
        if (profile && !profile.disabled) {
            profile.click();
            return;
        }
        const wallet = document.getElementById("wallet-view");
        if (wallet) wallet.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    document.addEventListener("click", (event) => {
        const button = event.target?.closest?.("#daily-task-list .daily-task-row button");
        if (!button || button.disabled) return;

        const row = button.closest(".daily-task-row");
        const title = rowTitle(row);
        if (title !== TASK_TITLES.activity && title !== TASK_TITLES.referrals) return;

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        if (title === TASK_TITLES.activity) openActivity();
        if (title === TASK_TITLES.referrals) openReferralProfile();
    }, true);

    function start() {
        patchLabels();
        const observer = new MutationObserver(() => patchLabels());
        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }
})();
