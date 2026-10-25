(() => {
  "use strict";

  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const feedback = $("feedback");
  const form = $("idea-form");
  const titleInput = $("idea-title");
  const descriptionInput = $("idea-description");
  const sendButton = $("send-button");
  const ownerPanel = $("owner-panel");
  let session = "";
  let busy = false;
  let moderatorBusy = false;
  let activeFilter = "pending";

  tg?.ready?.();
  tg?.expand?.();

  // The Mini App supplies signed initData; independent browsers use a short
  // server-signed session issued only after Telegram Login Widget verification.
  const miniInitData = tg?.initData || "";
  let useMini = Boolean(miniInitData);
  try { session = miniInitData || sessionStorage.getItem("nyan_ideas_browser_auth") || ""; }
  catch (_) { session = miniInitData; }

  function setFeedback(message) { feedback.textContent = message || ""; }
  function show(id) {
    for (const panel of ["auth-panel", "form-panel", "result-panel"]) $(panel).hidden = panel !== id;
  }
  function currentHeader() { return useMini ? miniInitData : (session ? "browser:" + session : ""); }

  async function request(path, method = "GET", body = null, auth = true) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 13000);
    let response, result;
    try {
      response = await fetch(API + path, {
        method,
        headers: {
          ...(body === null ? {} : { "Content-Type": "application/json" }),
          ...(auth ? { "X-Telegram-Init-Data": currentHeader() } : {})
        },
        body: body === null ? undefined : JSON.stringify(body),
        cache: "no-store",
        signal: controller.signal,
      });
      try { result = await response.json(); } catch (_) { result = null; }
    } catch (error) {
      if (controller.signal.aborted) throw Error("Сервер долго не отвечает. Проверь интернет и попробуй ещё раз.");
      throw Error("Нет связи с сервером Nyan Wallet. Попробуй позже.");
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) {
      const problem = typeof result?.detail === "string" ? result.detail : "Не удалось выполнить запрос.";
      const err = Error(problem);
      err.status = response.status;
      throw err;
    }
    return result;
  }

  function buildWidget() {
    window.onNyanIdeasTelegramAuth = async (tgUser) => {
      setFeedback("подтверждаем вход…");
      try {
        const response = await request("/api/interactive-ideas/auth/widget", "POST", tgUser, false);
        session = response.session;
        useMini = false;
        try { sessionStorage.setItem("nyan_ideas_browser_auth", session); } catch (_) {}
        await refreshMine();
      } catch (error) {
        setFeedback(error.message || "Не удалось подтвердить Telegram.");
      }
    };
    const holder = $("telegram-login");
    if (holder.querySelector("script")) return;
    const widget = document.createElement("script");
    widget.src = "https://telegram.org/js/telegram-widget.js?22";
    widget.async = true;
    widget.setAttribute("data-telegram-login", "nyancash_bot");
    widget.setAttribute("data-size", "large");
    widget.setAttribute("data-radius", "12");
    widget.setAttribute("data-userpic", "false");
    widget.setAttribute("data-onauth", "onNyanIdeasTelegramAuth(user)");
    widget.addEventListener("error", () => setFeedback("Не удалось загрузить вход Telegram. Обнови страницу."));
    holder.append(widget);
  }

  function showLogin(message) {
    ownerPanel.hidden = true;
    show("auth-panel");
    buildWidget();
    setFeedback(message || "");
  }

  function setResult(idea) {
    show("result-panel");
    const title = $("result-title");
    const text = $("result-text");
    const label = $("result-label");
    const amount = $("reward-result");
    const note = $("moderator-note");
    const summary = $("idea-summary");
    label.textContent = `заявка №${idea.id}`;
    amount.hidden = true;
    note.hidden = true;
    summary.hidden = false;
    $("idea-summary-title").textContent = idea.title;
    if (idea.status === "pending") {
      title.textContent = "идея отправлена!";
      text.textContent = "твоя задумка уже на модерации. когда решение будет принято, статус обновится здесь. повторно подавать заявку не нужно.";
    } else if (idea.status === "approved") {
      title.textContent = "идея одобрена";
      text.textContent = "спасибо за предложение! награда начислена на баланс Nyan Wallet и появилась в истории операций.";
      amount.hidden = false;
    } else {
      title.textContent = "идея отклонена";
      text.textContent = "владелец рассмотрел заявку и отказал. согласно правилам, повторная отправка недоступна.";
    }
    if (idea.moderator_note) {
      note.hidden = false;
      note.textContent = "комментарий: " + idea.moderator_note;
    }
  }

  async function refreshMine() {
    setFeedback("проверяем заявку…");
    try {
      const data = await request("/api/interactive-ideas/me");
      if (data.idea) setResult(data.idea);
      else show("form-panel");
      ownerPanel.hidden = !data.is_owner;
      if (data.is_owner) await refreshModeration();
      setFeedback("");
    } catch (error) {
      if (error.status === 401 && !miniInitData) {
        session = "";
        try { sessionStorage.removeItem("nyan_ideas_browser_auth"); } catch (_) {}
        showLogin("срок входа истёк. войди снова через Telegram.");
      } else if (error.status === 401) {
        useMini = false;
        session = "";
        showLogin("сессия Telegram устарела. открой страницу заново из Telegram.");
      } else {
        setFeedback(error.message || "Не удалось получить статус заявки.");
      }
    }
  }

  function updateCounters() {
    $("title-count").textContent = `${titleInput.value.length} / 100`;
    $("description-count").textContent = `${descriptionInput.value.length} / 4000`;
  }
  titleInput.addEventListener("input", updateCounters);
  descriptionInput.addEventListener("input", updateCounters);

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || !currentHeader()) return;
    const title = titleInput.value.trim().replace(/\s+/g, " ");
    const description = descriptionInput.value.trim();
    if (title.length < 5 || description.replace(/\s+/g, " ").length < 40) {
      setFeedback("укажи название и подробно опиши интерактив (от 40 символов).");
      return;
    }
    if (!$("one-attempt").checked) {
      setFeedback("подтверди, что понимаешь правило одной заявки.");
      return;
    }
    if (!window.confirm("Отправить идею на модерацию? Это единственная попытка, даже если в итоге будет отказ.")) return;
    busy = true;
    sendButton.disabled = true;
    sendButton.textContent = "отправляем…";
    setFeedback("");
    try {
      const response = await request("/api/interactive-ideas", "POST", { title, description });
      tg?.HapticFeedback?.notificationOccurred?.("success");
      setResult(response.idea);
    } catch (error) {
      // An HTTP timeout can happen after a successful commit. Read server
      // status before exposing another send button to this account.
      if (error.status === 409) {
        await refreshMine();
      } else {
        try {
          const state = await request("/api/interactive-ideas/me");
          if (state.idea) { setResult(state.idea); return; }
        } catch (_) {}
        setFeedback(error.message || "Отправить идею не получилось.");
      }
    } finally {
      busy = false;
      sendButton.disabled = false;
      sendButton.textContent = "отправить на модерацию";
    }
  });

  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  }

  function formatTime(iso) {
    try { return new Date(iso).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Moscow" }) + " МСК"; }
    catch (_) { return ""; }
  }

  function renderModeration(ideas) {
    const container = $("owner-list");
    container.replaceChildren();
    if (!ideas.length) {
      container.append(element("div", "empty-list", "здесь пока нет заявок"));
      return;
    }
    for (const idea of ideas) {
      const card = element("article", "owner-card");
      const meta = element("div", "owner-meta");
      meta.append(element("span", "", `№${idea.id} · ${idea.status}`));
      meta.append(element("time", "", formatTime(idea.created_at)));
      card.append(meta, element("h3", "", idea.title));
      const name = idea.username ? "@" + idea.username : (idea.first_name || "участник");
      card.append(element("div", "author", `${name} · ${idea.telegram_id}`));
      card.append(element("div", "idea-body", idea.description));
      if (idea.moderator_note) card.append(element("div", "moderator-note", "комментарий: " + idea.moderator_note));
      if (idea.status === "pending") {
        const note = element("textarea", "", "");
        note.placeholder = "комментарий автору (необязательно)";
        note.maxLength = 600;
        note.rows = 2;
        const actions = element("div", "owner-actions");
        for (const [decision, text] of [["approve", "одобрить · +500 🐾"], ["reject", "отклонить"]]) {
          const button = element("button", decision === "reject" ? "reject" : "", text);
          button.type = "button";
          button.addEventListener("click", () => review(idea, decision, note.value, actions));
          actions.append(button);
        }
        card.append(note, actions);
      }
      container.append(card);
    }
  }

  async function refreshModeration() {
    if (ownerPanel.hidden) return;
    const container = $("owner-list");
    container.replaceChildren(element("div", "empty-list", "загружаем заявки…"));
    try {
      const data = await request("/api/interactive-ideas/moderation?status=" + encodeURIComponent(activeFilter));
      renderModeration(data.ideas || []);
    } catch (error) {
      container.replaceChildren(element("div", "empty-list", error.message || "Ошибка загрузки"));
    }
  }

  async function review(idea, decision, note, actions) {
    if (moderatorBusy) return;
    const meaning = decision === "approve"
      ? `Одобрить идею №${idea.id} и начислить автору 500 🐾?`
      : `Отклонить идею №${idea.id}? Автор больше не сможет подать другую заявку.`;
    if (!window.confirm(meaning)) return;
    moderatorBusy = true;
    for (const button of actions.querySelectorAll("button")) button.disabled = true;
    try {
      await request(`/api/interactive-ideas/${idea.id}/review`, "POST", { decision, note: note.trim() || null });
      setFeedback(decision === "approve" ? `идея №${idea.id} одобрена, +500 🐾 начислены` : `идея №${idea.id} отклонена`);
      await refreshModeration();
      await refreshMine();
    } catch (error) {
      setFeedback(error.status === 409 ? "эту заявку уже рассмотрели, обновляем список" : error.message);
      await refreshModeration();
    } finally { moderatorBusy = false; }
  }

  document.querySelectorAll(".filter").forEach(button => button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    document.querySelectorAll(".filter").forEach(item => item.classList.toggle("active", item === button));
    refreshModeration();
  }));
  $("owner-refresh").addEventListener("click", refreshModeration);

  if (currentHeader()) refreshMine();
  else showLogin("");
})();
