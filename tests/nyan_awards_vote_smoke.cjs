/* Run: node tests/nyan_awards_vote_smoke.cjs
   Local-only UI smoke test: all remote API calls are intercepted. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const mime = {html:'text/html; charset=utf-8',js:'application/javascript',css:'text/css',jpg:'image/jpeg',png:'image/png',webp:'image/webp'};
const server = http.createServer((request, response) => {
  const requested = decodeURIComponent(new URL(request.url,'http://localhost').pathname);
  const target = path.resolve(root, '.' + requested);
  if (!target.startsWith(root + path.sep)) { response.writeHead(403).end(); return; }
  fs.readFile(target, (error, body) => {
    if (error) { response.writeHead(404).end(); return; }
    response.writeHead(200, {'Content-Type': mime[path.extname(target).slice(1)] || 'application/octet-stream'}).end(body);
  });
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({executablePath:'/usr/bin/chromium', headless:true, args:['--no-sandbox']});
  const page = await browser.newPage({viewport:{width:390,height:850}});
  const votes = [];
  let phase = 'review';
  await page.route('https://telegram.org/js/telegram-web-app.js', route => route.fulfill({
    contentType:'application/javascript', body:'window.Telegram={WebApp:{initData:"test-telegram-auth",ready(){},expand(){},HapticFeedback:{notificationOccurred(){}}}};'
  }));
  await page.route('https://nyan-wallet-bridge.qwertsyik.workers.dev/**', async route => {
    const url = route.request().url();
    if (url.endsWith('/official/status')) return route.fulfill({json:{phase,ballot:{legend_nyan:[6968551476,5291356933,5354595027],discovery:[6651466766,8162240045]},my_votes:{}}});
    if (url.endsWith('/official/vote')) {votes.push(JSON.parse(route.request().postData()));return route.fulfill({json:{ok:true}});}
    return route.fulfill({status:404,json:{detail:'unknown'}});
  });
  const base = `http://127.0.0.1:${server.address().port}/nyan-awards-vote.html`;
  await page.goto(base, {waitUntil:'domcontentloaded'});
  await page.getByText('скоро открытие', {exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:/подтвердить голос/}).isEnabled(),false);
  assert.equal(await page.getByRole('button',{name:'Открыть фотографию Пиксель целиком'}).count(),1);
  await page.getByRole('button',{name:'Открыть фотографию Пиксель целиком'}).click();
  assert.equal(await page.locator('#image-lightbox').evaluate(el=>el.open),true);
  assert.equal(await page.locator('#lightbox-photo').evaluate(el=>getComputedStyle(el).objectFit),'contain');
  await page.getByRole('button',{name:'Закрыть фотографию'}).click();

  phase = 'voting';
  await page.reload({waitUntil:'domcontentloaded'});
  await page.getByText('голосование открыто', {exact:true}).waitFor();
  await page.locator('[data-select="pixel"]').click();
  await page.locator('#confirm-vote').click();
  await page.getByText('голос учтён ✓').waitFor();
  assert.deepEqual(votes, [{category:'legend_nyan',candidate_id:6968551476}]);
  await page.locator('[data-index="4"]').click();
  assert.equal(await page.locator('#confirm-vote').isVisible(),false);
  assert.equal(await page.getByText('номинация не проводится',{exact:true}).count() > 0,true);
  console.log('PASS: pre-open gate, full photo, official Telegram vote, solo nomination disabled');
  await browser.close();
  server.close();
})().catch(error => {console.error(error);server.close();process.exitCode=1;});
