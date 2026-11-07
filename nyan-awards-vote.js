const finalists = {
  pixel: {
    id: '6968551476', name: 'Пиксель', username: '@PIXEL_ARE_YOU_OKAY', photo: '01-21455.jpg',
    role: 'участник экосистемы',
    summary: 'Участвует в интерактивах, розыгрышах и проектах Нян. Продвигает магазин, делится им с друзьями и работает в пиаре.',
    highlights: ['Le Nyan Paris', 'интерактивы Няника', 'продвижение Нян Шоп'],
    contribution: '«Я поддерживал всё, начиная от интерактивов и заканчивая другими проектами». Пиксель отмечает развитие Nyan Wallet и старания команды.'
  },
  viks: {
    id: '6651466766', name: 'Викс', username: '@liviskas', photo: '02-21456.jpg',
    role: 'активный участник',
    summary: 'Помогала развивать партию фембоев на выборах: создавала постеры, плакаты, стикеры и предлагала идеи.',
    highlights: ['выборы Нян', 'постеры и стикеры', 'идеи для партии'],
    contribution: 'Больше всего гордится участием в выборах. По её словам, вклад был не самым большим, но затронул сразу несколько направлений.'
  },
  yutsu: {
    id: '7338522630', name: 'Ютсу', username: '@Yut1su', photo: '03-21457.jpg',
    role: 'администрация Нян',
    summary: 'Общается с участниками, поддерживает активность и следит за порядком в сообществе.',
    highlights: ['модерация', 'общение', 'поддержка порядка'],
    contribution: 'Главным вкладом Ютсу называет своё появление в администрации. В анкете с юмором рассказывает о комментариях и наблюдении за порядком.'
  },
  cherry: {
    id: '6471573189', name: 'Черри', username: '@Cherrymirakle', photo: '04-21458.jpg',
    role: 'участница сообщества',
    summary: 'Знакома с Нян Шоп около полугода, рассказывала о нём друзьям и поддерживает людей в общении.',
    highlights: ['рекомендации друзьям', 'поддержка участников', 'общение'],
    contribution: 'Черри рассказала о магазине четырём друзьям и считает, что даже простое согласие и поддержка помогают людям чувствовать себя не одинокими.'
  },
  snickers: {
    id: '8061154778', name: 'Сникерс', username: '@aytizm_rab', photo: '05-21459.jpg',
    role: 'участник Nyan Games',
    summary: 'Активно общался в Nyan Games и участвовал в пробных партиях мафии после открытия проекта.',
    highlights: ['тесты мафии', 'Nyan Games', 'игровой актив'],
    contribution: 'Участвовал в тестовых раундах мафии. В одном из матчей играл за мафию и был вычислен после нескольких раундов.'
  },
  fishka: {
    id: '5291356933', name: 'Фишка', username: '.sofiyusheva', photo: '06-21460.jpg',
    role: 'участница Нян',
    summary: 'В сообществе с января 2026 года. Активна в комментариях, конкурсах и интерактивах.',
    highlights: ['с января 2026', 'комментарии', 'конкурсы и интерактивы'],
    contribution: 'В анкете отмечает регулярное участие в конкурсах, интерактивах и обсуждениях в комментариях.'
  },
  musya: {
    id: '5354595027', name: 'Муся', username: '@vampr1kski', photo: '07-21461.jpg',
    role: 'участница экосистемы',
    summary: 'Помогала Нян, иногда участвовала в оформлении постов. Активно пользуется Nyan Wallet.',
    highlights: ['помощь команде', 'оформление постов', 'Nyan Wallet'],
    contribution: 'Говорит, что помогала по разным вопросам, но не выделяет один конкретный случай. Отмечает оформление постов и собственный прогресс в кошельке.'
  },
  loli: {
    id: '8162240045', name: 'Лолиська', username: '@Op1Lolipop', photo: '08-21462.jpg',
    role: 'участница Нян',
    summary: 'Поддерживает публикации реакциями, делится розыгрышами с друзьями и участвует в играх.',
    highlights: ['реакции и репосты', 'розыгрыши', 'три победы в «Шпионе»'],
    contribution: 'Лолиська рассказала, что регулярно поддерживала канал реакциями и репостами, а также трижды побеждала в игре «Шпион».'
  },
  molly: {
    id: '1129986805', name: 'Молли', username: '@nasttchl', photo: '09-21463.jpg',
    role: 'команда Нян',
    summary: 'Работает в команде Нян, помогает Кверту и занимается творчеством. Нарисовала собственную аватарку, связанную с Нян.',
    highlights: ['работа в команде', 'рисование', 'авторский образ'],
    contribution: 'Молли рассказывает об участии в работе Нян и творческом опыте. В анкете упоминает рисунок аватарки для своего аккаунта.'
  }
};

