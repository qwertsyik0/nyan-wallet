(() => {
  "use strict";
  const API = "https://nyan-wallet-153-76-175-145.sslip.io";
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const authenticated = Boolean(tg?.initData);
  const BUTTON_LINK = "https://t.me/nyancash_bot?startapp=nyanik_skins";
  const previews = [
    {sku:"moon_sail",title:"Лунный парус",description:"Ночной залив и лодка в лунном свете",image:"./assets/wallet-skins/nyanik-moon-sail.webp"},
    {sku:"lighthouse",title:"Тихий маяк",description:"Маяк на берегу в винных оттенках",image:"./assets/wallet-skins/nyanik-lighthouse.webp"},
    {sku:"balloon",title:"Тихое небо",description:"Воздушный шар и хвойные оттенки",image:"./assets/wallet-skins/nyanik-balloon.webp"},
    {sku:"arch",title:"Арка воспоминаний",description:"Каменная арка в тёплых терракотовых тонах",image:"./assets/wallet-skins/nyanik-arch.webp"},
  ];
  let state = {ready:false,balance:null,blocked:false,items:previews.map(p => ({...p,total:6,remaining:6,price:500,available:false,purchased:false}))};
  let loading = false;
  let pending = false;
  let selection = null;
  tg?.ready?.();
  tg?.expand?.();

  const node = (tag, className, value) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = String(value);
    return element;
  };
  const setNotice = (message, kind="") => {
    $("notice").textContent = message;
    $("notice").className = `notice ${kind}`;
  };
  const messageOf = error => /Failed to fetch|NetworkError|Load failed|abort/i.test(String(error.message)) ? "Не удалось соединиться с сервером. Попробуй ещё раз." : error.message;

  async function request(path, method="GET", data) {
    if (method !== "GET" && !authenticated) throw new Error("Открой лавку в Telegram, чтобы купить фон.");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(),method === "GET" ? 14000 : 28000);
    try {
      const response = await fetch(`${API}${path}`,{
        method, cache:"no-store", signal:controller.signal,
        headers:{...(authenticated ? {"X-Telegram-Init-Data":tg.initData} : {}), ...(data ? {"Content-Type":"application/json"} : {})},
        body:data ? JSON.stringify(data) : undefined,
      });
      const json = await response.json().catch(() => ({}));
      if (!response.ok || !json.ok) throw new Error(typeof json.detail === "string" ? json.detail : `Ошибка сервера (${response.status})`);
      return json;
    } finally { window.clearTimeout(timeout); }
  }

  function walletPreview(image,title) {
    const section = node("div","wallet-preview");
    section.style.setProperty("--skin-image", `url("${image}")`);
    section.setAttribute("role","img");
    section.setAttribute("aria-label",`Предпросмотр карточки Nyan Wallet с фоном «${title}»`);
    section.innerHTML = '<div class="wallet-top"><div class="wallet-brand"><div class="wallet-mark" aria-hidden="true">🐾</div><div><div class="preview-name">Nyan Wallet</div><div class="preview-type">карта экосистемы Нян</div></div></div><span class="preview-status">Участник Нян</span></div><div class="wallet-middle"><div class="preview-label">ваш баланс</div><div class="preview-amount">2 450 <span>🐾</span></div><div class="preview-units">лапкоинов</div></div><div class="wallet-bottom"><div><div class="detail-label">номер кошелька</div><div class="preview-number">NYAN 0000 0000 0000</div></div><div class="wallet-owner"><div class="detail-label">владелец</div><div class="preview-holder">пользователь</div></div></div>';
    return section;
  }

  function render() {
    $("user-balance").textContent = state.balance == null ? (authenticated ? "— 🐾" : "в Telegram") : `${Number(state.balance).toLocaleString("ru-RU")} 🐾`;
    $("telegram-entry").hidden = authenticated;
    if (!authenticated) setNotice("Посмотри фоны здесь, а для покупки открой страницу через Telegram.");
    else if (state.blocked) setNotice("Покупки недоступны для этого аккаунта.","error");
    else if (state.balance === null) setNotice("Сначала открой Nyan Wallet, чтобы создать кошелёк.","error");
    else if (!state.ready) setNotice("Лавка готовится к открытию. Обнови страницу чуть позже.");
    else setNotice("Выбери фон и нажми «Купить». Каждый представлен всего в шести экземплярах.");
    const products = $("products");
    products.replaceChildren();
    for (const item of state.items) {
      const product = node("article","product");
      const heading = node("div","product-head");
      const titleWrap = node("div","");
      titleWrap.append(node("div","product-name",item.title),node("p","product-desc",item.description));
      const stock = node("span",`stock${item.remaining === 0 ? " out" : ""}`,`осталось ${item.remaining} из ${item.total}`);
      heading.append(titleWrap,stock);
      const row = node("div","purchase-row");
      const price = node("div","price",`${item.price} 🐾`);
      price.append(node("small","", "за один экземпляр"));
      const owned = !!item.purchased;
      const sold = item.remaining < 1;
      const insufficient = state.balance !== null && state.balance < item.price;
      const btn = node("button",`buy-button${owned ? " owned" : ""}`,owned ? "✓ Куплено" : sold ? "Раскуплено" : insufficient && authenticated ? "Мало 🐾" : !authenticated ? "В Telegram" : "Купить");
      btn.type = "button";
      btn.disabled = pending || loading || !state.ready || !item.available || owned || sold || (authenticated && (state.blocked || insufficient || state.balance === null));
      if (!authenticated && item.available && state.ready && !sold) btn.disabled = false;
      btn.addEventListener("click",() => authenticated ? openConfirm(item.sku) : window.location.assign(BUTTON_LINK));
      row.append(price,btn);
      product.append(heading,walletPreview(item.image,item.title),row);
      products.append(product);
    }
  }

  async function refresh(silent=false) {
    if (loading || pending) return;
    loading = true;
    $("refresh").disabled = true;
    let feedback = null;
    try {
      const result = await request(authenticated ? "/api/nyanik-skins/status" : "/api/nyanik-skins/catalog");
      const images = Object.fromEntries(previews.map(p => [p.sku,p.image]));
      state = {...result,items:result.items.map(item => ({...item,image:images[item.sku] || item.image}))};
      if (!silent) feedback = ["Остатки обновлены.","success"];
    } catch (error) {
      feedback = [messageOf(error),"error"];
    } finally {
      loading = false;
      $("refresh").disabled = false;
      render();
      if (feedback) setNotice(...feedback);
    }
  }

  function openConfirm(sku) {
    if (pending || !authenticated) return;
    selection = state.items.find(item => item.sku === sku);
    if (!selection || selection.purchased || selection.remaining < 1 || state.blocked || state.balance < selection.price) return;
    $("modal-heading").textContent = `«${selection.title}»`;
    $("modal-desc").textContent = `За 500 🐾 фон появится в коллекции и сразу установится на твой кошелёк. Осталось ${selection.remaining} из ${selection.total}.`;
    $("modal-notice").textContent = "";
    $("confirm-modal").hidden = false;
  }

  function closeConfirm() {
    if (pending) return;
    $("confirm-modal").hidden = true;
    selection = null;
  }

  function requestKey(sku) {
    const key = `nyanik-skins-pending-v1:${tg?.initDataUnsafe?.user?.id || "anon"}:${sku}`;
    let value = window.sessionStorage.getItem(key);
    if (!value) {
      value = window.crypto?.randomUUID?.().replaceAll("-","") || `${Date.now()}_${Math.random().toString(36).slice(2)}_${Math.random().toString(36).slice(2)}`;
      window.sessionStorage.setItem(key,value);
    }
    return {key,value};
  }

  async function purchase() {
    if (pending || !selection) return;
    const sku = selection.sku;
    const {key,value} = requestKey(sku);
    pending = true;
    $("confirm-buy").disabled = true;
    $("cancel-buy").disabled = true;
    $("confirm-buy").textContent = "Покупаем…";
    try {
      const result = await request("/api/nyanik-skins/buy","POST",{sku,request_key:value});
      window.sessionStorage.removeItem(key);
      $("confirm-modal").hidden = true;
      selection = null;
      state.balance = result.balance;
      const item = state.items.find(entry => entry.sku === sku);
      if (item) {item.purchased = true; if (typeof result.remaining === "number") item.remaining = result.remaining;}
      tg?.HapticFeedback?.notificationOccurred?.("success");
      render();
      setNotice("Фон куплен и установлен! Найти его можно в настройках кошелька.","success");
    } catch (error) {
      $("modal-notice").textContent = messageOf(error);
      tg?.HapticFeedback?.notificationOccurred?.("error");
    } finally {
      pending = false;
      $("confirm-buy").disabled = false;
      $("cancel-buy").disabled = false;
      $("confirm-buy").textContent = "Купить";
    }
  }

  $("refresh").addEventListener("click",()=>refresh());
  $("cancel-buy").addEventListener("click",closeConfirm);
  $("modal-shade").addEventListener("click",closeConfirm);
  $("confirm-buy").addEventListener("click",purchase);
  $("telegram-entry").href = BUTTON_LINK;
  render();
  refresh(true);
  window.setInterval(() => {if (document.visibilityState === "visible" && $("confirm-modal").hidden) refresh(true);},45000);
})();
