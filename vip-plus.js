/* Nyan VIP visual kit and owner-controlled entitlements.
 * Requires the existing vip.js purchase flow; no payment code is replaced.
 */
(() => {
  'use strict';
  const tg = window.Telegram?.WebApp;
  const API = 'https://nyan-wallet-bridge.qwertsyik.workers.dev';
  const ASSETS = './assets/vip/';
  const SKIN_KEY = 'nyan-vip-exclusive-wallpaper';
  let lastState = null;
  let loading = false;
  const $ = id => document.getElementById(id);
  const asset = name => ASSETS + name;
  const image = (name, alt, className = '') => {
    const node = document.createElement('img');
    node.src = asset(name);
    node.alt = alt;
    node.loading = 'lazy';
    node.className = className;
    return node;
  };
  const elem = (tag, className = '', value = '') => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value) node.textContent = value;
    return node;
  };
  function notice(value, isError = false) {
    const el = $('nyan-vip-plus-notice');
    if (!el) return;
    el.textContent = value;
    el.dataset.error = String(isError);
  }
  async function request(path, method = 'GET', body = null) {
    if (!tg?.initData) throw new Error('Открой Nyan Wallet через Telegram');
    const response = await fetch(API + path, {
      method, cache: 'no-store',
      headers: {
        'X-Telegram-Init-Data': tg.initData,
        ...(body === null ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === null ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.detail || 'Не удалось получить VIP данные');
    return data;
  }
  function enabledSkin() { try { return localStorage.getItem(SKIN_KEY) === '1'; } catch { return false; } }
  function saveSkin(enabled) { try { localStorage.setItem(SKIN_KEY, enabled ? '1' : '0'); } catch {} }
  function applySkin() {
    document.documentElement.classList.toggle('nyan-vip-exclusive-skin', Boolean(lastState?.active && enabledSkin()));
    const button = $('nyan-vip-skin-toggle');
    if (button) {
      button.disabled = !lastState?.active;
      button.textContent = !lastState?.active ? 'Доступно после активации VIP' :
        enabledSkin() ? 'Убрать VIP фон кошелька' : 'Применить VIP фон кошелька';
    }
  }
  const PERKS = [
    { img: '09_vip_30days_promo.png', title: '30 дней VIP', desc: '30 дней с возможностью продления' },
    { img: '08_vip_medallion.png', title: 'VIP значок', desc: 'Отображается в Nyan ID' },
    { img: '11_vip_profile_frame.png', title: 'Рамка Nyan ID', desc: 'Эксклюзивное оформление профиля' },
    { img: '10_vip_priority_support.png', title: 'Приоритет обращений', desc: 'Ваши заявки поднимаются выше в очереди Nyan Wallet' },
    { img: '16_vip_cashback.png', title: 'Кэшбэк 8%', desc: 'Вместо обычных 5% за подтверждённые покупки Nyan Shop' },
    { img: '12_vip_gift.png', title: 'Подарки', desc: 'Выдаёт администрация вручную' },
    { img: '15_vip_raffle.png', title: 'VIP розыгрыши', desc: 'Допуск выдаёт администрация вручную' },
    { img: '13_vip_early_access.png', title: 'Ранний доступ', desc: 'Анонсы и материалы для активных VIP' },
    { img: '14_vip_wallet_customization.png', title: 'VIP оформление', desc: 'Эксклюзивный фон кошелька' },
  ];
  function addSection(root) {
    const banner = image('01_vip_hero_banner.png', 'Nyan VIP: Няник и Мишня', 'nyan-vip-plus-banner');
    const heading = root.querySelector('.nyan-vip-head');
    heading?.insertAdjacentElement('afterend', banner);

    const original = root.querySelector('.nyan-vip-perks');
    const section = elem('section', 'nyan-vip-plus');
    section.id = 'nyan-vip-plus';
    section.setAttribute('aria-label', 'Привилегии подписки');
    const subtitle = elem('h3', 'nyan-vip-plus-title', 'Все преимущества VIP');
    const grid = elem('div', 'nyan-vip-plus-grid');
    for (const info of PERKS) {
      const card = elem('article', 'nyan-vip-plus-card');
      card.append(image(info.img, '', 'nyan-vip-plus-icon'));
      const box = elem('div', 'nyan-vip-plus-card-copy');
      box.append(elem('strong', '', info.title), elem('span', '', info.desc));
      card.append(box);
      grid.append(card);
    }
    section.append(subtitle, grid);

    const controls = elem('div', 'nyan-vip-plus-controls');
    const toggle = elem('button', 'nyan-vip-plus-button', 'VIP фон кошелька');
    toggle.id = 'nyan-vip-skin-toggle';
    toggle.type = 'button';
    toggle.addEventListener('click', () => {
      if (!lastState?.active) return;
      saveSkin(!enabledSkin());
      applySkin();
      notice(enabledSkin() ? 'VIP оформление включено' : 'Возвращён ваш обычный фон кошелька');
    });
    const appeal = elem('button', 'nyan-vip-plus-button secondary', 'Перейти к обращениям');
    appeal.type = 'button';
    appeal.addEventListener('click', () => {
      $('nyan-vip-close')?.click();
      const trigger = $('appeals-button');
      if (trigger) trigger.click();
      else notice('Раздел обращений пока не загружен. Открой его с главного экрана.', true);
    });
    controls.append(toggle, appeal);
    const ownerNote = elem('p', 'nyan-vip-plus-hint', 'Подарки и места в VIP розыгрышах назначаются администрацией отдельно.');
    const access = elem('section', 'nyan-vip-plus-access');
    access.id = 'nyan-vip-plus-access';
    const grants = elem('section', 'nyan-vip-plus-grants');
    grants.id = 'nyan-vip-plus-grants';
    const message = elem('div', 'nyan-vip-plus-notice');
    message.id = 'nyan-vip-plus-notice';
    message.setAttribute('role', 'status');
    section.append(controls, ownerNote, access, grants, message);

    if (original) {
      original.hidden = true;
      original.insertAdjacentElement('afterend', section);
    } else root.querySelector('.nyan-vip-state')?.insertAdjacentElement('afterend', section);

    const admin = makeAdminPanel();
    section.append(admin);
    applySkin();
  }
  function input(label, type, id, placeholder) {
    const wrapper = elem('label', 'nyan-vip-plus-field');
    wrapper.append(elem('span', '', label));
    let field = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') field.type = type;
    field.id = id;
    field.placeholder = placeholder || '';
    field.autocomplete = 'off';
    wrapper.append(field);
    return wrapper;
  }
  function ownerAction(text, handler) {
    const button = elem('button', 'nyan-vip-plus-button', text);
    button.type = 'button';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await handler(); notice('Сохранено'); await refresh(); }
      catch (e) { notice(e.message || 'Не удалось выполнить действие', true); }
      finally { button.disabled = false; }
    });
    return button;
  }
  function required(id) { return ($(id)?.value || '').trim(); }
  function userId() { const v = Number(required('nyan-vip-admin-user')); if (!Number.isSafeInteger(v) || v < 1) throw new Error('Укажи Telegram ID'); return v; }
  function makeAdminPanel() {
    const box = elem('details', 'nyan-vip-plus-admin');
    box.id = 'nyan-vip-plus-admin';
    box.hidden = true;
    box.append(elem('summary', '', 'Управление VIP (владелец)'));
    const fields = elem('div', 'nyan-vip-plus-fields');
    fields.append(
      input('Telegram ID получателя', 'number', 'nyan-vip-admin-user', '123456789'),
      input('ID события / заказа', 'text', 'nyan-vip-admin-key', 'gift_2026_001'),
      input('Название подарка / розыгрыша', 'text', 'nyan-vip-admin-title', 'VIP подарок'),
      input('Лапкоины за подарок (0 для предмета)', 'number', 'nyan-vip-admin-amount', '0'),
    );
    const actions = elem('div', 'nyan-vip-plus-admin-actions');
    actions.append(
      ownerAction('Выдать VIP подарок', () => request('/api/owner/vip/grants', 'POST', {
        telegram_id: userId(), kind: 'gift', event_key: required('nyan-vip-admin-key'),
        title: required('nyan-vip-admin-title'), amount: Number(required('nyan-vip-admin-amount') || 0),
      })),
      ownerAction('Допустить к VIP розыгрышу', () => request('/api/owner/vip/grants', 'POST', {
        telegram_id: userId(), kind: 'raffle', event_key: required('nyan-vip-admin-key'),
        title: required('nyan-vip-admin-title'), amount: 0,
      })),
      ownerAction('Отозвать допуск', () => request('/api/owner/vip/raffles/revoke', 'POST', {
        telegram_id: userId(), event_key: required('nyan-vip-admin-key'),
      })),
    );
    const cashback = elem('div', 'nyan-vip-plus-admin-cashback');
    cashback.append(elem('h4', '', 'Подтверждённый заказ Nyan Shop'));
    cashback.append(input('Сумма в рублях (например 251.10)', 'number', 'nyan-vip-admin-rub', '251.10'));
    cashback.append(ownerAction('Начислить 5% / VIP 8%', () => {
      const rubles = required('nyan-vip-admin-rub');
      if (!/^\d{1,7}(?:[.,]\d{1,2})?$/.test(rubles)) throw new Error('Неверная сумма покупки');
      const [whole, cents = ''] = rubles.replace(',', '.').split('.');
      const kopecks = Number(whole) * 100 + Number(cents.padEnd(2, '0'));
      return request('/api/owner/vip/shop-cashback', 'POST', {
        telegram_id: userId(), order_id: required('nyan-vip-admin-key'), paid_kopecks: kopecks,
      });
    }));
    const preview = elem('div', 'nyan-vip-plus-admin-preview');
    preview.append(elem('h4', '', 'VIP ранний доступ'));
    preview.append(
      input('Название анонса', 'text', 'nyan-vip-admin-preview-title', 'Скоро в Nyan'),
      input('Описание (только для VIP)', 'textarea', 'nyan-vip-admin-preview-text', 'Что нового'),
      input('HTTPS ссылка (необязательно)', 'url', 'nyan-vip-admin-preview-url', 'https://...'),
    );
    preview.append(ownerAction('Опубликовать VIP анонс', () => request('/api/owner/vip/early-access', 'POST', {
      enabled: true,
      title: required('nyan-vip-admin-preview-title'),
      description: required('nyan-vip-admin-preview-text'),
      url: required('nyan-vip-admin-preview-url') || null,
    })));
    preview.append(ownerAction('Скрыть VIP анонс', () => request('/api/owner/vip/early-access', 'POST', {
      enabled: false,
      title: required('nyan-vip-admin-preview-title') || 'Nyan VIP',
      description: required('nyan-vip-admin-preview-text'),
      url: required('nyan-vip-admin-preview-url') || null,
    })));
    box.append(fields, actions, cashback, preview);
    return box;
  }
  function renderBenefits(data) {
    lastState = data;
    applySkin();
    const admin = $('nyan-vip-plus-admin');
    if (admin) admin.hidden = !data.is_owner;
    const cashback = document.querySelector('.nyan-vip-plus-card:nth-child(5) .nyan-vip-plus-card-copy span');
    if (cashback) cashback.textContent = data.active
      ? 'Активно: 8% вместо 5% за подтверждённые покупки Nyan Shop'
      : 'Активируется с VIP, стандартный кэшбэк 5%';
    const access = $('nyan-vip-plus-access');
    if (access) {
      access.replaceChildren();
      access.append(elem('h4', '', 'Ранний доступ'));
      if (data.early_access) {
        access.append(elem('strong', '', data.early_access.title));
        access.append(elem('p', '', data.early_access.description));
        if (data.early_access.url) {
          const link = elem('a', 'nyan-vip-plus-preview-link', 'Открыть анонс');
          link.href = data.early_access.url;
          link.rel = 'noopener noreferrer';
          link.target = '_blank';
          access.append(link);
        }
      } else access.append(elem('p', '', data.active ? 'Новых VIP анонсов пока нет.' : 'Доступно после активации VIP.'));
    }
    const grants = $('nyan-vip-plus-grants');
    if (grants) {
      grants.replaceChildren();
      grants.append(elem('h4', '', 'Мои VIP подарки и розыгрыши'));
      const items = [...(data.manual_gifts || []), ...(data.raffle_entries || [])];
      if (!items.length) grants.append(elem('p', '', 'Администрация пока не выдавала подарков или допусков.'));
      else for (const item of items) {
        grants.append(elem('div', 'nyan-vip-plus-grant', (item.kind === 'gift' ? 'Подарок: ' : 'Розыгрыш: ') +
          item.title + (item.amount ? ' · +' + item.amount + ' 🐾' : '')));
      }
    }
  }
  async function refresh() {
    if (loading || !tg?.initData) return;
    loading = true;
    try {
      const data = await request('/api/vip/benefits');
      renderBenefits(data);
      notice('');
    } catch (err) {
      // Fail closed: no cosmetic privileges without verified server state.
      lastState = null;
      applySkin();
      if ($('nyan-vip-plus')) notice(err.message || 'Проверка VIP недоступна', true);
    } finally { loading = false; }
  }
  function enhance() {
    const overlay = $('nyan-vip-overlay');
    if (!overlay || $('nyan-vip-plus')) return;
    addSection(overlay);
    refresh();
  }
  function onEntryClick(event) {
    if (event.target?.closest?.('#nyan-vip-open')) {
      queueMicrotask(() => { enhance(); refresh(); });
    }
  }
  function init() {
    document.addEventListener('click', onEntryClick, true);
    const observer = new MutationObserver(enhance);
    observer.observe(document.body, {childList:true});
    const entryObserver = new MutationObserver(() => {
      const entry = document.querySelector('#nyan-vip-open .nyan-vip-symbol');
      if (entry && !entry.querySelector('img')) entry.replaceChildren(image('03_vip_round_badge.png', '', 'nyan-vip-entry-img'));
    });
    entryObserver.observe(document.body, {childList:true, subtree:true});
    enhance();
    refresh();
    window.addEventListener('nyan:vip-updated', refresh);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true});
  else init();
})();
