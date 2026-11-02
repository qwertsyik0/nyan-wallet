(() => {
  'use strict';

  const API = 'https://nyan-wallet-bridge.qwertsyik.workers.dev';
  const tg = window.Telegram?.WebApp;
  tg?.ready?.();
  tg?.expand?.();
  const initData = tg?.initData || '';
  const $ = (id) => document.getElementById(id);
  const screens = ['loading', 'idle', 'join', 'waiting', 'locked', 'role', 'ended'];
  const actions = ['owner-open', 'owner-close', 'owner-finish'];
  let state = null;
  let busy = false;
  let checking = false;

  function showScreen(name) {
    screens.forEach((key) => { $(`${key}-screen`).hidden = key !== name; });
  }

  function notice(message) {
    $('notice').hidden = !message;
    $('notice').textContent = message || '';
    $('retry').hidden = !message;
  }

  function errorText(error) {
    if (error.name === 'AbortError') return 'сервер не ответил вовремя. попробуй ещё раз.';
    if (error instanceof TypeError) return 'не удалось связаться с сервером. проверь интернет.';
    return error.message || 'что-то пошло не так. попробуй снова.';
  }

  async function api(path, method = 'GET') {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 14000);
    try {
      const response = await fetch(`${API}${path}`, {
        method,
        headers: { 'X-Telegram-Init-Data': initData },
        cache: 'no-store',
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(typeof data.detail === 'string' ? data.detail : 'сервер временно недоступен');
        error.status = response.status;
        throw error;
      }
      return data;
    } finally {
      clearTimeout(timer);
    }
  }

  function display(data) {
    state = data;
    notice('');
    const phase = data.phase;
    $('round-number').textContent = data.round_id ? `РАУНД #${data.round_id}` : 'РАУНД —';
    $('live-indicator').textContent = ({ idle: 'ОЖИДАНИЕ', registration: 'НАБОР ОТКРЫТ', playing: 'ИГРА ИДЁТ', finished: 'ЗАВЕРШЕНО' })[phase] || 'ОЖИДАНИЕ';
    $('population').hidden = !data.round_id;
    $('player-count').textContent = `${data.players ?? 0} ${plural(data.players ?? 0)}`;

    if (phase === 'registration') showScreen(data.joined ? 'waiting' : 'join');
    else if (phase === 'playing') {
      if (data.joined && data.role) {
        $('role-card').classList.toggle('spy', data.role === 'spy');
        $('role-mark').textContent = data.role === 'spy' ? '⌁' : '✦';
        $('role-title').textContent = data.role === 'spy' ? 'ты — шпион' : 'ты — мирный';
        $('role-description').textContent = data.role === 'spy'
          ? 'остальные знают место, но ты — нет. слушай ответы, не выдавай себя и угадай локацию.'
          : 'осторожно отвечай на вопросы. вычисли шпиона и не раскрывай ему место.';
        $('location-panel').hidden = data.role !== 'local';
        $('location-name').textContent = data.role === 'local' ? (data.location || '') : '';
        showScreen('role');
      } else showScreen('locked');
    } else if (phase === 'finished') showScreen('ended');
    else showScreen('idle');

    $('owner-panel').hidden = !data.is_owner;
    $('owner-open').hidden = !(data.is_owner && (phase === 'idle' || phase === 'finished'));
    $('owner-close').hidden = !(data.is_owner && phase === 'registration');
    $('owner-finish').hidden = !(data.is_owner && (phase === 'registration' || phase === 'playing'));
    if (data.is_owner) {
      $('owner-help').textContent = phase === 'registration'
        ? `записано ${data.players} ${plural(data.players)}. закрыть набор можно от 3 участников.`
        : phase === 'playing' ? 'роли выданы всем участникам. когда закончите, заверши раунд.'
          : 'новый набор отправит в группу сообщение с кнопкой.';
      $('owner-close').disabled = phase === 'registration' && data.players < 3;
    }
  }

  function plural(number) {
    const n = Math.abs(number) % 100;
    const m = n % 10;
    if (n > 10 && n < 20) return 'участников';
    if (m === 1) return 'участник';
    if (m >= 2 && m <= 4) return 'участника';
    return 'участников';
  }

  async function refresh() {
    if (!initData || checking || busy) return;
    checking = true;
    try {
      const data = await api('/api/nyan-spy/status');
      display(data);
    } catch (error) {
      notice(errorText(error));
      if (!state) showScreen('loading');
    } finally {
      checking = false;
    }
  }

  async function act(path, message) {
    if (busy) return;
    if (message && !window.confirm(message)) return;
    busy = true;
    const button = document.activeElement;
    if (button instanceof HTMLButtonElement) button.disabled = true;
    notice('');
    try {
      await api(path, 'POST');
      tg?.HapticFeedback?.notificationOccurred?.('success');
      await refreshAfterAction();
    } catch (error) {
      notice(errorText(error));
    } finally {
      busy = false;
      if (button instanceof HTMLButtonElement) button.disabled = false;
    }
  }

  async function refreshAfterAction() {
    const data = await api('/api/nyan-spy/status');
    display(data);
  }

  $('join-button').addEventListener('click', () => act('/api/nyan-spy/join'));
  $('owner-open').addEventListener('click', () => act('/api/owner/nyan-spy/open', 'открыть регистрацию и отправить приглашение в группу?'));
  $('owner-close').addEventListener('click', () => act('/api/owner/nyan-spy/close', 'закрыть регистрацию и случайно распределить роли?'));
  $('owner-finish').addEventListener('click', () => act('/api/owner/nyan-spy/finish', 'завершить текущий раунд?'));
  $('retry').addEventListener('click', () => void refresh());

  if (!initData) {
    showScreen('idle');
    $('idle-screen').querySelector('h3').textContent = 'открой через Telegram';
    $('idle-screen').querySelector('p').textContent = 'для записи и получения роли требуется открыть страницу внутри бота.';
    $('open-telegram').hidden = false;
  } else {
    void refresh();
    window.setInterval(() => { if (!document.hidden) void refresh(); }, 6500);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
  }
})();
