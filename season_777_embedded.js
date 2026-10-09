
(() => {
  "use strict";

  const API = "https://nyan-wallet-api.onrender.com";
  const tg = window.Telegram?.WebApp;
  let opened = false;
  let loading = false;

  const view = () => document.getElementById("season777-view");
  const body = () => document.getElementById("season777-body");
  const progress = () => document.getElementById("season777-progress");

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, m => ({
      "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
    }[m]));
  }

  function auth() {
    return tg?.initData || "";
  }

  function headers(json = false) {
    const h = { "X-Telegram-Init-Data": auth() };
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  async function json(response) {
    try { return await response.json(); } catch (_) { return {}; }
  }

  async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: ctrl.signal, cache: "no-store" });
    } finally {
      clearTimeout(timer);
    }
  }

  function showOnlySeason() {
    const v = view();
    if (!v) return;
    document.querySelectorAll(".app > main").forEach(node => {
      if (node !== v) node.classList.add("hidden");
    });
    v.classList.remove("hidden");
    window.scrollTo(0, 0);
    opened = true;
  }

  function closeSeason() {
    const v = view();
    if (v) v.classList.add("hidden");
    const wallet = document.getElementById("wallet-view");
    if (wallet) wallet.classList.remove("hidden");
    opened = false;
    window.scrollTo(0, 0);
  }

  function dots(s) {
    const p = progress();
    if (!p) return;
    const vals = [s.chapter1_choice, s.chapter2_choice, s.chapter3_choice, s.final_choice];
    p.innerHTML = vals.map(v => '<span class="season777-dot ' + (v ? 'on' : '') + '"></span>').join("");
  }

  function when(v) {
    if (!v) return "";
    try {
      return new Intl.DateTimeFormat("ru-RU", {
        day:"numeric", month:"long", hour:"2-digit", minute:"2-digit"
      }).format(new Date(v));
    } catch (_) { return v; }
  }

  function choices(items, step, secret = false) {
    return '<div class="season777-actions">' +
      items.map(([id,label]) =>
        '<button type="button" class="season777-choice ' + (secret && id === "nobody" ? "secret" : "") +
        '" data-season-step="' + step + '" data-season-choice="' + id + '">' + esc(label) + '</button>'
      ).join("") + '</div>';
  }

  function renderChapter1() {
    body().innerHTML =
      '<div class="season777-inner"><div class="season777-k">ошибка синхронизации</div>' +
      '<h1 class="season777-title">кошелёк, которого не существует</h1>' +
      '<div class="season777-terminal">КОШЕЛЁК: NYAN 0000 0000 0000\nВЛАДЕЛЕЦ: ███████\nБАЛАНС: 777 🐾\n\nпоследняя операция: -777 🐾\nстатус: ОТМЕНЕНО</div>' +
      '<div class="season777-copy">сумма вернулась обратно, но владелец больше ни разу не открыл кошелёк. что проверим первым?</div>' +
      choices([["owner","посмотреть информацию о владельце"],["transfer","проверить отменённый перевод"],["greed","попробовать забрать 777 🐾"]],"chapter1") +
      '</div>';
  }

  function renderChapter2() {
    body().innerHTML =
      '<div class="season777-inner"><div class="season777-k">глава II · 1 лапкоин</div>' +
      '<h1 class="season777-title">архив изменился</h1>' +
      '<div class="season777-terminal">БАЛАНС: 776 🐾\n\n-1 🐾\nполучатель: NYAN 0714 0211 0318\nстатус: ДОСТАВЛЕНО</div>' +
      '<div class="season777-copy">вчера этого кошелька не существовало. сейчас он зарегистрирован без имени владельца.</div>' +
      choices([["contact","отправить туда ещё 1 🐾"],["watch","ничего не отправлять и наблюдать"],["admin","пожаловаться администрации"]],"chapter2") +
      '</div>';
  }

  function renderChapter3() {
    body().innerHTML =
      '<div class="season777-inner"><div class="season777-k">глава III · кто лжёт</div>' +
      '<h1 class="season777-title">две версии</h1>' +
      '<div class="season777-terminal">НЕИЗВЕСТНЫЙ:\n«я сообщил об ошибке. после этого меня удалили.»\n\nСИСТЕМА:\n«объект 00000001 создал незаконно 14 280 🐾.»</div>' +
      '<div class="season777-copy">в архиве, который ты видел раньше, никаких 14 280 🐾 не было. кому верить?</div>' +
      choices([["system","поверить системе"],["unknown","поверить неизвестному"],["logs","проверить журнал изменений"]],"chapter3") +
      '</div>';
  }

  function renderFinal(canSecret) {
    const items = [["mine","отправить 777 🐾 мне"],["return","вернуть их системе"],["split","разделить между всеми"]];
    if (canSecret) items.push(["nobody","никому"]);
    body().innerHTML =
      '<div class="season777-inner"><div class="season777-k">финал · NYAN-0</div>' +
      '<h1 class="season777-title">последняя операция</h1>' +
      '<div class="season777-copy">«я не человек. я — первая тестовая версия системы начислений. мне осталось выполнить одну операцию.»</div>' +
      '<div class="season777-terminal">777 🐾 должны получить владельца.\n\nкому их отправить?</div>' +
      choices(items,"final",canSecret) + '</div>';
  }

  function renderWaiting(s) {
    body().innerHTML =
      '<div class="season777-wait"><div class="season777-wait-symbol">◷</div><h2>архив пока молчит</h2>' +
      '<p>следующая запись откроется <strong>' + esc(when(s.waiting_until)) + '</strong>.<br>предыдущие решения уже сохранены.</p></div>';
  }

  function renderComplete(s,c) {
    const names = {
      season777_truth:"Ошибка №777",
      season777_collective:"На всех",
      season777_archivist:"Архивариус",
      season777_greed:"А вдруг прокатит?",
      season777_owner:"Новый владелец"
    };
    const name = names[s.achievement_key] || "финал";
    let extra = "";
    if (s.achievement_key === "season777_truth") {
      extra = '<p>«правильно. 777 — не баланс. это номер теста.»<br><br>ТЕСТ №777 ЗАВЕРШЁН.</p>';
    } else if (s.achievement_key === "season777_collective") {
      extra = '<p>ты выбрал общий фонд. таких решений сейчас: <strong>' + esc(c.split_endings) + '</strong>.</p>';
    }
    body().innerHTML =
      '<div class="season777-result"><div class="season777-k">сезон завершён</div><h2>' + esc(name) + '</h2>' +
      extra + '<div class="season777-reward">+' + esc(s.reward_amount) + ' 🐾</div>' +
      '<div class="season777-ach">достижение: ' + esc(name) + '</div><p>награда уже начислена на баланс.</p></div>';
  }

  function render(data) {
    const s = data.state || {}, e = data.event || {};
    dots(s);
    if (s.completed) return renderComplete(s, data.community || {});
    if (e.status === "ended") {
      body().innerHTML = '<div class="season777-wait"><div class="season777-wait-symbol">×</div><h2>архив закрыт</h2><p>сезон уже завершён.</p></div>';
      return;
    }
    if (e.status === "upcoming" || (!s.current_step && s.waiting_until)) return renderWaiting(s);
    if (s.current_step === "chapter1") return renderChapter1();
    if (s.current_step === "chapter2") return renderChapter2();
    if (s.current_step === "chapter3") return renderChapter3();
    if (s.current_step === "final") return renderFinal(Boolean(s.can_secret));
    renderWaiting(s);
  }

  function loadingView() {
    body().innerHTML = '<div class="season777-loading"><div><strong>открываем архив</strong><span>проверяем сохранённые решения</span><div class="season777-spinner"></div></div></div>';
  }

  async function load(silent = false) {
    if (loading) return;
    loading = true;
    if (!silent) loadingView();

    if (!auth()) {
      body().innerHTML = '<div class="season777-wait"><h2>Telegram не передал данные Mini App</h2><p>закрой Nyan Wallet полностью и открой его заново кнопкой бота.</p></div>';
      loading = false;
      return;
    }

    try {
      const r = await fetchWithTimeout(API + "/api/season-777/status", { headers: headers() }, 8000);
      const d = await json(r);
      if (!r.ok) throw new Error(d?.detail || "не удалось открыть архив");
      render(d);
    } catch (e) {
      const msg = esc(e?.name === "AbortError" ? "сервер отвечает слишком долго." : (e?.message || "ошибка загрузки"));
      if (silent) {
        body().insertAdjacentHTML("beforeend",
          '<div class="season777-error">не удалось синхронизировать архив: ' + msg +
          ' <button type="button" id="season777-retry" class="season777-choice" style="margin-top:10px">повторить</button></div>');
      } else {
        body().innerHTML =
          '<div class="season777-wait"><h2>архив не ответил</h2><p>' + msg +
          '</p><button type="button" id="season777-retry" class="season777-choice">попробовать ещё раз</button></div>';
      }
      document.getElementById("season777-retry")?.addEventListener("click", () => load(false));
    } finally {
      loading = false;
    }
  }

  async function pick(step, choice) {
    document.querySelectorAll(".season777-choice[data-season-step]").forEach(b => b.disabled = true);
    try {
      const r = await fetchWithTimeout(API + "/api/season-777/choice", {
        method:"POST",
        headers:headers(true),
        body:JSON.stringify({step, choice})
      }, 8000);
      const d = await json(r);
      if (!r.ok) throw new Error(d?.detail || "не удалось сохранить выбор");
      tg?.HapticFeedback?.selectionChanged?.();
      render(d);
    } catch (e) {
      body().insertAdjacentHTML("beforeend", '<div class="season777-error">' + esc(e?.message || "ошибка") + '</div>');
      document.querySelectorAll(".season777-choice[data-season-step]").forEach(b => b.disabled = false);
    }
  }

  window.__nyanOpenSeason777 = () => {
    showOnlySeason();
    renderChapter1();
    window.setTimeout(() => void load(true), 30);
  };
  window.__nyanCloseSeason777 = closeSeason;

  document.addEventListener("click", e => {
    const choice = e.target.closest("[data-season-step]");
    if (choice) {
      void pick(choice.dataset.seasonStep, choice.dataset.seasonChoice);
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("season777-back")?.addEventListener("click", closeSeason);
  }, {once:true});
})();
