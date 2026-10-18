(() => {
"use strict";
const tg=window.Telegram?.WebApp;
const API="https://nyan-wallet.tail327bb6.ts.net/api/elections";
const $=id=>document.getElementById(id);
const create=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
let state=null,busy=false,proposed=null;
const phases={campaign:"Ожидает открытия",voting:"Голосование открыто",results:"Голосование завершено",closed:"Результаты",registration:"Регистрация",recruitment:"Набор участников"};
tg?.ready?.();tg?.expand?.();

async function call(path,post=false,body={}){
  if(!tg?.initData)throw Error("Открой Nyan Elections через Telegram.");
  const response=await fetch(API+path,{
    method:post?"POST":"GET",
    headers:{"X-Telegram-Init-Data":tg.initData,...(post?{"Content-Type":"application/json"}:{})},
    body:post?JSON.stringify(body):undefined,cache:"no-store"
  });
  let data;
  try{data=await response.json();}catch(_){data=null;}
  if(!response.ok){
    const detail=data?.detail;
    if(response.status===404)throw Error("Система голосования ещё не опубликована на сервере.");
    throw Error(typeof detail==="string"?detail:"Ошибка сервера (HTTP "+response.status+").");
  }
  return data;
}
function error(message){$("vote-alert").hidden=!message;$("vote-alert").textContent=message||"";}
function imageOf(p){
  if(!p.emblem_url)return null;
  try{
    const target=new URL(p.emblem_url,new URL(API).origin);
    if(target.protocol!=="https:")return null;
    const img=create("img","vote-emblem");
    img.alt="Эмблема партии "+p.name;img.loading="lazy";img.src=target.href;
    return img;
  }catch(_){return null;}
}
function card(p){
  const box=create("article","vote-party"),head=create("div","vote-party-head");
  const headText=create("div",""),title=create("h3","vote-party-name",p.name);
  headText.append(title,create("span","vote-chair","Председатель: "+p.chair_label));
  head.append(headText,create("span","el-party-short",p.short_name));box.append(head);
  const img=imageOf(p);if(img)box.append(img);
  box.append(create("p","vote-summary",p.summary||p.program));
  const details=create("details","vote-details");
  details.append(create("summary","","Читать полную программу"),
    create("p","vote-full-program",p.program));
  box.append(details);
  if(state.phase==="voting" && state.my_vote_party_id===null){
    const btn=create("button","el-button vote-pick","Выбрать партию");
    btn.type="button";btn.dataset.partyId=String(p.id);box.append(btn);
  }else if(state.my_vote_party_id===p.id){
    box.append(create("div","vote-selected","Твой голос учтён"));
  }
  return box;
}
function renderResults(){
  const area=$("vote-results");area.hidden=!["results","closed"].includes(state.phase);
  if(area.hidden)return;
  const total=Number(state.total_votes||0);
  $("vote-results-total").textContent="Подтверждённых голосов: "+total;
  const container=$("vote-result-list");container.replaceChildren();
  const counts=new Map((state.results||[]).map(item=>[item.party_id,item.votes]));
  for(const p of [...(state.ballot||[])].sort((a,b)=>(counts.get(b.id)||0)-(counts.get(a.id)||0)||a.id-b.id)){
    const votes=counts.get(p.id)||0,percent=total?100*votes/total:0;
    const card=create("div","vote-result");
    const top=create("div","vote-result-top");
    top.append(create("strong","",p.name),create("span","",votes+" · "+percent.toFixed(1)+"%"));
    const bar=create("div","vote-bar"),fill=create("div","vote-bar-fill");
    fill.style.width=percent.toFixed(2)+"%";bar.append(fill);
    card.append(top,bar);container.append(card);
  }
}
function renderOwner(){
  const area=$("vote-owner");area.hidden=!state.is_owner;
  if(!state.is_owner)return;
  const note=$("vote-owner-note"),btn=$("vote-owner-action");
  btn.hidden=true;btn.disabled=busy;
  if(state.phase==="campaign"){
    note.textContent="Предпросмотр готов. При открытии список партий будет зафиксирован, вступление в партии закроется. Голосование завершится только по твоей команде.";
    btn.textContent="Открыть голосование";btn.dataset.action="open";
    btn.hidden=!(state.ballot?.length>=2);
  }else if(state.phase==="voting"){
    note.textContent="Проголосовало: "+(state.total_votes||0)+". Промежуточные результаты пользователям не показываются. Закрытие необратимо.";
    btn.textContent="Завершить голосование";btn.dataset.action="close";btn.hidden=false;
  }else if(["results","closed"].includes(state.phase)){
    note.textContent="Голосование закрыто. Всего учтено голосов: "+(state.total_votes||0)+". Результаты опубликованы.";
    if(state.phase==="results"){
      btn.textContent="Архивировать сезон";btn.dataset.action="archive";btn.hidden=false;
    }
  }else{
    note.textContent="Голосование можно открыть после завершения агитации.";
  }
}
function render(){
  $("vote-loading").hidden=true;
  $("vote-phase").textContent=phases[state.phase]||"Ожидает начала";
  const intro=$("vote-intro"),title=$("vote-intro-title"),desc=$("vote-intro-desc");
  intro.hidden=false;
  if(state.phase==="voting"){
    title.textContent=state.my_vote_party_id===null?"Твой голос важен":"Голос принят";
    desc.textContent=state.my_vote_party_id===null
      ?"Изучи предложения каждой партии. Перед записью голоса мы попросим подтверждение. После него изменить выбор нельзя."
      :"Твой выбор зарегистрирован и сохранён. Повторно голосовать нельзя.";
  }else if(["results","closed"].includes(state.phase)){
    title.textContent="Голосование завершено";
    desc.textContent="Приём голосов закрыт решением владельца. Ниже опубликованы итоговые результаты.";
  }else if(state.phase==="campaign"){
    title.textContent=state.is_owner?"Предпросмотр бюллетеня":"Дебаты завершены";
    desc.textContent=state.is_owner
      ?"Ниже список допущенных партий. Проверь состав и программы до открытия голосования."
      :"Скоро откроется голосование. Вернись в этот раздел после объявления владельца.";
  }else{
    title.textContent="Выборы ещё не дошли до голосования";
    desc.textContent="Подготовка продолжается. Здесь появится бюллетень после открытия.";
  }
  const list=$("vote-list"),parties=$("vote-parties");
  list.hidden=!state.ballot?.length || !["voting","results","closed","campaign"].includes(state.phase);
  $("vote-list-title").textContent=state.phase==="campaign"?"Предпросмотр партий":state.phase==="voting"?"Партии в бюллетене":"Участники голосования";
  parties.replaceChildren();
  if(!list.hidden)for(const p of state.ballot)parties.append(card(p));
  renderResults();renderOwner();
}
async function load(){
  if(busy)return;
  $("vote-loading").hidden=false;error("");
  try{
    const data=await call("/voting/status");
    state=data;render();
  }catch(e){
    $("vote-loading").hidden=true;
    $("vote-intro").hidden=false;
    $("vote-intro-title").textContent="Не удалось загрузить бюллетень";
    $("vote-intro-desc").textContent="Повтори запрос, не закрывая Telegram.";
    $("vote-list").hidden=true;$("vote-results").hidden=true;$("vote-owner").hidden=true;
    error(e instanceof TypeError?"Соединение с API прервалось. Попробуй ещё раз.":e.message);
  }
}
function closeModal(){
  if(busy)return;
  proposed=null;$("vote-confirm").hidden=true;
  document.body.classList.remove("vote-modal-open");
}
function showModal(kind,id=null){
  if(busy)return;
  let text="",label="Подтвердить",title="Подтверждение";
  if(kind==="cast"){
    const party=state?.ballot?.find(p=>p.id===id);
    if(!party||state.phase!=="voting"||state.my_vote_party_id!==null)return;
    text="Ты выбираешь «"+party.name+"». После подтверждения изменить или отменить голос нельзя.";
    title="Подтвердить голос";label="Отдать голос";
  }else if(kind==="open"){
    if(!state?.is_owner||state.phase!=="campaign")return;
    title="Открыть голосование";
    text="Открыть приём голосов за "+state.ballot.length+" партии? Список участников будет зафиксирован. Автоматического завершения не будет.";
    label="Открыть";
  }else if(kind==="close"){
    if(!state?.is_owner||state.phase!=="voting")return;
    title="Завершить голосование";
    text="Остановить приём голосов и сразу опубликовать результаты? Это действие необратимо.";
    label="Завершить";
  }else if(kind==="archive"){
    if(!state?.is_owner||state.phase!=="results")return;
    title="Архивировать сезон";
    text="Перевести завершённый сезон в архив? Все итоги останутся сохранены, а в Nyan Elections можно будет создать следующий сезон.";
    label="Архивировать";
  }else return;
  proposed={kind,id};
  $("vote-confirm-title").textContent=title;
  $("vote-confirm-text").textContent=text;
  $("vote-submit").textContent=label;
  $("vote-confirm").hidden=false;document.body.classList.add("vote-modal-open");
  $("vote-cancel").focus();
}
async function submit(){
  if(!proposed||busy)return;
  const {kind,id}=proposed;busy=true;
  $("vote-submit").disabled=true;$("vote-cancel").disabled=true;
  try{
    if(kind==="cast")await call("/voting/cast",true,{party_id:id});
    else if(kind==="open")await call("/owner/voting/open",true);
    else if(kind==="close")await call("/owner/voting/close",true);
    else if(kind==="archive")await call("/owner/voting/archive",true);
    proposed=null;$("vote-confirm").hidden=true;document.body.classList.remove("vote-modal-open");
    busy=false;await load();
  }catch(e){
    proposed=null;$("vote-confirm").hidden=true;document.body.classList.remove("vote-modal-open");
    busy=false;
    error(e instanceof TypeError
      ?"Соединение прервалось. Проверяем статус: действие могло сохраниться."
      :e.message);
    // Always re-read server state rather than blindly resubmit on network failure.
    if(e instanceof TypeError)await load();
  }finally{
    $("vote-submit").disabled=false;$("vote-cancel").disabled=false;
  }
}
document.addEventListener("click",event=>{
  const selected=event.target.closest("[data-party-id]");
  if(selected){showModal("cast",Number(selected.dataset.partyId));return;}
});
$("vote-owner-action").addEventListener("click",event=>showModal(event.currentTarget.dataset.action));
$("vote-cancel").addEventListener("click",closeModal);
$("vote-submit").addEventListener("click",submit);
$("vote-refresh").addEventListener("click",load);
$("vote-back").addEventListener("click",()=>{
  const url=new URL("./elections.html",location.href);
  url.search=location.search;url.hash=location.hash;
  location.assign(url.toString());
});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!busy)load();});
load();
})();