const categories = [
  { id: 'legend', title: 'Легенда Нян', subtitle: 'За длительное участие, поддержку и вклад в развитие экосистемы.', type: 'public', candidates: ['pixel', 'fishka', 'musya'] },
  { id: 'discovery', title: 'Открытие года', subtitle: 'За яркое появление и заметное участие в жизни Нян.', type: 'public', candidates: ['viks', 'loli'] },
  { id: 'admin', title: 'Администратор года', subtitle: 'За работу с участниками и заботу о сообществе.', type: 'inactive', candidates: ['yutsu'] },
  { id: 'soul', title: 'Душа Нян', subtitle: 'За тепло, поддержку и атмосферу, в которую хочется возвращаться.', type: 'inactive', candidates: ['cherry'] },
  { id: 'creator', title: 'Творец Нян', subtitle: 'За идеи, творчество и визуальный вклад.', type: 'inactive', candidates: ['molly'] },
  { id: 'face', title: 'Лицо Нян', subtitle: 'За личный образ и участие в жизни команды.', type: 'inactive', candidates: ['molly'] },
  { id: 'games', title: 'Легенда Nyan Games', subtitle: 'За участие в играх, тестировании и развитие игрового сообщества.', type: 'inactive', candidates: ['snickers'] },
  { id: 'mafia', title: 'Мастер мафии', subtitle: 'За игру, тактику и результаты в мафии.', type: 'inactive', candidates: ['snickers'] },
  { id: 'finance', title: 'Финансовый стратег', subtitle: 'За достижения и участие в экономике Nyan Wallet.', type: 'inactive', candidates: ['musya'] }
];

const menu = document.getElementById('category-menu');
const cards = document.getElementById('candidates');
const modal = document.getElementById('candidate-modal');
const modalContent = document.getElementById('modal-content');
const lightbox = document.getElementById('image-lightbox');
const selectionByCategory = new Map();
const savedVotes = new Map();
const API = 'https://nyan-wallet-bridge.qwertsyik.workers.dev';
const SERVER_CATEGORY = {legend:'legend_nyan',discovery:'discovery'};
const tg = window.Telegram?.WebApp;
const initData = tg?.initData || '';
let activeCategory = 0;
let toastTimer;
let phase = 'loading';
let busy = false;
let officialResults = {};

tg?.ready?.();
tg?.expand?.();

