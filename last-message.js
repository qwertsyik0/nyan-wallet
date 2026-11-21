(() => {
  "use strict";

  const API = "https://nyan-wallet-bridge.qwertsyik.workers.dev";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  let previousStatus = null;
  let latest = null;
  let busy = false;
  let animationTimer = null;
  let typeTimer = null;
  let toastTimer = null;

  try { tg?.ready(); tg?.expand(); tg?.setHeaderColor?.("#fff9fb"); } catch (_) {}

  function toast(message) {
    const node = $("lm-toast");
    if (!node) return;
    clearTimeout(toastTimer);
    node.textContent = message;
    node.hidden = false;
    toastTimer = setTimeout(() => { node.hidden = true; }, 4500);
  }

  async function request(path, options = {}) {
    if (!tg?.initData) {
      throw new Error("Откройте событие внутри Telegram через Nyan Wallet.");
    }
    const response = await fetch(API + path, {
      method: options.method || "GET",
      headers: {
        "X-Telegram-Init-Data": tg.initData,
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
    });
    let data;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) {
      const detail = data?.detail;
      throw new Error(typeof detail === "string" ? detail : "Сервер временно не отвечает");
    }
    return data;
  }

  function prepareLetter(message, animate) {
    const text = $("lm-letter-text");
    if (!text) return;
    clearInterval(typeTimer);
    if (!animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      text.textContent = message;
      return;
    }
    text.textContent = "";
    let position = 0;
    typeTimer = setInterval(() => {
      position = Math.min(message.length, position + 3);
      text.textContent = message.slice(0, position);
      if (position >= message.length) clearInterval(typeTimer);
    }, 46);
  }

  function playReveal(force) {
    if (!force && previousStatus === "revealed") return;
    const stage = $("lm-visual");
    if (!stage || !latest || latest.status !== "revealed") return;
    clearTimeout(animationTimer);
    clearInterval(typeTimer);
    $("lm-letter-panel").hidden = true;
    $("lm-letter-text").textContent = "";
    stage.classList.remove("is-opening", "is-opened");
    void stage.offsetWidth;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        stage.classList.add("is-opening");
        try { tg?.HapticFeedback?.impactOccurred("medium"); } catch (_) {}
      });
    });
    animationTimer = setTimeout(() => {
      stage.classList.remove("is-opening");
      stage.classList.add("is-opened");
      $("lm-letter-panel").hidden = false;
      $("lm-witness").hidden = !latest.witness;
      prepareLetter(latest.letter || "", true);
    }, 3600);
  }

  function puzzleNode(item, index, data) {
    const article = document.createElement("article");
    article.className = "lm-puzzle" + (item.solved ? " solved" : "");

    const row = document.createElement("div");
    row.className = "lm-puzzle-top";
    const number = document.createElement("span");
    number.className = "lm-puzzle-number";
    number.textContent = "ФРАГМЕНТ " + String(index + 1).padStart(2, "0");
    const status = document.createElement("span");
    status.className = "lm-puzzle-state";
    status.textContent = item.solved
      ? "найден"
      : item.attempts_left === 0 ? "попытки закончились"
        : String(item.attempts_left) + " попытки";
    row.append(number, status);

    const title = document.createElement("h3");
    title.textContent = item.title;
    const question = document.createElement("p");
    question.textContent = item.question;
    const choices = document.createElement("div");
    choices.className = "lm-choices";

    item.choices.forEach((choice, choiceIndex) => {
      const button = document.createElement("button");
      button.className = "lm-choice";
      button.type = "button";
      button.textContent = choice;
      button.disabled = busy || item.solved ||
        item.attempts_left <= 0 || data.my_fragments >= data.my_limit ||
        data.status !== "active";
      button.addEventListener("click", () => solve(item.id, choiceIndex));
      choices.appendChild(button);
    });
    article.append(row, title, question, choices);
    return article;
  }

  function render(data) {
    latest = data;
    $("lm-loading").hidden = true;
    $("lm-content").hidden = false;
    $("lm-counter").textContent = String(data.collected) + " / " + String(data.goal);
    $("lm-progress").style.width = Math.min(100, (100 * data.collected / Math.max(1, data.goal))) + "%";
    const bar = document.querySelector(".lm-progress");
    bar?.setAttribute("aria-valuenow", String(data.collected));
    bar?.setAttribute("aria-valuemax", String(data.goal));

    $("lm-my-count").textContent = "ваши фрагменты: " + data.my_fragments + " / " + data.my_limit;
    $("lm-members").textContent = "участники события: " + data.participants;

    const descriptions = {
      active: "каждый найденный фрагмент приближает раскрытие тайны",
      paused: "расшифровка временно приостановлена",
      revealed: "все фрагменты собраны. письмо открыто",
    };
    $("lm-description").textContent = descriptions[data.status] || "";
    $("lm-status").textContent =
      data.status === "revealed" ? "Печать разрушена. Послание доступно всем." :
      data.status === "paused" ? "Сбор фрагментов временно остановлен." :
      data.my_fragments >= data.my_limit
        ? "Вы нашли все доступные фрагменты. Ждём остальных."
        : "Найдите два фрагмента, чтобы помочь открыть письмо.";

    $("lm-challenges-section").hidden = data.status === "revealed";
    const list = $("lm-puzzles");
    list.replaceChildren(...data.challenges.map((item, i) => puzzleNode(item, i, data)));

    $("lm-owner").hidden = !data.is_owner;
    if (data.is_owner) {
      $("lm-owner-summary").textContent = "режим: " + data.status +
        " · найдено: " + data.collected + " · участников: " + data.participants;
      $("lm-pause").disabled = data.status !== "active";
      $("lm-resume").disabled = data.status !== "paused";
      $("lm-reveal").disabled = data.status === "revealed";
    }

    if (data.status === "revealed") {
      if (previousStatus !== "revealed") {
        playReveal(true);
      } else if (!$("lm-visual").classList.contains("is-opening") &&
                 !$("lm-visual").classList.contains("is-opened")) {
        $("lm-visual").classList.add("is-opened");
        $("lm-letter-panel").hidden = false;
        $("lm-letter-text").textContent = data.letter || "";
      }
    } else {
      $("lm-letter-panel").hidden = true;
      $("lm-visual").classList.remove("is-opening", "is-opened");
    }
    previousStatus = data.status;
  }

  async function refresh(silent = false) {
    if (busy) return;
    try {
      const data = await request("/api/last-message");
      render(data);
    } catch (error) {
      if (!silent) {
        $("lm-loading").hidden = false;
        $("lm-loading").textContent = error.message || "Не удалось загрузить письмо";
        toast(error.message || "Ошибка подключения");
      }
    }
  }

  async function solve(challenge, choice) {
    if (busy || latest?.status !== "active") return;
    busy = true;
    try {
      const result = await request("/api/last-message/solve", {
        method: "POST",
        body: { challenge, choice },
      });
      toast(result.message || (result.ok ? "Фрагмент найден" : "Ответ не подошёл"));
      if (result.ok) {
        try { tg?.HapticFeedback?.notificationOccurred("success"); } catch (_) {}
      } else {
        try { tg?.HapticFeedback?.notificationOccurred("error"); } catch (_) {}
      }
    } catch (error) {
      toast(error.message || "Попробуйте позже");
    } finally {
      busy = false;
      await refresh();
    }
  }

  async function control(action) {
    if (busy) return;
    if (action === "reveal" && !window.confirm(
      "Открыть письмо для ВСЕХ пользователей прямо сейчас? Это действие нельзя отменить."
    )) return;
    busy = true;
    try {
      const result = await request("/api/owner/last-message/control", {
        method: "POST", body: { action },
      });
      toast("Статус события: " + result.status);
    } catch (error) {
      toast(error.message || "Не удалось выполнить действие");
    } finally {
      busy = false;
      await refresh();
    }
  }

  $("lm-pause").addEventListener("click", () => control("pause"));
  $("lm-resume").addEventListener("click", () => control("resume"));
  $("lm-reveal").addEventListener("click", () => control("reveal"));
  $("lm-owner-refresh").addEventListener("click", () => refresh());
  $("lm-replay").addEventListener("click", () => playReveal(true));

  refresh();
  const poll = setInterval(() => {
    if (!document.hidden) refresh(true);
  }, 15000);
  window.addEventListener("pagehide", () => {
    clearInterval(poll);
    clearTimeout(animationTimer);
    clearInterval(typeTimer);
  }, { once: true });
})();
