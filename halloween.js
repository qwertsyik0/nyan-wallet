(() => {
  "use strict";

  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const START = Date.parse("2026-10-29T14:00:00Z");
  const SECRET = Date.parse("2026-10-29T20:00:00Z");
  const END = Date.parse("2026-10-31T21:00:00Z");
  const META = {
    loupe: {icon:"⌕", description:"Небольшая подсказка к выбранной комнате"},
    candle:{icon:"◑", description:"Покажет начало ответа"},
    key:{icon:"⚿", description:"Открывает последнюю дверь после 23:00"},
    eye:{icon:"◉", description:"Почти полностью раскрывает ответ"},
  };

  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  let auth = tg?.initData || "";
  let state = null;
  let selectedRoom = null;
  let working = false;

  tg?.ready?.();
  tg?.expand?.();
  try { if (!auth) auth = "browser:" + (sessionStorage.getItem("nyan_ideas_browser_auth") || ""); } catch (_) {}
  if (auth === "browser:") auth = "";

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = String(value);
    return element;
  }
  function button(label, action, className, disabled) {
    const b = node("button", className, label);
    b.type = "button";
    b.disabled = Boolean(disabled || working);
    b.addEventListener("click", action);
    return b;
  }
  function format(n) { return Number(n).toLocaleString("ru-RU"); }
  function alertMessage(message, error = false) {
    $("event-notice").textContent = message || "";
    $("event-notice").classList.toggle("error", error);
  }
  function humanError(error) {
    const details = error?.message || "Неизвестная ошибка";
    return details.includes("Failed to fetch") ? "Нет связи с сервером. Попробуй позже." : details;
  }
  async function api(path, method = "GET", payload = undefined) {
    if (!auth) throw new Error("Открой страницу через Telegram");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), method === "GET" ? 18000 : 30000);
    try {
      const response = await fetch(API + path, {
        method,
        headers: {"X-Telegram-Init-Data":auth, ...(payload === undefined ? {} : {"Content-Type":"application/json"})},
        body: payload === undefined ? undefined : JSON.stringify(payload),
        cache:"no-store", signal:controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        const reason = typeof data.detail === "string" ? data.detail : (data.detail?.message || `HTTP ${response.status}`);
        throw new Error(reason);
      }
      return data;
    } catch (error) {
      if (controller.signal.aborted) throw new Error("Сервер долго отвечает. Попробуй ещё раз.");
      throw error;
    } finally { clearTimeout(timer); }
  }
  function requestKey(label) {
    const cacheKey = `nyan-halloween-2026-${label}`;
    let key = "";
    try { key = sessionStorage.getItem(cacheKey) || ""; } catch (_) {}
    if (!key) {
      key = (window.crypto?.randomUUID?.() || `${Date.now()}${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`).replaceAll("-", "");
      try { sessionStorage.setItem(cacheKey, key); } catch (_) {}
    }
    return {value:key, clear:()=>{try {sessionStorage.removeItem(cacheKey);} catch (_) {}}};
  }
  async function run(action) {
    if (working) return;
    working = true;
    try { await action(); }
    catch (error) { alertMessage(humanError(error), true); }
    finally { working = false; render(); }
  }

  function clock() {
    const now = Date.now();
    const target = now < START ? START : END;
    const count = Math.max(0, Math.ceil((target - now) / 1000));
    const hours = Math.floor(count / 3600);
    const minutes = Math.floor((count % 3600) / 60);
    const seconds = count % 60;
    const duration = `${String(hours).padStart(2,"0")}:${String(minutes).padStart(2,"0")}:${String(seconds).padStart(2,"0")}`;
    $("event-clock").textContent = now < START ? `До начала · ${duration}` : now < END ? `До завершения · ${duration}` : "Событие завершено";
  }

  function drawRooms() {
    const holder = $("rooms");
    holder.replaceChildren();
    for (const room of state.rooms) {
      const playable = room.accessible || room.completed;
      const card = button("", () => selectRoom(room.room), `room-card${room.completed ? " done" : ""}${selectedRoom === room.room ? " selected" : ""}`, !playable);
      card.setAttribute("aria-label", `${room.title}: ${room.completed ? "пройдено" : playable ? "доступно" : "закрыто"}`);
      card.append(node("span", "room-number", room.room === 6 ? "◈" : String(room.room).padStart(2,"0")));
      const main = node("span", "room-main");
      main.append(node("strong", "", room.title), node("small", "", room.subtitle));
      card.append(main);
      const label = room.completed ? `+${room.reward} 🐾` : room.accessible ? "войти" : "закрыто";
      card.append(node("span", "room-status", label));
      holder.append(card);
    }
  }

  function drawPuzzle(puzzle) {
    const holder = $("puzzle");
    holder.replaceChildren();
    if (!puzzle) return;
    if (puzzle.lines) {
      const lines = node("div", "puzzle-lines");
      puzzle.lines.forEach(line => lines.append(node("div", "", line)));
      holder.append(lines);
    }
    if (puzzle.kind === "monitors") {
      const grid = node("div", "monitors");
      for (const tile of puzzle.tiles) grid.append(node("span", `monitor${tile.marked ? " marked" : ""}`, tile.digit));
      holder.append(grid);
    }
    if (puzzle.kind === "cipher") {
      holder.append(node("div", "puzzle-code", puzzle.cipher));
      holder.append(node("p", "", `Сдвиг: ${puzzle.shift} буквы вправо`));
    }
    if (puzzle.kind === "fragments") {
      const order = node("div", "puzzle-order");
      puzzle.order.forEach(i => order.append(node("span", "", `№${i}`)));
      holder.append(order);
    }
    if (puzzle.kind === "final") {
      holder.append(node("div", "puzzle-code", `+${puzzle.step}`));
    }
    holder.append(node("p", "", puzzle.question));
  }

  function drawDetail() {
    const panel = $("room-panel");
    const room = state.rooms.find(r => r.room === selectedRoom);
    if (!room || (!room.accessible && !room.completed)) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    $("room-kicker").textContent = room.room === 6 ? "СЕКРЕТ" : `КОМНАТА ${String(room.room).padStart(2,"0")}`;
    $("room-title").textContent = room.title;
    $("room-story").textContent = room.subtitle;
    drawPuzzle(room.puzzle);
    const clues = $("room-clues");
    clues.replaceChildren();
    for (const clue of room.clues) {
      const entry = node("div", "clue");
      entry.append(node("b", "", state.shop.find(s => s.key === clue.item)?.title || "Подсказка"), node("span", "", clue.text));
      clues.append(entry);
    }
    $("answer-form").hidden = room.completed || !room.accessible;
    $("answer-meta").textContent = room.completed ? "Ответ принят" : room.retry_at && Date.parse(room.retry_at) > Date.now()
      ? "После трёх ошибок сделай небольшой перерыв" : `Ошибок до перерыва: ${Math.max(1, 3 - room.attempts)}`;
    const disabled = Boolean(room.retry_at && Date.parse(room.retry_at) > Date.now());
    $("answer-input").disabled = disabled || working;
    $("answer-submit").disabled = disabled || working;

    const holder = $("room-inventory");
    holder.replaceChildren();
    if (room.accessible && !room.completed) {
      holder.append(node("span", "inventory-label", "Предметы для этой комнаты"));
      let available = false;
      for (const item of state.shop.filter(s => s.key !== "key")) {
        if (!(state.inventory[item.key] > 0) || room.clues.some(c => c.item === item.key)) continue;
        available = true;
        holder.append(button(`${item.title} · ${state.inventory[item.key]} шт.`, () => useItem(room.room, item.key), "inventory-use"));
      }
      if (!available) holder.append(node("small", "hint-label", "Подсказки можно получить в лавке ниже."));
    }
    if (room.completed) holder.append(node("div", "clue", `Улика найдена: фрагмент ${room.fragment}. Получено ${room.reward} 🐾 и ${room.pumpkins_reward} 🎃.`));
  }

  function drawShop() {
    const holder = $("shop");
    holder.replaceChildren();
    for (const item of state.shop) {
      const meta = META[item.key];
      const row = node("article", "shop-item");
      row.append(node("span", "shop-icon", meta.icon));
      const top = node("div", "");
      top.append(node("strong", "", item.title), node("p", "", meta.description));
      row.append(top);
      const bottom = node("div", "shop-bottom");
      bottom.append(node("span", "", `${item.price} 🎃`));
      const owned = state.inventory[item.key] || 0;
      const limited = item.key === "key" && (owned > 0 || state.secret_unlocked);
      bottom.append(button(limited ? "уже есть" : owned > 0 ? `ещё · ${owned} шт.` : "получить",
        () => buyItem(item), "shop-buy", !state.active || state.pumpkins < item.price || limited));
      row.append(bottom);
      holder.append(row);
    }
  }

  function drawEnding() {
    const box = $("ending");
    box.replaceChildren();
    const secretRoom = state.rooms[5];
    box.classList.toggle("revealed", Boolean(secretRoom.completed));
    if (secretRoom.completed) {
      box.append(node("div", "ending-kicker", "ДЕЛО ЗАКРЫТО · ПОСЛЕДНЯЯ ЗАПИСЬ"));
      box.append(node("h2", "ending-title", "Няник никуда не исчезал"));
      box.append(node("p", "ending-paragraph", "За шестой дверью лежит конверт. На нём — тот же отпечаток лапы, что и на старом чеке."));
      const letter = node("blockquote", "ending-letter", "«Я сам оставил чек, шифр и запертые двери. Хотел узнать, кто сумеет дойти до конца. Теперь у лавки есть хранитель. Это ты. — Няник»");
      box.append(letter);
      box.append(node("p", "ending-paragraph", "За спиной звенит колокольчик. На прилавке сидит Няник — словно никуда и не уходил."));
      const awards = node("div", "ending-awards");
      for (const badge of [
        { image: "./assets/badges/halloween-keeper-2026.webp", name: "Хранитель тайны" },
        ...(state.first_witness ? [{ image: "./assets/badges/halloween-first-witness-2026.webp", name: "Первый свидетель", first: true }] : []),
      ]) {
        const row = node("div", `ending-award${badge.first ? " first" : ""}`);
        const img = document.createElement("img");
        img.src = badge.image;
        img.alt = "";
        img.width = 36;
        img.height = 36;
        row.append(img, node("span", "", `${badge.name} · получено`));
        awards.append(row);
      }
      box.append(awards);
      box.append(node("small", "ending-footnote", "Награды сохранены в достижениях Nyan Wallet. Финальная комната принесла +100 🐾."));
      return;
    }
    box.append(node("span", "", "◈"));
    if (state.badge) box.append(node("p", "", "Значок «Призрак Няника» получен"));
    else box.append(node("p", "", "За пять комнат тебя ждёт значок «Призрак Няника»"));
    if (state.owner_early_access) {
      box.append(node("small", "", "Ранний доступ владельца. Комната без номера уже открыта."));
      box.append(button("Войти в последнюю комнату", () => selectRoom(6), "secret-button", !secretRoom.accessible));
    } else if (!state.active) {
      box.append(node("small", "", "Тайная дверь открывается 29 октября в 23:00 МСК"));
    } else if (Date.now() < SECRET) {
      box.append(node("small", "", "Комната без номера откроется в 23:00 МСК"));
    } else if (!state.secret_unlocked) {
      box.append(node("small", "", "Собери пять фрагментов и используй ржавый ключ из лавки"));
      const ready = state.rooms.slice(0,5).every(r => r.completed) && (state.inventory.key || 0) > 0;
      box.append(button("Открыть последнюю дверь", unlockSecret, "secret-button", !ready));
    } else {
      box.append(node("small", "", "Дверь открыта. Последняя комната ждёт тебя выше."));
      box.append(button("Перейти к загадке", () => selectRoom(6), "secret-button"));
    }
  }

  function render() {
    clock();
    if (!state) return;
    $("stat-rooms").textContent = `${state.rooms.slice(0,5).filter(r=>r.completed).length} / 5`;
    $("stat-pumpkins").textContent = `${format(state.pumpkins)} 🎃`;
    $("stat-earned").textContent = `${format(state.wallet_earned)} 🐾`;
    drawRooms();
    drawDetail();
    drawShop();
    drawEnding();
  }

  function selectRoom(number) {
    selectedRoom = number;
    $("answer-input").value = "";
    render();
    $("room-panel").scrollIntoView({behavior:"smooth",block:"start"});
  }
  async function submitAnswer(event) {
    event.preventDefault();
    const room = selectedRoom;
    const answer = $("answer-input").value.trim();
    if (!room || !answer) return;
    await run(async () => {
      const key = requestKey(`answer-${room}-${encodeURIComponent(answer)}`);
      const result = await api("/api/halloween-2026/answer", "POST", {room,answer,request_key:key.value});
      key.clear();
      state = result.state;
      alertMessage(result.correct ? result.already_completed ? "Комната уже пройдена." : `Верно! На кошелёк начислено +${result.reward} 🐾.` : "Пока неверно. Попробуй ещё раз.");
      if (result.correct) $("answer-input").value = "";
    });
  }
  async function buyItem(item) {
    if (!window.confirm(`Получить «${item.title}» за ${item.price} 🎃?`)) return;
    await run(async () => {
      const key = requestKey(`buy-${item.key}`);
      const result = await api("/api/halloween-2026/buy", "POST", {item:item.key,request_key:key.value});
      key.clear();
      state = result.state;
      alertMessage(result.duplicate ? "Эта покупка уже учтена." : `Предмет «${item.title}» добавлен в инвентарь.`);
    });
  }
  async function useItem(room, item) {
    await run(async () => {
      const result = await api("/api/halloween-2026/use", "POST", {room,item});
      state = result.state;
      alertMessage(result.duplicate ? "Подсказка уже открыта." : "Подсказка открыта под загадкой.");
    });
  }
  async function unlockSecret() {
    await run(async () => {
      const result = await api("/api/halloween-2026/unlock-secret", "POST");
      state = result.state;
      alertMessage("Последняя дверь открыта.");
      selectedRoom = 6;
    });
  }
  async function load(silent = false) {
    if (!auth) {
      $("event-login").hidden = false;
      alertMessage("Открой через Telegram, чтобы сохранить прогресс и получать награды.");
      return;
    }
    if (!silent) alertMessage("Проверяем прогресс…");
    try {
      state = await api("/api/halloween-2026/status");
      if (!silent) alertMessage(state.active ? "Событие открыто. Удачи!" : state.finished ? "Событие завершено. История прохождения сохранена." : "Начинаем 29 октября в 17:00 МСК!");
      render();
    } catch (error) {
      alertMessage(humanError(error), true);
      if (/Telegram|сессия|вход/i.test(humanError(error))) $("event-login").hidden = false;
    }
  }

  $("room-close").addEventListener("click", () => {selectedRoom = null; render();});
  $("answer-form").addEventListener("submit", submitAnswer);
  clock();
  load();
  setInterval(clock, 1000);
  setInterval(() => {if (auth && !working && document.visibilityState === "visible") load(true);}, 60000);
})();
