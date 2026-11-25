(() => {
  "use strict";
  const tg = window.Telegram?.WebApp;
  tg?.ready(); tg?.expand();
  const suffix = location.search + location.hash;
  document.getElementById("world-info-back").href = "./index.html" + suffix;
  for (const id of ["world-info-join", "world-info-join-bottom"]) {
    document.getElementById(id).href = "./nyan-world.html" + suffix;
  }
  if (!tg?.initData) return;
  fetch("https://nyan-wallet-bridge.qwertsyik.workers.dev/api/world/state", {
    headers: { "X-Telegram-Init-Data": tg.initData }, cache: "no-store"
  }).then(async response => {
    if (!response.ok) return;
    const data = await response.json();
    const season = data.season;
    if (!season) return;
    const labels = {draft:"Сезон готовится",registration:"Идёт регистрация",active:"Сезон идёт",paused:"Сезон на паузе",finished:"Сезон завершён"};
    document.getElementById("world-info-season").textContent = season.name + " · " + (labels[season.status] || "Подробнее в кабинете");
    if (season.rules) {
      document.getElementById("world-info-rules-section").hidden = false;
      document.getElementById("world-info-season-name").textContent = season.name;
      document.getElementById("world-info-rules").textContent = season.rules;
    }
    if (typeof season.chat_url === "string" && season.chat_url.startsWith("https://t.me/")) {
      const chat = document.getElementById("world-info-chat");
      chat.href = season.chat_url; chat.hidden = false;
    }
  }).catch(() => {});
})();