(() => {
  const tg = window.Telegram?.WebApp;
  const API = "https://nyan-wallet-api.onrender.com";
  let profileData = null;
  let achievementData = null;
  let notificationData = null;
  let eventData = null;
  let catalogData = null;
  let activeRewardFilter = "all";
  let rewardEnhanceBusy = false;

  const headers = (json = false) => {
    const h = { "X-Telegram-Init-Data": tg?.initData || "" };
    if (json) h["Content-Type"] = "application/json";
    return h;
  };

  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  async function getJson(path) {
    if (!tg?.initData) return null;
    try {
      const r = await fetch(API + path, { headers: headers() });
      const d = await r.json();
      return r.ok ? d : null;
    } catch (_) {
      return null;
    }
  }

  function currentBalance() {
    const value = document.getElementById("balance")?.textContent?.trim();
    if (value === "∞") return Infinity;
    const n = Number(String(value || "0").replace(/\s/g, ""));
    return Number.isFinite(n) ? n : 0;
  }

  function userName() {
    const u = tg?.initDataUnsafe?.user;
    return u?.first_name || u?.username || document.getElementById("username")?.textContent || "пользователь";
  }

  function userHandle() {
    const u = tg?.initDataUnsafe?.user;
    if (u?.username) return "@" + u.username;
    return "Nyan Wallet";
  }

  function avatarHtml() {
    const u = tg?.initDataUnsafe?.user;
    if (u?.photo_url) return `<img src="${esc(u.photo_url)}" alt="">`;
    const initials = [u?.first_name, u?.last_name].filter(Boolean).map(x => x[0]).join("").slice(0, 2) || "N";
    return esc(initials.toUpperCase());
  }

  async function refreshData() {
    const [profile, ach, notifications, events, catalog] = await Promise.all([
      getJson("/api/profile"),
      getJson("/api/achievements"),
      getJson("/api/notifications"),
      getJson("/api/events"),
      getJson("/api/catalog"),
    ]);
    if (profile) profileData = profile;
    if (ach) achievementData = ach;
    if (notifications) notificationData = notifications;
    if (events) eventData = events;
    if (catalog) catalogData = catalog;
    renderHome();
    renderProfileEnhancements();
    enhanceRewards();
  }

  function ensureHome() {
    const wallet = document.getElementById("wallet-view");
    if (!wallet || document.getElementById("ny-home")) return;

    const home = document.createElement("div");
    home.id = "ny-home";
    home.className = "ny-home";
    home.innerHTML = `
      <section class="ny-section">
        <div class="ny-section-head"><div class="ny-section-title">Кошелёк</div></div>
        <div class="ny-stats" id="ny-home-stats">
          <div class="ny-stat"><div class="ny-stat-value">…</div><div class="ny-stat-label">заработано</div></div>
          <div class="ny-stat"><div class="ny-stat-value">…</div><div class="ny-stat-label">наград получено</div></div>
          <div class="ny-stat"><div class="ny-stat-value">…</div><div class="ny-stat-label">друзей приглашено</div></div>
        </div>
      </section>

      <section class="ny-section">
        <div class="ny-section-head"><div class="ny-section-title">Быстрый доступ</div></div>
        <div class="ny-quick">
          <button type="button" data-ny-action="rewards"><span class="ny-quick-icon">🎁</span>Награды</button>
          <button type="button" data-ny-action="achievements"><span class="ny-quick-icon">◇</span>Достижения</button>
          <button type="button" data-ny-action="referral"><span class="ny-quick-icon">♡</span>Рефералы</button>
          <button type="button" data-ny-action="history"><span class="ny-quick-icon">≡</span>История</button>
        </div>
      </section>

      <section class="ny-section ny-goal" id="ny-next-goal">
        <div class="ny-goal-title">Следующая цель</div>
        <div class="ny-goal-meta">Загружаем доступные награды…</div>
        <div class="ny-progress"><span style="width:0%"></span></div>
        <button type="button" data-ny-action="rewards">Перейти к наградам</button>
      </section>

      <section class="ny-section" id="ny-event-section" hidden>
        <div class="ny-section-head"><div class="ny-section-title">Событие</div></div>
        <div id="ny-event-content"></div>
      </section>

      <section class="ny-section" id="ny-latest-section">
        <div class="ny-section-head">
          <div class="ny-section-title">Последнее</div>
          <button type="button" class="ny-section-link" data-ny-action="notifications">Все уведомления</button>
        </div>
        <div class="ny-latest" id="ny-latest-list"><div class="ny-latest-item"><div class="ny-latest-meta">Загружаем…</div></div></div>
      </section>`;

    const actions = wallet.querySelector(".actions");
    const history = wallet.querySelector(".history");
    if (actions) actions.insertAdjacentElement("beforebegin", home);
    else if (history) history.insertAdjacentElement("beforebegin", home);
    else wallet.appendChild(home);

    home.addEventListener("click", (event) => {
      const button = event.target.closest("[data-ny-action]");
      if (!button) return;
      const action = button.dataset.nyAction;
      if (action === "rewards") document.getElementById("spend-button")?.click();
      if (action === "notifications") document.getElementById("adv-notifications-button")?.click();
      if (action === "history") {
        document.querySelector("#wallet-view .history")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      if (action === "achievements" || action === "referral") {
        document.getElementById("adv-profile-button")?.click();
        setTimeout(() => {
          const target = action === "achievements" ? document.getElementById("nyan-achievements-panel") : document.getElementById("adv-referral-box")?.closest("section");
          target?.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 250);
      }
    });
  }

  function renderHome() {
    ensureHome();
    const stats = profileData?.stats || {};
    const homeStats = document.getElementById("ny-home-stats");
    if (homeStats) {
      const earned = profileData?.level?.lifetime_earned ?? stats.lifetime_earned ?? 0;
      const rewards = stats.fulfilled_rewards ?? achievementData?.items?.find(x => x.key === "reward_hunter")?.current ?? 0;
      const invited = profileData?.referral?.invited_count ?? stats.invited_count ?? 0;
      homeStats.innerHTML = `
        <div class="ny-stat"><div class="ny-stat-value">${esc(earned)} 🐾</div><div class="ny-stat-label">заработано</div></div>
        <div class="ny-stat"><div class="ny-stat-value">${esc(rewards)}</div><div class="ny-stat-label">наград получено</div></div>
        <div class="ny-stat"><div class="ny-stat-value">${esc(invited)}</div><div class="ny-stat-label">друзей приглашено</div></div>`;
    }

    const goal = document.getElementById("ny-next-goal");
    if (goal) {
      const balance = currentBalance();
      const rewards = [...(catalogData?.rewards || [])].sort((a, b) => a.cost - b.cost);
      const target = rewards.find(r => balance !== Infinity && r.cost > balance) || rewards[0];
      if (target) {
        const progress = balance === Infinity ? 100 : Math.min(100, Math.round((balance / Math.max(1, target.cost)) * 100));
        const meta = balance === Infinity
          ? `Каталог открыт. «${esc(target.title)}» стоит ${target.cost} 🐾`
          : balance >= target.cost
            ? `На «${esc(target.title)}» уже хватает лапкоинов`
            : `До «${esc(target.title)}» осталось ${target.cost - balance} 🐾`;
        goal.querySelector(".ny-goal-meta").innerHTML = meta;
        goal.querySelector(".ny-progress span").style.width = progress + "%";
      } else {
        goal.querySelector(".ny-goal-meta").textContent = "Каталог наград временно пуст";
        goal.querySelector(".ny-progress span").style.width = "0%";
      }
    }

    const eventSection = document.getElementById("ny-event-section");
    const eventContent = document.getElementById("ny-event-content");
    const event = eventData?.events?.[0];
    if (eventSection && eventContent) {
      eventSection.hidden = !event;
      if (event) {
        eventContent.innerHTML = `<div class="ny-event-card">
          ${event.badge ? `<div class="ny-event-badge">${esc(event.badge)}</div>` : ""}
          <div class="ny-event-title">${esc(event.title)}</div>
          <div class="ny-event-desc">${esc(event.description || "Лимитированное событие Nyan Wallet")}</div>
        </div>`;
      }
    }

    const latest = document.getElementById("ny-latest-list");
    if (latest) {
      const items = notificationData?.items?.slice(0, 2) || [];
      latest.innerHTML = items.length
        ? items.map(item => `<div class="ny-latest-item"><div class="ny-latest-title">${esc(item.title)}</div><div class="ny-latest-meta">${esc(item.body || "")}</div></div>`).join("")
        : `<div class="ny-latest-item"><div class="ny-latest-meta">Пока ничего нового</div></div>`;
    }
  }

  function ensureProfileEnhancements() {
    const profile = document.getElementById("adv-profile-view");
    if (!profile) return false;
    if (!document.getElementById("ny-profile-hero")) {
      const header = profile.querySelector(".subpage-header");
      const hero = document.createElement("section");
      hero.id = "ny-profile-hero";
      hero.className = "ny-profile-hero";
      hero.innerHTML = `<div class="ny-avatar" id="ny-avatar">${avatarHtml()}</div><div class="ny-profile-main"><div class="ny-profile-name" id="ny-profile-name">${esc(userName())}</div><div class="ny-profile-handle">${esc(userHandle())}</div><div class="ny-profile-chips" id="ny-profile-chips"></div></div>`;
      header?.insertAdjacentElement("afterend", hero);
    }
    if (!document.getElementById("ny-profile-stats")) {
      const hero = document.getElementById("ny-profile-hero");
      const stats = document.createElement("section");
      stats.id = "ny-profile-stats";
      stats.className = "ny-profile-stats";
      hero?.insertAdjacentElement("afterend", stats);
    }
    if (!document.getElementById("ny-profile-ach-preview")) {
      const achPanel = document.getElementById("nyan-achievements-panel");
      if (achPanel) {
        const selected = achPanel.querySelector("#ach-selected");
        const preview = document.createElement("div");
        preview.id = "ny-profile-ach-preview";
        selected?.insertAdjacentElement("afterend", preview);
      }
    }
    return true;
  }

  function renderProfileEnhancements() {
    if (!ensureProfileEnhancements()) return;
    const chips = document.getElementById("ny-profile-chips");
    const level = profileData?.level;
    const selected = achievementData?.selected_badge;
    if (chips) chips.innerHTML = `
      <span class="ny-chip">${esc(level?.name || "Новичок")}</span>
      ${selected ? `<span class="ny-chip">${esc(selected.title)}</span>` : ""}`;

    const stats = profileData?.stats || {};
    const balance = stats.unlimited_balance ? "∞" : (stats.balance ?? currentBalance());
    const statsBox = document.getElementById("ny-profile-stats");
    if (statsBox) {
      statsBox.innerHTML = [
        [balance + " 🐾", "баланс"],
        [(stats.lifetime_earned ?? level?.lifetime_earned ?? 0) + " 🐾", "заработано"],
        [(stats.lifetime_spent ?? 0) + " 🐾", "потрачено"],
        [stats.fulfilled_rewards ?? 0, "наград получено"],
        [stats.promo_uses ?? 0, "промокодов"],
        [stats.invited_count ?? profileData?.referral?.invited_count ?? 0, "друзей приглашено"],
      ].map(([v, l]) => `<div class="ny-profile-stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
    }

    const preview = document.getElementById("ny-profile-ach-preview");
    if (preview) {
      const unlocked = (achievementData?.items || []).filter(x => x.unlocked).slice(-3).reverse();
      preview.innerHTML = unlocked.map(item => {
        const card = document.querySelector(`.ach-card[data-ach-key="${CSS.escape(item.key)}"] .ach-icon`);
        const icon = card?.innerHTML || "◇";
        return `<div class="ny-ach-mini">${icon}<div class="ny-ach-mini-name">${esc(item.title)}</div></div>`;
      }).join("");
    }
  }

  function ensureRewardFilters() {
    const spend = document.getElementById("spend-view");
    const list = document.getElementById("reward-list");
    if (!spend || !list || document.getElementById("ny-reward-filters")) return;
    const filters = document.createElement("div");
    filters.id = "ny-reward-filters";
    filters.innerHTML = [
      ["all", "Все"],
      ["stars", "Stars"],
      ["shop", "Нян Шоп"],
      ["gifts", "Подарки"],
      ["giveaways", "Розыгрыши"],
      ["boosts", "Бонусы"],
      ["design", "Оформление"],
      ["limited", "Лимитированные"],
    ].map(([key, label]) => `<button type="button" class="ny-filter ${key === "all" ? "active" : ""}" data-filter="${key}">${label}</button>`).join("");
    list.insertAdjacentElement("beforebegin", filters);
    filters.addEventListener("click", event => {
      const button = event.target.closest("[data-filter]");
      if (!button) return;
      activeRewardFilter = button.dataset.filter;
      filters.querySelectorAll(".ny-filter").forEach(x => x.classList.toggle("active", x === button));
      applyRewardFilter();
    });
  }

  function rewardCategory(reward) {
    const title = (reward?.title || "").toLowerCase();
    const limited = reward?.stock_limit != null || reward?.available_until || title.includes("лимитирован");
    const shop = title.includes("скидк") || title.includes("гаранти") || title.includes("замена аккаунта") || title.includes("физический аккаунт");
    const gifts = title.includes("подарок");
    const giveaways = title.includes("билет") || title.includes("розыгрыш");
    const boosts = title.includes("x2 лапкоин") || title.includes("vip");
    const design = title.includes("кошельк") || title.includes("фон") || title.includes("значок рядом");
    return { stars: title.includes("star"), shop, gifts, giveaways, boosts, design, limited: Boolean(limited) };
  }

  function catalogByTitle(title) {
    return (catalogData?.rewards || []).find(x => x.title.trim() === title.trim()) || null;
  }

  function enhanceRewards() {
    if (rewardEnhanceBusy) return;
    const list = document.getElementById("reward-list");
    if (!list) return;
    rewardEnhanceBusy = true;
    try {
      ensureRewardFilters();
      const balance = currentBalance();
      for (const card of list.querySelectorAll(".feature-card")) {
        const title = card.querySelector("h3")?.textContent?.trim() || "";
        const reward = catalogByTitle(title);
        if (!reward) continue;
        const category = rewardCategory(reward);
        card.dataset.nyStars = category.stars ? "1" : "0";
        card.dataset.nyShop = category.shop ? "1" : "0";
        card.dataset.nyGifts = category.gifts ? "1" : "0";
        card.dataset.nyGiveaways = category.giveaways ? "1" : "0";
        card.dataset.nyBoosts = category.boosts ? "1" : "0";
        card.dataset.nyDesign = category.design ? "1" : "0";
        card.dataset.nyLimited = category.limited ? "1" : "0";
        card.dataset.nyRewardTitle = reward.title;
        card.classList.add("ny-reward-detail-trigger");

        let extra = card.querySelector(".ny-reward-extra");
        if (!extra) {
          extra = document.createElement("div");
          extra.className = "ny-reward-extra";
          const button = card.querySelector("button");
          button?.insertAdjacentElement("beforebegin", extra);
        }
        const enough = balance === Infinity || balance >= reward.cost;
        const progress = balance === Infinity ? 100 : Math.min(100, Math.round(balance * 100 / Math.max(1, reward.cost)));
        const missing = enough ? 0 : reward.cost - balance;
        const signature = [balance, reward.cost, reward.stock_remaining, reward.available_until, enough, progress].join("|");
        if (extra.dataset.nySignature !== signature) {
          extra.dataset.nySignature = signature;
          extra.innerHTML = `
            <div class="ny-reward-tags">
              <span class="ny-reward-tag">${category.stars ? "Stars" : "Награда"}</span>
              ${category.limited ? '<span class="ny-reward-tag limited">Лимитированная</span>' : ""}
              <span class="ny-reward-tag ${enough ? "ready" : "short"}">${enough ? "Доступно" : "Не хватает"}</span>
            </div>
            <div class="ny-reward-progress"><span style="width:${progress}%"></span></div>
            <div class="ny-reward-missing">${enough ? "Можно получить сейчас" : `Не хватает ещё ${missing} 🐾`}</div>`;
        }

        const button = card.querySelector("button");
        if (button) {
          if (!button.dataset.nyOriginalText) button.dataset.nyOriginalText = button.textContent;
          const nextText = enough ? button.dataset.nyOriginalText : `Не хватает ${missing} 🐾`;
          if (button.disabled === enough) button.disabled = !enough;
          if (button.textContent !== nextText) button.textContent = nextText;
        }

        if (!card.dataset.nyDetailBound) {
          card.dataset.nyDetailBound = "1";
          card.addEventListener("click", event => {
            if (event.target.closest("button")) return;
            openRewardModal(reward, card);
          });
        }
      }
      applyRewardFilter();
    } finally {
      rewardEnhanceBusy = false;
    }
  }

  function applyRewardFilter() {
    const list = document.getElementById("reward-list");
    if (!list) return;
    for (const card of list.querySelectorAll(".feature-card")) {
      let show = true;
      if (activeRewardFilter === "stars") show = card.dataset.nyStars === "1";
      if (activeRewardFilter === "shop") show = card.dataset.nyShop === "1";
      if (activeRewardFilter === "gifts") show = card.dataset.nyGifts === "1";
      if (activeRewardFilter === "giveaways") show = card.dataset.nyGiveaways === "1";
      if (activeRewardFilter === "boosts") show = card.dataset.nyBoosts === "1";
      if (activeRewardFilter === "design") show = card.dataset.nyDesign === "1";
      if (activeRewardFilter === "limited") show = card.dataset.nyLimited === "1";
      card.hidden = !show;
    }
  }

  function ensureModal(id) {
    let backdrop = document.getElementById(id);
    if (backdrop) return backdrop;
    backdrop = document.createElement("div");
    backdrop.id = id;
    backdrop.className = "ny-modal-backdrop";
    backdrop.hidden = true;
    backdrop.innerHTML = '<div class="ny-modal" role="dialog" aria-modal="true"></div>';
    document.body.appendChild(backdrop);
    backdrop.addEventListener("click", e => {
      if (e.target === backdrop || e.target.closest("[data-ny-close]")) closeModal(backdrop);
    });
    return backdrop;
  }

  function openModal(backdrop) {
    backdrop.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeModal(backdrop) {
    backdrop.hidden = true;
    document.body.style.overflow = "";
  }

  function openRewardModal(reward, card) {
    const backdrop = ensureModal("ny-reward-modal");
    const modal = backdrop.querySelector(".ny-modal");
    const balance = currentBalance();
    const enough = balance === Infinity || balance >= reward.cost;
    const missing = enough ? 0 : reward.cost - balance;
    const originalButton = card.querySelector("button");
    modal.innerHTML = `
      <div class="ny-modal-head"><div><div class="ny-modal-title">${esc(reward.title)}</div><div class="ny-modal-sub">${esc(reward.description || "Награда из каталога Nyan Wallet")}</div></div><button type="button" class="ny-modal-close" data-ny-close>×</button></div>
      <div class="ny-modal-price">${reward.cost} 🐾</div>
      <div class="ny-modal-meta">
        <div><b>Ваш баланс</b><span>${balance === Infinity ? "∞" : balance} 🐾</span></div>
        <div><b>Статус</b><span>${enough ? "Доступно" : `Не хватает ${missing} 🐾`}</span></div>
        ${reward.stock_remaining != null ? `<div><b>Осталось</b><span>${reward.stock_remaining} шт.</span></div>` : ""}
        ${reward.available_until ? `<div><b>Доступно до</b><span>${new Date(reward.available_until).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}</span></div>` : ""}
      </div>
      <div class="ny-progress"><span style="width:${balance === Infinity ? 100 : Math.min(100, Math.round(balance * 100 / Math.max(1,reward.cost)))}%"></span></div>
      <button type="button" class="ny-modal-primary" id="ny-modal-buy" ${enough ? "" : "disabled"}>${enough ? "Получить награду" : `Не хватает ${missing} 🐾`}</button>
      <button type="button" class="ny-modal-secondary" data-ny-close>Закрыть</button>`;
    modal.querySelector("#ny-modal-buy")?.addEventListener("click", () => {
      closeModal(backdrop);
      originalButton?.click();
    });
    openModal(backdrop);
  }

  function achievementItem(key) {
    return achievementData?.items?.find(x => x.key === key) || null;
  }

  function enhanceAchievementCards() {
    for (const card of document.querySelectorAll(".ach-card")) {
      const item = achievementItem(card.dataset.achKey);
      if (!item) continue;
      if (card.disabled) {
        card.disabled = false;
        card.setAttribute("aria-disabled", "true");
      }
    }
  }

  function rarityLabel(value) {
    return ({ common:"Обычное", rare:"Редкое", epic:"Эпическое", legendary:"Легендарное" })[value] || "Достижение";
  }

  function openAchievementModal(item, card) {
    const backdrop = ensureModal("ny-achievement-modal");
    const modal = backdrop.querySelector(".ny-modal");
    const icon = card?.querySelector(".ach-icon")?.innerHTML || "◇";
    const reward = item.reward > 0 ? "+" + item.reward + " 🐾" : "Коллекционный значок";
    const selected = Boolean(item.selected);
    modal.innerHTML = `
      <div class="ny-modal-head"><div><div class="ny-ach-modal-icon">${icon}</div><div class="ny-modal-title">${esc(item.title)}</div><span class="ny-ach-rarity">${esc(rarityLabel(item.rarity))}</span></div><button type="button" class="ny-modal-close" data-ny-close>×</button></div>
      <div class="ny-modal-sub">${esc(item.description)}</div>
      <div class="ny-ach-condition"><b>Прогресс</b><span>${item.unlocked ? "Выполнено" : `${item.current} / ${item.target}`}</span></div>
      <div class="ny-modal-meta">
        <div><b>Награда</b><span>${esc(reward)}</span></div>
        <div><b>Статус</b><span>${item.unlocked ? "Открыто" : "Закрыто"}</span></div>
      </div>
      ${item.unlocked_at ? `<div class="ny-ach-condition"><b>Дата получения</b><span>${new Date(item.unlocked_at).toLocaleDateString("ru-RU")}</span></div>` : ""}
      ${item.unlocked ? `<button type="button" class="ny-modal-primary" id="ny-ach-badge-action">${selected ? "Снять бейдж" : "Сделать бейджем профиля"}</button>` : ""}
      <button type="button" class="ny-modal-secondary" data-ny-close>Закрыть</button>`;
    modal.querySelector("#ny-ach-badge-action")?.addEventListener("click", async () => {
      const next = selected ? null : item.key;
      const r = await fetch(API + "/api/achievements/badge", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ key: next }),
      });
      if (!r.ok) return;
      tg?.HapticFeedback?.selectionChanged?.();
      closeModal(backdrop);
      await refreshData();
      document.getElementById("adv-profile-button")?.click();
      setTimeout(() => document.getElementById("nyan-achievements-panel")?.scrollIntoView({behavior:"smooth",block:"start"}), 180);
    });
    openModal(backdrop);
  }

  function bindAchievementCapture() {
    document.addEventListener("click", event => {
      const card = event.target.closest(".ach-card");
      if (!card) return;
      const item = achievementItem(card.dataset.achKey);
      if (!item) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      openAchievementModal(item, card);
    }, true);
  }

  function observeDynamicUI() {
    let rewardObserver = null;
    let achievementObserver = null;
    let attachAttempts = 0;

    const attach = () => {
      attachAttempts += 1;

      const rewardList = document.getElementById("reward-list");
      if (rewardList && !rewardObserver) {
        let rewardTimer = null;
        rewardObserver = new MutationObserver(() => {
          clearTimeout(rewardTimer);
          rewardTimer = setTimeout(enhanceRewards, 60);
        });
        rewardObserver.observe(rewardList, { childList:true, subtree:true });
      }

      const achGrid = document.getElementById("ach-grid");
      if (achGrid && !achievementObserver) {
        achievementObserver = new MutationObserver(() => {
          enhanceAchievementCards();
        });
        achievementObserver.observe(achGrid, { childList:true, subtree:false });
      }

      if ((!rewardObserver || !achievementObserver) && attachAttempts < 16) {
        setTimeout(attach, 250);
      }
    };

    attach();

    const balance = document.getElementById("balance");
    if (balance) {
      let balanceTimer = null;
      new MutationObserver(() => {
        clearTimeout(balanceTimer);
        balanceTimer = setTimeout(() => {
          renderHome();
          enhanceRewards();
          renderProfileEnhancements();
        }, 50);
      }).observe(balance, { childList:true, characterData:true, subtree:true });
    }
  }

  function bindRefreshTriggers() {
    document.getElementById("adv-profile-button")?.addEventListener("click", () => {
      setTimeout(async () => {
        const profile = await getJson("/api/profile");
        if (profile) profileData = profile;
        ensureProfileEnhancements();
        renderProfileEnhancements();
        enhanceAchievementCards();
      }, 180);
    });
    document.getElementById("spend-button")?.addEventListener("click", () => {
      setTimeout(async () => {
        const catalog = await getJson("/api/catalog");
        if (catalog) catalogData = catalog;
        enhanceRewards();
      }, 260);
    });
  }

  async function start() {
    ensureHome();
    ensureProfileEnhancements();
    bindAchievementCapture();
    observeDynamicUI();
    bindRefreshTriggers();
    await refreshData();
    enhanceAchievementCards();
    setTimeout(() => {
      ensureHome();
      ensureProfileEnhancements();
      renderProfileEnhancements();
      enhanceRewards();
      enhanceAchievementCards();
    }, 1200);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once:true });
  else start();
})();