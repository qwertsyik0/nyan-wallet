(() => {
  "use strict";

  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const SECTORS = [10, 25, 50, 100, 0, 200, 25, 500];
  const COLORS = ["#f8e1e9", "#fff0d8", "#f0cfdc", "#e9e3f8", "#ebe8f0", "#fae4ec", "#f5dec1", "#ded7f5"];
  const PENDING_KEY = "nyan-fortune-pending-v1";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const rotor = $("fortune-rotor");
  const button = $("fortune-spin");
  const message = $("fortune-message");
  const timer = $("fortune-timer");
  let auth = tg?.initData || "";
  let nextAt = null;
  let blocked = false;
  let busy = false;
  let currentRotation = 0;

  tg?.ready?.();
  tg?.expand?.();

  function drawWheel() {
    const svg = $("fortune-wheel");
    const ns = "http://www.w3.org/2000/svg";
    function node(name, attrs, content) {
      const e = document.createElementNS(ns, name);
      for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
      if (content !== undefined) e.textContent = content;
      svg.append(e);
    }
    const center = 300;
    const radius = 290;
    const point = (r, degrees) => {
      const rad = degrees * Math.PI / 180;
      return [center + r * Math.cos(rad), center + r * Math.sin(rad)];
    };
    SECTORS.forEach((amount, i) => {
      const start = -90 + i * 45;
      const end = start + 45;
      const [x1, y1] = point(radius, start);
      const [x2, y2] = point(radius, end);
      node("path", {
        d: `M${center} ${center} L${x1} ${y1} A${radius} ${radius} 0 0 1 ${x2} ${y2} Z`,
        fill: COLORS[i], stroke: "#fff", "stroke-width": "5", "stroke-linejoin": "round",
      });
      const [cx, cy] = point(200, start + 22.5);
      node("text", {
        x: cx, y: cy, "text-anchor": "middle", "dominant-baseline": "central",
        fill: "#795f72", "font-size": "29", "font-family": "Arial, sans-serif", "font-weight": "650",
      }, String(amount));
      // 🐾 is the exact currency emoji used by Nyan Wallet, not a drawn paw icon.
      node("text", {
        x: cx, y: cy + 29, "text-anchor": "middle", "dominant-baseline": "central",
        "font-size": "23", "font-family": "Apple Color Emoji, Segoe UI Emoji, Noto Color Emoji, sans-serif",
      }, "🐾");
    });
    node("circle", { cx: center, cy: center, r: radius, fill: "none", stroke: "#fff", "stroke-width": "6" });
  }

  function setMessage(value) { message.textContent = value || ""; }

  function formatWait(ms) {
    const seconds = Math.max(0, Math.ceil(ms / 1000));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor(seconds % 3600 / 60);
    const rest = seconds % 60;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }

  function refreshControls() {
    if (busy) return;
    if (blocked) {
      timer.textContent = "Участие недоступно";
      button.disabled = true;
      return;
    }
    if (pendingKey()) {
      timer.textContent = "Незавершённое вращение можно восстановить";
      button.disabled = !auth;
      button.textContent = "Восстановить вращение";
      return;
    }
    const wait = nextAt ? new Date(nextAt).getTime() - Date.now() : 0;
    const available = wait <= 0;
    timer.textContent = available ? "Бесплатное вращение доступно" : `Следующая попытка через ${formatWait(wait)}`;
    button.disabled = !available || !auth;
    button.textContent = available ? "Крутить бесплатно" : "Уже вращали сегодня";
  }

  async function api(path, method = "GET", payload = null) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), method === "GET" ? 20000 : 30000);
    try {
      const response = await fetch(API + path, {
        method, headers: { "X-Telegram-Init-Data": auth, ...(payload ? { "Content-Type": "application/json" } : {}) },
        body: payload ? JSON.stringify(payload) : undefined,
        cache: "no-store", signal: controller.signal,
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = data?.detail;
        const error = new Error(typeof detail === "string" ? detail : detail?.message || `Ошибка сервера ${response.status}`);
        if (detail?.next_at) error.nextAt = detail.next_at;
        throw error;
      }
      if (!data?.ok) throw new Error("Некорректный ответ сервера");
      return data;
    } catch (error) {
      if (controller.signal.aborted) throw new Error("Сервер долго отвечает. Попробуй ещё раз.");
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function pendingKey() {
    try { return sessionStorage.getItem(PENDING_KEY) || ""; } catch (_) { return ""; }
  }
  function savePending(key) {
    try { sessionStorage.setItem(PENDING_KEY, key); } catch (_) {}
  }
  function clearPending() {
    try { sessionStorage.removeItem(PENDING_KEY); } catch (_) {}
  }
  function showResult(spin) {
    $("fortune-result").hidden = false;
    $("fortune-prize").textContent = `+${spin.reward} 🐾`;
    $("fortune-result-description").textContent = spin.reward
      ? "Лапкоины уже начислены на твой кошелёк."
      : "В этот раз без награды. Возвращайся завтра!";
  }

  function showPreviousPosition(spin) {
    if (!spin || !Number.isInteger(spin.sector_index) || SECTORS[spin.sector_index] !== spin.reward) return;
    currentRotation = ((-22.5 - 45 * spin.sector_index) % 360 + 360) % 360;
    rotor.style.transition = "none";
    rotor.style.transform = `rotate(${currentRotation}deg)`;
  }

  async function animateTo(spin) {
    if (!Number.isInteger(spin.sector_index) || SECTORS[spin.sector_index] !== spin.reward) {
      throw new Error("Результат не совпадает с секторами колеса");
    }
    // Sector zero is centered at -67.5°, while the stationary pointer is -90°.
    const stop = -22.5 - 45 * spin.sector_index;
    const remainder = ((stop - currentRotation) % 360 + 360) % 360;
    const target = currentRotation + 6 * 360 + remainder;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    rotor.style.transition = reduce ? "none" : "transform 8s cubic-bezier(.12,.72,.12,1)";
    // Ensure a visible start and an 8-second smooth deceleration.
    void rotor.offsetWidth;
    rotor.style.transform = `rotate(${target}deg)`;
    currentRotation = target;
    if (!reduce) await new Promise(resolve => setTimeout(resolve, 8000));
  }

  async function spin() {
    if (busy || button.disabled || !auth) return;
    busy = true;
    button.disabled = true;
    button.textContent = "Подготавливаем колесо…";
    $("fortune-result").hidden = true;
    setMessage("");
    let key = pendingKey();
    if (!key) {
      const uuid = window.crypto?.randomUUID?.();
      if (uuid) key = uuid.replaceAll("-", "");
      else if (window.crypto?.getRandomValues) {
        const bytes = new Uint8Array(16);
        window.crypto.getRandomValues(bytes);
        key = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
      }
    }
    if (!key || key.length < 16) {
      busy = false;
      refreshControls();
      setMessage("Не удалось подготовить защищённое вращение. Перезапусти страницу.");
      return;
    }
    savePending(key);
    try {
      const result = await api("/api/fortune/spin", "POST", { request_key: key });
      nextAt = result.next_at;
      timer.textContent = "Колесо вращается…";
      button.textContent = "Вращается…";
      await animateTo(result.spin);
      clearPending();
      showResult(result.spin);
      setMessage(result.spin.reward ? `Поздравляем! +${result.spin.reward} 🐾` : "Сегодня удача решила отдохнуть ♡");
    } catch (error) {
      if (error.nextAt) nextAt = error.nextAt;
      // A network timeout could occur after the award was committed. Keep the
      // same key so retrying cannot produce another award.
      if (error.nextAt) clearPending();
      setMessage(error.message || "Не удалось завершить вращение");
    } finally {
      busy = false;
      refreshControls();
    }
  }

  async function initialize() {
    drawWheel();
    if (!auth) {
      $("fortune-login").hidden = false;
      timer.textContent = "Открой игру через Telegram";
      setMessage("Без подтверждённого Telegram-аккаунта вращение недоступно.");
      return;
    }
    button.addEventListener("click", spin);
    try {
      const data = await api("/api/fortune");
      nextAt = data.next_at;
      blocked = data.blocked;
      window.setInterval(refreshControls, 1000);
      if (data.last_spin) {
        showResult(data.last_spin);
        showPreviousPosition(data.last_spin);
      }
      // In-flight request retries use the exact same key as the original POST.
      if (pendingKey() && !blocked) {
        refreshControls();
        return;
      }
      refreshControls();
    } catch (error) {
      setMessage(error.message);
      timer.textContent = "Не удалось проверить попытку";
      button.disabled = true;
    }
  }

  initialize();
})();
