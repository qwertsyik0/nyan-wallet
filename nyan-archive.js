(() => {
  "use strict";

  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const openingUTC = Date.UTC(2026, 9, 30, 19);
  const teaserRecords = [
    ["Снимок без номера", "Фотоплёнка, проявленная дважды"],
    ["Лист без подписи", "Страница, не внесённая в дневник"],
    ["Показания неизвестного", "Аудиозапись · расшифровка"],
    ["Вопрос, которого не было", "Заключительный лист · дело №0"],
  ].map(([title, subtitle], index) => ({
    id:index + 1, title, subtitle,
    opens_at:new Date(openingUTC + index * 2 * 3600000).toISOString(),
    available:false,
  }));
  const teaser = {records:teaserRecords, is_open:false, owner_preview:false, solved:false};
  const state = {data:teaser, selected:0, sending:false, skew:0, feedback:"", feedbackError:false, refreshing:false, lastRefreshAt:0};
  const initData = tg?.initData || "";
  tg?.ready?.();
  tg?.expand?.();

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function message(text, isError=false) {
    $("notice").textContent = text || "";
    $("notice").classList.toggle("error", isError);
  }

  function humanError(error) {
    if (error?.name === "AbortError") return "Сервер долго отвечает. Попробуй позже.";
    const detail = error?.message || "Не удалось связаться с архивом";
    return /Failed to fetch|NetworkError|Load failed/i.test(detail) ? "Нет связи с сервером. Попробуй позже." : detail;
  }

  async function api(path, method="GET", data) {
    if (method !== "GET" && !initData) throw new Error("Открой архив через Telegram");
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), method === "GET" ? 18000 : 30000);
    try {
      const res = await fetch(API + path, {
        method, cache:"no-store", signal:controller.signal,
        headers:{...(initData ? {"X-Telegram-Init-Data":initData} : {}), ...(data ? {"Content-Type":"application/json"} : {})},
        body:data ? JSON.stringify(data) : undefined,
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || !json.ok) {
        throw new Error(typeof json.detail === "string" ? json.detail : `Ошибка сервера (${res.status})`);
      }
      return json;
    } finally { window.clearTimeout(timer); }
  }

  function localNow() { return Date.now() + state.skew; }

  function releaseClock(iso) {
    const d = new Date(iso);
    return new Intl.DateTimeFormat("ru-RU", {timeZone:"Europe/Moscow", hour:"2-digit",minute:"2-digit"}).format(d);
  }

  function countdown() {
    const data = state.data;
    if (!data) return;
    const next = data.records.find(item => !item.available);
    const opening = $("opening-state");
    if (data.owner_preview && !data.is_open) {
      opening.textContent = "Просмотр владельца · открытие сегодня в 22:00";
    } else if (next) {
      const until = Math.max(0, Date.parse(next.opens_at) - localNow());
      const hours = Math.floor(until / 3600000);
      const minutes = Math.floor((until % 3600000) / 60000);
      const seconds = Math.floor((until % 60000) / 1000);
      const clock = `${String(hours).padStart(2,"0")}:${String(minutes).padStart(2,"0")}:${String(seconds).padStart(2,"0")}`;
      opening.textContent = `${data.is_open ? "Следующая запись" : "Открытие"} · ${clock} · ${releaseClock(next.opens_at)} МСК`;
      if (until === 0 && !state.refreshing && Date.now() - state.lastRefreshAt > 15000) refresh();
    } else {
      opening.textContent = "Все записи доступны";
    }
  }

  function recordButton(record) {
    const card = element("button", `record${state.selected === record.id ? " selected" : ""}`);
    card.type = "button";
    card.disabled = !record.available;
    const number = element("span", "record-number", String(record.id).padStart(2,"0"));
    const copy = element("span", "record-copy");
    copy.append(element("strong", "", record.title), element("small", "", record.subtitle));
    const status = element("span", "record-state", record.available ? "открыть" : `${releaseClock(record.opens_at)} мск`);
    card.append(number, copy, status);
    card.addEventListener("click", () => select(record.id));
    return card;
  }

  function select(id) {
    const record = state.data?.records.find(item => item.id === id && item.available);
    if (!record) return;
    state.selected = id;
    render();
    $("reader").scrollIntoView({behavior:"smooth",block:"nearest"});
  }

  function renderReader() {
    const record = state.data.records.find(item => item.id === state.selected && item.available);
    const reader = $("reader");
    reader.hidden = !record;
    if (!record) return;
    $("reader-index").textContent = `МАТЕРИАЛ №${String(record.id).padStart(2,"0")}`;
    $("reader-title").textContent = record.title;
    $("reader-subtitle").textContent = record.subtitle;
    $("reader-body").textContent = record.body || "";
    $("reader-note").textContent = record.note || "";
    $("reader-photo").hidden = record.kind !== "photo";
  }

  function render() {
    const data = state.data;
    if (!data) return;
    const records = $("records");
    records.replaceChildren(...data.records.map(recordButton));
    $("records-count").textContent = `${data.records.filter(record => record.available).length} / ${data.records.length}`;
    if (!data.records.some(record => record.available && record.id === state.selected)) state.selected = 0;
    renderReader();
    $("ending").hidden = !data.solved;
    if (data.solved) $("ending-text").textContent = data.ending || "Дело восстановлено.";
    const finalRecord = data.records[data.records.length - 1];
    const finalOpen = Boolean(finalRecord?.available) && (data.owner_preview || (data.is_open && localNow() >= Date.parse(finalRecord.opens_at)));
    $("answer-section").hidden = !finalOpen || data.solved;
    $("telegram-link").hidden = !finalOpen || Boolean(initData) || data.solved;
    $("answer-form").hidden = !initData;
    $("answer-button").disabled = state.sending;
    $("answer-feedback").textContent = state.feedback;
    $("answer-feedback").classList.toggle("error", state.feedbackError);
    countdown();
  }

  async function refresh() {
    if (state.refreshing) return;
    state.refreshing = true;
    state.lastRefreshAt = Date.now();
    try {
      const result = await api("/api/nyan-archive-2026/status");
      const serverMs = Date.parse(result.server_now);
      if (Number.isFinite(serverMs)) state.skew = serverMs - Date.now();
      state.data = result;
      message("");
      render();
    } catch (error) {
      message(
        localNow() < Date.parse(teaserRecords[0].opens_at)
          ? "Архив ожидает открытия. Доступ к материалам проверится сегодня в 22:00."
          : humanError(error),
        localNow() >= Date.parse(teaserRecords[0].opens_at),
      );
    } finally { state.refreshing = false; }
  }

  async function submit(event) {
    event.preventDefault();
    if (state.sending || !state.data || state.data.solved) return;
    const answer = $("answer").value.trim();
    if (!answer) return;
    state.sending = true;
    $("answer-button").disabled = true;
    state.feedback = "";
    render();
    try {
      const result = await api("/api/nyan-archive-2026/solve", "POST", {answer});
      if (result.correct) {
        $("answer").value = "";
        await refresh();
        $("ending").scrollIntoView({behavior:"smooth",block:"center"});
      } else {
        state.feedback = "Это слово не подходит. Вернись к первым трём записям.";
        state.feedbackError = true;
        await refresh();
      }
    } catch (error) {
      state.feedback = humanError(error);
      state.feedbackError = true;
    } finally {
      state.sending = false;
      render();
    }
  }

  $("reader-close").addEventListener("click", () => {state.selected=0;render();});
  $("answer-form").addEventListener("submit", submit);
  document.addEventListener("visibilitychange", () => {if (!document.hidden) refresh();});
  window.setInterval(countdown, 1000);
  render();
  refresh();
})();
