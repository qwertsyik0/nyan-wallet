(() => {
  "use strict";
  const API = "https://nyan-wallet-api.onrender.com";
  const tg = window.Telegram?.WebApp || null;
  const $ = id => document.getElementById(id);
  const LABEL = {
    grant: "Начисление", debit: "Списание", investigate: "Проверка операции",
    pending: "На рассмотрении", approved: "Одобрено", rejected: "Отклонено"
  };
  let role = "user";
  let requestToken = "";
  let busy = false;

  function notify(message, error = false) {
    const node = $("fw-notice");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("error", !!error);
  }
  function create(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function prettyTime(iso) {
    try { return new Date(iso).toLocaleString("ru-RU", {
      day:"2-digit", month:"2-digit", year:"numeric",
      hour:"2-digit", minute:"2-digit"
    }); } catch (_) { return "—"; }
  }
  function requestId() {
    if (typeof crypto?.randomUUID === "function") {
      return crypto.randomUUID().replaceAll("-", "");
    }
    const random = new Uint8Array(16);
    if (typeof crypto?.getRandomValues === "function") crypto.getRandomValues(random);
    else throw new Error("Не удалось сформировать безопасный идентификатор заявки");
    return [...random].map(v => v.toString(16).padStart(2, "0")).join("");
  }
  function preservedLink(relative) {
    const url = new URL(relative, window.location.href);
    if (location.hash) url.hash = location.hash;
    return url.toString();
  }
  async function call(path, method = "GET", payload) {
    if (!tg?.initData) throw new Error("Откройте панель через бота Nyan Wallet в Telegram");
    const options = {
      method, cache: "no-store",
      headers: { "X-Telegram-Init-Data": tg.initData }
    };
    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    options.signal = controller.signal;
    let response;
    try { response = await fetch(API + path, options); }
    catch (error) {
      if (error?.name === "AbortError") throw new Error("Сервер долго отвечает, проверьте историю заявок перед повторной отправкой");
      throw error;
    } finally { clearTimeout(timeout); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : "Ошибка запроса, код " + response.status);
    }
    return data;
  }
  function emptyList(element, text) {
    element.replaceChildren(create("div", "fw-card-meta", text));
  }
  function cardHeading(item, showTrainee = false) {
    const card = create("article", "fw-card");
    const head = create("div", "fw-card-head");
    const main = create("div");
    main.append(
      create("div", "fw-card-title", "№" + item.id + " · " + (LABEL[item.action] || item.action) +
        (item.action === "investigate" ? "" : " · " + item.amount + " 🐾")),
      create("div", "fw-card-meta",
        (item.action === "investigate" ? "Объект проверки: " : "Кошелёк: ") + item.target_label +
        (item.target_id !== null && item.target_id !== undefined ? " · ID " + item.target_id : "")),
      create("div", "fw-card-meta", prettyTime(item.created_at))
    );
    if (showTrainee) main.append(create("div", "fw-card-meta",
      "Стажёр: " + item.trainee_label + " · ID " + item.trainee_id));
    head.append(main, create("span", "fw-status " + item.status, LABEL[item.status] || item.status));
    card.appendChild(head);
    card.appendChild(create("div", "fw-card-reason", "Основание: " + item.reason));
    if (item.evidence) card.appendChild(create("div", "fw-card-meta", "Подтверждения: " + item.evidence));
    if (item.owner_note) card.appendChild(create("div", "fw-card-meta", "Решение владельца: " + item.owner_note));
    if (item.transaction_id) card.appendChild(create("div", "fw-card-meta", "Транзакция №" + item.transaction_id));
    return card;
  }
  async function refreshMine() {
    const list = $("fw-my-list");
    emptyList(list, "Загружаем заявки…");
    try {
      const data = await call("/api/finance/workspace/requests");
      list.replaceChildren();
      if (!data.requests.length) return emptyList(list, "Заявок пока нет");
      for (const item of data.requests) list.appendChild(cardHeading(item));
    } catch (error) {
      emptyList(list, error.message || "Не удалось получить список заявок");
    }
  }
  function syncAction() {
    const investigate = $("fw-action").value === "investigate";
    $("fw-amount-group").hidden = investigate;
    $("fw-amount").required = !investigate;
    $("fw-target").required = !investigate;
    $("fw-target-label").textContent = investigate
      ? "Кошелёк, номер перевода или объект проверки (необязательно)"
      : "Получатель / участник";
    $("fw-target").placeholder = investigate
      ? "Например, TX-101, Telegram ID или @username"
      : "@username или Telegram ID";
    $("fw-target-hint").textContent = investigate
      ? "Укажите номер транзакции или аккаунт, если известен. Можно оставить поле пустым и описать ситуацию ниже"
      : "Для начисления и списания пользователь должен иметь кошелёк Nyan Wallet";
    if (investigate) $("fw-amount").value = "0";
    else if ($("fw-amount").value === "0") $("fw-amount").value = "";
  }
  async function submit(event) {
    event.preventDefault();
    if (busy || role !== "trainee") return;
    const form = $("fw-form");
    if (!form.reportValidity()) return;
    const action = $("fw-action").value;
    const amount = action === "investigate" ? 0 : Number($("fw-amount").value);
    if (action !== "investigate" && (!Number.isSafeInteger(amount) || amount < 1 || amount > 100000)) {
      return notify("Укажите целое число от 1 до 100000", true);
    }
    const target = $("fw-target").value.trim();
    const reason = $("fw-reason").value.trim().replace(/\s+/g, " ");
    const evidence = $("fw-evidence").value.trim().replace(/\s+/g, " ") || null;
    if (reason.length < 10) return notify("Основание должно содержать минимум 10 символов", true);
    if (!window.confirm(
      "Отправить заявку на проверку?\n" +
      (LABEL[action] || action) + (action === "investigate" ? "" : " · " + amount + " 🐾") +
      "\nПользователь: " + target +
      "\n\nБаланс не изменится, пока владелец не одобрит операцию"
    )) return;
    busy = true;
    $("fw-send").disabled = true;
    notify("Отправляем заявку владельцу…");
    try {
      if (!requestToken) requestToken = requestId();
      const result = await call("/api/finance/workspace/requests", "POST", {
        action, amount, target, reason, evidence, request_token: requestToken
      });
      requestToken = "";
      notify(result.already_submitted
        ? "Заявка уже была отправлена, повторной заявки не создано"
        : "Заявка №" + result.request.id + " отправлена владельцу, ожидайте проверки");
      form.reset();
      syncAction();
      await refreshMine();
      tg?.HapticFeedback?.notificationOccurred?.("success");
    } catch (error) {
      notify(error.message || "Не удалось отправить заявку", true);
      tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
      busy = false;
      $("fw-send").disabled = false;
    }
  }
  async function decide(item, decision, note, buttons) {
    if (busy) return;
    const actionName = decision === "approve" ? "ОДОБРИТЬ" : "ОТКЛОНИТЬ";
    if (decision === "reject" && !note.trim()) return notify("Для отказа укажите причину", true);
    const statement = item.action === "investigate" ?
      "Подтверждение только зафиксирует решение без изменения баланса" :
      "При одобрении баланс пользователя будет изменён на " + item.amount + " 🐾";
    if (!window.confirm(
      actionName + " заявку №" + item.id + "?\n" +
      (LABEL[item.action] || item.action) +
      "\nПолучатель: " + item.target_label +
      "\n" + statement
    )) return;
    busy = true;
    buttons.forEach(button => { button.disabled = true; });
    notify("Сохраняем решение владельца…");
    try {
      const result = await call(
        "/api/owner/finance/requests/" + item.id + "/decision",
        "POST", { decision, note: note.trim() || null }
      );
      notify(decision === "approve"
        ? (result.request.transaction_id
          ? "Заявка №" + item.id + " одобрена, транзакция №" + result.request.transaction_id + " проведена. Уведомление получателю отправляется отдельно"
          : "Проверка по заявке №" + item.id + " согласована без изменения баланса")
        : "Заявка №" + item.id + " отклонена");
      await refreshOwner();
      tg?.HapticFeedback?.notificationOccurred?.("success");
    } catch (error) {
      notify(error.message || "Не удалось рассмотреть заявку", true);
      buttons.forEach(button => { button.disabled = false; });
    } finally {
      busy = false;
    }
  }
  function ownerCard(item) {
    const card = cardHeading(item, true);
    if (item.status !== "pending") return card;
    const label = create("label", "fw-review-note", "Комментарий владельца (при отказе обязателен)");
    const note = create("textarea");
    note.maxLength = 400;
    note.rows = 2;
    note.placeholder = "Причина решения или замечание стажёру";
    label.appendChild(note);
    const actions = create("div", "fw-card-actions");
    const yes = create("button", "fw-approve", item.action === "investigate" ? "Согласовать проверку" : "Одобрить и провести");
    const no = create("button", "fw-reject", "Отклонить");
    yes.type = no.type = "button";
    actions.append(yes, no);
    yes.addEventListener("click", () => decide(item, "approve", note.value, [yes, no]));
    no.addEventListener("click", () => decide(item, "reject", note.value, [yes, no]));
    card.append(label, actions);
    return card;
  }
  async function refreshOwner() {
    const list = $("fw-owner-list");
    emptyList(list, "Загружаем заявки…");
    try {
      const status = $("fw-filter").value;
      const data = await call("/api/owner/finance/requests?status=" + encodeURIComponent(status));
      list.replaceChildren();
      if (!data.requests.length) return emptyList(list, "Заявок с этим статусом нет");
      for (const item of data.requests) list.appendChild(ownerCard(item));
    } catch (error) { emptyList(list, error.message || "Не удалось получить заявки"); }
  }
  async function revoke(item, button) {
    if (!window.confirm("Отозвать права стажёра " + item.name + "?\nОн больше не сможет отправлять заявки")) return;
    button.disabled = true;
    try {
      await call("/api/owner/finance/trainees/" + item.telegram_id + "/revoke", "POST", {});
      notify("Доступ стажёра " + item.name + " отозван");
      await refreshStaff();
    } catch (error) {
      notify(error.message || "Не удалось отозвать доступ", true);
      button.disabled = false;
    }
  }
  async function refreshStaff() {
    const list = $("fw-staff-list");
    emptyList(list, "Загружаем стажёров…");
    try {
      const data = await call("/api/owner/finance/trainees");
      list.replaceChildren();
      if (!data.trainees.length) return emptyList(list, "Стажёров пока нет. Назначьте кандидата в разделе анкет");
      for (const item of data.trainees) {
        const card = create("article", "fw-card");
        const head = create("div", "fw-card-head");
        head.append(create("div", "fw-card-title", item.name),
          create("span", "fw-status " + (item.active ? "approved" : "rejected"), item.active ? "Активен" : "Отключён"));
        card.append(
          head,
          create("div", "fw-card-meta", "Telegram ID: " + item.telegram_id),
          create("div", "fw-card-meta", "Назначен: " + prettyTime(item.granted_at))
        );
        if (item.active) {
          const button = create("button", "fw-small-button", "Отозвать доступ");
          button.type = "button";
          button.addEventListener("click", () => revoke(item, button));
          card.append(button);
        }
        list.appendChild(card);
      }
    } catch (error) { emptyList(list, error.message || "Не удалось загрузить стажёров"); }
  }
  async function start() {
    $("fw-back").href = preservedLink("./index.html");
    $("fw-candidates-link").href = preservedLink("./finance-review.html");
    $("fw-form").addEventListener("submit", submit);
    $("fw-action").addEventListener("change", () => { requestToken = ""; syncAction(); });
    for (const id of ["fw-target", "fw-amount", "fw-reason", "fw-evidence"]) {
      $(id).addEventListener("input", () => { requestToken = ""; });
    }
    $("fw-my-refresh").addEventListener("click", refreshMine);
    $("fw-owner-refresh").addEventListener("click", refreshOwner);
    $("fw-staff-refresh").addEventListener("click", refreshStaff);
    $("fw-filter").addEventListener("change", refreshOwner);
    syncAction();
    tg?.ready?.();
    tg?.expand?.();
    try {
      const data = await call("/api/finance/workspace/access");
      role = data.role;
      if (role === "owner") {
        $("fw-role-name").textContent = "Панель владельца";
        $("fw-intro").textContent = "Просматривай предложения стажёров, подтверждай или отклоняй операции и управляй доступом";
        $("fw-owner-section").hidden = false;
        $("fw-staff-section").hidden = false;
        notify("");
        await Promise.all([refreshOwner(), refreshStaff()]);
      } else if (role === "trainee") {
        $("fw-role-name").textContent = "Стажировка · Nyan Wallet";
        $("fw-intro").textContent = "Ты готовишь финансовые заявки и передаёшь их владельцу. Без его решения никаких изменений в кошельках не происходит";
        $("fw-trainee-section").hidden = false;
        $("fw-my-section").hidden = false;
        notify("");
        await refreshMine();
      } else {
        $("fw-role-name").textContent = "Доступ ограничен";
        $("fw-intro").textContent = "Раздел доступен только назначенным стажёрам и владельцу";
        notify("Для получения доступа владелец должен назначить тебя стажёром через список кандидатов");
      }
    } catch (error) { notify(error.message || "Не удалось проверить права", true); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
