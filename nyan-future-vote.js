(() => {
  'use strict';

  const API = 'https://nyan-wallet-bridge.qwertsyik.workers.dev';
  const tg = window.Telegram?.WebApp;
  const pledgeScreen = document.querySelector('#pledge-screen');
  const voteScreen = document.querySelector('#vote-screen');
  const completeScreen = document.querySelector('#complete-screen');
  const completeCopy = document.querySelector('#complete-copy');
  const completeReward = document.querySelector('#complete-reward');
  const accept = document.querySelector('#accept-pledge');
  const form = document.querySelector('#vote-form');
  const submit = document.querySelector('#submit-vote');
  const notice = document.querySelector('#notice');
  const telegramLink = document.querySelector('#open-telegram');

  tg?.ready?.();
  tg?.expand?.();

  const initData = tg?.initData || '';
  let checking = false;
  let submitted = false;
  let pledged = false;

  function message(value) {
    notice.textContent = value || '';
    notice.hidden = !value;
  }

  function finish(previous = false) {
    submitted = true;
    pledgeScreen.hidden = true;
    voteScreen.hidden = true;
    completeScreen.hidden = false;
    completeCopy.textContent = previous
      ? 'Ты уже голосовал(а). Твой выбор сохранён, награда начислена ранее.'
      : 'Спасибо! Твой выбор учтён, лапкоины начислены.';
    completeReward.textContent = previous ? 'ГОЛОС УЧТЁН' : '+100 🐾';
    message('');
    telegramLink.hidden = true;
  }

  async function request(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 16000);
    try {
      const response = await fetch(`${API}${path}`, {
        ...options,
        signal: controller.signal,
        cache: 'no-store',
        headers: {
          'X-Telegram-Init-Data': initData,
          ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message;
        const error = new Error(detail || 'Сервер не ответил. Попробуй ещё раз.');
        error.status = response.status;
        throw error;
      }
      return data;
    } finally {
      clearTimeout(timeout);
    }
  }

  function describe(error) {
    if (error?.name === 'AbortError') return 'Проверка заняла слишком много времени. Повтори попытку.';
    if (error?.message === 'Failed to fetch' || error instanceof TypeError) {
      return 'Нет соединения с сервером. Проверь сеть и попробуй снова.';
    }
    return error?.message || 'Не удалось связаться с сервером.';
  }

  async function checkStatus() {
    if (!initData || checking || submitted) return;
    checking = true;
    try {
      const result = await request('/api/nyan-future-vote/status');
      if (result.completed) finish(true);
      else message('');
    } catch (error) {
      message(describe(error));
    } finally {
      checking = false;
    }
  }

  accept.addEventListener('click', () => {
    if (submitted) return;
    pledged = true;
    pledgeScreen.hidden = true;
    voteScreen.hidden = false;
    message('');
    voteScreen.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (!initData) {
      message('Для голосования открой эту страницу через Telegram Mini App.');
      telegramLink.hidden = false;
      submit.disabled = true;
    }
  });

  form.addEventListener('change', () => {
    submit.disabled = !initData || !pledged || submitted || !form.elements.choice.value;
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!initData || !pledged || submitted || !form.elements.choice.value) return;

    submit.disabled = true;
    submit.querySelector('span').textContent = '…';
    message('');
    try {
      await request('/api/nyan-future-vote/submit', {
        method: 'POST',
        body: JSON.stringify({ choice: form.elements.choice.value, pledged: true }),
      });
      tg?.HapticFeedback?.notificationOccurred?.('success');
      finish();
    } catch (error) {
      if (error.status === 409) {
        finish(true);
        return;
      }
      message(describe(error));
      submit.disabled = false;
    } finally {
      submit.querySelector('span').textContent = '↗';
    }
  });

  if (initData) void checkStatus();
})();
