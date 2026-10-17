(() => {
"use strict";
const tg=window.Telegram?.WebApp;
const API="https://nyan-wallet.tail327bb6.ts.net/api/elections";
const $=id=>document.getElementById(id);
let state=null,busy=false;
tg?.ready?.();tg?.expand?.();
function error(message){$("game-error").hidden=!message;$("game-error").textContent=message||"";}
async function call(path,post=false){
  if(!tg?.initData)throw Error("Откройте страницу из Telegram-бота Nyan Wallet.");
  const response=await fetch(API+path,{method:post?"POST":"GET",headers:{"X-Telegram-Init-Data":tg.initData},cache:"no-store"});
  let data={};try{data=await response.json()}catch(_){}
  if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Ошибка сервера (HTTP "+response.status+").");
  return data;
}
function node(tag,cls,text){const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x;}
function button(text,callback){const x=node("button","el-button",text);x.type="button";x.disabled=busy;x.addEventListener("click",callback);return x;}
async function refresh(){state=await call("/games/status");render();if(state.is_owner)loadOwnerRoster();}

async function loadOwnerRoster(){
  const list=$("game-owner-list");
  $("game-owner-section").hidden=false;
  list.replaceChildren(node("p","el-muted","Загружаем подтверждения…"));
  try {
    const data=await call("/owner/games/signups");
    list.replaceChildren();
    if(!data.signups.length)list.append(node("p","el-muted","Пока никто не подтвердил участие."));
    for(const signup of data.signups){
      const entry=node("article","games-owner-row");
      entry.append(node("strong","",((signup.username||"Без username")+" · "+signup.telegram_id)));
      entry.append(node("small","",signup.party));
      list.append(entry);
    }
  }catch(e){list.replaceChildren(node("p","el-muted",e.message||"Не удалось загрузить список."));}
}
function render(){
 const status=$("game-status"),actions=$("game-actions"),wrap=$("game-party-section"),parties=$("game-parties");
 actions.replaceChildren();parties.replaceChildren();error("");
 if(!state.season){status.textContent="Игры пока не объявлены.";wrap.hidden=true;return;}
 if(!["recruitment","campaign"].includes(state.season.phase)){status.textContent="Запись на игры сейчас закрыта.";wrap.hidden=true;return;}
 const mine=state.parties.find(p=>p.id===state.my_party_id);
 if(mine){
   wrap.hidden=true;
   if(state.confirmed){status.textContent="Участие подтверждено · "+mine.name;status.classList.add("games-good");}
   else{status.classList.remove("games-good");status.textContent="Ты состоишь в партии «"+mine.name+"», но ещё не подтвердил участие.";actions.append(button("Подтвердить участие",()=>submit("/games/confirm")));}
 }else{
   status.classList.remove("games-good");status.textContent="Ты пока не состоишь в партии. Выбери одну из доступных партий, чтобы записаться.";wrap.hidden=false;
   for(const p of state.parties){
      const box=node("article","el-party games-party"),name=node("div","el-party-title games-party-name",p.name),small=node("p","games-muted","После вступления потребуется подтвердить участие.");
      box.append(name,small,button("Вступить в партию",()=>submit("/parties/"+encodeURIComponent(p.id)+"/join")));parties.append(box);
   }
   if(!state.parties.length)parties.append(node("p","el-muted","Нет доступных партий."));
 }
}
async function submit(path){
 if(busy)return;busy=true;document.querySelectorAll("button").forEach(n=>n.disabled=true);error("");
 try{await call(path,true);await refresh();}
 catch(e){error(e.message||"Не удалось записаться.");}
 finally{busy=false;document.querySelectorAll("button").forEach(n=>n.disabled=false);}
}
refresh().catch(e=>{$("game-status").textContent="Не удалось загрузить запись.";error(e.message||"Попробуйте позже.");});
})();