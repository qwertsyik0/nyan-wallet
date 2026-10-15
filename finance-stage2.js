(() => {
  "use strict";

  const tg = window.Telegram?.WebApp;
  const API = "https://nyan-wallet-api.onrender.com";
  const fields = ["balance", "duplicate", "audit", "fraud", "access", "dispute", "internship"];
  const mins = {balance:15, audit:25, fraud:35, dispute:35, internship:30};
  const sections = [...document.querySelectorAll(".step")];
  const names = ["01. расчёты", "02. безопасность", "03. работа с людьми"];
  const form = document.getElementById("candidate-form");
  const stage = document.getElementById("form-stage");
  const done = document.getElementById("done");
  const access = document.getElementById("access-state");
  const accessTitle = document.getElementById("access-heading");
  const accessMessage = document.getElementById("access-message");
  const retry = document.getElementById("retry-access");
  const error = document.getElementById("form-error");
  const back = document.getElementById("back");
  const next = document.getElementById("next");
  const finish = document.getElementById("finish");
  let step = 0, busy = false, submitted = false;

  tg?.ready?.();
  tg?.expand?.();

  function headers(json=false) {
    const h = {"X-Telegram-Init-Data": tg?.initData || ""};
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  async function call(path, method="GET", payload) {
    const request = {method, headers: headers(payload !== undefined), cache:"no-store"};
    if (payload !== undefined) request.body = JSON.stringify(payload);
    const response = await fetch(API+path, request);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail :
        (data.detail?.message || "Не удалось связаться с сервером."));
    }
    return data;
  }

  function showGate(heading, description, allowRetry=false) {
    access.hidden = false;
    stage.hidden = true;
    done.hidden = true;
    accessTitle.textContent = heading;
    accessMessage.textContent = description;
    retry.hidden = !allowRetry;
  }

  function showDone() {
    submitted = true;
    access.hidden = true;
    stage.hidden = true;
    done.hidden = false;
    document.querySelector(".sheet").scrollIntoView({behavior:"smooth",block:"start"});
  }

  async function checkAccess() {
    if (!tg?.initData) {
      showGate("Открой через Telegram", "Эта анкета доступна только по приглашению в Mini App Nyan Wallet. Открой кнопку из личного сообщения бота.");
      return;
    }
    retry.disabled = true;
    showGate("Проверяем приглашение…", "Проверяем твою анкету и текущий статус отбора.");
    try {
      const data = await call("/api/recruitment/finance/stage2/me");
      if (data.submitted) {
        showDone();
      } else if (data.can_submit) {
        access.hidden = true;
        stage.hidden = false;
      } else {
        showGate("Заявка недоступна", "Свяжись с администрацией Nyan Wallet.");
      }
    } catch (exc) {
      const msg = exc?.message || "Не удалось проверить приглашение.";
      const terminal = /недоступно вашему аккаунту|текущего статуса заявки/i.test(msg);
      showGate(terminal ? "Это персональное приглашение" : "Не удалось загрузить анкету", msg, !terminal);
    } finally {
      retry.disabled = false;
    }
  }

  function renderStep(index, scroll=true) {
    step = Math.max(0, Math.min(index, sections.length - 1));
    sections.forEach((el, i) => el.hidden = i !== step);
    document.getElementById("step-title").textContent = names[step];
    document.getElementById("step-count").textContent = (step + 1) + " / " + sections.length;
    document.getElementById("progress-fill").style.width = ((step + 1) * 100 / sections.length) + "%";
    back.hidden = step === 0;
    next.hidden = step === sections.length - 1;
    finish.hidden = step !== sections.length - 1;
    error.textContent = "";
    if (scroll) document.querySelector(".sheet").scrollIntoView({behavior:"smooth",block:"start"});
  }

  function validate(section) {
    const textareas = [...section.querySelectorAll("textarea")];
    const radios = [...section.querySelectorAll('input[type="radio"]')];
    for (const textarea of textareas) {
      textarea.classList.remove("error-field");
      const value = textarea.value.replace(/\s+/g," ").trim();
      if (value.length < (mins[textarea.name] || 1)) {
        textarea.classList.add("error-field");
        error.textContent = "Ответ слишком короткий. Напиши подробнее, как ты поступишь.";
        textarea.focus();
        return false;
      }
    }
    const names = [...new Set(radios.map(el => el.name))];
    for (const key of names) {
      const input = section.querySelector('input[name="' + key + '"]:checked');
      if (!input) {
        error.textContent = "Выбери один вариант ответа, чтобы продолжить.";
        section.querySelector('input[name="' + key + '"]')?.focus();
        return false;
      }
    }
    error.textContent = "";
    return true;
  }

  function lock(locked) {
    busy = locked;
    [back,next,finish].forEach(b => b.disabled = locked);
    finish.textContent = locked ? "Отправляем…" : "Отправить ответы ↗";
  }

  next.addEventListener("click", () => {
    if (!busy && validate(sections[step])) renderStep(step+1);
  });
  back.addEventListener("click", () => {
    if (!busy && step > 0) renderStep(step-1);
  });
  retry.addEventListener("click", () => void checkAccess());
  form.addEventListener("input", evt => {
    evt.target.classList?.remove("error-field");
    error.textContent = "";
  });

  finish.addEventListener("click", async () => {
    if (busy || submitted || !tg?.initData) return;
    for (let i=0;i<sections.length;i++) {
      if (!validate(sections[i])) {
        if (i !== step) { renderStep(i); validate(sections[i]); }
        return;
      }
    }
    const data = {};
    for (const key of fields) {
      const radio = form.querySelector('input[type="radio"][name="' + key + '"]:checked');
      const textarea = form.querySelector('textarea[name="' + key + '"]');
      data[key] = radio ? radio.value : textarea?.value.trim();
    }
    lock(true);
    try {
      await call("/api/recruitment/finance/stage2/submit","POST",data);
      tg?.HapticFeedback?.notificationOccurred?.("success");
      showDone();
    } catch (exc) {
      if (/уже отправлены/i.test(exc?.message||"")) {
        showDone();
      } else {
        error.textContent = exc?.message || "Не удалось сохранить ответы. Попробуй снова.";
        tg?.HapticFeedback?.notificationOccurred?.("error");
      }
    } finally {
      lock(false);
    }
  });

  document.getElementById("restart").addEventListener("click", () => {
    if (tg?.close) tg.close();
    else window.close();
  });
  renderStep(0, false);
  void checkAccess();
})();
