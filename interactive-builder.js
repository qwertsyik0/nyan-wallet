(() => {
  "use strict";
  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  let auth = tg?.initData || "";
  let isOwner = false;
  let activities = [];
  let selected = null;
  let editId = null;
  let reviewActivityId = null;
  let saving = false;
  let sending = false;

  tg?.ready?.();
  tg?.expand?.();
  if (auth && Number(tg?.initDataUnsafe?.user?.id) === 6289461565) {
    // Presentation hint only; every owner request is signature-checked by API.
    $("studio-owner").hidden = false;
  }
  try { if (!auth) auth = "browser:" + (sessionStorage.getItem("nyan_ideas_browser_auth") || ""); }
  catch (_) {}
  if (auth === "browser:") auth = "";

  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = String(value);
    return node;
  }
  function status(value) { $("studio-global-status").textContent = value || ""; }
  function date(value) {
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime())
      ? parsed.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })
      : "";
  }
  function activityUrl(id) {
    const url = new URL("./interactive-builder.html", location.href);
    url.search = "";
    url.hash = "";
    url.searchParams.set("activity", String(id));
    return url.toString();
  }
  async function api(path, method = "GET", body = null) {
    if (!auth) throw Error("Войди через Telegram");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), method === "GET" ? 16000 : 25000);
    try {
      const response = await fetch(API + path, {
        method,
        headers: {
          "X-Telegram-Init-Data": auth,
          ...(body === null ? {} : { "Content-Type": "application/json" }),
        },
        body: body === null ? undefined : JSON.stringify(body),
        cache: "no-store", signal: controller.signal,
      });
      let data;
      try { data = await response.json(); } catch (_) { data = null; }
      if (!response.ok) throw Error(
        typeof data?.detail === "string" ? data.detail : `HTTP ${response.status}`
      );
      if (!data?.ok) throw Error("Некорректный ответ сервера");
      return data;
    } catch (error) {
      if (controller.signal.aborted) throw Error("Сервер долго отвечает. Попробуй обновить список.");
      throw error;
    } finally { clearTimeout(timer); }
  }

  function optionButton(label, handler, cls = "") {
    const button = el("button", cls, label);
    button.type = "button";
    button.addEventListener("click", handler);
    return button;
  }

  async function loadActivities() {
    if (!auth) {
      $("studio-login").hidden = false;
      status("Для участия нужно войти через Telegram.");
      return;
    }
    status("загружаем интерактивы…");
    try {
      const data = await api("/api/activities");
      activities = data.activities;
      isOwner = Boolean(data.is_owner);
      $("studio-owner").hidden = !isOwner;
      renderActivities();
      status("");
      const requested = new URLSearchParams(location.search).get("activity");
      if (requested && /^\d+$/.test(requested)) {
        await openActivity(Number(requested));
      }
    } catch (error) {
      if (/вход|подпис|Telegram|авторизац/i.test(error.message)) {
        auth = "";
        $("studio-login").hidden = false;
      }
      status("Не удалось получить интерактивы: " + error.message);
      $("studio-list").replaceChildren(el("div", "studio-placeholder", "список недоступен · попробуй обновить"));
    }
  }

  function renderActivities() {
    $("studio-owner-count").textContent = String(activities.length);
    const ownerList = $("studio-owner-list");
    const list = $("studio-list");
    ownerList.replaceChildren();
    list.replaceChildren();
    if (!activities.length) list.append(el("div", "studio-placeholder", "пока нет опубликованных интерактивов"));
    let publicCount = 0;
    for (const item of activities) {
      if (isOwner) ownerList.append(ownerCard(item));
      if (item.status === "published" || (!isOwner && item.my_answer)) {
        publicCount++;
        list.append(participantCard(item));
      }
    }
    if (isOwner && !activities.length) ownerList.append(el("div", "studio-placeholder", "ещё нет интерактивов · создай первый черновик"));
    if (isOwner && !publicCount) list.append(el("div", "studio-placeholder", "опубликованных игр пока нет"));
  }

  function ownerCard(item) {
    const card = el("article", "studio-activity");
    const head = el("div", "studio-activity-head");
    head.append(
      el("span", "studio-label", `№${item.id} · ${item.visibility === "closed" ? "закрытый тест · " : ""}${item.status === "published" && item.starts_at && new Date(item.starts_at) > new Date() ? "запланирован" : ({draft:"черновик",published:"опубликован",closed:"закрыт"}[item.status] || item.status)}`),
      el("span", "studio-reward", `+${item.reward} 🐾`)
    );
    card.append(head, el("h3", "", item.title), el("p", "", item.description),
      el("div", "studio-label", `одобрено: ${item.winner_count} / ${item.max_winners}${item.starts_at ? " · начало " + date(item.starts_at) : ""}`));
    const buttons = el("div", "studio-buttons");
    if (item.status === "draft") {
      buttons.append(optionButton("редактировать", () => editActivity(item)));
      buttons.append(optionButton("опубликовать", () => setStatus(item, "publish"), "primary"));
    }
    if (item.status === "published") {
      buttons.append(optionButton("закрыть", () => setStatus(item, "close")));
      buttons.append(optionButton("открыть", () => openActivity(item.id)));
    }
    if (item.status !== "draft") buttons.append(optionButton("участники и ответы", () => loadReview(item)));
    if (item.status !== "draft") {
      buttons.append(optionButton("скопировать ссылку", () => {
        const link = activityUrl(item.id);
        navigator.clipboard?.writeText(link).then(() => status("ссылка скопирована")).catch(() => status(link));
        if (!navigator.clipboard) status(link);
      }));
    }
    card.append(buttons);
    return card;
  }

  function participantCard(item) {
    const card = el("article", "studio-activity");
    const head = el("div", "studio-activity-head");
    head.append(
      el("span", "studio-label", item.kind === "manual" ? "проверяет владелец" : "автоматическая проверка"),
      el("span", "studio-reward", `+${item.reward} 🐾`)
    );
    card.append(head, el("h3", "", item.title), el("p", "", item.description));
    const button = optionButton(
      item.my_answer ? "посмотреть результат" : "участвовать",
      () => openActivity(item.id), "primary"
    );
    const controls = el("div", "studio-buttons");
    controls.append(button);
    card.append(controls);
    return card;
  }

  function switchKind() {
    const kind = $("studio-kind").value;
    $("studio-choice-fields").hidden = kind !== "choice";
    $("studio-text-field").hidden = kind !== "text";
    $("studio-manual-hint").hidden = kind !== "manual";
  }

  function switchVisibility() {
    const closed = $("studio-visibility").value === "closed";
    $("studio-tester-field").hidden = !closed;
    $("studio-reward").disabled = closed;
    if (closed) $("studio-reward").value = "0";
  }

  function localDateTime(iso) {
    if (!iso) return "";
    const time = new Date(iso);
    return Number.isFinite(time.getTime())
      ? new Date(time.getTime() - time.getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "";
  }

  function resetForm() {
    editId = null;
    $("studio-form").reset();
    $("studio-form-title").textContent = "Новый интерактив";
    $("studio-save").textContent = "сохранить черновик";
    $("studio-cancel-edit").hidden = true;
    $("studio-create-feedback").textContent = "";
    switchKind();
    switchVisibility();
  }
  function editActivity(item) {
    editId = item.id;
    $("studio-title").value = item.title;
    $("studio-description").value = item.description;
    $("studio-prompt").value = item.prompt;
    $("studio-kind").value = item.kind;
    $("studio-choices").value = (item.choices || []).join("\n");
    $("studio-correct-index").value = item.kind === "choice" ? Number(item.correct_answer) + 1 : 1;
    $("studio-correct-text").value = item.kind === "text" ? item.correct_answer || "" : "";
    $("studio-visibility").value = item.visibility || "public";
    $("studio-tester-ids").value = (item.tester_ids || []).join("\n");
    $("studio-reward").value = item.reward;
    $("studio-max-winners").value = item.max_winners;
    $("studio-starts-at").value = localDateTime(item.starts_at);
    $("studio-ends-at").value = localDateTime(item.ends_at);
    $("studio-form-title").textContent = `Редактирование №${item.id}`;
    $("studio-save").textContent = "сохранить изменения";
    $("studio-cancel-edit").hidden = false;
    switchKind();
    switchVisibility();
    $("studio-form").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function saveActivity(event) {
    event.preventDefault();
    if (saving || !isOwner) return;
    const kind = $("studio-kind").value;
    const choices = kind === "choice"
      ? $("studio-choices").value.split("\n").map(value => value.trim()).filter(Boolean)
      : [];
    const correctAnswer = kind === "choice" ? String(Number($("studio-correct-index").value) - 1)
      : kind === "text" ? $("studio-correct-text").value.trim() : null;
    const endValue = $("studio-ends-at").value;
    const startValue = $("studio-starts-at").value;
    const visibility = $("studio-visibility").value;
    const testers = $("studio-tester-ids").value.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean);
    if (visibility === "closed" && (!testers.length || testers.some(s => !/^\d{1,16}$/.test(s)))) {
      $("studio-create-feedback").textContent = "Укажи Telegram ID тестировщиков цифрами.";
      return;
    }
    const payload = {
      title: $("studio-title").value.trim(),
      description: $("studio-description").value.trim(),
      prompt: $("studio-prompt").value.trim(), kind, choices,
      correct_answer: correctAnswer,
      reward: visibility === "closed" ? 0 : Number($("studio-reward").value),
      max_winners: Number($("studio-max-winners").value),
      ends_at: endValue ? new Date(endValue).toISOString() : null,
      starts_at: startValue ? new Date(startValue).toISOString() : null,
      visibility,
      tester_ids: visibility === "closed" ? [...new Set(testers)].map(Number) : [],
    };
    saving = true;
    $("studio-save").disabled = true;
    $("studio-create-feedback").textContent = "сохраняем…";
    try {
      const path = editId ? `/api/owner/activities/${editId}/edit` : "/api/owner/activities";
      await api(path, "POST", payload);
      resetForm();
      await loadActivities();
      $("studio-create-feedback").textContent = "черновик сохранён. Для участия его нужно опубликовать.";
    } catch (error) {
      $("studio-create-feedback").textContent = "Не удалось сохранить: " + error.message;
    } finally {
      saving = false;
      $("studio-save").disabled = false;
    }
  }

  async function setStatus(item, action) {
    if (!confirm(action === "publish"
      ? `Опубликовать «${item.title}»? После публикации параметры и правильный ответ изменить нельзя.`
      : `Закрыть «${item.title}»? Новые ответы больше не принимаются.`)) return;
    try {
      await api(`/api/owner/activities/${item.id}/status`, "POST", { action });
      await loadActivities();
      status(action === "publish" ? "интерактив опубликован" : "интерактив закрыт");
    } catch (error) { status(error.message); }
  }

  async function openActivity(id) {
    try {
      const data = await api(`/api/activities/${id}`);
      selected = data.activity;
      $("studio-play").hidden = false;
      $("studio-play-title").textContent = selected.title;
      $("studio-play-description").textContent = selected.description;
      $("studio-play-reward").textContent = `+${selected.reward} 🐾`;
      $("studio-play-question").textContent = selected.prompt;
      const answers = $("studio-answer-input");
      answers.replaceChildren();
      const result = $("studio-play-result");
      result.hidden = true;
      const form = $("studio-answer-form");
      const notStarted = selected.starts_at && new Date(selected.starts_at) > new Date();
      form.hidden = Boolean(selected.my_answer || selected.status !== "published" || notStarted);
      if (selected.my_answer) {
        result.hidden = false;
        result.textContent = {
          pending: "Ответ отправлен на модерацию. Когда владелец примет решение, статус обновится здесь.",
          approved: `Готово! Награда +${selected.my_answer.reward_amount} 🐾 начислена на кошелёк.`,
          rejected: "Ответ не принят. Повторная попытка в этом интерактиве недоступна.",
        }[selected.my_answer.status] || "Ответ сохранён.";
      } else if (notStarted) {
        result.hidden = false;
        result.textContent = "Интерактив начнётся " + date(selected.starts_at) + ".";
      } else if (selected.status !== "published") {
        result.hidden = false;
        result.textContent = "Интерактив закрыт.";
      } else if (selected.kind === "choice") {
        const options = el("div", "studio-options");
        selected.choices.forEach((choice, index) => {
          const label = el("label", "studio-option");
          const input = el("input");
          input.type = "radio";
          input.name = "nyan-studio-choice";
          input.value = String(index);
          input.required = true;
          label.append(input, el("span", "", choice));
          options.append(label);
        });
        answers.append(options);
      } else {
        const input = el("textarea");
        input.id = "studio-user-answer";
        input.required = true;
        input.maxLength = 3000;
        input.rows = selected.kind === "manual" ? 6 : 2;
        input.placeholder = selected.kind === "manual" ? "Опиши, как ты выполнил задание…" : "Напиши ответ…";
        answers.append(input);
      }
      $("studio-play").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) { status("Не удалось открыть интерактив: " + error.message); }
  }

  async function sendAnswer(event) {
    event.preventDefault();
    if (sending || !selected || selected.my_answer) return;
    let answer = "";
    if (selected.kind === "choice") {
      answer = document.querySelector('input[name="nyan-studio-choice"]:checked')?.value ?? "";
    } else {
      answer = $("studio-user-answer")?.value.trim() || "";
    }
    if (!answer) { status("сначала выбери или напиши ответ"); return; }
    if (!confirm("Отправить ответ? Повторной попытки не будет.")) return;
    sending = true;
    $("studio-send").disabled = true;
    status("отправляем ответ…");
    try {
      await api(`/api/activities/${selected.id}/answer`, "POST", { answer });
      tg?.HapticFeedback?.notificationOccurred?.("success");
    } catch (error) {
      // A timed-out POST may have been committed. Refresh verified state;
      // never automatically repeat a potentially rewarding operation.
      status(error.message);
    } finally {
      sending = false;
      $("studio-send").disabled = false;
      await openActivity(selected.id);
      await loadActivities();
    }
  }

  async function loadReview(item, beforeId = null) {
    reviewActivityId = item.id;
    $("studio-review").hidden = false;
    $("studio-review-title").textContent = `Участники · ${item.title}`;
    const list = $("studio-review-list");
    if (!beforeId) list.replaceChildren(el("div", "studio-placeholder", "загружаем ответы…"));
    else list.querySelector(".studio-more-answers")?.remove();
    try {
      const params = beforeId ? `?limit=80&before_id=${encodeURIComponent(beforeId)}` : "?limit=80";
      const data = await api(`/api/owner/activities/${item.id}/answers${params}`);
      if (reviewActivityId !== item.id) return;
      if (!beforeId) list.replaceChildren();
      if (!data.answers.length && !beforeId) list.append(el("div", "studio-placeholder", "пока никто не участвовал"));
      for (const response of data.answers) {
        const row = el("div", "studio-respondent");
        row.append(
          el("strong", "", response.username ? "@" + response.username : response.first_name),
          el("small", "", `ID ${response.telegram_id} · ${date(response.created_at)} · ${{pending:"ожидает",approved:"одобрено",rejected:"отказ"}[response.status] || response.status}`),
          el("p", "", response.answer)
        );
        if (response.status === "pending" && item.kind === "manual") {
          const buttons = el("div", "studio-buttons");
          buttons.append(
            optionButton("одобрить", () => review(item.id, response.id, "approve"), "primary"),
            optionButton("отказать", () => review(item.id, response.id, "reject"))
          );
          row.append(buttons);
        }
        list.append(row);
      }
      if (data.next_cursor) {
        const next = optionButton("показать ещё участников", () => loadReview(item, data.next_cursor), "studio-more-answers");
        list.append(next);
      }
      $("studio-review").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      list.replaceChildren(el("div", "studio-placeholder", error.message));
    }
  }

  async function review(activityId, answerId, decision) {
    if (!confirm(decision === "approve" ? "Одобрить и начислить награду?" : "Отклонить ответ без начисления?")) return;
    try {
      await api(`/api/owner/activities/${activityId}/answers/${answerId}/review`, "POST", { decision });
      await loadActivities();
      const item = activities.find(activity => activity.id === activityId);
      if (item) await loadReview(item);
    } catch (error) { status(error.message); }
  }

  $("studio-kind").addEventListener("change", switchKind);
  $("studio-visibility").addEventListener("change", switchVisibility);
  $("studio-form").addEventListener("submit", saveActivity);
  $("studio-cancel-edit").addEventListener("click", resetForm);
  $("studio-reload").addEventListener("click", loadActivities);
  $("studio-review-close").addEventListener("click", () => { $("studio-review").hidden = true; reviewActivityId = null; });
  $("studio-answer-form").addEventListener("submit", sendAnswer);
  $("studio-back").addEventListener("click", () => {
    $("studio-play").hidden = true;
    history.replaceState(null, "", "./interactive-builder.html");
  });

  switchKind();
  switchVisibility();
  if (auth) void loadActivities();
  else {
    $("studio-login").hidden = false;
    $("studio-list").replaceChildren(el("div", "studio-placeholder", "Войди через Telegram, чтобы увидеть интерактивы"));
  }
  // Scheduled games become visible automatically while the Studio tab is open.
  window.setInterval(() => {
    if (auth && !document.hidden && $("studio-play").hidden && !saving && !sending && !document.activeElement?.closest("form")) {
      void loadActivities();
    }
  }, 60_000);
})();
