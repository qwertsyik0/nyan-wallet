(() => {
  "use strict";
  const API = "https://nyan-wallet-api.onrender.com";
  const tg = window.Telegram?.WebApp;
  const form = document.getElementById("apply-form");
  const formArea = document.getElementById("form-area");
  const statusCard = document.getElementById("status-card");
  const note = document.getElementById("form-message");
  const steps = [...document.querySelectorAll(".form-step")];
  const progressFill = document.getElementById("progress-fill");
  const stepCount = document.getElementById("step-count");
  const stepHeading = document.getElementById("step-heading");
  const back = document.getElementById("back");
  const next = document.getElementById("next");
  const submitButton = document.getElementById("submit");
  const titles = ["01. знакомство", "02. опыт и навыки", "03. твои решения"];
  let active = 0;
  let busy = false;
  let alreadySubmitted = false;

  tg?.ready?.();
  tg?.expand?.();

  function headers(json = false) {
    const result = { "X-Telegram-Init-Data": tg?.initData || "" };
    if (json) result["Content-Type"] = "application/json";
    return result;
  }

  async function parse(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof data.detail === "string" ? data.detail :
        (data.detail?.message || "Не удалось выполнить запрос.");
      throw new Error(detail);
    }
    return data;
  }

  function setMessage(value) {
    note.textContent = value || "";
  }

  function showStep(index) {
    active = Math.max(0, Math.min(index, steps.length - 1));
    steps.forEach((section, i) => { section.hidden = i !== active; });
    progressFill.style.width = ((active + 1) / steps.length * 100) + "%";
    stepHeading.textContent = titles[active];
    stepCount.textContent = (active + 1) + " / " + steps.length;
    back.hidden = active === 0;
    next.hidden = active === steps.length - 1;
    submitButton.hidden = active !== steps.length - 1;
    setMessage("");
    window.scrollTo({ top: Math.max(0, formArea.getBoundingClientRect().top + window.scrollY - 16), behavior: "smooth" });
  }

  function validateStep(section) {
    const fields = section.querySelectorAll("input, select, textarea");
    for (const field of fields) {
      field.classList.remove("invalid");
      const value = field.type === "checkbox" ? "" : String(field.value || "").replace(/\s+/g, " ").trim();
      if (!field.checkValidity() ||
          (field.required && field.type !== "checkbox" && !value) ||
          (field.type !== "checkbox" && field.minLength > 0 && value.length < field.minLength)) {
        field.classList.add("invalid");
        setMessage(field.type === "checkbox"
          ? "Подтверди согласие, чтобы отправить анкету."
          : "Заполни обязательные поля. Для развёрнутых ответов нужно несколько предложений.");
        field.focus();
        return false;
      }
    }
    setMessage("");
    return true;
  }

  function lock(locked) {
    busy = locked;
    for (const button of [back, next, submitButton]) button.disabled = locked || alreadySubmitted;
    submitButton.textContent = locked ? "Отправляем…" : "Отправить анкету ↗";
  }

  function statusView(heading, message, state = "info", application = null) {
    formArea.hidden = true;
    statusCard.hidden = false;
    statusCard.replaceChildren();
    const mark = document.createElement("div");
    mark.className = "status-mark";
    mark.textContent = state === "done" ? "✦" : "🐾";
    const title = document.createElement("h2");
    title.textContent = heading;
    const body = document.createElement("p");
    body.textContent = message;
    statusCard.append(mark, title, body);
    if (application?.id) {
      const stamp = document.createElement("span");
      stamp.className = "status-stamp";
      stamp.textContent = "заявка №" + application.id + " · " + new Date(application.created_at).toLocaleDateString("ru-RU");
      statusCard.appendChild(stamp);
    }
  }

  function renderApplication(application) {
    alreadySubmitted = true;
    const messages = {
      pending: ["анкета получена", "Твои ответы сохранены. Сейчас заявка ожидает рассмотрения администрацией.", "done"],
      interview: ["следующий этап", "Анкета рассмотрена: ты приглашён(а) на следующий этап отбора. Следи за сообщениями бота.", "done"],
      reserve: ["ты в резерве", "Кандидатура сохранена в резерве. Если появится возможность, администрация свяжется с тобой.", "done"],
      rejected: ["отбор завершён", "Спасибо за уделённое время. На данный момент администрация не готова продолжить отбор.", "info"],
    };
    const [heading, text, kind] = messages[application.status] || messages.pending;
    const noteText = application.owner_note ? "\n\nКомментарий администрации: " + application.owner_note : "";
    statusView(heading, text + noteText, kind, application);
  }

  next.addEventListener("click", () => {
    if (busy || alreadySubmitted) return;
    if (validateStep(steps[active])) showStep(active + 1);
  });
  back.addEventListener("click", () => { if (!busy && active > 0) showStep(active - 1); });

  form.addEventListener("input", event => {
    if (event.target?.classList) event.target.classList.remove("invalid");
    setMessage("");
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || alreadySubmitted || !tg?.initData) return;
    for (let i = 0; i < steps.length; i++) {
      if (!validateStep(steps[i])) {
        if (i !== active) { showStep(i); validateStep(steps[i]); }
        return;
      }
    }
    const keys = ["display_name", "age_group", "timezone", "availability",
      "experience", "motivation", "skills", "situation_discrepancy", "situation_farm"];
    const payload = {};
    for (const key of keys) payload[key] = document.getElementById(key).value.trim();
    payload.consent = document.getElementById("consent").checked;
    lock(true);
    try {
      const response = await fetch(API + "/api/recruitment/finance/apply", {
        method: "POST", headers: headers(true), body: JSON.stringify(payload),
      });
      const data = await parse(response);
      tg?.HapticFeedback?.notificationOccurred?.("success");
      renderApplication(data.application);
      window.scrollTo({top: 0, behavior: "smooth"});
    } catch (error) {
      if (String(error?.message || "").includes("уже отправлена")) {
        await checkStatus();
      } else {
        setMessage(error?.message || "Не удалось отправить. Проверь соединение и попробуй снова.");
      }
      tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
      lock(false);
    }
  });

  async function checkStatus() {
    if (!tg?.initData) {
      statusView("открой через Telegram",
        "Для подачи анкеты открой эту страницу через кнопку Mini App бота Nyan Wallet.");
      return;
    }
    try {
      const response = await fetch(API + "/api/recruitment/finance/me", {
        headers: headers(), cache: "no-store",
      });
      const data = await parse(response);
      if (data.application) renderApplication(data.application);
      else {
        statusCard.hidden = true;
        formArea.hidden = false;
      }
    } catch (error) {
      formArea.hidden = true;
      statusView("нет связи с сервером", error?.message || "Не удалось загрузить состояние анкеты.");
      const button = document.createElement("button");
      button.className = "status-retry";
      button.type = "button";
      button.textContent = "Попробовать снова";
      button.addEventListener("click", () => void checkStatus());
      statusCard.appendChild(button);
    }
  }

  void checkStatus();
})();
