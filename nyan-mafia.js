(() => {
  'use strict';

  const API = 'https://nyan-wallet-bridge.qwertsyik.workers.dev';
  const IMAGE_ROOT = './assets/nyan-mafia/';
  const tg = window.Telegram?.WebApp;
  tg?.ready?.();
  tg?.expand?.();
  const initData = tg?.initData || '';
  const ownId = Number(tg?.initDataUnsafe?.user?.id || 0);
  const $ = (id) => document.getElementById(id);
  const ROLE_ACTIONS = {
    mafia: 'ночная цель мафии', don: 'ночная цель мафии', maniac: 'кого устранить',
    commissioner: 'кого проверить', doctor: 'кого спасти', bodyguard: 'кого защитить',
    journalist: 'выбери двух игроков для сравнения', lover: 'кого заблокировать',
    lawyer: 'кого защитить от изгнания', kamikaze: 'кого забрать с собой',
  };
  const PHASES = {
    idle: ['ожидаем начало', 'ведущий ещё не объявил регистрацию.'],
    registration: ['набор участников', 'займи место до закрытия записи. после этого система случайно выдаст роли.'],
    night: ['город засыпает', 'проверь свою роль ниже. если у неё есть действие, выбери цель и нажми «подтвердить выбор». мафия общается в отдельной вкладке чата.'],
    day: ['город просыпается', 'пролистай ниже до «игровой чат», обсуди события с остальными и найди подозреваемого.'],
    vote: ['время голосовать', 'найди раздел «твой голос» ниже, выбери игрока и нажми «подтвердить выбор».'],
    finished: ['игра окончена', 'все роли раскрыты. спасибо за игру!'],
  };
  const NAMES = { idle: 'ОЖИДАНИЕ', registration: 'НАБОР', night: 'НОЧЬ', day: 'ДЕНЬ', vote: 'ГОЛОСОВАНИЕ', finished: 'ФИНАЛ' };
  const ROLES = new Set(['civilian', 'mafia', 'don', 'doctor', 'commissioner', 'bodyguard', 'maniac', 'journalist', 'lover', 'immortal', 'lawyer', 'kamikaze']);
  const ROLE_NAMES = { civilian: 'мирный житель', mafia: 'мафия', don: 'дон', doctor: 'доктор', commissioner: 'комиссар', bodyguard: 'телохранитель', maniac: 'маньяк', journalist: 'журналист', lover: 'любовница', immortal: 'бессмертный', lawyer: 'адвокат', kamikaze: 'камикадзе' };

  let state = null;
  let channel = 'public';
  let busy = false;
  let checking = false;
  let loadingChat = false;
  let sendPending = false;
  let lastSentAt = 0;
  let renderedChatKey = '';
  let revealed = false;
  let selected = [];
  let selectionHydrated = false;
  let lastPhase = '';
  let lastRound = 0;
  const cachedMessages = { public: [], mafia: [] };
  const cursor = { public: 0, mafia: 0 };

  function errorText(err) {
    if (err.name === 'AbortError') return 'сервер долго не отвечает, попробуй ещё раз.';
    if (err instanceof TypeError) return 'нет соединения с сервером. проверь интернет.';
    return err.message || 'что-то пошло не так.';
  }

  async function api(path, method = 'GET', body = undefined) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 14000);
    try {
      const response = await fetch(`${API}${path}`, {
        method, cache: 'no-store', signal: controller.signal,
        headers: {
          'X-Telegram-Init-Data': initData,
          ...(body ? { 'Content-Type': 'application/json' } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      const json = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof json.detail === 'string' ? json.detail : `ошибка ${response.status}`);
      return json;
    } finally {
      clearTimeout(timeout);
    }
  }

  function notice(message) {
    $('error').hidden = !message;
    $('error').textContent = message || '';
    $('retry').hidden = !message;
  }

  function chatFeedback(message = '', type = '') {
    const feedback = $('chat-feedback');
    feedback.hidden = !message;
    feedback.textContent = message;
    feedback.dataset.type = type;
  }

  function avatar(player, compact = false) {
    const imageUrl = player.photo_url;
    const el = document.createElement(imageUrl ? 'img' : 'span');
    el.className = 'avatar';
    if (compact) el.style.width = el.style.height = '29px';
    if (imageUrl) {
      el.src = imageUrl;
      el.alt = '';
      el.loading = 'lazy';
      el.referrerPolicy = 'no-referrer';
      el.addEventListener('error', () => {
        const fallback = document.createElement('span');
        fallback.className = 'avatar';
        if (compact) fallback.style.width = fallback.style.height = '29px';
        fallback.textContent = (player.name || '?').slice(0, 1).toUpperCase();
        el.replaceWith(fallback);
      }, { once: true });
    } else {
      el.textContent = (player.name || '?').slice(0, 1).toUpperCase();
    }
    return el;
  }

  function nick(player) {
    return player.username ? `@${player.username}` : `ID ${player.id}`;
  }

  function canOpenProfile(player) {
    return typeof player.username === 'string' && /^[A-Za-z0-9_]{5,32}$/.test(player.username);
  }

  function openProfile(player) {
    if (!canOpenProfile(player)) return;
    const link = `https://t.me/${player.username}`;
    if (tg?.openTelegramLink) tg.openTelegramLink(link);
    else window.open(link, '_blank', 'noopener,noreferrer');
  }

  function renderPlayers() {
    const container = $('players');
    container.replaceChildren();
    $('player-total').textContent = `${state.players.length} / 20`;
    if (!state.players.length) {
      const empty = document.createElement('div');
      empty.className = 'chat-empty';
      empty.textContent = 'пока никого нет. стань первым участником!';
      container.append(empty);
    }
    for (const player of state.players) {
      const el = document.createElement(canOpenProfile(player) ? 'button' : 'div');
      if (el instanceof HTMLButtonElement) {
        el.type = 'button';
        el.addEventListener('click', () => openProfile(player));
        el.title = `открыть Telegram-профиль ${nick(player)}`;
      }
      const isAlly = Boolean(state.mafia_team?.includes(player.id) && player.id !== ownId);
      el.className = `player${!player.alive ? ' is-dead' : ''}${player.id === ownId ? ' self' : ''}${isAlly ? ' is-ally' : ''}`;
      el.append(avatar(player));
      const details = document.createElement('span');
      details.className = 'player-name';
      const name = document.createElement('strong');
      name.textContent = player.name;
      const user = document.createElement('small');
      user.textContent = player.id === ownId ? 'ты' : nick(player);
      if (!player.alive) user.textContent += ' · выбыл';
      const revealedRole = state.revealed_roles?.[String(player.id)];
      if (revealedRole && ROLE_NAMES[revealedRole]) user.textContent += ` · ${ROLE_NAMES[revealedRole]}`;
      details.append(name, user);
      if (isAlly) {
        const badge = document.createElement('span');
        badge.className = 'ally-tag';
        badge.textContent = 'ТВОЙ СОЮЗНИК';
        details.append(badge);
      }
      el.append(details);
      container.append(el);
    }
  }

  function resetGameSession(gameId) {
    lastRound = gameId;
    selected = [];
    selectionHydrated = false;
    revealed = false;
    channel = 'public';
    for (const key of ['public', 'mafia']) {
      cachedMessages[key] = [];
      cursor[key] = 0;
    }
    lastPhase = '';
    renderedChatKey = '';
    chatFeedback('');
  }

  function drawRole() {
    $('role-section').hidden = !state.joined || !state.my_role;
    if (!state.my_role) return;
    const role = ROLES.has(state.my_role) ? state.my_role : 'civilian';
    const image = $('role-image');
    image.src = `${IMAGE_ROOT}${revealed ? role : 'card-back'}.webp`;
    image.alt = revealed ? `твоя роль: ${state.my_role_title}` : 'закрытая карта роли';
    $('role-action').textContent = revealed ? 'скрыть роль' : 'показать мою роль';
    $('role-reveal').setAttribute('aria-pressed', String(revealed));
    $('role-reveal').setAttribute('aria-label', revealed ? 'скрыть секретную роль' : 'показать секретную роль');
    $('role-hint').hidden = !revealed;
    $('role-hint').textContent = revealed ? state.my_role_hint : '';
    const mafia = ['mafia', 'don'].includes(role);
    const allies = $('mafia-allies');
    allies.hidden = !mafia;
    if (mafia) {
      const list = $('mafia-allies-list');
      list.replaceChildren();
      const teammates = state.players.filter(p => p.id !== ownId && state.mafia_team?.includes(p.id));
      if (!teammates.length) {
        const line = document.createElement('p');
        line.textContent = 'ты единственный игрок мафии в этой партии.';
        list.append(line);
      } else {
        for (const teammate of teammates) {
          const line = document.createElement('div');
          line.className = 'ally-person';
          line.append(avatar(teammate, true));
          const detail = document.createElement('span');
          const label = document.createElement('strong');
          label.textContent = teammate.name;
          const username = document.createElement('small');
          username.textContent = nick(teammate) + (teammate.alive ? '' : ' · выбыл');
          detail.append(label, username);
          line.append(detail);
          list.append(line);
        }
      }
    }
  }

  function eligibleTargets() {
    const role = state.my_role;
    const team = new Set(state.mafia_team || []);
    const canChooseSelf = state.phase === 'night' && ['doctor', 'lawyer'].includes(role);
    return state.players.filter((p) => p.alive && (p.id !== ownId || canChooseSelf) &&
      !(state.phase === 'night' && ['don', 'mafia'].includes(role) && team.has(p.id)));
  }

  function drawTargets() {
    const isNight = state.phase === 'night';
    const hasAction = isNight && Boolean(ROLE_ACTIONS[state.my_role]);
    const isVote = state.phase === 'vote';
    const visible = state.joined && state.alive && (hasAction || isVote);
    $('select-panel').hidden = !visible;
    if (!visible) return;
    const max = isNight && state.my_role === 'journalist' ? 2 : 1;
    const options = eligibleTargets();
    const validIds = new Set(options.map(p => p.id));
    selected = selected.filter((id) => validIds.has(id)).slice(0, max);
    const prior = state.my_choice;
    if (prior && !selectionHydrated) {
      selected = [prior.target_id, prior.second_target_id].filter((n) => validIds.has(n)).slice(0, max);
    }
    selectionHydrated = true;
    $('select-title').textContent = isVote ? 'твой голос' : 'ночное действие';
    $('select-hint').textContent = isVote ? 'выбери одного игрока. твоё решение тайное до итогов голосования.' : ROLE_ACTIONS[state.my_role];
    $('select-count').textContent = `${selected.length} / ${max}`;
    const grid = $('target-list');
    grid.replaceChildren();
    for (const player of options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `target${selected.includes(player.id) ? ' selected' : ''}`;
      button.setAttribute('aria-pressed', String(selected.includes(player.id)));
      button.append(avatar(player, true));
      const caption = document.createElement('span');
      caption.textContent = player.name;
      button.append(caption);
      button.addEventListener('click', () => {
        if (selected.includes(player.id)) selected = selected.filter(id => id !== player.id);
        else if (max === 1) selected = [player.id];
        else selected = [...selected, player.id].slice(-max);
        drawTargets();
      });
      grid.append(button);
    }
    $('submit-choice').disabled = selected.length !== max || busy;
    $('submit-choice').textContent = prior ? 'изменить выбор' : 'подтвердить выбор';
    $('choice-note').textContent = prior ? 'выбор принят. изменить его можно до конца фазы.' : 'твой выбор будет сохранён только после подтверждения';
  }

  function renderChatSettings() {
    const hasGame = ['night', 'day', 'vote', 'finished'].includes(state.phase);
    $('chat-panel').hidden = !hasGame;
    if (!hasGame) return;
    const isMafia = ['mafia', 'don'].includes(state.my_role) && state.alive;
    $('mafia-tab').hidden = !isMafia;
    if (!isMafia && channel === 'mafia') channel = 'public';
    for (const tab of document.querySelectorAll('.chat-tab')) {
      tab.classList.toggle('is-active', tab.dataset.channel === channel);
      tab.setAttribute('aria-selected', String(tab.dataset.channel === channel));
    }
    const writable = state.joined && state.alive && (
      (channel === 'public' && ['day', 'vote'].includes(state.phase)) ||
      (channel === 'mafia' && state.phase === 'night' && isMafia)
    );
    $('compose').hidden = !writable;
    $('chat-lock').hidden = writable;
    $('chat-lock').textContent = state.alive ? 'этот чат сейчас закрыт для сообщений' : 'наблюдатели могут только читать';
    $('chat-privacy').textContent = channel === 'mafia' ? 'ТОЛЬКО МАФИЯ' : 'ОБЩИЙ';
    $('message-list').classList.toggle('mafia', channel === 'mafia');
  }

  function renderMessages() {
    const list = $('message-list');
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 70;
    list.replaceChildren();
    const items = cachedMessages[channel];
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'chat-empty';
      empty.textContent = 'пока тихо. первым может быть твоё сообщение.';
      list.append(empty);
    }
    for (const message of items) {
      const el = document.createElement('article');
      el.className = `msg${message.system ? ' system' : ''}${message.sender_id === ownId ? ' mine' : ''}`;
      if (!message.system) {
        const heading = document.createElement('div');
        heading.className = 'msg-name';
        heading.textContent = message.username ? `@${message.username}` : message.name;
        const time = document.createElement('span');
        time.className = 'msg-time';
        const parsed = new Date(message.created_at);
        time.textContent = Number.isFinite(parsed.valueOf()) ? parsed.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) : '';
        heading.append(time);
        el.append(heading);
      }
      const text = document.createElement('div');
      text.className = 'msg-body';
      text.textContent = message.text;
      el.append(text);
      list.append(el);
    }
    if (nearBottom) list.scrollTop = list.scrollHeight;
  }

  async function loadChat() {
    if (!state || !['night', 'day', 'vote', 'finished'].includes(state.phase) || loadingChat) return;
    if (channel === 'mafia' && !(['mafia', 'don'].includes(state.my_role) && state.alive)) return;
    loadingChat = true;
    const requestedChannel = channel;
    try {
      const result = await api(`/api/nyan-mafia/messages?channel=${encodeURIComponent(requestedChannel)}&after=${cursor[requestedChannel]}`);
      if (requestedChannel !== channel || !state || Number(state.round_id) !== lastRound) return;
      if (result.messages?.length) {
        const existing = new Set(cachedMessages[requestedChannel].map(m => m.id));
        let changed = false;
        for (const msg of result.messages) {
          if (!existing.has(msg.id)) {
            cachedMessages[requestedChannel].push(msg);
            changed = true;
          }
          cursor[requestedChannel] = Math.max(cursor[requestedChannel], msg.id);
        }
        cachedMessages[requestedChannel] = cachedMessages[requestedChannel].slice(-120);
        if (changed) renderMessages();
      }
      if ($('chat-feedback').dataset.type === 'network') chatFeedback('');
    } catch (error) {
      chatFeedback('не удалось обновить сообщения: ' + errorText(error) + '. повторяем подключение автоматически.', 'network');
    } finally {
      loadingChat = false;
    }
  }

  function renderResult() {
    const ended = state.phase === 'finished';
    $('result-panel').hidden = !ended;
    if (!ended) return;
    $('result-image').className = `result-image ${state.winner || ''}`;
    const titles = { civilians: 'победа мирных', mafia: 'победа мафии', maniac: 'победа маньяка', draw: 'ничья' };
    $('result-title').textContent = titles[state.winner] || 'игра завершена';
    const revealedRoles = Object.entries(state.revealed_roles || {});
    $('result-description').textContent = revealedRoles.length
      ? `раскрыто ролей: ${revealedRoles.length}. можешь посмотреть роли в списке игроков после окончания.`
      : 'спасибо всем за игру!';
  }

  function renderGameUpdates() {
    const registering = state.phase === 'registration';
    $('registration-progress').hidden = !registering;
    if (registering) {
      const minimum = Number(state.min_players || 4);
      const count = state.players.length;
      const remaining = Math.max(0, minimum - count);
      $('registration-count').textContent = `${count} / ${minimum}`;
      $('registration-fill').style.width = `${Math.min(100, Math.round(count / minimum * 100))}%`;
      $('registration-track').setAttribute('aria-valuemax', String(minimum));
      $('registration-track').setAttribute('aria-valuenow', String(Math.min(count, minimum)));
      $('registration-caption').textContent = remaining ? 'собираем игроков' : 'можно начинать!';
      $('registration-hint').textContent = remaining
        ? `до минимального состава осталось ${remaining}`
        : 'минимальный состав собран. ведущий может начать игру.';
    }
    const currentEvent = state.last_elimination || state.last_event;
    const eventVisible = Boolean(currentEvent) && state.phase !== 'registration';
    $('event-strip').hidden = !eventVisible;
    if (eventVisible) $('event-text').textContent = currentEvent;

    // Results belong only to the Telegram account that performed the action.
    // They remain visible through the following daytime discussion and vote.
    const privateVisible = Boolean(state.joined && state.night_result &&
      ['day', 'vote'].includes(state.phase));
    $('private-result').hidden = !privateVisible;
    $('private-result-text').textContent = privateVisible ? state.night_result : '';
  }

  function renderOwner() {
    $('host-panel').hidden = !state.is_owner;
    if (!state.is_owner) return;
    const phase = state.phase;
    $('host-open').hidden = true; // Only private /mafia command can open registration.
    $('host-start').hidden = phase !== 'registration';
    $('host-start').disabled = state.players.length < 4 || busy;
    $('host-next').hidden = !['night', 'day', 'vote'].includes(phase);
    $('host-finish').hidden = !['registration', 'night', 'day', 'vote'].includes(phase);
    $('host-info').textContent = phase === 'registration'
      ? `записано ${state.players.length} игроков. нужно минимум 4, максимум 20.`
      : phase === 'idle' || phase === 'finished'
        ? 'при открытии регистрации бот отправит сообщение с кнопкой в игровую группу.'
        : 'смена дня, ночи и голосования происходит автоматически по таймеру. можешь завершить текущую фазу раньше.';
  }

  function render() {
    if (!state) return;
    if (Number(state.round_id || 0) !== lastRound) resetGameSession(Number(state.round_id || 0));
    if (state.phase !== lastPhase) {
      selected = [];
      selectionHydrated = false;
      lastPhase = state.phase;
      if (['night', 'day', 'vote'].includes(state.phase)) tg?.HapticFeedback?.selectionChanged?.();
    }
    $('top-state').textContent = NAMES[state.phase] || 'ИГРА';
    $('round-mark').textContent = state.round_id ? `РАУНД #${state.round_id}` : 'РАУНД —';
    $('phase-mark').textContent = NAMES[state.phase] || 'ОЖИДАНИЕ';
    $('phase-name').textContent = PHASES[state.phase]?.[0] || 'игра';
    $('phase-description').textContent = PHASES[state.phase]?.[1] || '';
    $('clock').hidden = !state.ends_at;
    $('join-controls').hidden = state.phase !== 'registration';
    $('join').hidden = Boolean(state.joined);
    $('leave').hidden = !state.joined;
    $('room').hidden = !state.round_id;
    $('game-panel').hidden = !['night', 'day', 'vote'].includes(state.phase);
    $('stage').className = `illustrated-stage ${state.alive === false && state.joined ? 'spectator' : state.phase}`;
    $('stage-label').textContent = state.alive === false && state.joined ? 'НАБЛЮДАТЕЛЬ' : NAMES[state.phase] || 'NYAN MAFIA';
    renderGameUpdates();
    renderPlayers();
    drawRole();
    drawTargets();
    renderChatSettings();
    renderResult();
    renderOwner();
    const key = `${lastRound}:${channel}`;
    if (key !== renderedChatKey) {
      renderedChatKey = key;
      renderMessages();
    }
  }

  async function refresh() {
    if (!initData || checking || busy) return;
    checking = true;
    try {
      state = await api('/api/nyan-mafia/status');
      notice('');
      render();
      void loadChat();
    } catch (err) {
      notice(errorText(err));
      if (!state) $('phase-description').textContent = 'не удалось загрузить игру. попробуй повторить.';
    } finally {
      checking = false;
    }
  }

  async function act(path, body = undefined, confirmation = '') {
    if (busy || (confirmation && !window.confirm(confirmation))) return;
    busy = true;
    try {
      await api(path, 'POST', body);
      notice('');
      tg?.HapticFeedback?.notificationOccurred?.('success');
      state = await api('/api/nyan-mafia/status');
      render();
      void loadChat();
    } catch (err) {
      tg?.HapticFeedback?.notificationOccurred?.('error');
      notice(errorText(err));
    } finally {
      busy = false;
      if (state) render();
    }
  }

  function updateClock() {
    if (!state?.ends_at) return;
    const seconds = Math.max(0, Math.ceil((new Date(state.ends_at).getTime() - Date.now()) / 1000));
    $('clock').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  }

  $('join').addEventListener('click', () => void act('/api/nyan-mafia/join'));
  $('leave').addEventListener('click', () => void act('/api/nyan-mafia/leave', undefined, 'отменить запись на эту игру?'));
  $('retry').addEventListener('click', () => void refresh());
  $('host-open').addEventListener('click', () => void act('/api/owner/nyan-mafia/open', undefined, 'открыть новый набор и отправить кнопку в группу?'));
  $('host-start').addEventListener('click', () => void act('/api/owner/nyan-mafia/start', undefined, 'закрыть запись и случайно раздать роли?'));
  $('host-next').addEventListener('click', () => void act('/api/owner/nyan-mafia/advance', undefined, 'завершить текущую фазу досрочно?'));
  $('host-finish').addEventListener('click', () => void act('/api/owner/nyan-mafia/finish', undefined, 'завершить всю игру?'));
  $('role-reveal').addEventListener('click', () => { revealed = !revealed; drawRole(); });
  $('submit-choice').addEventListener('click', () => {
    const max = state.phase === 'night' && state.my_role === 'journalist' ? 2 : 1;
    if (selected.length !== max) return;
    void act('/api/nyan-mafia/action', { target_id: selected[0], second_target_id: selected[1] || null });
  });
  document.querySelectorAll('.chat-tab').forEach((tab) => tab.addEventListener('click', () => {
    channel = tab.dataset.channel;
    renderChatSettings();
    renderMessages();
    void loadChat();
  }));
  $('compose').addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = $('message-text');
    const value = input.value.trim();
    if (!value || busy) return;
    busy = true;
    $('send').disabled = true;
    try {
      await api('/api/nyan-mafia/messages', 'POST', { text: value, channel });
      input.value = '';
      await loadChat();
    } catch (err) { notice(errorText(err)); }
    finally { busy = false; $('send').disabled = false; }
  });

  if (!initData) {
    $('phase-description').textContent = 'открой эту игру через кнопку Telegram-бота, чтобы зарегистрироваться и получить роль.';
    $('phase-name').textContent = 'нужен Telegram';
    $('top-state').textContent = 'ВНЕ ИГРЫ';
    $('phase-mark').textContent = 'ВХОД';
    $('telegram-link').hidden = false;
  } else {
    void refresh();
    window.setInterval(() => { if (!document.hidden) void refresh(); }, 3300);
    window.setInterval(() => { if (!document.hidden) void loadChat(); }, 2100);
    window.setInterval(updateClock, 500);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
  }
})();
