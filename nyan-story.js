(() => {
  'use strict';
  const API = 'https://nyan-wallet-bridge.qwertsyik.workers.dev';
  const tg = window.Telegram?.WebApp;
  tg?.ready?.();
  tg?.expand?.();
  const initData = tg?.initData || '';
  const $ = id => document.getElementById(id);
  let busy = false;

  const sections = ['loading-state', 'join-state', 'success-state', 'closed-state'];
  function show(section) {
    sections.forEach(id => { $(id).hidden = id !== section; });
  }
  function message(error) {
    if (error?.name === 'AbortError') return 'сервер долго не отвечает, попробуй ещё раз';
    if (error instanceof TypeError) return 'нет связи с сервером, проверь интернет';
    return error?.message || 'не удалось выполнить запрос';
  }
  function showError(text) {
    $('error').textContent = text;
    $('error').hidden = !text;
    $('retry-button').hidden = !text;
  }
  async function request(path, method = 'GET') {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 14000);
    try {
      const response = await fetch(API + path, {
        method,
        headers: {'X-Telegram-Init-Data': initData},
        cache: 'no-store', signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'сервис временно недоступен');
      return data;
    } finally { clearTimeout(timer); }
  }
  function display(data) {
    $('username').textContent = data.username ? data.username : 'юзернейм не указан';
    $('round-number').textContent = data.round_id ? String(data.round_id).padStart(3, '0') : '???';
    if (data.phase === 'registration') show(data.joined ? 'success-state' : 'join-state');
    else if (data.joined) {
      show('success-state');
      $('success-state').querySelector('p').textContent = 'набор закрыт. жди сообщения от ведущего.';
    } else {
      show('closed-state');
      $('closed-title').textContent = data.phase === 'closed' ? 'НАБОР ЗАВЕРШЁН.' : 'ДВЕРЬ ЗАКРЫТА.';
      $('closed-description').textContent = data.phase === 'closed' ? 'дождись следующей записи.' : 'регистрация ещё не началась.';
    }
    if (!data.username && data.phase === 'registration' && !data.joined) {
      $('join-button').disabled = true;
      showError('для записи установи публичный @username в Telegram и открой страницу снова.');
    }
  }
  async function refresh() {
    if (!initData || busy) return;
    show('loading-state');
    showError('');
    try { display(await request('/api/nyan-story/status')); }
    catch (error) { show('closed-state'); showError(message(error)); }
  }
  $('join-button').addEventListener('click', async () => {
    if (busy || !initData) return;
    busy = true;
    $('join-button').disabled = true;
    showError('');
    try {
      await request('/api/nyan-story/join', 'POST');
      const data = await request('/api/nyan-story/status');
      display(data);
      tg?.HapticFeedback?.notificationOccurred?.('success');
    } catch (error) {
      showError(message(error));
      tg?.HapticFeedback?.notificationOccurred?.('error');
    } finally { busy = false; $('join-button').disabled = false; }
  });
  $('retry-button').addEventListener('click', () => void refresh());
  if (!initData) {
    show('closed-state');
    $('username').textContent = 'нужен Telegram';
    $('closed-title').textContent = 'ОТКРОЙ В TELEGRAM.';
    $('closed-description').textContent = 'запись доступна только через кнопку в боте.';
    $('telegram-link').hidden = false;
  } else {
    const name = tg?.initDataUnsafe?.user?.username;
    if (name) $('username').textContent = name;
    void refresh();
  }
})();
