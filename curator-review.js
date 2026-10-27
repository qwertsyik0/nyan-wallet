(() => {
  "use strict";
  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const label = {pending:"Ожидает проверки",interview:"Собеседование",rejected:"Отказано"};
  const questionLabels = [
    ["experience","04. Опыт управления"],
    ["admin_control","05. Организация администрации"],
    ["pr_control","06. Контроль пиара"],
    ["payroll","07. Зарплаты в ⭐ и рублях"],
    ["friend_violation","08. Нарушения друга"],
    ["fake_pr_reports","09. Поддельные отчёты"],
    ["staff_conflict","10. Конфликт администрации"],
    ["overpayment","11. Ошибка при выплате звёзд"],
    ["owner_absent","12. Отсутствие владельца"],
    ["blackmail","13. Шантаж сотрудника"],
    ["owner_disagreement","14. Несогласие с владельцем"],
    ["motivation","15. Почему доверить управление"],
  ];
  const list = $("application-list");
  let loading = false;

  tg?.ready?.();
  tg?.expand?.();

  function el(tag, cls, content) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (content !== undefined) node.textContent = String(content);
    return node;
  }
  function status(message) { $("review-status").textContent = message; }
  async function request(path, body) {
    const response = await fetch(API + path, {
      method: body === undefined ? "GET" : "POST",
      cache: "no-store",
      headers: {"X-Telegram-Init-Data":tg?.initData || "", ...(body === undefined ? {} : {"Content-Type":"application/json"})},
      ...(body === undefined ? {} : {body:JSON.stringify(body)}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Ошибка связи с сервером");
    return data;
  }
  function fieldValue(labelText, value) {
    const section = el("div","answer-item");
    section.append(el("strong","",labelText),el("p","",value || "—"));
    return section;
  }
  function renderDetails(item) {
    const content = el("div", "answers-panel");
    content.append(
      fieldValue("01. Как обращаться", item.display_name),
      fieldValue("02. Возраст", item.age),
      fieldValue("03. Время и часовой пояс", `${item.availability} · ${item.timezone}`),
    );
    for (const [key, title] of questionLabels) content.appendChild(fieldValue(title, item.answers?.[key]));
    if (item.status !== "pending") {
      content.appendChild(el("div", "internal-note", `Оценка: ${item.owner_score ?? "—"}/100\nЛичная заметка: ${item.owner_note || "—"}\nКандидату: ${item.candidate_note || "—"}`));
      return content;
    }
    const form = el("div", "review-form");
    const scoreLabel = el("label", "", "Оценка кандидата (0–100)");
    const score = el("input");
    score.type = "number"; score.min = "0"; score.max = "100"; score.step = "1"; score.placeholder = "Например: 82"; score.required = true;
    scoreLabel.appendChild(score);
    const privateLabel = el("label", "", "Заметка для себя (кандидат не увидит)");
    const privateNote = el("textarea"); privateNote.maxLength = 1500; privateNote.placeholder = "Комментарий к проверке";
    privateLabel.appendChild(privateNote);
    const publicLabel = el("label", "", "Комментарий кандидату (необязательно)");
    const publicNote = el("textarea"); publicNote.maxLength = 500; publicNote.placeholder = "Пояснение решения";
    publicLabel.appendChild(publicNote);
    const actions = el("div", "review-actions");
    async function decide(decision) {
      const value = Number(score.value);
      if (score.value.trim() === "" || !Number.isInteger(value) || value < 0 || value > 100) {
        status("Сначала укажи оценку от 0 до 100 баллов."); score.focus(); return;
      }
      const word = decision === "interview" ? "пригласить на собеседование" : "отказать";
      const question = `Точно ${word} кандидату №${item.id}? Решение окончательное.`;
      const confirmed = tg?.showConfirm ? await new Promise(resolve => tg.showConfirm(question, resolve)) : window.confirm(question);
      if (!confirmed) return;
      for (const button of actions.querySelectorAll("button")) button.disabled = true;
      status("Сохраняем решение…");
      try {
        await request(`/api/owner/recruitment/curator/${item.id}/review`, {
          decision, score:value, owner_note:privateNote.value.trim() || null,
          candidate_note:publicNote.value.trim() || null,
        });
        tg?.HapticFeedback?.notificationOccurred?.("success");
        await load();
      } catch (error) {
        status(error?.message || "Не удалось сохранить решение");
        for (const button of actions.querySelectorAll("button")) button.disabled = false;
      }
    }
    for (const [decision, caption, cls] of [["interview","Пригласить","accept"],["rejected","Отказать","reject"]]) {
      const button = el("button",cls,caption);
      button.type = "button";
      button.addEventListener("click", () => void decide(decision));
      actions.appendChild(button);
    }
    form.append(scoreLabel,privateLabel,publicLabel,actions);
    content.appendChild(form);
    return content;
  }
  function renderCard(item) {
    const card = el("article", "application-card");
    const head = el("div", "app-head");
    head.append(el("h3", "", item.username ? "@" + item.username : item.display_name),el("span","app-num","№"+item.id));
    card.appendChild(head);
    const date = new Date(item.created_at).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"});
    card.appendChild(el("p","app-sub",`Telegram ID: ${item.telegram_id} · ${date}`));
    card.appendChild(el("span","status-label "+item.status,label[item.status] || item.status));
    const open = el("button", "secondary open-button", "Посмотреть ответы ↓");
    open.type = "button";
    let details = null;
    open.addEventListener("click", async () => {
      if (details) {details.remove();details=null;open.textContent="Посмотреть ответы ↓";return;}
      open.disabled=true;open.textContent="Загружаем…";
      try {
        const data = await request(`/api/owner/recruitment/curator/${item.id}`);
        details = renderDetails(data.application);
        card.appendChild(details);
        open.textContent="Свернуть ответы ↑";
      } catch (error) { status(error?.message || "Не удалось загрузить анкету");open.textContent="Повторить просмотр"; }
      finally {open.disabled=false;}
    });
    card.appendChild(open);
    return card;
  }
  async function load() {
    if (loading) return;
    if (!tg?.initData) { status("Открой панель через Telegram Mini App бота Nyan Wallet.");return; }
    loading=true; $("refresh").disabled=true;status("Загружаем анкеты…");
    try {
      const data = await request("/api/owner/recruitment/curator?status="+encodeURIComponent($("status-filter").value));
      list.replaceChildren();
      if (!data.applications?.length) list.appendChild(el("div","review-empty","В этой категории пока нет анкет."));
      else for (const item of data.applications) list.appendChild(renderCard(item));
      status(`Найдено: ${data.applications.length}`+(data.applications.length===200?" · показаны последние 200":""));
    } catch (error) { list.replaceChildren();status(error?.message || "Нет связи с сервером"); }
    finally { loading=false;$("refresh").disabled=false; }
  }

  $("refresh").addEventListener("click",()=>void load());
  $("status-filter").addEventListener("change",()=>void load());
  void load();
})();
