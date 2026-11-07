'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'referral_ui_fix.js'), 'utf8');
const start = source.indexOf('    function readStartParam() {');
const end = source.indexOf('\n    function headers(', start);
assert.ok(start > -1 && end > start);
const promoReader = source.slice(start, end);

function promoAt(href, startParam = '') {
  return vm.runInNewContext(`${promoReader}\nreadStartParam()`, {
    URL,
    URLSearchParams,
    window: { location: { href } },
    tg: {
      initDataUnsafe: { start_param: startParam },
      initData: startParam ? `start_param=${encodeURIComponent(startParam)}` : '',
    },
  });
}

const base = 'https://qwertsyik0.github.io/nyan-wallet/';
for (const game of ['nyan_story', 'nyan_spy', 'nyan_mafia', 'nyan_awards', 'lottery']) {
  assert.equal(promoAt(`${base}?tgWebAppStartParam=${game}`), null, `${game} hijacked`);
  assert.equal(promoAt(base, game), null, `${game} initData hijacked`);
}
assert.equal(promoAt(`${base}?startapp=promo_nyan109`), 'nyan109');
assert.equal(promoAt(`${base}?startapp=nyan200`), 'nyan200');
assert.equal(promoAt(`${base}?promo=custom_special`), 'custom-special');

const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const routing = html.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1];
assert.ok(routing, 'Mini App routing script absent');
function navigate(startParam) {
  let href = null;
  vm.runInNewContext(routing, {
    URL,
    URLSearchParams,
    window: {
      location: {
        href: `${base}index.html`,
        replace(target) { href = target; },
      },
      Telegram: { WebApp: { initData: `start_param=${startParam}`, initDataUnsafe: {} } },
    },
  });
  return href;
}
assert.equal(navigate('nyan_story'), `${base}nyan-story.html`);
assert.equal(navigate('nyan_spy'), `${base}nyan-spy.html`);
console.log('Mini App routing: game start params never open the promo card');
