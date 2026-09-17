const tgAch = window.Telegram?.WebApp;
const API_ACH = "https://nyan-wallet-api.onrender.com";
let achievementsState = null;

function achHeaders(json = false) {
    const headers = { "X-Telegram-Init-Data": tgAch?.initData || "" };
    if (json) headers["Content-Type"] = "application/json";
    return headers;
}

async function achJson(response) {
    try { return await response.json(); } catch (_) { return {}; }
}

function achEsc(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function achDate(value) {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function achIcon(name, extraClass = "") {
    const start = `<svg class="ach-svg ${extraClass}" viewBox="0 0 16 16" aria-hidden="true" shape-rendering="crispEdges">`;
    const end = `</svg>`;
    const icons = {
        paw: `<circle cx="5" cy="4" r="2"/><circle cx="11" cy="4" r="2"/><circle cx="3" cy="8" r="1.5"/><circle cx="13" cy="8" r="1.5"/><path d="M4.5 12c0-2.5 1.7-4 3.5-4s3.5 1.5 3.5 4c0 1.3-1.1 2-2.1 1.5L8 13l-1.4.5c-1 .5-2.1-.2-2.1-1.5Z"/>`,
        coin: `<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.8"/><rect x="7" y="4" width="2" height="8"/><rect x="5" y="6" width="6" height="2"/>`,
        bag: `<path d="M5 2h6l-1 3h2l2 8c.2.7-.4 1-1 1H3c-.6 0-1.2-.3-1-1l2-8h2L5 2Zm1 5h4v1H6V7Zm0 3h4v1H6v-1Z"/>`,
        piggy: `<path d="M3 6h2l1-2 2 1h3c2 0 3 1.5 3 3.5 0 1.6-.8 2.7-2 3.2V14h-2v-1H6v1H4v-2c-1.2-.6-2-1.8-2-3.5V7h1V6Zm7 1h1v1h-1V7Z"/><rect x="1" y="7" width="2" height="1"/>`,
        star: `<path d="M8 1.5 10 6l4.8.4-3.7 3.1 1.2 4.7L8 11.7l-4.3 2.5 1.2-4.7-3.7-3.1L6 6l2-4.5Z"/>`,
        gem: `<path d="M4 2h8l3 4-7 8-7-8 3-4Zm1 2L3.5 6H7L5 4Zm3 0L7 6h2L8 4Zm3 0L9 6h3.5L11 4ZM4 7l4 5 4-5H4Z"/>`,
        gift: `<rect x="2" y="7" width="12" height="7"/><rect x="1" y="5" width="14" height="3"/><rect x="7" y="5" width="2" height="9" fill="#fff" opacity=".9"/><path d="M8 5C5 5 3.5 4 4 2.5 4.5 1 7 2 8 4c1-2 3.5-3 4-1.5C12.5 4 11 5 8 5Z"/>`,
        gift_star: `<rect x="2" y="7" width="12" height="7"/><rect x="1" y="5" width="14" height="3"/><rect x="7" y="5" width="2" height="9" fill="#fff" opacity=".9"/><path d="M12 1.2 12.7 3l1.9.1-1.5 1.2.5 1.8L12 5.2l-1.6.9.5-1.8-1.5-1.2 1.9-.1.7-1.8Z"/>`,
        ticket: `<path d="M2 3h12v3c-1 0-2 .8-2 2s1 2 2 2v3H2v-3c1 0 2-.8 2-2S3 6 2 6V3Zm5 2h2v2H7V5Zm0 4h2v2H7V9Z"/>`,
        clover: `<circle cx="5" cy="5" r="3"/><circle cx="11" cy="5" r="3"/><circle cx="5" cy="10" r="3"/><circle cx="11" cy="10" r="3"/><rect x="7" y="9" width="2" height="6" transform="rotate(-20 8 12)"/>`,
        friend: `<circle cx="5" cy="5" r="2.5"/><circle cx="11" cy="5" r="2.5"/><path d="M1 13c.2-3 1.8-4.5 4-4.5S8.8 10 9 13H1Zm6 0c.2-3 1.8-4.5 4-4.5s3.8 1.5 4 4.5H7Z"/>`,
        group: `<circle cx="8" cy="4" r="2.3"/><circle cx="3.5" cy="6" r="2"/><circle cx="12.5" cy="6" r="2"/><path d="M4 14c.2-3.6 1.6-5.5 4-5.5s3.8 1.9 4 5.5H4ZM0 13c.1-2.8 1.2-4.3 3.3-4.3 1 0 1.8.3 2.4.9C4.5 10.7 4 11.8 4 13H0Zm12 0c0-1.2-.5-2.3-1.7-3.4.6-.6 1.4-.9 2.4-.9 2.1 0 3.2 1.5 3.3 4.3h-4Z"/>`,
        crown: `<path d="M2 4 5.5 7 8 2l2.5 5L14 4l-1 9H3L2 4Zm2 7h8l.2-2H3.8L4 11Z"/>`,
        calendar: `<rect x="2" y="3" width="12" height="11" rx="1"/><rect x="4" y="1" width="2" height="4"/><rect x="10" y="1" width="2" height="4"/><rect x="4" y="7" width="2" height="2" fill="#fff" opacity=".9"/><rect x="7" y="7" width="2" height="2" fill="#fff" opacity=".9"/><rect x="10" y="7" width="2" height="2" fill="#fff" opacity=".9"/><rect x="4" y="10" width="2" height="2" fill="#fff" opacity=".9"/><rect x="7" y="10" width="2" height="2" fill="#fff" opacity=".9"/>`,
        medal: `<path d="M4 1h3l1 4-3 2-1-6Zm5 0h3l-1 6-3-2 1-4Z"/><circle cx="8" cy="10" r="4.5"/><path d="M8 7.2 8.8 9l2 .2-1.5 1.3.5 1.9L8 11.4l-1.8 1 .5-1.9-1.5-1.3 2-.2L8 7.2Z" fill="#fff" opacity=".9"/>`,
        legend: `<path d="M8 1v2M2.5 3.5 4 5M13.5 3.5 12 5M1 9h2M13 9h2" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="5" cy="7" r="1.5"/><circle cx="11" cy="7" r="1.5"/><circle cx="3.5" cy="10" r="1.2"/><circle cx="12.5" cy="10" r="1.2"/><path d="M5 13c0-2 1.4-3.2 3-3.2s3 1.2 3 3.2c0 1-.9 1.5-1.7 1.1L8 13.5l-1.3.6C5.9 14.5 5 14 5 13Z"/>`,
    };
    return start + (icons[name] || icons.paw) + end;
}

function addAchStyles() {
    if (document.getElementById("nyan-achievements-styles")) return;
    const style = document.createElement("style");
    style.id = "nyan-achievements-styles";
    style.textContent = `
      .ach-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.ach-count{font-size:12px;font-weight:800;color:#922954;background:#fff0f6;border:1px solid #efd8e2;padding:7px 10px;border-radius:999px;white-space:nowrap}
      .ach-selected{display:flex;align-items:center;gap:10px;margin-top:12px;padding:11px 12px;border:1px solid #efd8e2;border-radius:14px;background:#fff}.ach-selected-icon{width:34px;height:34px;display:grid;place-items:center;border-radius:11px;background:#fff2f7;color:#922954}.ach-selected-text{min-width:0}.ach-selected-title{font-size:12px;font-weight:800;color:#6d304a}.ach-selected-sub{font-size:10px;color:#a67589;margin-top:2px}
      .ach-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:14px}.ach-card{appearance:none;text-align:left;width:100%;min-width:0;padding:13px;border-radius:17px;border:1px solid #efd8e2;background:#fff;color:inherit;position:relative;overflow:hidden}.ach-card.unlocked{cursor:pointer}.ach-card.locked{opacity:.57;filter:saturate(.7)}.ach-card.selected{border-color:#922954;box-shadow:0 0 0 1px #922954 inset}.ach-card:active.unlocked{transform:scale(.985)}
      .ach-card-top{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.ach-icon{width:42px;height:42px;display:grid;place-items:center;border-radius:13px;background:#fff3f7;color:#a33a64;border:1px solid #f0dce5}.ach-svg{width:25px;height:25px;fill:currentColor}.ach-lock{font-size:9px;font-weight:800;color:#b18a9a;background:#faf4f7;border-radius:999px;padding:5px 7px}.ach-rarity{font-size:8px;text-transform:uppercase;letter-spacing:.06em;font-weight:800;margin-top:8px;color:#b47a91}.ach-card[data-rarity="rare"] .ach-icon{background:#fff0f7;color:#b12266}.ach-card[data-rarity="epic"] .ach-icon{background:#fbf0ff;color:#8b3d9e}.ach-card[data-rarity="legendary"] .ach-icon{background:linear-gradient(135deg,#fff1f7,#fff8dc);color:#a06227;box-shadow:0 0 16px rgba(160,98,39,.12)}
      .ach-title{margin-top:5px;font-size:13px;font-weight:850;color:#6d304a;line-height:1.2}.ach-desc{margin-top:5px;font-size:10px;color:#a67589;line-height:1.35;min-height:27px}.ach-reward{margin-top:8px;display:inline-flex;align-items:center;padding:5px 7px;border-radius:999px;background:#fff4f8;color:#922954;font-size:9px;font-weight:800}.ach-reward.badge-only{color:#8d7080;background:#faf5f7}.ach-progress{height:5px;background:#f3e4ea;border-radius:999px;overflow:hidden;margin-top:9px}.ach-progress>span{display:block;height:100%;border-radius:999px;background:#a73a66}.ach-progress-meta{font-size:9px;color:#ae8696;margin-top:4px}.ach-date{font-size:9px;color:#ae8696;margin-top:7px}.ach-selected-mark{position:absolute;top:10px;right:10px;width:18px;height:18px;border-radius:50%;display:grid;place-items:center;background:#922954;color:#fff;font-size:10px;font-weight:900}
      .ach-wallet-badge{display:inline-flex;align-items:center;gap:5px;margin-top:4px;padding:4px 7px;border-radius:999px;background:#fff0f6;border:1px solid #efd8e2;color:#8b3156;font-size:9px;font-weight:800;vertical-align:middle}.ach-wallet-badge .ach-svg{width:12px;height:12px}.ach-hint{margin-top:10px;font-size:10px;line-height:1.4;color:#a67589}.ach-toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:9999;width:min(88vw,340px);padding:12px 14px;border-radius:16px;background:#6f2747;color:#fff;box-shadow:0 12px 35px rgba(67,24,43,.22);font-size:12px;font-weight:700;text-align:center;animation:achIn .2s ease-out}@keyframes achIn{from{opacity:0;transform:translate(-50%,8px)}to{opacity:1;transform:translate(-50%,0)}}
      @media(max-width:360px){.ach-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
}

function rarityLabel(value) {
    return ({ common: "Обычное", rare: "Редкое", epic: "Эпическое", legendary: "Легендарное" })[value] || "Достижение";
}

function buildAchievementsUI() {
    const profile = document.getElementById("adv-profile-view");
    if (!profile || document.getElementById("nyan-achievements-panel")) return false;
    addAchStyles();

    const panel = document.createElement("section");
    panel.id = "nyan-achievements-panel";
    panel.className = "adv-panel";
    panel.innerHTML = `
      <div class="ach-head">
        <div><div class="adv-title">Достижения</div><div class="adv-sub">Собирайте значки за активность в Nyan Wallet</div></div>
        <div id="ach-count" class="ach-count">0 / 16</div>
      </div>
      <div id="ach-selected"></div>
      <div id="ach-grid" class="ach-grid"><div class="adv-sub">Загружаем достижения…</div></div>
      <div class="ach-hint">Нажмите на открытый значок, чтобы установить его в профиль. Повторное нажатие снимет значок.</div>`;

    const levelSection = document.getElementById("adv-profile-level")?.closest("section");
    if (levelSection) levelSection.insertAdjacentElement("afterend", panel);
    else profile.appendChild(panel);

    document.getElementById("adv-profile-button")?.addEventListener("click", () => loadAchievements(false));
    return true;
}

function renderWalletBadge(selected) {
    let badge = document.getElementById("ach-wallet-badge");
    const username = document.getElementById("username");
    if (!selected) {
        badge?.remove();
        return;
    }
    if (!badge) {
        badge = document.createElement("span");
        badge.id = "ach-wallet-badge";
        badge.className = "ach-wallet-badge";
        username?.insertAdjacentElement("afterend", badge);
    }
    badge.innerHTML = `${achIcon(selected.icon)}<span>${achEsc(selected.title)}</span>`;
}

function renderAchievements(data) {
    achievementsState = data;
    const count = document.getElementById("ach-count");
    if (count) count.textContent = `${data.unlocked_count} / ${data.total}`;

    const selectedBox = document.getElementById("ach-selected");
    if (selectedBox) {
        selectedBox.innerHTML = data.selected_badge
            ? `<div class="ach-selected"><div class="ach-selected-icon">${achIcon(data.selected_badge.icon)}</div><div class="ach-selected-text"><div class="ach-selected-title">${achEsc(data.selected_badge.title)}</div><div class="ach-selected-sub">выбранный значок профиля</div></div></div>`
            : `<div class="adv-sub" style="margin-top:10px">Значок профиля пока не выбран.</div>`;
    }
    renderWalletBadge(data.selected_badge);

    const grid = document.getElementById("ach-grid");
    if (!grid) return;
    grid.innerHTML = data.items.map(item => {
        const reward = item.reward > 0 ? `+${item.reward} 🐾` : "значок";
        const progressText = item.unlocked
            ? "Выполнено"
            : `${Math.min(item.current, item.target)} / ${item.target}`;
        return `
          <button type="button" class="ach-card ${item.unlocked ? "unlocked" : "locked"} ${item.selected ? "selected" : ""}" data-ach-key="${achEsc(item.key)}" data-rarity="${achEsc(item.rarity)}" ${item.unlocked ? "" : "disabled"}>
            ${item.selected ? `<span class="ach-selected-mark">✓</span>` : ""}
            <div class="ach-card-top"><div class="ach-icon">${achIcon(item.icon)}</div>${item.unlocked ? "" : `<span class="ach-lock">закрыто</span>`}</div>
            <div class="ach-rarity">${rarityLabel(item.rarity)}</div>
            <div class="ach-title">${achEsc(item.title)}</div>
            <div class="ach-desc">${achEsc(item.description)}</div>
            <div class="ach-reward ${item.reward ? "" : "badge-only"}">${reward}</div>
            <div class="ach-progress"><span style="width:${item.progress}%"></span></div>
            <div class="ach-progress-meta">${progressText}</div>
            ${item.unlocked_at ? `<div class="ach-date">Открыто ${achDate(item.unlocked_at)}</div>` : ""}
          </button>`;
    }).join("");

    for (const card of grid.querySelectorAll(".ach-card.unlocked")) {
        card.addEventListener("click", () => toggleAchievementBadge(card.dataset.achKey));
    }
}

function showAchievementToast(items) {
    if (!items?.length) return;
    document.querySelector(".ach-toast")?.remove();
    const toast = document.createElement("div");
    toast.className = "ach-toast";
    toast.textContent = items.length === 1 ? "Открыто новое достижение" : `Открыто новых достижений: ${items.length}`;
    document.body.appendChild(toast);
    tgAch?.HapticFeedback?.notificationOccurred?.("success");
    setTimeout(() => toast.remove(), 2800);
}

async function loadAchievements(silent = true) {
    if (!tgAch?.initData) return;
    try {
        const response = await fetch(`${API_ACH}/api/achievements`, { headers: achHeaders() });
        const data = await achJson(response);
        if (!response.ok) throw new Error(data.detail || "Не удалось загрузить достижения");
        renderAchievements(data);
        const balance = document.getElementById("balance");
        if (balance && balance.textContent.trim() !== "∞" && Number.isFinite(Number(data.balance))) {
            balance.textContent = String(data.balance);
        }
        if (!silent && data.newly_unlocked?.length) showAchievementToast(data.newly_unlocked);
        if (silent && data.newly_unlocked?.length) showAchievementToast(data.newly_unlocked);
    } catch (_) {
        const grid = document.getElementById("ach-grid");
        if (grid && !achievementsState) grid.innerHTML = `<div class="adv-sub">Не удалось загрузить достижения.</div>`;
    }
}

async function toggleAchievementBadge(key) {
    if (!achievementsState) return;
    const current = achievementsState.selected_badge?.key || null;
    const next = current === key ? null : key;
    try {
        const response = await fetch(`${API_ACH}/api/achievements/badge`, {
            method: "POST",
            headers: achHeaders(true),
            body: JSON.stringify({ key: next }),
        });
        const data = await achJson(response);
        if (!response.ok) throw new Error(data.detail || "Не удалось выбрать значок");
        tgAch?.HapticFeedback?.selectionChanged?.();
        await loadAchievements(true);
    } catch (error) {
        tgAch?.showAlert?.(error.message || "Не удалось выбрать значок");
    }
}

function waitForAchievementsUI() {
    let attempts = 0;
    const timer = setInterval(() => {
        attempts += 1;
        if (buildAchievementsUI()) {
            clearInterval(timer);
            loadAchievements(true);
        } else if (document.getElementById("nyan-achievements-panel")) {
            clearInterval(timer);
            loadAchievements(true);
        } else if (attempts > 30) {
            clearInterval(timer);
        }
    }, 150);
}

waitForAchievementsUI();
