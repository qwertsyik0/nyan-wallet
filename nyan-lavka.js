(() => {
  'use strict';

  const API = 'https://nyan-wallet-bridge.qwertsyik.workers.dev';
  const tg = window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const PENDING_KEY = 'nyan-lavka-pending-v1';
  const goods = [
    { id: 'hint', image: './assets/nyan-lavka/hint.svg', title: 'подсказка Няника', short: 'намёк на решение загадки', details: 'Небольшая подсказка к одному из раундов. Иногда одного намёка достаточно, чтобы всё встало на место.', tag: 'бонус', kind: 'boost' },
    { id: 'chance', image: './assets/nyan-lavka/chance.svg', title: 'второй шанс', short: 'ещё одна попытка в раунде', details: 'Позволяет попробовать ответить ещё раз, если первая попытка оказалась неверной. Действует в одном раунде.', tag: 'бонус', kind: 'boost' },
    { id: 'box', image: './assets/nyan-lavka/box.svg', title: 'тайная коробка', short: 'содержимое неизвестно', details: 'Никто не знает, что внутри, пока коробка не будет открыта. Сюрприз может оказаться приятным.', tag: 'сюрприз', kind: 'secret' },
    { id: 'ticket', image: './assets/nyan-lavka/ticket.svg', title: 'дополнительный билет', short: 'больше шансов в финале', details: 'Дополнительный игровой билет для финального розыгрыша события.', tag: 'бонус', kind: 'boost' },
    { id: 'key', image: './assets/nyan-lavka/key.svg', title: 'золотой ключ', short: 'открывает тайный ящик', details: 'Ключ от одного из запертых ящиков. Что находится за замком, станет известно только во время события.', tag: 'редкое', kind: 'secret' },
    { id: 'letter', image: './assets/nyan-lavka/letter.svg', title: 'запечатанное письмо', short: 'важная часть истории', details: 'Кто-то оставил письмо без имени отправителя. Его содержимое может повлиять на развязку.', tag: 'секретное', kind: 'secret' },
    {"id":"time","image":"./assets/nyan-lavka/time.svg","title":"карманное время","short":"ещё 30 секунд на ответ","details":"Маленькие песочные часы добавляют 30 секунд к таймеру одного раунда. Чтобы успеть проверить свою догадку и не отвечать наугад.","tag":"бонус","kind":"boost","tone":"pink","isNew":true},
    {"id":"shield","image":"./assets/nyan-lavka/shield.svg","title":"щит удачи","short":"защита от одного штрафа","details":"Защищает от одного игрового штрафа за неверный ответ. После использования щит исчезает. На другие правила раунда не влияет.","tag":"защита","kind":"boost","tone":"lilac","isNew":true},
    {"id":"compass","image":"./assets/nyan-lavka/compass.svg","title":"лунный компас","short":"верное направление в истории","details":"Стрелка этого компаса указывает на один из верных путей в сюжетной развилке. Решение остаётся за тобой, но заблудиться будет сложнее.","tag":"секретное","kind":"secret","tone":"lilac","isNew":true},
    {"id":"magnifier","image":"./assets/nyan-lavka/magnifier.svg","title":"внимательный взгляд","short":"одна скрытая деталь загадки","details":"Няник покажет одну деталь, которую легко упустить в задании. Предмет помогает внимательнее посмотреть на загадку, но не раскрывает готовый ответ.","tag":"бонус","kind":"boost","tone":"pink","isNew":true},
    {"id":"map","image":"./assets/nyan-lavka/map.svg","title":"обрывок карты","short":"путь к спрятанному тайнику","details":"На старой карте отмечен тайник события. Собери подсказки из истории, чтобы понять, где он находится. Содержимое тайника пока остаётся секретом.","tag":"находка","kind":"secret","tone":"gold","isNew":true},
    {"id":"crystal","image":"./assets/nyan-lavka/crystal.svg","title":"розовый кристалл","short":"открывает скрытый фрагмент","details":"Если поднести кристалл к свету, можно увидеть скрытый фрагмент истории. Он поможет связать воедино события, о которых рассказали не всё.","tag":"редкое","kind":"secret","tone":"pink","isNew":true},
    {"id":"potion","image":"./assets/nyan-lavka/potion.svg","title":"эликсир спокойствия","short":"убирает один ложный вариант","details":"Убирает один неверный вариант в раунде с выбором ответа. Немного тишины в голове, немного уверенности и один шаг ближе к решению.","tag":"бонус","kind":"boost","tone":"lilac","isNew":true},
    {"id":"charm","image":"./assets/nyan-lavka/charm.svg","title":"талисман Няника","short":"личная записка перед финалом","details":"Талисман с маленькой лапкой хранит личную записку от Няника. Её можно открыть перед финальным раундом и узнать дополнительную деталь истории.","tag":"особое","kind":"secret","tone":"pink","isNew":true}
  ];
  const fallbackPrices = { hint: 120, chance: 190, box: 320, ticket: 260, key: 590, letter: 210, time: 90, shield: 240, compass: 280, magnifier: 150, map: 360, crystal: 450, potion: 230, charm: 380 };
  const dialog = $('product-dialog');
  let state = null;
  let filter = 'all';
  let query = '';
  let selected = null;
  let busy = false;
  let offset = 0;

  tg?.ready?.();
  tg?.expand?.();

  function auth() { return Boolean(tg?.initData); }
  function price(value) { return Number(value).toLocaleString('ru-RU') + ' лапкоинов'; }
  function priceNode(value) {
    const node = document.createElement('span');
    node.className = 'price-value';
    node.setAttribute('aria-label', value == null ? 'баланс пока недоступен' : price(value));
    const amount = document.createElement('span');
    amount.setAttribute('aria-hidden', 'true');
    amount.textContent = value == null ? '—' : Number(value).toLocaleString('ru-RU');
    const coin = document.createElement('img');
    coin.className = 'currency-icon';
    coin.src = './assets/lapcoin/lapcoin.webp';
    coin.alt = '';
    coin.setAttribute('aria-hidden', 'true');
    coin.width = 28;
    coin.height = 28;
    coin.decoding = 'async';
    node.append(amount, coin);
    return node;
  }
  function productCount(count) {
    const last = count % 10, two = count % 100;
    return count + ' ' + (last === 1 && two !== 11 ? 'товар' : last >= 2 && last <= 4 && (two < 12 || two > 14) ? 'товара' : 'товаров');
  }
  function live() { return !!state?.is_open && !!state?.closes_at && Date.now() + offset < Date.parse(state.closes_at); }
  function notice(message, error = false) {
    $('notice').textContent = message;
    $('notice').classList.toggle('error', error);
    $('notice').hidden = !message;
  }
  function pending() { try { return JSON.parse(sessionStorage.getItem(PENDING_KEY) || 'null'); } catch (_) { return null; } }
  function remember(item) { try { item ? sessionStorage.setItem(PENDING_KEY, JSON.stringify(item)) : sessionStorage.removeItem(PENDING_KEY); } catch (_) {} }
  async function request(path, method = 'GET', payload = null, authenticated = true) {
    if (authenticated && !auth()) throw new Error('Открой лавку через Telegram');
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), method === 'GET' ? 14000 : 23000);
    try {
      const response = await fetch(API + path, { method, headers: {
        ...(authenticated ? { 'X-Telegram-Init-Data': tg.initData } : {}),
        ...(payload ? { 'Content-Type': 'application/json' } : {})
      }, body: payload ? JSON.stringify(payload) : undefined, cache: 'no-store', signal: abort.signal });
      const json = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof json.detail === 'string' ? json.detail : `Ошибка сервера (${response.status})`);
      if (!json.ok) throw new Error('Не удалось прочитать данные лавки');
      return json;
    } catch (error) {
      if (abort.signal.aborted) throw new Error('Сервер долго отвечает');
      if (error instanceof TypeError) throw new Error('Нет соединения с Nyan Wallet');
      throw error;
    } finally { clearTimeout(timer); }
  }

  function itemFor(meta) { return state?.items?.find(item => item.sku === meta.id) || { sku: meta.id, price: fallbackPrices[meta.id], remaining: 0, total: 0, purchased: false }; }
  function tick() {
    const open = live();
    $('shop-status').textContent = open ? 'лавка открыта' : state?.has_opened ? 'лавка закрыта' : 'скоро открытие';
    $('shop-status').classList.toggle('is-open', open);
    if (open) {
      const seconds = Math.max(0, Math.ceil((Date.parse(state.closes_at) - Date.now() - offset) / 1000));
      $('countdown').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    } else $('countdown').textContent = '';
    if (selected && dialog.open && !$('dialog-note').classList.contains('error')) updateBuy();
  }

  function updateBuy() {
    if (!selected) return;
    const item = itemFor(selected);
    const button = $('dialog-buy');
    const note = $('dialog-note');
    const available = auth() && live() && !state?.blocked && !item.purchased && item.remaining > 0 && state?.balance != null && state.balance >= item.price;
    button.disabled = !available || busy;
    button.textContent = busy ? 'проверяем покупку…' : item.purchased ? 'уже куплено' : !live() ? 'лавка пока закрыта' : item.remaining <= 0 ? 'раскуплено' : !auth() ? 'открыть в Telegram' : state?.balance == null ? 'нет кошелька' : state.balance < item.price ? 'не хватает лапкоинов' : 'купить за ' + price(item.price);
    if (available && !busy) {
      button.textContent = 'купить за ';
      button.append(priceNode(item.price));
    }
    note.textContent = item.purchased ? 'этот предмет уже есть у тебя' : !live() ? 'покупки станут доступны после открытия лавки' : 'один экземпляр товара на аккаунт';
  }

  function showProduct(meta) {
    selected = meta;
    const item = itemFor(meta);
    $('dialog-category').textContent = meta.tag.toUpperCase();
    const icon = $('dialog-icon');
    icon.replaceChildren();
    const image = document.createElement('img');
    image.src = meta.image;
    image.alt = '';
    icon.append(image);
    $('dialog-title').textContent = meta.title;
    $('dialog-description').textContent = meta.details;
    $('dialog-price').replaceChildren(priceNode(item.price));
    $('dialog-icon').dataset.tone = meta.tone || (meta.id === 'key' ? 'gold' : ['chance', 'ticket'].includes(meta.id) ? 'lilac' : 'pink');
    $('dialog-note').classList.remove('error');
    updateBuy();
    dialog.showModal();
  }

  function render() {
    $('telegram-entry').hidden = auth();
    if (auth()) $('wallet-balance').replaceChildren(priceNode(state?.balance));
    else $('wallet-balance').textContent = 'в Telegram';
    const list = $('product-grid');
    list.replaceChildren();
    const filtered = goods.filter(meta => (filter === 'all' || meta.kind === filter) && (meta.title + ' ' + meta.short + ' ' + meta.tag).toLocaleLowerCase('ru-RU').includes(query));
    $('visible-count').textContent = productCount(filtered.length);
    if (!filtered.length) {
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = 'Ничего не нашлось. Попробуй другое название или категорию';
      list.append(empty);
    }
    filtered.forEach(meta => {
      const item = itemFor(meta);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'product';
      button.dataset.tone = meta.tone || (meta.id === 'key' ? 'gold' : ['chance', 'ticket'].includes(meta.id) ? 'lilac' : 'pink');
      if (live() && item.remaining <= 0) button.classList.add('is-sold-out');
      button.setAttribute('aria-label', `${meta.title}, ${price(item.price)}, подробнее`);
      const icon = document.createElement('span');
      icon.className = 'product-icon';
      icon.setAttribute('aria-hidden', 'true');
      const image = document.createElement('img');
      image.src = meta.image;
      image.alt = '';
      image.loading = 'lazy';
      icon.append(image);
      const art = document.createElement('span');
      art.className = 'product-art';
      art.setAttribute('aria-hidden', 'true');
      art.append(icon);
      if (meta.isNew) {
        const badge = document.createElement('span');
        badge.className = 'new-label';
        badge.textContent = 'новое';
        art.append(badge);
      }
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = meta.tag;
      const title = document.createElement('h3');
      title.textContent = meta.title;
      const desc = document.createElement('p');
      desc.textContent = meta.short;
      const bottom = document.createElement('span');
      bottom.className = 'product-bottom';
      const cost = document.createElement('strong');
      cost.className = 'product-price';
      cost.append(priceNode(item.price));
      const arrow = document.createElement('span');
      arrow.className = 'product-detail';
      arrow.setAttribute('aria-hidden', 'true');
      arrow.innerHTML = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 11v5m0-9v.1"/></svg>';
      bottom.append(cost, arrow);
      button.append(art, tag, title, desc, bottom);
      button.addEventListener('click', () => showProduct(meta));
      list.append(button);
    });
    ownerControls();
    tick();
  }

  function ownerControls() {
    $('owner-panel').hidden = !state?.is_owner;
    if (!state?.is_owner) return;
    $('owner-open').disabled = state.has_opened || !state.ready;
    $('owner-close').disabled = !live();
    const stock = $('owner-stock');
    stock.replaceChildren();
    goods.forEach(meta => {
      const item = itemFor(meta);
      const row = document.createElement('div');
      row.className = 'owner-stock-row';
      const label = document.createElement('label');
      label.textContent = meta.title;
      const input = document.createElement('input');
      input.type = 'number';
      input.min = '0';
      input.max = '100000';
      input.value = String(item.total);
      input.disabled = state.has_opened;
      const save = document.createElement('button');
      save.type = 'button';
      save.textContent = 'сохранить';
      save.disabled = state.has_opened;
      save.addEventListener('click', async () => {
        if (busy) return;
        try { await request('/api/nyan-lavka/owner/stock', 'POST', { sku: meta.id, total: Number(input.value) }); await refresh(); notice('Остаток обновлён'); }
        catch (error) { notice(error.message, true); }
      });
      row.append(label, input, save);
      stock.append(row);
    });
  }

  async function refresh(silent = false) {
    try {
      const data = await request(auth() ? '/api/nyan-lavka/status' : '/api/nyan-lavka/catalog', 'GET', null, auth());
      offset = Date.parse(data.server_now) - Date.now();
      state = data;
      render();
      if (data.blocked) notice('Покупки для аккаунта недоступны', true);
      else if (!silent) notice('');
    } catch (error) {
      if (!silent) notice(error.message || 'Лавка временно недоступна', true);
      render();
    }
  }

  async function buy() {
    if (!selected || busy || !auth() || !live()) return;
    const item = itemFor(selected);
    if (item.purchased || item.remaining <= 0 || state.balance < item.price) return;
    if (!window.confirm(`Купить «${selected.title}» за ${price(item.price)}? Сумма будет списана с Nyan Wallet.`)) return;
    const existing = pending();
    const payload = existing?.sku === selected.id ? existing : { sku: selected.id, request_key: 'lavka_' + crypto.randomUUID().replace(/-/g, '') };
    remember(payload);
    busy = true;
    updateBuy();
    let purchaseError = '';
    try {
      const result = await request('/api/nyan-lavka/buy', 'POST', payload);
      remember(null);
      dialog.close();
      selected = null;
      tg?.HapticFeedback?.notificationOccurred?.('success');
      await refresh(true);
      notice(`Куплено за ${price(result.purchase.price)}. Остаток: ${price(result.purchase.balance)}.`);
    } catch (error) {
      const uncertain = /соединени|долго отвечает|fetch/i.test(error.message || '');
      if (!uncertain) remember(null);
      purchaseError = error.message + (uncertain ? ' Повторное списание при повторе исключено.' : '');
    } finally {
      busy = false;
      updateBuy();
      if (purchaseError) {
        $('dialog-note').textContent = purchaseError;
        $('dialog-note').classList.add('error');
      }
    }
  }

  async function ownerAction(path, payload, confirmation) {
    if (!state?.is_owner || !window.confirm(confirmation)) return;
    try { await request(path, 'POST', payload); await refresh(); notice('Готово'); }
    catch (error) { notice(error.message, true); }
  }

  async function ownerOrders() {
    if (!state?.is_owner) return;
    try {
      const data = await request('/api/nyan-lavka/owner/orders');
      const box = $('owner-orders-list');
      box.replaceChildren();
      for (const order of data.orders) {
        const row = document.createElement('div');
        row.className = 'owner-order';
        row.textContent = `${order.username ? '@' + order.username : order.telegram_id} · ${order.title} · ${price(order.price)}`;
        if (!order.redeemed) {
          const button = document.createElement('button');
          button.type = 'button';
          button.textContent = 'отметить выданным';
          button.addEventListener('click', async () => {
            if (!window.confirm('Отметить предмет выданным?')) return;
            try { await request(`/api/nyan-lavka/owner/orders/${order.id}/redeem`, 'POST'); await ownerOrders(); }
            catch (error) { notice(error.message, true); }
          });
          row.append(document.createElement('br'), button);
        }
        box.append(row);
      }
      if (!data.orders.length) box.textContent = 'покупок пока нет';
      box.hidden = false;
    } catch (error) { notice(error.message, true); }
  }

  $('catalog-search').addEventListener('input', event => {
    query = event.target.value.trim().toLocaleLowerCase('ru-RU');
    render();
  });
  document.querySelectorAll('.filter').forEach(button => {
    button.querySelector('.filter-count').textContent = String(goods.filter(meta => button.dataset.filter === 'all' || meta.kind === button.dataset.filter).length);
  });
  document.querySelectorAll('.filter').forEach(button => button.addEventListener('click', () => {
    filter = button.dataset.filter;
    document.querySelectorAll('.filter').forEach(other => {
      const active = other === button;
      other.classList.toggle('is-active', active);
      other.setAttribute('aria-pressed', String(active));
    });
    render();
  }));
  $('dialog-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
  tg?.BackButton?.show?.();
  tg?.BackButton?.onClick?.(() => {
    if (dialog.open) { dialog.close(); return; }
    const target = new URL('./index.html', location.href);
    target.hash = location.hash;
    location.replace(target.toString());
  });
  $('dialog-buy').addEventListener('click', () => void buy());
  $('owner-open').addEventListener('click', () => void ownerAction('/api/nyan-lavka/owner/open', { minutes: Number($('owner-minutes').value) }, 'Открыть лавку? Повторного запуска не будет.'));
  $('owner-close').addEventListener('click', () => void ownerAction('/api/nyan-lavka/owner/close', null, 'Закрыть лавку досрочно?'));
  $('owner-orders').addEventListener('click', () => void ownerOrders());
  setInterval(tick, 500);
  setInterval(() => { if (!document.hidden && !busy) void refresh(true); }, 10000);
  (async () => {
    if (auth() && pending()) {
      try { await request('/api/nyan-lavka/buy', 'POST', pending()); remember(null); }
      catch (error) { if (!/соединени|долго отвечает/i.test(error.message || '')) remember(null); }
    }
    await refresh();
  })();
})();
