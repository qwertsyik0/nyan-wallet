(() => {
"use strict";
const tg=window.Telegram?.WebApp;tg?.ready();tg?.expand();
const suffix=location.search+location.hash;
for(const [id,path] of [["news-back","index.html"],["news-about","nyan-world-info.html"],["news-join","nyan-world.html"],["news-rules","nyan-world-rules.html"]])
 document.getElementById(id).href="./"+path+suffix;
if(!tg?.initData)return;
fetch("https://nyan-wallet-bridge.qwertsyik.workers.dev/api/world/state",{
 headers:{"X-Telegram-Init-Data":tg.initData},cache:"no-store"
}).then(async r=>{
 if(!r.ok)return;const data=await r.json();if(!data.season)return;
 const label=document.getElementById("news-vacancies"),button=document.getElementById("news-join");
 if(!["registration","active"].includes(data.season.status)){
  label.textContent="Сейчас набор на страны закрыт. Состояние сезона можно посмотреть в кабинете.";
  button.textContent="открыть кабинет";return;
 }
 const free=(data.countries||[]).filter(c=>!c.occupied);
 if(data.my_country_id){
  label.textContent="У тебя уже есть страна. Первые события можно продолжить своим решением.";
  button.textContent="перейти к своей стране";
 }else if(free.length){
  label.textContent="Свободные страны: "+free.map(c=>c.name).join(", ")+".";
 }else{
  label.textContent="Сейчас все страны заняты. Следи за следующим набором.";
  button.textContent="посмотреть страны";
 }
}).catch(()=>{});
})();