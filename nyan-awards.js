(() => {
  'use strict';

  const API = 'https://nyan-wallet-bridge.qwertsyik.workers.dev';
  const tg = window.Telegram?.WebApp;
  const initData = tg?.initData || '';
  const $ = (selector) => document.querySelector(selector);
  const IMAGES = {
    legend_nyan: '01_legend_nyan.webp', soul_nyan: '05_heart_nyan.webp',
    face_nyan: '02_face_nyan.webp', discovery: '06_discovery_year.webp',
    creator: '07_creator_nyan.webp', engine: '08_engine_nyan.webp',
    games_legend: '04_legend_nyan_games.webp', mafia_master: '09_master_mafia.webp',
    finance: '10_financial_strategist.webp', admin: '11_admin_of_year.webp',
    flood_legend: '03_legend_flood.webp',
  };
  const FALLBACK = [
    ['legend_nyan','Легенда Нян','Главная награда экосистемы','100 ⭐ · физ. аккаунт Японии · 600 🐾'],
    ['soul_nyan','Душа Нян','Тот, кто делает сообщество теплее','250 🐾'],
    ['face_nyan','Лицо Нян','Самый узнаваемый участник','50 ⭐ · 300 🐾'],
    ['discovery','Открытие года','Главное новое имя года','150 🐾'],
    ['creator','Творец Нян','Идеи, творчество и вдохновение','200 🐾'],
    ['engine','Двигатель Нян','Человек, который двигает проекты вперёд','200 🐾'],
    ['games_legend','Легенда Nyan Games','Выдающиеся игровые достижения','25 ⭐ · физ. аккаунт · 250 🐾'],
    ['mafia_master','Мастер мафии','Игра, тактика и победы','200 🐾'],
    ['finance','Финансовый стратег','Успехи в экономике Nyan Wallet','150 🐾'],
    ['admin','Администратор года','Забота о проектах и участниках','200 🐾'],
    ['flood_legend','Легенда флуда','Награда партнёрского флуда','75 ⭐ · физ. аккаунт · 300 🐾'],
  ].map(([key,title,description,prize]) => ({ key,title,description,prize,
    evidence_based: ['games_legend','mafia_master','finance'].includes(key),partner:key==='flood_legend' }));

  const PHASE_LABELS = {
    soon:'скоро старт', nominations:'идёт выдвижение', review:'выбираем финалистов',
    voting:'голосование открыто', ceremony_wait:'готовим церемонию', results:'итоги объявлены',
  };
  const STATUS_LABELS = {
    awaiting_confirmation:'ожидает твоего подтверждения', confirmed:'участие подтверждено',
    finalist:'финалист', rejected:'не прошёл в финал', declined:'кандидатура отклонена',
  };

  let state = { categories: FALLBACK, phase:'nominations', my_nominations:[], finalists:[], my_votes:{} };
  let busy = false;

  tg?.ready?.();
  tg?.expand?.();

  function el(tag, cls, content) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (content !== undefined) node.textContent = content;
    return node;
  }

  function clear(node) { node.replaceChildren(); }

  function notice(text, isError = false) {
    const node = $('#notice');
    node.textContent = text || '';
    node.classList.toggle('error', isError);
    node.hidden = !text;
  }

  function explain(error) {
    if (error?.name === 'AbortError') return 'Сервер отвечает слишком долго. Попробуй снова.';
    if (error instanceof TypeError) return 'Нет соединения с сервером. Проверь интернет.';
    return error?.message || 'Что-то пошло не так. Попробуй ещё раз.';
  }

  async function request(path, options = {}) {
    if (!initData) throw new Error('Открой NYAN AWARDS через Telegram Mini App.');
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 18000);
    try {
      const response = await fetch(`${API}${path}`, {
        ...options, signal:controller.signal, cache:'no-store',
        headers: { 'X-Telegram-Init-Data':initData,
          ...(options.body ? { 'Content-Type':'application/json' } : {}) },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message;
        const error = new Error(detail || 'Не удалось выполнить запрос.');
        error.status = response.status;
        throw error;
      }
      return data;
    } finally { window.clearTimeout(timeout); }
  }

  function deadline(phase) {
    const target = {
      soon:'2026-11-05T00:00:00+03:00',nominations:'2026-11-07T00:00:00+03:00',
      review:'2026-11-08T00:00:00+03:00',voting:'2026-11-09T00:00:00+03:00',
      ceremony_wait:'2026-11-09T19:00:00+03:00',
    }[phase];
    if (!target) return 'зал славы открыт';
    const left = Math.max(0, Date.parse(target) - Date.now());
    const days = Math.floor(left / 86400000);
    const hours = Math.floor(left / 3600000) % 24;
    const minutes = Math.floor(left / 60000) % 60;
    return days ? `ещё ${days} д. ${hours} ч.` : `ещё ${hours} ч. ${minutes} мин.`;
  }

  function renderPhase() {
    $('#phase-label').textContent = PHASE_LABELS[state.phase] || 'NYAN AWARDS';
    $('#phase-countdown').textContent = deadline(state.phase);
    document.querySelectorAll('.schedule-stage').forEach((node) => {
      const stage = node.dataset.stage;
      node.classList.toggle('active', stage === state.phase || (stage==='results' && ['ceremony_wait','results'].includes(state.phase)));
    });
    $('#nomination-panel').hidden = state.phase !== 'nominations';
    $('#vote-panel').hidden = state.phase !== 'voting';
    $('#results-panel').hidden = state.phase !== 'results';
    $('#telegram-link').hidden = Boolean(initData);
  }

  function chooseCategory(key) {
    if (state.phase !== 'nominations') return;
    $('#nomination-category').value = key;
    $('#nomination-panel').scrollIntoView({behavior:'smooth',block:'start'});
    $('#nomination-category').focus({preventScroll:true});
  }

  function renderCategories() {
    const grid = $('#nominations-grid');
    clear(grid);
    const select = $('#nomination-category');
    const selected = select.value;
    clear(select);
    state.categories.forEach((category) => {
      const card = el('article', 'nomination-card' + (category.partner ? ' partner' : ''));
      const img = el('img','nomination-icon');
      img.src = `./assets/nyan-awards/${IMAGES[category.key] || ''}`;
      img.alt = '';
      img.width = 92; img.height = 92; img.loading = 'lazy';
      card.append(img);
      const content = el('div','nomination-copy');
      content.append(el('h3',null,category.title));
      content.append(el('p',null,category.description));
      if (category.prize) content.append(el('span','nomination-prize',category.prize));
      const caption = category.evidence_based ? 'по достижениям' : 'по итогам голосования';
      if (state.phase === 'nominations') {
        const button = el('button',null,'Выдвинуть ↗');
        button.type = 'button';
        button.addEventListener('click', () => chooseCategory(category.key));
        content.append(button);
      } else {
        content.append(el('span','nomination-prize',caption));
      }
      card.append(content);
      grid.append(card);
      const option = el('option',null,category.title);
      option.value = category.key;
      select.append(option);
    });
    if (selected && state.categories.some(row => row.key === selected)) select.value = selected;
  }

  function renderMine() {
    const list = $('#my-nominations');
    clear(list);
    $('#my-panel').hidden = !state.my_nominations.length;
    state.my_nominations.forEach((candidate) => {
      const category = state.categories.find(item => item.key === candidate.category);
      const item = el('article','my-item');
      item.append(el('strong',null,category?.title || candidate.category));
      item.append(el('small',null,STATUS_LABELS[candidate.status] || candidate.status));
      if (candidate.status === 'awaiting_confirmation' && ['nominations','review'].includes(state.phase)) {
        const buttons = el('div','item-actions');
        const accept = el('button','secondary','Подтвердить');
        const decline = el('button','secondary danger','Отказаться');
        accept.addEventListener('click', () => confirmCandidate(candidate.id, true));
        decline.addEventListener('click', () => confirmCandidate(candidate.id, false));
        buttons.append(accept, decline);
        item.append(buttons);
      }
      list.append(item);
    });
  }

  function renderVoting() {
    const list = $('#vote-list');
    clear(list);
    state.categories.forEach((category) => {
      const section = el('section','vote-category');
      section.append(el('h3',null,category.title));
      if (category.evidence_based) {
        section.append(el('p','empty-note','Эта номинация определяется по подтверждённым игровым или финансовым достижениям.'));
        list.append(section);
        return;
      }
      const finalists = state.finalists.filter(candidate => candidate.category === category.key);
      if (finalists.length < 3) {
        section.append(el('p','empty-note','Список финалистов ещё не сформирован (нужно от 3 до 5 участников).'));
        list.append(section);
        return;
      }
      const form = el('form','vote-form');
      finalists.forEach((candidate) => {
        const label = el('label','finalist');
        const input = el('input');
        input.type = 'radio'; input.name = 'candidate'; input.value = String(candidate.id);
        input.checked = state.my_votes[category.key] === candidate.id;
        input.required = true;
        label.append(input,el('span',null,candidate.username ? `${candidate.name} · @${candidate.username}` : candidate.name));
        form.append(label);
      });
      const button = el('button','primary','Сохранить голос ↗');
      button.type = 'submit';
      form.append(button);
      if (state.my_votes[category.key]) section.append(el('p','saved-vote','Твой голос уже записан. До закрытия его можно изменить.'));
      form.addEventListener('submit',(event) => {
        event.preventDefault();
        const choice = form.querySelector('input[name="candidate"]:checked');
        if (choice) void vote(category.key,Number(choice.value));
      });
      section.append(form);
      list.append(section);
    });
  }

  function renderResults() {
    const list = $('#results-list');
    clear(list);
    state.categories.forEach((category) => {
      const section = el('section','result-category');
      section.append(el('h3',null,category.title));
      const finalists = (state.results || []).filter(row => row.category === category.key)
        .sort((a,b) => Number(b.winner)-Number(a.winner) || b.votes-a.votes);
      const winner = finalists.find(row => row.winner);
      if (winner) {
        const card = el('div','winner-card');
        const badge = el('img','winner-badge');
        badge.src = `./assets/nyan-awards/${IMAGES[category.key]}`;
        badge.alt = `Значок «${category.title}»`;
        const copy = el('div','winner-copy');
        copy.append(el('span','winner-tag','ЛАУРЕАТ · NYAN AWARDS 2026'));
        copy.append(el('strong',null,winner.name));
        copy.append(el('small',null,category.prize));
        card.append(badge,copy);
        section.append(card);
      } else {
        section.append(el('p','empty-note','Победитель пока не определён. Итоги уточняются.'));
      }
      finalists.forEach((row) => {
        if (row.winner) return;
        const record = el('div','result-row');
        record.append(el('span',null,row.name),el('b',null,category.evidence_based ? 'финалист' : `${row.votes} голосов`));
        section.append(record);
      });
      list.append(section);
    });
  }

  async function withBusy(callback) {
    if (busy) return;
    busy = true;
    try {
      await callback();
      tg?.HapticFeedback?.notificationOccurred?.('success');
    } catch (error) { notice(explain(error),true); }
    finally { busy = false; }
  }

  async function confirmCandidate(id, accept) {
    await withBusy(async () => {
      await request('/api/nyan-awards/confirm',{method:'POST',body:JSON.stringify({nomination_id:id,accept})});
      notice(accept ? 'Участие подтверждено!' : 'Кандидатура отклонена.');
      await load();
    });
  }

  async function vote(category, nominationId) {
    await withBusy(async () => {
      await request('/api/nyan-awards/vote',{method:'POST',body:JSON.stringify({category,nomination_id:nominationId})});
      notice('Голос сохранён. До закрытия голосования его можно изменить.');
      await load();
    });
  }

  async function loadOwner() {
    try {
      const data = await request('/api/owner/nyan-awards/candidates');
      const panel = $('#owner-panel');
      panel.hidden = false;
      const list = $('#owner-list');
      clear(list);
      state.categories.forEach((category) => {
        const candidates = data.candidates.filter(candidate => candidate.category === category.key);
        if (!candidates.length) return;
        const section = el('section','owner-category');
        section.append(el('h3',null,category.title));
        const leaders = data.leaders?.[category.key] || [];
        const currentWinner = data.manual_winners?.[category.key]?.nomination_id;
        const isTie = !category.evidence_based && leaders.length > 1;
        if (state.phase === 'ceremony_wait') {
          section.append(el('p','empty-note',category.evidence_based
            ? 'Выбери победителя по проверенным достижениям и укажи основание.'
            : isTie ? 'Голоса разделились поровну. Выбери одного из лидеров.'
              : leaders.length === 1 ? 'Победитель уже определяется голосами автоматически.'
                : 'Нет голосов за эту номинацию.'));
        }
        candidates.forEach((candidate) => {
          const row = el('div','owner-row');
          const copy = el('div','owner-row-info');
          copy.append(el('strong',null,`${candidate.name} · ${STATUS_LABELS[candidate.status] || candidate.status}`));
          if (candidate.reason) copy.append(el('small',null,candidate.reason));
          row.append(copy);
          if (['confirmed','finalist'].includes(candidate.status) && state.phase === 'review') {
            const button = el('button','secondary',candidate.status==='finalist' ? 'Снять' : 'В финал');
            button.type = 'button';
            button.addEventListener('click',() => withBusy(async () => {
              await request('/api/owner/nyan-awards/finalist',{method:'POST',body:JSON.stringify({nomination_id:candidate.id,finalist:candidate.status!=='finalist'})});
              notice('Список финалистов обновлён.');
              await load();
            }));
            row.append(button);
          }
          if (candidate.status === 'finalist' && state.phase === 'ceremony_wait'
              && (category.evidence_based || (isTie && leaders.includes(candidate.id)))) {
            const form = el('form','owner-winner-form');
            if (category.evidence_based) {
              const explanation = el('input','owner-evidence');
              explanation.name = 'justification';
              explanation.maxLength = 500;
              explanation.minLength = 10;
              explanation.required = true;
              explanation.placeholder = 'За какие подтверждённые достижения?';
              if (currentWinner === candidate.id) explanation.value = data.manual_winners[category.key].justification || '';
              form.append(explanation);
            }
            const pick = el('button','secondary',currentWinner === candidate.id ? '✓ утверждён' : 'Назначить победителем');
            pick.type = 'submit';
            form.append(pick);
            form.addEventListener('submit',(event) => {
              event.preventDefault();
              void withBusy(async () => {
                await request('/api/owner/nyan-awards/winner',{
                  method:'POST',body:JSON.stringify({category:category.key,nomination_id:candidate.id,
                    justification:form.elements.justification?.value || ''}),
                });
                notice('Лауреат утверждён. Имя станет видно всем после начала церемонии.');
                await load();
              });
            });
            row.append(form);
          }
          section.append(row);
        });
        list.append(section);
      });
    } catch (error) {
      if (error.status !== 403) console.warn('Не удалось загрузить панель наград:',explain(error));
    }
  }

  async function load() {
    if (!initData) return;
    const data = await request('/api/nyan-awards/status');
    state = data;
    renderPhase();
    renderCategories();
    renderMine();
    renderVoting();
    renderResults();
    await loadOwner();
  }

  $('#nomination-form').addEventListener('change',() => {
    const other = $('#nomination-form').elements.who.value === 'other';
    $('#nominee-field').hidden = !other;
    $('#nomination-form').elements.nominee.required = other;
  });
  $('#nomination-form').addEventListener('submit',(event) => {
    event.preventDefault();
    if (!initData) {
      notice('Открой страницу в Telegram, чтобы предложить кандидата.',true);
      $('#telegram-link').hidden = false;
      return;
    }
    if (state.phase !== 'nominations') return;
    const form = event.currentTarget;
    const category = form.elements.category.value;
    const nominee = form.elements.who.value === 'me' ? 'me' : form.elements.nominee.value;
    const reason = form.elements.reason.value;
    void withBusy(async () => {
      const result = await request('/api/nyan-awards/nominate',{method:'POST',body:JSON.stringify({category,nominee,reason})});
      notice(result.already_exists ? 'Эта кандидатура уже предложена.' : nominee==='me' ? 'Твоя кандидатура отправлена!' : 'Кандидатура отправлена. Теперь человек должен подтвердить участие.');
      form.elements.reason.value = '';
      await load();
    });
  });

  renderPhase();
  renderCategories();
  if (!initData) {
    notice('Чтобы участвовать в номинациях и голосовании, открой страницу через Telegram Mini App.');
  } else {
    load().catch(error => notice(explain(error),true));
  }
  window.setInterval(() => { $('#phase-countdown').textContent = deadline(state.phase); },60000);
})();
