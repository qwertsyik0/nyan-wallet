(() => {
  "use strict";

  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const sections = [...document.querySelectorAll(".step")];
  const titles = ["01. Знакомство", "02. Опыт и управление", "03. Практические ситуации", "04. Решения и ответственность"];
  const questions = [
    ["experience", "04. Был ли у тебя опыт управления Telegram-проектами или администрацией? Расскажи подробно", "management"],
    ["admin_control", "05. Как организуешь работу администрации, чтобы каждый выполнял обязанности?", "management"],
    ["pr_control", "06. Как будешь контролировать пиарщиков и проверять достоверность их отчётов?", "management"],
    ["payroll", "07. Как организуешь зарплаты в Telegram Stars и рублях без ошибок и повторных выплат?", "management"],
    ["friend_violation", "08. Близкий друг в администрации регулярно нарушает правила. Что предпримешь?", "situations-a"],
    ["fake_pr_reports", "09. Пиарщик подделал отчёты и требует оплату. Опиши свои действия", "situations-a"],
    ["staff_conflict", "10. Два администратора конфликтуют и отказываются работать вместе. Как решишь ситуацию?", "situations-a"],
    ["overpayment", "11. Ты по ошибке выплатил(а) сотруднику слишком много звёзд. Как исправишь ситуацию?", "situations-a"],
    ["owner_absent", "12. Владелец отсутствует несколько дней, появились жалобы покупателей, конфликты и вопросы по зарплатам. Что будешь решать первым и почему?", "situations-b"],
    ["blackmail", "13. Администратор использует свои полномочия ради выгоды и угрожает репутации проекта при увольнении. Что сделаешь?", "situations-b"],
    ["owner_disagreement", "14. Владелец принимает решение, которое ты считаешь ошибочным. Как поступишь?", "situations-b"],
    ["motivation", "15. Почему тебе можно доверить управление Nyan Shop? Что изменишь в первую очередь?", "situations-b"],
  ];
  let active = 0, busy = false, sent = false;
  let draftKey = "nyan_curator_draft";

  tg?.ready?.();
  tg?.expand?.();

  function show(id) {
    for (const section of ["loading", "warning", "form-panel", "result"]) $(section).hidden = section !== id;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function setError(message) { $("form-error").textContent = message || ""; }
  function text(tag, className, content) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    el.textContent = content;
    return el;
  }
  function makeQuestions() {
    for (const [key, label, group] of questions) {
      const field = text("label", "field", "");
      field.appendChild(text("span", "", label));
      const area = document.createElement("textarea");
      area.id = key;
      area.required = true;
      area.minLength = 40;
      area.maxLength = 1800;
      area.rows = 5;
      area.placeholder = "Твой подробный ответ (от 40 символов)…";
      field.appendChild(area);
      $("questions-" + group).appendChild(field);
    }
  }
  function saveDraft() {
    if (sent) return;
    const fields = ["display_name", "age", "timezone", "availability", ...questions.map(item => item[0])];
    const values = Object.fromEntries(fields.map(key => [key, $(key).value]));
    try { localStorage.setItem(draftKey, JSON.stringify(values)); } catch (_) {}
  }
  function restoreDraft() {
    try {
      const values = JSON.parse(localStorage.getItem(draftKey) || "{}");
      for (const [key, value] of Object.entries(values)) if ($(key) && typeof value === "string") $(key).value = value;
    } catch (_) {}
  }
  function clearDraft() { try { localStorage.removeItem(draftKey); } catch (_) {} }

  function setStep(index) {
    active = Math.min(sections.length - 1, Math.max(0, index));
    sections.forEach((section, i) => section.hidden = i !== active);
    $("step-title").textContent = titles[active];
    $("step-counter").textContent = `${active + 1} / ${sections.length}`;
    $("progress-bar").style.width = `${(active + 1) / sections.length * 100}%`;
    $("prev-step").hidden = active === 0;
    $("next-step").hidden = active === sections.length - 1;
    $("submit-form").hidden = active !== sections.length - 1;
    setError("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function validate(index) {
    for (const input of sections[index].querySelectorAll("input,textarea")) {
      const cleaned = input.type === "checkbox" ? "" : String(input.value || "").replace(/\s+/g, " ").trim();
      const tooShort = input.type !== "checkbox" && input.minLength > 0 && cleaned.length < input.minLength;
      if (!input.checkValidity() || (input.required && !cleaned && input.type !== "checkbox") || tooShort) {
        input.classList.add("invalid");
        setError(input.type === "checkbox" ? "Подтверди согласие с условиями." : "Заполни все поля. Ответы на ситуации должны быть развёрнутыми (от 40 символов).");
        input.focus();
        return false;
      }
      input.classList.remove("invalid");
    }
    return true;
  }
  function lock(value) {
    busy = value;
    for (const id of ["prev-step", "next-step", "submit-form"]) $(id).disabled = value;
    $("submit-form").textContent = value ? "Отправляем…" : "Отправить анкету ↗";
  }
  async function request(path, payload) {
    const response = await fetch(API + path, {
      method: payload ? "POST" : "GET",
      cache: "no-store",
      headers: { "X-Telegram-Init-Data": tg?.initData || "", ...(payload ? { "Content-Type": "application/json" } : {}) },
      ...(payload ? { body: JSON.stringify(payload) } : {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Сервер временно недоступен");
    return data;
  }
  function result(heading, description, row = null, retry = false) {
    const container = $("result");
    container.replaceChildren(text("div", "status-icon", "🐾"), text("h2", "", heading), text("p", "", description));
    if (row?.id) container.appendChild(text("span", "status-pill", `заявка №${row.id}`));
    if (retry) {
      const button = text("button", "primary", "Повторить подключение");
      button.type = "button";
      button.addEventListener("click", () => void checkStatus());
      container.appendChild(button);
    }
    show("result");
  }
  function showApplication(row) {
    sent = true;
    clearDraft();
    const states = {
      pending: ["Анкета отправлена", "Твои ответы сохранены. Заявка ожидает личного рассмотрения владельцем Nyan Shop."],
      interview: ["Приглашение на собеседование", "Твоя анкета прошла отбор. Владелец свяжется с тобой по поводу следующего этапа."],
      rejected: ["Отбор завершён", "В этот раз твоя кандидатура не прошла отбор. Повторная подача анкеты недоступна."],
    };
    const [heading, body] = states[row.status] || states.pending;
    result(heading, body + (row.candidate_note ? "\n\nКомментарий: " + row.candidate_note : ""), row);
  }
  async function checkStatus() {
    show("loading");
    if (!tg?.initData) {
      result("Открой через Telegram", "Эта анкета работает только через мини-приложение бота Nyan Wallet.");
      const link = text("a", "launch-link", "Открыть анкету в Telegram ↗");
      link.href = "https://t.me/nyancash_bot?startapp=curator_apply";
      $("result").appendChild(link);
      return;
    }
    try {
      const { application } = await request("/api/recruitment/curator/me");
      if (application) showApplication(application);
      else show("warning");
    } catch (error) {
      result("Не удалось открыть анкету", error?.message || "Проверь подключение и попробуй снова.", null, true);
    }
  }
  function confirmSubmit() {
    const prompt = "Отправить анкету владельцу? После отправки изменить ответы или пройти анкету заново нельзя.";
    if (tg?.showConfirm) return new Promise(resolve => tg.showConfirm(prompt, resolve));
    return Promise.resolve(window.confirm(prompt));
  }
  function payload() {
    return {
      display_name: $("display_name").value.trim(),
      age: Number($("age").value),
      timezone: $("timezone").value.trim(),
      availability: $("availability").value.trim(),
      answers: Object.fromEntries(questions.map(([key]) => [key, $(key).value.trim()])),
      rules_accepted: $("start-agree").checked && $("submit-agree").checked,
    };
  }

  makeQuestions();
  draftKey += "_" + String(tg?.initDataUnsafe?.user?.id || "telegram");
  restoreDraft();
  $("start-agree").addEventListener("change", () => { $("start-button").disabled = !$("start-agree").checked; });
  $("start-button").addEventListener("click", () => {
    if (!$("start-agree").checked) return;
    show("form-panel");
    setStep(0);
  });
  $("curator-form").addEventListener("input", event => {
    event.target?.classList?.remove("invalid");
    setError("");
    saveDraft();
  });
  $("next-step").addEventListener("click", () => { if (!busy && validate(active)) setStep(active + 1); });
  $("prev-step").addEventListener("click", () => { if (!busy) setStep(active - 1); });
  $("curator-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || sent || !tg?.initData) return;
    for (let i = 0; i < sections.length; i++) {
      if (!validate(i)) { setStep(i); validate(i); return; }
    }
    if (!await confirmSubmit()) return;
    lock(true);
    try {
      const response = await request("/api/recruitment/curator/apply", payload());
      tg?.HapticFeedback?.notificationOccurred?.("success");
      showApplication(response.application);
    } catch (error) {
      tg?.HapticFeedback?.notificationOccurred?.("error");
      if (/уже отправили|повторная подача/i.test(error?.message || "")) {
        await checkStatus();
      } else {
        setError(error?.message || "Не удалось отправить анкету.");
      }
    } finally {
      lock(false);
    }
  });

  void checkStatus();
})();
