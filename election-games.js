(() => {
  "use strict";
  const tg = window.Telegram?.WebApp;
  const API = "https://nyan-wallet-api.onrender.com/api/elections";
  const $ = id => document.getElementById(id);
  let busy = false;
  tg?.ready?.();
  tg?.expand?.();

  function showMessage(text) {
    const el = $("eg-message");
    el.textContent = text || "";
    el.hidden = !text;
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  async function api(path, payload) {
    if (!tg?.initData) throw new Error("Открой эту страницу через Telegram-бота Nyan Wallet.");
    const options = {
      method: payload === undefined ? "GET" : "POST",
      headers: {"X-Telegram-Init-Data": tg.initData},
      cache: "no-store"
    };
    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(API + path, options);
    let data;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) {
      const detail = data?.detail;
      if (response.status === 403 && typeof detail === "string" && detail.includes("кошелёк")) {
        throw new Error("Сначала открой основной Nyan Wallet и создай кошелёк, затем вернись на страницу записи.");
      }
      if (response.status === 503) throw new Error("На сервере технические работы. Попробуй позже.");
      throw new Error(typeof detail === "string" ? detail : "Ошибка соединения (" + response.status + ").");
    }
    return data;
  }

  function partyById(parties, id) {
    return (parties || []).find(p => p.id === id);
  }

  function render(elections, signup) {
    $("eg-loading").hidden = true;
    $("eg-content").hidden = false;
    for (const id of ["eg-confirmed", "eg-existing", "eg-new", "eg-closed", "eg-owner"]) $(id).hidden = true;
    const myParty = partyById(elections.parties, signup.my_party_id);
    if (signup.registered && myParty) {
      $("eg-confirmed-party").textContent = "Твоя партия: " + myParty.name;
      $("eg-confirmed").hidden = false;
    } else if (!signup.registration_open || !elections.season) {
      $("eg-closed").hidden = false;
    } else if (myParty) {
      $("eg-current-party").textContent = "Ты состоишь в партии «" + myParty.name + "». Подтверди, что будешь участвовать в играх.";
      $("eg-existing").hidden = false;
    } else if (signup.my_party_id) {
      $("eg-closed").hidden = false;
      $("eg-closed").querySelector(".el-muted").textContent = "Твоя партия сейчас недоступна. Обратись к организаторам.";
    } else {
      $("eg-new").hidden = false;
      const list = $("eg-parties");
      list.replaceChildren();
      for (const party of elections.parties || []) {
        const card = element("article", "el-party eg-party");
        const head = element("div", "eg-party-head");
        head.append(element("h3", "", party.name), element("span", "eg-party-short", party.short_name));
        const meta = element("p", "eg-party-desc", "Председатель: " + party.chair_label + " · Участников: " + party.member_count);
        const btn = element("button", "el-button eg-join", "Вступить и записаться");
        btn.type = "button";
        btn.dataset.partyId = String(party.id);
        card.append(head, meta, btn);
        list.append(card);
      }
      if (!elections.parties?.length) list.append(element("p", "el-muted", "Пока нет партий для вступления."));
    }
    if (elections.is_owner) {
      $("eg-owner").hidden = false;
      showOwnerList();
    }
  }

  async function showOwnerList() {
    const list = $("eg-owner-list");
    list.replaceChildren(element("p", "el-muted", "Загружаем участников…"));
    try {
      const data = await api("/owner/games/signups");
      if ($("eg-owner").hidden) return;
      list.replaceChildren();
      $("eg-count").textContent = data.signups.length + " записано";
      for (const item of data.signups) {
        const card = element("div", "eg-owner-row");
        card.append(
          element("span", "", (item.username || "Без username") + " · " + item.telegram_id),
          element("small", "", item.party_name)
        );
        list.append(card);
      }
      if (!data.signups.length) list.append(element("p", "el-muted", "Пока нет подтверждённых участников."));
    } catch (error) {
      list.replaceChildren(element("p", "el-muted", error.message || "Список пока недоступен."));
    }
  }

  async function reload() {
    const [elections, signup] = await Promise.all([api(""), api("/games/status")]);
    if (signup.season_id !== (elections.season?.id ?? null)) {
      throw new Error("Данные выборов обновились. Попробуй ещё раз.");
    }
    render(elections, signup);
  }

  async function act(path, payload) {
    if (busy) return;
    busy = true;
    document.querySelectorAll("button").forEach(b => { b.disabled = true; });
    showMessage("");
    try {
      await api(path, payload);
      await reload();
      showMessage("Участие подтверждено. Ты записан на игры!");
    } catch (error) {
      showMessage(error.message || "Не удалось сохранить запись.");
    } finally {
      busy = false;
      document.querySelectorAll("button").forEach(b => { b.disabled = false; });
    }
  }

  $("eg-confirm-button").addEventListener("click", () => act("/games/confirm", {}));
  $("eg-parties").addEventListener("click", event => {
    const btn = event.target.closest("button[data-party-id]");
    if (!btn || busy) return;
    const id = Number(btn.dataset.partyId);
    if (Number.isSafeInteger(id) && id > 0) act("/games/join", {party_id: id});
  });

  reload().catch(error => {
    $("eg-loading").hidden = false;
    $("eg-loading").textContent = "Не удалось загрузить регистрацию.";
    showMessage(error.message || "Попробуй ещё раз.");
  });
})();