async function api(path, options = {}) {
  if (!initData) throw new Error('Открой голосование через Telegram Mini App.');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 18000);
  try {
    const response = await fetch(API + path, {
      ...options, cache: 'no-store', signal: controller.signal,
      headers: {
        'X-Telegram-Init-Data': initData,
        ...(options.body ? {'Content-Type':'application/json'} : {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось связаться с сервером.');
    return data;
  } finally { clearTimeout(timer); }
}

function setPhase(nextPhase) {
  phase = nextPhase;
  const labels = {
    loading: ['подключение', 'проверяем доступ к голосованию'],
    review: ['скоро открытие', 'голосование начнётся сегодня в 15:25 мск'],
    voting: ['голосование открыто', 'выбери финалиста и подтверди голос'],
    ceremony_wait: ['голосование завершено', 'результаты объявим на церемонии 09.11 в 19:00'],
    results: ['церемония награждения', 'результаты голосования доступны'],
    login: ['вход через Telegram', 'для голосования нужен подтверждённый Telegram-аккаунт'],
    error: ['ошибка соединения', 'голоса не отправляются — попробуй обновить страницу'],
  };
  const label = labels[phase] || labels.error;
  document.getElementById('phase-status').textContent = label[0];
  document.getElementById('phase-hint').textContent = label[1];
  document.getElementById('telegram-entry').hidden = Boolean(initData);
  renderCategory();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function profileUrl(username) {
  return /^@[a-z0-9_]{5,32}$/i.test(username) ? `https://t.me/${username.slice(1)}` : null;
}

function cardMarkup(id, index, category) {
  const person = finalists[id];
  const selected = selectionByCategory.get(category.id) === id;
  const link = profileUrl(person.username);
  return `<article class="candidate-card${selected ? ' selected' : ''}">
    <button type="button" class="photo-wrap" data-photo="${id}" aria-label="Открыть фотографию ${escapeHtml(person.name)} целиком"><img loading="lazy" src="./assets/nyan-awards/finalists/${escapeHtml(person.photo)}" alt="Изображение, выбранное участником ${escapeHtml(person.name)}" width="720" height="720"><span class="photo-number">0${index + 1}</span><span class="photo-sparkle" aria-hidden="true">✦</span></button>
    <div class="candidate-info"><div class="candidate-role">${escapeHtml(person.role)}</div><h4>${escapeHtml(person.name)}</h4>
    ${link ? `<a class="candidate-handle" href="${link}" rel="noopener noreferrer" target="_blank">${escapeHtml(person.username)}</a>` : `<span class="candidate-handle">${escapeHtml(person.username)}</span>`}
    <p class="candidate-desc">${escapeHtml(person.summary)}</p>
    <div class="tags">${person.highlights.slice(0,2).map(h=>`<span>${escapeHtml(h)}</span>`).join('')}</div>
    <div class="candidate-actions"><button type="button" class="more-button" data-details="${id}">анкета <span aria-hidden="true">↗</span></button>
    ${category.type === 'public' ? `<button type="button" class="choose-button" data-select="${id}" aria-pressed="${selected}" ${phase !== 'voting' ? 'disabled' : ''}><span class="choose-circle">${selected ? '✓' : ''}</span>${selected ? 'выбрано' : 'выбрать'}</button>` : '<span class="jury-label">без голосования</span>'}</div></div></article>`;
}

function renderMenu() {
  menu.innerHTML = categories.map((category, index) => {
    const selected = savedVotes.has(category.id);
    const inactive = category.type === 'inactive';
    const divider = index === 2 ? '<div class="rail-group-label">НЕ ПРОВОДЯТСЯ · 07</div>' : '';
    return `${divider}<button type="button" class="category-tab${index===activeCategory?' active':''}${inactive?' inactive':''}" data-index="${index}" aria-current="${index===activeCategory?'true':'false'}"><span class="tab-num">${String(index+1).padStart(2,'0')}</span><span class="tab-name">${escapeHtml(category.title)}</span>${selected?'<span class="tab-check" aria-label="выбран кандидат">✓</span>':''}${inactive?'<span class="tab-inactive" aria-label="не проводится">—</span>':'<span class="tab-arrow" aria-hidden="true">↗</span>'}</button>`;
  }).join('');
}

function renderCategory() {
  const category = categories[activeCategory];
  document.getElementById('stage-index').textContent = `${String(activeCategory+1).padStart(2,'0')} / 09`;
  document.getElementById('nomination-title').textContent = category.title;
  document.getElementById('nomination-description').textContent = category.subtitle;
  document.getElementById('nomination-type').textContent = category.type === 'inactive' ? 'не проводится' : phase === 'voting' ? 'голосование' : 'ожидание';
  document.getElementById('nomination-type').classList.toggle('is-jury', category.type === 'inactive');
  const count = category.candidates.length;
  document.getElementById('candidate-count').textContent = `${count} ${count===1?'финалист':count===2?'финалиста':'финалиста'}`;
  const result = officialResults[SERVER_CATEGORY[category.id]];
  const winner = result?.winner_id && category.candidates.find(id => Number(finalists[id].id) === result.winner_id);
  document.getElementById('vote-hint').textContent = category.type === 'inactive' ? 'нет соперников' : phase === 'voting' ? 'можно выбрать одного' : phase === 'results' ? winner ? `победитель: ${finalists[winner].name}` : 'итоги уточняются' : phase === 'review' ? 'откроется в 15:25' : 'голосование закрыто';
  document.getElementById('inactive-note').hidden = category.type !== 'inactive';
  cards.innerHTML = category.candidates.map((id,i)=>cardMarkup(id,i,category)).join('');
  const selected = selectionByCategory.get(category.id);
  document.getElementById('selected-name').textContent = category.type==='inactive' ? 'голосование не проводится' : selected ? finalists[selected].name : 'пока никто не выбран';
  const isSaved = Boolean(selected && savedVotes.get(category.id) === Number(finalists[selected].id));
  document.getElementById('selection-label').textContent = isSaved ? 'голос сохранён' : 'мой выбор';
  const confirm = document.getElementById('confirm-vote');
  confirm.hidden = category.type !== 'public';
  confirm.disabled = busy || phase !== 'voting' || !selected || isSaved;
  confirm.textContent = isSaved ? 'голос учтён ✓' : 'подтвердить голос ↗';
  const next = document.getElementById('next-category');
  next.innerHTML = activeCategory === categories.length-1 ? 'к первой номинации <span aria-hidden="true">↗</span>' : 'следующая номинация <span aria-hidden="true">→</span>';
  renderMenu();
}

function showToast(message) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>toast.classList.remove('visible'), 3300);
}

function selectCandidate(id) {
  const category = categories[activeCategory];
  if (phase !== 'voting' || busy || category.type!=='public' || !category.candidates.includes(id)) return;
  if (selectionByCategory.get(category.id) === id) {
    selectionByCategory.delete(category.id);
  } else {
    selectionByCategory.set(category.id,id);
  }
  renderCategory();
}

async function submitVote() {
  const category = categories[activeCategory];
  const selected = selectionByCategory.get(category.id);
  const serverCategory = SERVER_CATEGORY[category.id];
  if (busy || phase !== 'voting' || !serverCategory || !selected) return;
  const candidateId = Number(finalists[selected].id);
  if (savedVotes.get(category.id) === candidateId) return;
  busy = true;
  renderCategory();
  try {
    await api('/api/nyan-awards/official/vote', {
      method: 'POST', body: JSON.stringify({category: serverCategory, candidate_id: candidateId}),
    });
    savedVotes.set(category.id, candidateId);
    showToast(`Голос за ${finalists[selected].name} сохранён. До закрытия можно изменить.`);
    tg?.HapticFeedback?.notificationOccurred?.('success');
  } catch (error) {
    showToast(`Не удалось сохранить голос: ${error.message || 'ошибка сети'}`);
    tg?.HapticFeedback?.notificationOccurred?.('error');
  } finally {
    busy = false;
    renderCategory();
  }
}

async function loadOfficialBallot() {
  const data = await api('/api/nyan-awards/official/status');
  for (const [local, server] of Object.entries(SERVER_CATEGORY)) {
    const expected = categories.find(item => item.id === local).candidates.map(id => Number(finalists[id].id));
    const actual = data.ballot?.[server];
    if (!Array.isArray(actual) || expected.length !== actual.length || expected.some(id => !actual.includes(id))) {
      throw new Error('Список финалистов на сервере не совпадает с утверждённым. Голосование приостановлено.');
    }
    const saved = data.my_votes?.[server];
    if (saved && actual.includes(saved)) {
      savedVotes.set(local, saved);
      const slug = categories.find(item => item.id === local).candidates.find(id => Number(finalists[id].id) === saved);
      if (!selectionByCategory.has(local)) selectionByCategory.set(local, slug);
    }
  }
  officialResults = data.results || {};
  setPhase(data.phase);
}

function showDetails(id) {
  const p = finalists[id];
  if (!p) return;
  const nominations = categories.filter(c=>c.candidates.includes(id)).map(c=>c.title);
  const link = profileUrl(p.username);
  modalContent.innerHTML = `<div class="modal-profile"><button type="button" class="modal-photo" data-photo="${id}" aria-label="Открыть фотографию ${escapeHtml(p.name)} целиком"><img src="./assets/nyan-awards/finalists/${escapeHtml(p.photo)}" alt="Изображение ${escapeHtml(p.name)}"></button><div class="modal-identity"><span class="section-kicker">АНКЕТА ФИНАЛИСТА / 2026</span><h2 id="modal-name">${escapeHtml(p.name)}</h2>${link ? `<a class="modal-username" href="${link}" target="_blank" rel="noopener noreferrer">${escapeHtml(p.username)} ↗</a>`:`<span class="modal-username">${escapeHtml(p.username)}</span>`}</div></div><div class="modal-body"><p class="modal-summary">${escapeHtml(p.summary)}</p><h3>основное из анкеты</h3><p class="modal-contribution">${escapeHtml(p.contribution)}</p><h3>номинации</h3><div class="modal-tags">${nominations.map(n=>`<span>${escapeHtml(n)}</span>`).join('')}</div><small class="modal-note">Описание составлено по ответам кандидата.</small></div>`;
  modal.showModal();
}

function showFullImage(id) {
  const person = finalists[id];
  if (!person) return;
  const photo = document.getElementById('lightbox-photo');
  photo.src = `./assets/nyan-awards/finalists/${person.photo}`;
  photo.alt = `Полная фотография ${person.name}`;
  document.getElementById('lightbox-caption').textContent = `${person.name} · оригинальное изображение`;
  lightbox.showModal();
}

menu.addEventListener('click', event => {
  const button = event.target.closest('[data-index]');
  if (!button) return;
  activeCategory = Number(button.dataset.index);
  renderCategory();
  if (window.innerWidth > 540) document.querySelector('.nomination-stage').scrollIntoView({behavior:'smooth',block:'start'});
});
cards.addEventListener('click', event => {
  const photo = event.target.closest('[data-photo]');
  if (photo) return showFullImage(photo.dataset.photo);
  const detail = event.target.closest('[data-details]');
  if (detail) return showDetails(detail.dataset.details);
  const select = event.target.closest('[data-select]');
  if (select) selectCandidate(select.dataset.select);
});
document.getElementById('confirm-vote').addEventListener('click', () => void submitVote());
document.getElementById('next-category').addEventListener('click',()=>{
  activeCategory = (activeCategory+1)%categories.length;
  renderCategory();
  if (window.innerWidth > 540) document.querySelector('.nomination-stage').scrollIntoView({behavior:'smooth',block:'start'});
});
document.getElementById('modal-close').addEventListener('click',()=>modal.close());
modal.addEventListener('click',event=>{
  const photo = event.target.closest('[data-photo]');
  if (photo) return showFullImage(photo.dataset.photo);
  if(event.target===modal)modal.close();
});
document.getElementById('lightbox-close').addEventListener('click',()=>lightbox.close());
lightbox.addEventListener('click',event=>{if(event.target===lightbox)lightbox.close()});
if (!initData) {
  setPhase('login');
} else {
  setPhase('loading');
  loadOfficialBallot().catch(error => {
    setPhase('error');
    showToast(error.message || 'Нет соединения с сервером.');
  });
  // Pick up the scheduled opening at 15:25 without requiring a manual reload.
  setInterval(() => {
    if (phase === 'review' || phase === 'loading') {
      loadOfficialBallot().catch(() => setPhase('error'));
    }
  }, 15000);
}
