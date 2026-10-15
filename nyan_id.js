(() => {
  "use strict";

  const API = "https://nyan-wallet-api.onrender.com";
  const TELEGRAM = window.Telegram?.WebApp;
  const BOT_LINK = "https://t.me/nyancash_bot?startapp=nyanid";
  let identity = null;
  let fetching = false;
  let layer = null;
  let previousFocus = null;
  let theme = "powder";
  let scheduled = false;

  try {
    if (localStorage.getItem("nyan-id-card-theme") === "night") theme = "night";
  } catch (_) {}

  const el = id => document.getElementById(id);
  function say(message, isError = false) {
    const node = el("nyid-notice");
    if (!node) return;
    node.textContent = message;
    node.dataset.error = isError ? "true" : "false";
  }
  function text(id, value) {
    const node = el(id);
    if (node) node.textContent = String(value == null ? "" : value);
  }
  function shortDate(raw) {
    const date = new Date(raw);
    if (!Number.isFinite(date.getTime())) return "неизвестно";
    return new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC"
    }).format(date);
  }
  function nameInitials(name) {
    const value = String(name || "Nyan");
    const parts = value.trim().split(/\s+/);
    return (parts.length > 1 ? parts[0][0] + parts[1][0] : value.slice(0, 2)).toUpperCase();
  }

  function updateTheme() {
    const card = el("nyid-card");
    if (card) card.dataset.theme = theme;
    document.querySelectorAll(".nyid-theme-button").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.choice === theme));
    });
  }

  function updateCard(data) {
    text("nyid-name", data.display_name || "Пользователь");
    text("nyid-handle", data.username ? "@" + data.username : "участник экосистемы Nyan");
    text("nyid-number", data.number);
    text("nyid-rank", data.rank || "Новичок");
    text("nyid-since", shortDate(data.member_since));
    text("nyid-count", Number(data.achievement_count) || 0);
    text("nyid-avatar", nameInitials(data.display_name));
    text("nyid-edition", data.owner ? "ОСНОВАТЕЛЬ" : "КАРТА УЧАСТНИКА");
    text("nyid-badge", data.badge?.title || "пока нет выбранного значка");

    const container = el("nyid-achievements");
    if (container) {
      container.replaceChildren();
      const entries = Array.isArray(data.recent_achievements) ? data.recent_achievements.slice(0, 3) : [];
      if (!entries.length) {
        const empty = document.createElement("span");
        empty.className = "nyid-empty";
        empty.textContent = "Первые достижения ещё впереди.";
        container.appendChild(empty);
      }
      for (const title of entries) {
        const badge = document.createElement("span");
        badge.className = "nyid-achievement";
        badge.textContent = title;
        container.appendChild(badge);
      }
    }
    for (const id of ["nyid-share", "nyid-save", "nyid-copy"]) {
      const button = el(id);
      if (button) button.disabled = false;
    }
    updateTheme();
  }

  function ensureDialog() {
    if (layer) return layer;

    layer = document.createElement("div");
    layer.id = "nyid-layer";
    layer.className = "nyid-layer";
    layer.hidden = true;
    layer.innerHTML = [
      '<section class="nyid-dialog" role="dialog" aria-modal="true" aria-labelledby="nyid-dialog-title">',
      '  <header class="nyid-modal-header">',
      '    <div><div class="nyid-modal-kicker">ВАША КАРТОЧКА</div><div class="nyid-modal-title" id="nyid-dialog-title">Nyan ID</div></div>',
      '    <button class="nyid-close" id="nyid-close" type="button" aria-label="Закрыть">×</button>',
      '  </header>',
      '  <div class="nyid-card" id="nyid-card" data-theme="powder" aria-label="Карточка участника Nyan Wallet">',
      '    <div class="nyid-card-top">',
      '      <div class="nyid-brand"><span class="nyid-brand-mark" aria-hidden="true">🐾</span> NYAN WALLET</div>',
      '      <div class="nyid-edition" id="nyid-edition">КАРТА УЧАСТНИКА</div>',
      '    </div>',
      '    <div class="nyid-card-main">',
      '      <div class="nyid-label">ПЕРСОНАЛЬНЫЙ NYAN ID</div>',
      '      <div class="nyid-name" id="nyid-name">Загружаем...</div>',
      '      <div class="nyid-handle" id="nyid-handle">участник экосистемы Nyan</div>',
      '      <div class="nyid-card-number" id="nyid-number">NW-••••-••••-••••-••••</div>',
      '      <div class="nyid-card-meta">',
      '        <div><div class="nyid-meta-label">РАНГ</div><div class="nyid-meta-value" id="nyid-rank">—</div></div>',
      '        <div><div class="nyid-meta-label">С НАМИ С</div><div class="nyid-meta-value" id="nyid-since">—</div></div>',
      '        <div><div class="nyid-meta-label">ДОСТИЖЕНИЙ</div><div class="nyid-meta-value" id="nyid-count">—</div></div>',
      '      </div>',
      '    </div>',
      '    <div class="nyid-card-foot"><span>NYAN ID • 2026</span><b id="nyid-badge">загрузка значка...</b></div>',
      '  </div>',
      '  <div class="nyid-note" id="nyid-notice" role="status" aria-live="polite">Подключаем данные...</div>',
      '  <div class="nyid-themes" role="group" aria-label="Оформление Nyan ID">',
      '    <button type="button" class="nyid-theme-button" data-choice="powder" aria-pressed="true"><span class="nyid-theme-dot"></span>Пудровый</button>',
      '    <button type="button" class="nyid-theme-button" data-choice="night" aria-pressed="false"><span class="nyid-theme-dot"></span>Бордовый</button>',
      '  </div>',
      '  <div class="nyid-actions">',
      '    <button id="nyid-save" class="nyid-action" type="button" disabled>Сохранить PNG</button>',
      '    <button id="nyid-share" class="nyid-action primary" type="button" disabled>Поделиться</button>',
      '    <button id="nyid-copy" class="nyid-action nyid-copy" type="button" disabled>Скопировать номер ID</button>',
      '  </div>',
      '  <div class="nyid-detail-title">Недавние достижения</div>',
      '  <div id="nyid-achievements" class="nyid-achievements"><span class="nyid-empty">Загружаем...</span></div>',
      '</section>'
    ].join("");
    document.body.appendChild(layer);

    el("nyid-close")?.addEventListener("click", close);
    layer.addEventListener("click", event => { if (event.target === layer) close(); });
    layer.querySelectorAll("[data-choice]").forEach(button => {
      button.addEventListener("click", () => {
        theme = button.dataset.choice === "night" ? "night" : "powder";
        try { localStorage.setItem("nyan-id-card-theme", theme); } catch (_) {}
        updateTheme();
        TELEGRAM?.HapticFeedback?.selectionChanged?.();
      });
    });
    el("nyid-save")?.addEventListener("click", saveCard);
    el("nyid-share")?.addEventListener("click", shareCard);
    el("nyid-copy")?.addEventListener("click", copyNumber);
    updateTheme();
    return layer;
  }

  async function fetchIdentity() {
    if (fetching) return;
    fetching = true;
    say("Получаем ваш Nyan ID...");
    try {
      if (!TELEGRAM?.initData) throw new Error("Откройте Nyan Wallet через Telegram-бота.");
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 12000);
      let response;
      try {
        response = await fetch(API + "/api/nyan-id", {
          headers: { "X-Telegram-Init-Data": TELEGRAM.initData },
          signal: controller.signal,
          cache: "no-store"
        });
      } finally {
        clearTimeout(timeout);
      }
      const data = await response.json();
      if (!response.ok || !data.ok || !/^NW-(?:[A-F0-9]{4}-){3}[A-F0-9]{4}$/.test(data.number || "")) {
        const detail = typeof data.detail === "string" ? data.detail : "Не удалось получить карточку";
        throw new Error(response.status === 401 ? "Сессия устарела. Откройте приложение заново." : detail);
      }
      identity = data;
      updateCard(data);
      say("Ваш цифровой пропуск в экосистему Nyan");
    } catch (error) {
      say(error?.name === "AbortError" ? "Сервер долго отвечает. Закройте карточку и повторите попытку." : (error?.message || "Не удалось загрузить Nyan ID"), true);
    } finally {
      fetching = false;
    }
  }

  function open() {
    ensureDialog();
    previousFocus = document.activeElement;
    layer.hidden = false;
    document.documentElement.style.overflow = "hidden";
    el("nyid-close")?.focus();
    TELEGRAM?.HapticFeedback?.impactOccurred?.("light");
    if (identity) {
      updateCard(identity);
      say("Обновляем сведения...");
    }
    void fetchIdentity();
  }
  function close() {
    if (!layer) return;
    layer.hidden = true;
    document.documentElement.style.overflow = "";
    if (previousFocus && document.contains(previousFocus)) previousFocus.focus();
  }

  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && layer && !layer.hidden) close();
  });

  function ensureEntryPoints() {
    const profile = el("adv-profile-view");
    if (profile && !el("nyid-profile-open")) {
      const button = document.createElement("button");
      button.id = "nyid-profile-open";
      button.type = "button";
      button.className = "nyid-profile-entry";
      button.innerHTML =
        '<span class="nyid-entry-icon" aria-hidden="true">◇</span>' +
        '<span class="nyid-entry-copy"><strong>Nyan ID</strong><small>твоя персональная карточка участника</small></span>' +
        '<span class="nyid-entry-arrow" aria-hidden="true">›</span>';
      button.addEventListener("click", open);
      const anchor = el("ny-profile-hero") || profile.querySelector(".subpage-header");
      if (anchor) anchor.insertAdjacentElement("afterend", button);
      else profile.prepend(button);
    }

    const more = document.querySelector(".nyan-home-more");
    if (more && !el("nyid-home-open")) {
      const button = document.createElement("button");
      button.type = "button";
      button.id = "nyid-home-open";
      button.className = "nyan-home-more-button nyid-home-action";
      button.textContent = "Nyan ID";
      button.addEventListener("click", open);
      more.appendChild(button);
    }
  }

  function scheduleEntryPoints() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; ensureEntryPoints(); });
  }
  function drawRoundRect(ctx, x, y, w, h, r) {
    const radius = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }
  function fitText(ctx, value, maxWidth, size, minSize, weight = 800) {
    let str = String(value || "—");
    for (let s = size; s >= minSize; s -= 2) {
      ctx.font = String(weight) + " " + String(s) + "px system-ui, Arial, sans-serif";
      if (ctx.measureText(str).width <= maxWidth) return str;
    }
    ctx.font = String(weight) + " " + String(minSize) + "px system-ui, Arial, sans-serif";
    const letters = Array.from(str);
    while (letters.length && ctx.measureText(letters.join("") + "…").width > maxWidth) letters.pop();
    return letters.join("") + "…";
  }
  function drawCard() {
    if (!identity) throw new Error("Сначала дождитесь загрузки карточки.");
    const c = document.createElement("canvas");
    c.width = 1200;
    c.height = 780;
    const ctx = c.getContext("2d");
    if (!ctx) throw new Error("Экспорт изображения недоступен.");
    const night = theme === "night";
    const ink = night ? "#fff4f8" : "#6e274a";
    const muted = night ? "#e6b3cb" : "#aa6d88";
    const bg = ctx.createLinearGradient(0, 0, 1200, 780);
    if (night) {
      bg.addColorStop(0, "#331425"); bg.addColorStop(.55, "#5d2444"); bg.addColorStop(1, "#813b60");
    } else {
      bg.addColorStop(0, "#fffefe"); bg.addColorStop(.55, "#fff7fa"); bg.addColorStop(1, "#fae2ec");
    }
    ctx.fillStyle = bg; ctx.fillRect(0, 0, 1200, 780);

    const glow = ctx.createRadialGradient(1090, 30, 0, 1090, 30, 540);
    glow.addColorStop(0, night ? "rgba(239,126,179,.21)" : "rgba(242,163,197,.45)");
    glow.addColorStop(1, "rgba(242,163,197,0)");
    ctx.fillStyle = glow; ctx.fillRect(0, 0, 1200, 650);
    ctx.beginPath(); ctx.arc(1260, 220, 310, 0, Math.PI * 2);
    ctx.lineWidth = 62; ctx.strokeStyle = night ? "rgba(255,225,241,.07)" : "rgba(179,55,111,.055)"; ctx.stroke();

    drawRoundRect(ctx, 33, 33, 1134, 714, 40);
    ctx.lineWidth = 2; ctx.strokeStyle = night ? "rgba(255,240,247,.32)" : "#eac7d8"; ctx.stroke();

    drawRoundRect(ctx, 91, 88, 57, 57, 18);
    ctx.fillStyle = night ? "rgba(255,255,255,.1)" : "#ffe8f1"; ctx.fill();
    ctx.fillStyle = ink;
    ctx.beginPath(); ctx.ellipse(119, 124, 13, 10, 0, 0, Math.PI * 2); ctx.fill();
    [[99,108],[111,100],[127,100],[139,108]].forEach(([x,y]) => {
      ctx.beginPath(); ctx.arc(x, y, 5.5, 0, Math.PI * 2); ctx.fill();
    });
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = ink;
    ctx.font = "900 38px system-ui, Arial, sans-serif";
    ctx.fillText("NYAN WALLET", 167, 129);

    drawRoundRect(ctx, 892, 91, 229, 48, 24);
    ctx.lineWidth = 1.5; ctx.strokeStyle = night ? "rgba(255,255,255,.3)" : "#dfafc6"; ctx.stroke();
    ctx.fillStyle = ink; ctx.font = "800 18px system-ui, Arial, sans-serif"; ctx.textAlign = "center";
    ctx.fillText(identity.owner ? "ОСНОВАТЕЛЬ" : "КАРТА УЧАСТНИКА", 1006, 122);
    ctx.textAlign = "left";

    ctx.fillStyle = muted; ctx.font = "800 21px system-ui, Arial, sans-serif";
    ctx.fillText("ПЕРСОНАЛЬНЫЙ NYAN ID", 91, 238);
    ctx.fillStyle = ink;
    const name = fitText(ctx, identity.display_name, 1012, 63, 32, 900);
    ctx.fillText(name, 91, 318);
    ctx.fillStyle = muted; ctx.font = "600 25px system-ui, Arial, sans-serif";
    const handle = identity.username ? "@" + identity.username : "участник экосистемы Nyan";
    ctx.fillText(fitText(ctx, handle, 1012, 25, 22, 600), 91, 355);

    ctx.fillStyle = ink; ctx.font = "900 34px system-ui, Arial, sans-serif";
    ctx.fillText(identity.number, 91, 427);

    ctx.beginPath(); ctx.moveTo(91, 475); ctx.lineTo(1109, 475);
    ctx.lineWidth = 2; ctx.strokeStyle = night ? "rgba(255,255,255,.27)" : "#e5c6d5"; ctx.stroke();

    const columns = [
      {x:91,label:"РАНГ",value:identity.rank},
      {x:430,label:"С НАМИ С",value:shortDate(identity.member_since)},
      {x:780,label:"ДОСТИЖЕНИЙ",value:String(identity.achievement_count || 0)}
    ];
    for (const item of columns) {
      ctx.fillStyle = muted; ctx.font = "800 19px system-ui, Arial, sans-serif"; ctx.fillText(item.label, item.x, 526);
      ctx.fillStyle = ink;
      ctx.fillText(fitText(ctx, item.value, item.x === 780 ? 270 : 315, 32, 20, 900), item.x, 569);
    }

    ctx.fillStyle = muted; ctx.font = "700 22px system-ui, Arial, sans-serif";
    ctx.fillText("NYAN ID  •  2026", 91, 676);
    ctx.fillStyle = ink; ctx.textAlign = "right"; ctx.font = "800 22px system-ui, Arial, sans-serif";
    ctx.fillText(fitText(ctx, identity.badge?.title || "участник Nyan", 530, 22, 18, 800), 1109, 676);
    ctx.textAlign = "left";
    return c;
  }

  async function cardBlob() {
    const canvas = drawCard();
    return await new Promise((resolve, reject) => {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error("Не удалось сформировать PNG.")), "image/png");
    });
  }
  function saveBlob(blob) {
    const anchor = document.createElement("a");
    const url = URL.createObjectURL(blob);
    anchor.href = url;
    anchor.download = "nyan-id-" + identity.number.replace(/[^A-Za-z0-9-]/g, "") + ".png";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  async function saveCard() {
    try {
      const blob = await cardBlob();
      saveBlob(blob);
      say("PNG подготовлен. Если Telegram не сохранил файл, используйте системный скриншот.");
    } catch (error) { say(error.message || "Не удалось сохранить карточку.", true); }
  }
  async function shareCard() {
    if (!identity) return;
    try {
      const blob = await cardBlob();
      const file = new File([blob], "nyan-id.png", {type:"image/png"});
      if (typeof navigator.share === "function" &&
          typeof navigator.canShare === "function" &&
          navigator.canShare({ files: [file] })) {
        await navigator.share({
          title: "Мой Nyan ID",
          text: "Моя карточка участника Nyan Wallet",
          files: [file]
        });
        say("Карточка передана в меню отправки.");
        return;
      }
      const message = "Мой Nyan ID: " + identity.number + "\nСоздай свой: " + BOT_LINK;
      const shareUrl = "https://t.me/share/url?url=" + encodeURIComponent(BOT_LINK) +
        "&text=" + encodeURIComponent(message);
      if (typeof TELEGRAM?.openTelegramLink === "function") TELEGRAM.openTelegramLink(shareUrl);
      else window.open(shareUrl, "_blank", "noopener,noreferrer");
      say("Открыта отправка ссылки. Для картинки нажмите «Сохранить PNG».");
    } catch (error) {
      if (error?.name !== "AbortError") say("Не удалось поделиться: " + (error.message || "ошибка"), true);
    }
  }
  async function copyNumber() {
    if (!identity) return;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(identity.number);
      else {
        const input = document.createElement("textarea");
        input.value = identity.number;
        input.style.position = "fixed"; input.style.left = "-9999px";
        document.body.appendChild(input); input.select();
        const ok = document.execCommand("copy"); input.remove();
        if (!ok) throw new Error("Копирование недоступно");
      }
      TELEGRAM?.HapticFeedback?.notificationOccurred?.("success");
      say("Номер Nyan ID скопирован.");
    } catch (_) { say("Не удалось скопировать номер. Нажмите и удерживайте его на карточке.", true); }
  }

  function isDeepLink() {
    const values = [];
    try {
      const url = new URL(location.href);
      values.push(url.searchParams.get("startapp"));
      values.push(url.searchParams.get("tgWebAppStartParam"));
      const hash = new URLSearchParams(url.hash.replace(/^#/, ""));
      values.push(hash.get("startapp"));
      values.push(hash.get("tgWebAppStartParam"));
    } catch (_) {}
    values.push(TELEGRAM?.initDataUnsafe?.start_param);
    return values.some(value => ["nyanid", "nyan_id"].includes(String(value || "").toLowerCase()));
  }

  function start() {
    ensureEntryPoints();
    const observer = new MutationObserver(scheduleEntryPoints);
    observer.observe(document.body, {subtree:true, childList:true});
    if (isDeepLink()) {
      let tries = 0;
      const timer = setInterval(() => {
        tries += 1;
        const wallet = el("wallet-view");
        if (wallet && !wallet.classList.contains("hidden") && el("nyid-home-open") && el("wallet-number")?.textContent?.includes("NYAN ")) {
          clearInterval(timer);
          open();
        } else if (tries >= 80) clearInterval(timer);
      }, 250);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
  window.NyanID = Object.freeze({ open });
})();
