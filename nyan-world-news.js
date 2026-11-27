(() => {
"use strict";
const tg=window.Telegram?.WebApp;tg?.ready();tg?.expand();
const suffix=location.search+location.hash;
for(const [id,path] of [["news-back","index.html"],["news-about","nyan-world-info.html"],["news-join","nyan-world.html"],["news-rules","nyan-world-rules.html"]])
 document.getElementById(id).href="./"+path+suffix;
const editorLink=document.getElementById("news-editor-link");
if(editorLink)editorLink.href="./nyan-world-news-editor.html"+suffix;
// The embedded briefing remains readable until the server editor is installed.
fetch("https://nyan-wallet-bridge.qwertsyik.workers.dev/api/world/news/feed",{cache:"no-store"})
.then(async response=>{
 if(!response.ok)throw Error("feed unavailable");
 const data=await response.json();if(!data.ok||!Array.isArray(data.items))throw Error("invalid feed");
 const list=document.querySelector(".news-stories");list.replaceChildren();
 for(const post of data.items){
  const article=document.createElement("article");article.className="card";
  const category=document.createElement("span");category.className="news-category";
  category.textContent=String(post.category||"").replace(/[•·]/g,"//");
  const title=document.createElement("h2");title.textContent=post.title;
  article.append(category,title);
  for(const text of String(post.body||"").split(/\n\s*\n/)){
   if(!text.trim())continue;const p=document.createElement("p");p.textContent=text;article.append(p);
  }
  list.append(article);
 }
 if(!data.items.length){const empty=document.createElement("p");empty.className="empty";empty.textContent="Новый выпуск скоро появится";list.append(empty)}
}).catch(()=>{
 const note=document.getElementById("news-feed-status");
 if(note){note.hidden=false;note.textContent="Не удалось обновить сводку. Показан предыдущий выпуск."}
});
if(!tg?.initData)return;
fetch("https://nyan-wallet-bridge.qwertsyik.workers.dev/api/world/state",{
 headers:{"X-Telegram-Init-Data":tg.initData},cache:"no-store"
}).then(async r=>{
 if(!r.ok)return;const data=await r.json();
 if(editorLink&&data.is_owner)editorLink.hidden=false;
 if(!data.season)return;
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
