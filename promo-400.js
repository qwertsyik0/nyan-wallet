(() => {
  "use strict";

  const tg = window.Telegram?.WebApp;
  const API = "https://nyan-wallet-api.onrender.com";
  const CODE = "NYAN400";
  const btn = document.getElementById("activate");
  const status = document.getElementById("status");

  let busy = false;

  tg?.ready?.();
  tg?.expand?.();

  function setStatus(text, type = "") {
    status.textContent = text || "";
    status.className = "status" + (type ? " " + type : "");
  }

  function headers() {
    return {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": tg?.initData || ""
    };
  }

  function ready() {
    if (!tg?.initData) {
      btn.disabled = true;
      btn.textContent = "откройте через Telegram";
      setStatus("эта страница работает только внутри Telegram.", "error");
      return;
    }
    btn.disabled = false;
    btn.textContent = "активировать";
    tg?.MainButton?.setText?.("АКТИВИРОВАТЬ");
    tg?.MainButton?.enable?.();
    tg?.MainButton?.show?.();
  }

  async function activate() {
    if (busy || !tg?.initData) return;
    busy = true;
    btn.disabled = true;
    btn.textContent = "активируем…";
    tg?.MainButton?.disable?.();
    tg?.MainButton?.showProgress?.();
    setStatus("");

    try {
      const response = await fetch(API + "/api/promo/redeem", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ code: CODE })
      });

      let data = {};
      try { data = await response.json(); } catch (_) {}

      if (!response.ok) {
        if (response.status === 409) {
          window.location.replace("./promo-400-secret.html?used=1");
          return;
        }
        throw new Error(data?.detail || "не удалось активировать промокод");
      }

      try {
        sessionStorage.setItem("nyan400_reward", String(data?.reward ?? 50));
      } catch (_) {}

      tg?.HapticFeedback?.notificationOccurred?.("success");
      window.location.replace("./promo-400-secret.html");
    } catch (error) {
      btn.disabled = false;
      btn.textContent = "повторить";
      tg?.MainButton?.enable?.();
      setStatus(error?.message || "что-то пошло не так.", "error");
      tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
      busy = false;
      tg?.MainButton?.hideProgress?.();
    }
  }

  btn?.addEventListener("click", activate);
  tg?.MainButton?.onClick?.(activate);
  ready();
})();
