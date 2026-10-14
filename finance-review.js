(() => {
  "use strict";
  const API = "https://nyan-wallet-api.onrender.com";
  const tg = window.Telegram?.WebApp;
  const notice = document.getElementById("notice");
  const list = document.getElementById("applications");
  const filter = document.getElementById("filter");
  const refresh = document.getElementById("refresh");
  const ageLabels = {under_16: "до 16 лет", "16_17": "16–17 лет", "18_plus": "18+"};
  const hourLabels = {less_1: "менее часа", "1_2": "1–2 часа", "2_4": "2–4 часа", more_4: "4+ часа"};
  const statusLabels = {pending:"Ожидает проверки",interview:"Собеседование",reserve:"Резерв",rejected:"Отклонена"};
  const questions = [
    ["display_name", "Как обращаться"],
    ["age_group", "Возрастная категория"],
    ["timezone", "Часовой пояс"],
    ["availability", "Время в день"],
    ["experience", "Опыт"],
    ["skills", "Инструменты и навыки"],
    ["motivation", "Почему хочет в команду"],
    ["situation_discrepancy", "Ситуация: расхождение на 50 🐾"],
    ["situation_farm", "Ситуация: подозрительные переводы"],
  ];
  let loading = false;

  tg?.ready?.();
  tg?.expand?.();

  function create(tag, cls, content) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (content !== undefined) el.textContent = String(content);
    return el;
  }
  function headers(json = false) {
    const h = {"X-Telegram-Init-Data": tg?.initData || ""};
    if (json) h["Content-Type"] = "application/json";
    return h;
  }
  async function request(path, method = "GET", body = undefined) {
    const res = await fetch(API + path, {
      method, headers: headers(body !== undefined), cache: "no-store",
      ...(body !== undefined ? {body: JSON.stringify(body)} : {})
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ?
      data.detail : data.detail?.message || "Ошибка сервера");
    return data;
  }
  function answer(label, text) {
    const block = create("div", "answer");
    block.append(create("span", "answer-label", label), create("div", "answer-body", text || "—"));
    return block;
  }
  function renderCard(item) {
    const card = create("article", "candidate");
    const top = create("div", "candidate-head");
    const name = item.username ? "@" + item.username : item.display_name;
    top.append(create("div", "candidate-title", name), create("span", "candidate-num", "№" + item.id));
    card.appendChild(top);
    const line = create("div", "candidate-meta", "ID " + item.telegram_id + " · " +
      new Date(item.created_at).toLocaleString("ru-RU", {day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"}));
    card.append(line, create("span", "candidate-state", statusLabels[item.status] || item.status));

    for (const [key, label] of questions) {
      let value = item[key];
      if (key === "age_group") value = ageLabels[value] || value;
      if (key === "availability") value = hourLabels[value] || value;
      card.appendChild(answer(label, value));
    }
    if (item.owner_note) {
      card.appendChild(create("div", "owner-note", "Комментарий администрации: " + item.owner_note));
    }

    if (item.status !== "rejected") {
      const controls = create("div", "review-form");
      const id = "note-for-" + item.id;
      const label = create("label", "", "Комментарий кандидату (необязательно)");
      label.htmlFor = id;
      const input = create("textarea");
      input.id = id;
      input.maxLength = 400;
      input.placeholder = "Можно добавить комментарий к решению";
      input.value = item.owner_note || "";
      const actions = create("div", "review-actions");
      const choices = [
        ["interview", "На собеседование", "review-interview"],
        ["reserve", "В резерв", "review-reserve"],
        ["rejected", "Отклонить", "review-reject"],
      ];
      for (const [decision, text, cls] of choices) {
        if (decision === item.status) continue;
        const button = create("button", cls, text);
        button.type = "button";
        button.addEventListener("click", async () => {
          if (!window.confirm("Изменить статус анкеты №" + item.id + "?")) return;
          const buttons = actions.querySelectorAll("button");
          buttons.forEach(btn => { btn.disabled = true; });
          notice.textContent = "Сохраняем решение…";
          try {
            await request("/api/owner/recruitment/finance/" + item.id + "/review", "POST", {
              decision, note: input.value.trim() || null
            });
            tg?.HapticFeedback?.notificationOccurred?.("success");
            await load();
          } catch (error) {
            notice.textContent = error?.message || "Не удалось сохранить решение.";
            buttons.forEach(btn => { btn.disabled = false; });
            tg?.HapticFeedback?.notificationOccurred?.("error");
          }
        });
        actions.appendChild(button);
      }
      controls.append(label, input, actions);
      card.appendChild(controls);
    }
    return card;
  }

  async function load() {
    if (loading) return;
    if (!tg?.initData) {
      notice.textContent = "Эта страница работает только внутри Telegram Mini App владельца.";
      return;
    }
    loading = true;
    refresh.disabled = true;
    notice.textContent = "Загружаем анкеты…";
    try {
      const result = await request("/api/owner/recruitment/finance?status=" +
        encodeURIComponent(filter.value));
      const items = Array.isArray(result.applications) ? result.applications : [];
      list.replaceChildren();
      if (!items.length) {
        list.appendChild(create("div", "empty-candidates", "В этом разделе пока нет анкет."));
      } else {
        items.forEach(item => list.appendChild(renderCard(item)));
      }
      notice.textContent = "Найдено: " + items.length + (items.length === 100 ? " · показаны последние 100" : "");
    } catch (error) {
      list.replaceChildren();
      notice.textContent = error?.message || "Не удалось загрузить анкеты.";
    } finally {
      loading = false;
      refresh.disabled = false;
    }
  }
  refresh.addEventListener("click", () => void load());
  filter.addEventListener("change", () => void load());
  void load();
})();
