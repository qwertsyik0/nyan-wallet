(() => {
  "use strict";
  const tg = window.Telegram?.WebApp;
  const api = "https://nyan-wallet-153-76-175-145.sslip.io/api/halloween-boot-2026";
  const view = document.getElementById("halloween-boot-choice");
  const question = document.getElementById("hbc-question");
  const errorLine = document.getElementById("hbc-error");
  const buttons = [...view.querySelectorAll("[data-hbc-choice]")];
  let checked = false;
  let sending = false;
  if (!tg?.initData || !view) return;

  function isSpecialLaunch() {
    const params = new URL(window.location.href).searchParams;
    return Boolean(window.__nyanGiveawayDeepLinkActive || window.__nyanPaymentDeepLinkActive ||
      window.__nyanPromoDeepLinkActive || params.has("appeals") || params.has("appeal") || params.has("ownerAppeal"));
  }

  async function call(path, method="GET", body=null) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(),method === "GET" ? 12000 : 25000);
    try {
      const response = await fetch(api + path,{
        method,cache:"no-store",signal:controller.signal,
        headers:{"X-Telegram-Init-Data":tg.initData,...(body ? {"Content-Type":"application/json"} : {})},
        body:body ? JSON.stringify(body) : undefined,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось выполнить выбор. Попробуй ещё раз.");
      }
      return data;
    } finally {window.clearTimeout(timeout);}
  }

  async function check() {
    if (checked || isSpecialLaunch()) return;
    checked = true;
    try {
      const status = await call("/status");
      if (!status.eligible) return;
      view.hidden = false;
      document.body.classList.add("hbc-active");
      buttons[0].focus({preventScroll:true});
    } catch (error) {
      // The wallet must stay usable if an optional Halloween API isn't installed.
      console.warn("Halloween boot choice unavailable:", error);
    }
  }

  async function choose(button) {
    if (sending || view.hidden) return;
    sending = true;
    buttons.forEach(item => {item.disabled = true;});
    errorLine.hidden = true;
    try {
      const result = await call("/choose","POST",{choice:button.dataset.hbcChoice});
      question.textContent = `${result.amount > 0 ? "+" : "−"}${Math.abs(result.amount)} 🐾`;
      view.classList.add("hbc-done");
      tg?.HapticFeedback?.notificationOccurred?.(result.amount > 0 ? "success" : "warning");
      window.setTimeout(() => {
        view.hidden = true;
        document.body.classList.remove("hbc-active");
        window.dispatchEvent(new Event("nyan-halloween-choice-applied"));
      }, 1050);
    } catch (error) {
      errorLine.textContent = /Failed to fetch|abort|NetworkError/i.test(String(error))
        ? "Нет соединения с сервером. Попробуй ещё раз." : error.message;
      errorLine.hidden = false;
      buttons.forEach(item => {item.disabled = false;});
      sending = false;
      tg?.HapticFeedback?.notificationOccurred?.("error");
    }
  }

  for (const button of buttons) button.addEventListener("click",() => choose(button));
  window.addEventListener("nyan-wallet-ready",check);
  if (window.__nyanWalletReady) check();
})();
