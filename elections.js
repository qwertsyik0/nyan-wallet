(() => {
"use strict";
const tg=window.Telegram?.WebApp;
const API="https://nyan-wallet-api.onrender.com/api/elections";
const phaseLabels={registration:"Регистрация партий",recruitment:"Набор участников",campaign:"Предвыборная кампания",voting:"Голосование",results:"Итоги",closed:"Завершён"};
let state=null,busy=false;
const $=id=>document.getElementById(id);
tg?.ready?.(); tg?.expand?.();
function make(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=String(value);return n;}
function reset(node){node.replaceChildren();}
function alertUser(message){const n=$("el-alert");n.textContent=message||"";n.hidden=!message;}
function button(label,action,id,secondary=false){const n=make("button","el-button"+(secondary?" secondary":""),label);n.type="button";n.dataset.action=action;if(id!==undefined)n.dataset.id=String(id);return n;}
async function request(path="",payload){
  if(!tg?.initData)throw Error("Откройте выборы через кнопку в Telegram.");
  const r=await fetch(API+path,{method:payload===undefined?"GET":"POST",headers:{"X-Telegram-Init-Data":tg.initData,...(payload===undefined?{}:{"Content-Type":"application/json"})},body:payload===undefined?undefined:JSON.stringify(payload),cache:"no-store"});
  let data=null;try{data=await r.json();}catch(_){}
  if(!r.ok)throw Error(typeof data?.detail==="string"?data.detail:"Не удалось выполнить действие. Повторите позже.");
  return data;
}
function partyCard(p){
  const card=make("article","el-party"),head=make("div","el-party-head");
  head.append(make("div","el-party-title",p.name),make("span","el-party-short",p.short_name));card.append(head);
  card.append(make("div","el-party-meta","Председатель: "+p.chair_label+" · Участников: "+p.member_count));
  card.append(make("p","",p.program));
  if(["recruitment","campaign"].includes(state.season.phase)&&state.my_party_id!==p.id){
    const row=make("div","el-actions");
    row.append(button(state.my_party_id?"Сменить партию":"Вступить","join",p.id,true));card.append(row);
  }
  return card;
}
async function loadPending(){
  try {
    const data=await request("/owner/pending"),area=$("el-owner-pending");reset(area);
    for(const item of data.parties||[]){
      const card=partyCard(item),row=make("div","el-actions");
      row.append(button("Одобрить","approve",item.id),button("Отклонить","reject",item.id,true));
      card.append(row);area.append(card);
    }
    if(!data.parties?.length)area.append(make("p","el-muted","Нет ожидающих заявок."));
  }catch(e){alertUser(e.message);}
}
function renderOwner(){
  const section=$("el-owner-section");section.hidden=!state.is_owner;if(!state.is_owner)return;
  const area=$("el-owner-content");reset(area);reset($("el-owner-pending"));
  if(!state.season){
    const form=make("form","el-form");form.id="el-season-form";
    const label=make("label","","Название сезона"),input=make("input");
    input.name="title";input.required=true;input.minLength=4;input.maxLength=120;input.placeholder="Выборы Нян — октябрь";
    label.append(input);const submit=make("button","el-button","Создать сезон");submit.type="submit";
    form.append(label,submit);area.append(form);return;
  }
  if(state.season.phase==="registration"){
    area.append(button("Завершить регистрацию и открыть набор","phase","recruitment"));
    loadPending();
  }else if(state.season.phase==="recruitment"){
    area.append(button("Перейти к агитации","phase","campaign"));
  }else if(state.season.phase==="campaign"){
    area.append(make("p","el-muted","Голосование откроется после внедрения тайных бюллетеней и проверки антифрода."));
  }
}
function render(){
  $("el-loading").hidden=true;$("el-main").hidden=false;
  const season=state.season,parties=$("el-parties");
  $("el-phase").textContent=season?season.title+" · "+(phaseLabels[season.phase]||season.phase):"Сезон пока не объявлен";
  $("el-party-count").textContent=String(state.parties?.length||0);
  reset(parties);
  if(!state.parties?.length)parties.append(make("p","el-muted",season?"Одобренных партий пока нет.":"Выборы пока не объявлены."));
  else for(const item of state.parties)parties.append(partyCard(item));
  const mine=$("el-my-section"),body=$("el-my-content");reset(body);
  mine.hidden=!(state.my_party_id||state.applications?.length);
  const party=state.parties?.find(p=>p.id===state.my_party_id);
  if(party){
    body.append(make("p","el-muted","Вы состоите в партии «"+party.name+"»."));
    if(["recruitment","campaign"].includes(season?.phase))body.append(button("Покинуть партию","leave",undefined,true));
  }
  for(const p of state.applications||[]){
    body.append(make("p","el-muted","Заявка «"+p.name+"»: "+(p.status==="pending"?"на рассмотрении":"отклонена")+"."));
    if(p.decision_note)body.append(make("p","el-muted",p.decision_note));
  }
  $("el-create-section").hidden=!season||season.phase!=="registration"||Boolean(state.applications?.length)||Boolean(state.my_party_id);
  renderOwner();
}
async function reload(message=""){
  try{state=await request();render();alertUser(message);}
  catch(e){$("el-main").hidden=true;$("el-loading").hidden=false;$("el-loading").textContent="Данные выборов временно недоступны.";alertUser(e.message);}
}
async function mutate(path,payload={}){
  if(busy)return;busy=true;
  document.querySelectorAll("#el-main button").forEach(n=>n.disabled=true);
  try{await request(path,payload);await reload("Изменения сохранены.");}
  catch(e){alertUser(e.message);if(state)render();}
  finally{busy=false;}
}
document.addEventListener("click",event=>{
  const n=event.target.closest("button[data-action]");if(!n||busy)return;
  const action=n.dataset.action,id=n.dataset.id;
  if(action==="join")mutate("/parties/"+encodeURIComponent(id)+"/join");
  else if(action==="leave")mutate("/parties/leave");
  else if(action==="phase")mutate("/owner/phase",{next_phase:id});
  else if(action==="approve"||action==="reject")mutate("/owner/parties/"+encodeURIComponent(id)+"/review",{decision:action==="approve"?"approve":"reject"});
});
document.addEventListener("submit",event=>{
  const form=event.target;if(!["el-create","el-season-form"].includes(form.id))return;
  event.preventDefault();if(!form.reportValidity())return;
  const data=Object.fromEntries(new FormData(form));
  if(form.id==="el-season-form")mutate("/owner/seasons",{title:data.title});
  else mutate("/parties",{name:data.name,short_name:data.short_name,program:data.program,emblem_url:data.emblem_url||null});
});
$("el-back").addEventListener("click",()=>{
  if(history.length>1)history.back();
  else location.assign(new URL("./",location.href).toString());
});
reload();
})();