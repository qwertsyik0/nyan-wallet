(() => {
"use strict";
const tg=window.Telegram?.WebApp;
const API="https://nyan-wallet-api.onrender.com/api/elections";
const phaseLabels={registration:"Регистрация партий",recruitment:"Набор участников",campaign:"Предвыборная кампания",voting:"Голосование",results:"Итоги",closed:"Завершён"};
let state=null,busy=false,readingImage=false,selectedEmblem=null,previewUrl=null;
const $=id=>document.getElementById(id);
tg?.ready?.(); tg?.expand?.();
function make(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=String(value);return n;}
function reset(node){node.replaceChildren();}
function alertUser(message){const n=$("el-alert");n.textContent=message||"";n.hidden=!message;}
function formFeedback(message){
  const box=$("el-form-feedback");
  box.textContent=message||"";
  box.hidden=!message;
  if(message)box.scrollIntoView({behavior:"smooth",block:"nearest"});
}
function programCount(){
  const text=$("el-create").elements.namedItem("program")?.value?.trim()||"";
  const counter=$("el-program-counter");
  const length=text.length;
  counter.textContent=length>=30 ? length+" символов · достаточно для заявки" : length+" из 30 минимальных символов";
  counter.dataset.valid=String(length>=30);
}
function validateParty(form){
  const fields={
    name:form.elements.namedItem("name"),
    short_name:form.elements.namedItem("short_name"),
    program:form.elements.namedItem("program"),
  };
  const name=fields.name.value.trim().replace(/\s+/g," ");
  const abbreviation=fields.short_name.value.trim().replace(/\s+/g," ");
  const program=fields.program.value.trim();
  const errors=[
    [!name,"name","Введите название партии."],
    [name.length<3,"name","Название партии должно содержать не менее 3 символов."],
    [name.length>80,"name","Название партии не должно превышать 80 символов."],
    [!abbreviation,"short_name","Введите аббревиатуру партии."],
    [abbreviation.length<2 || abbreviation.length>15,"short_name","Аббревиатура должна содержать от 2 до 15 символов."],
    [abbreviation.length>=2 && !/^[A-Za-zА-Яа-яЁё0-9 -]+$/.test(abbreviation),"short_name","Аббревиатура может содержать только буквы, цифры, пробелы и дефисы."],
    [program.length<30,"program","Напишите программу партии: минимум 30 символов (сейчас "+program.length+")."],
    [program.length>3000,"program","Программа партии не должна превышать 3000 символов."],
  ];
  for(const [failed,field,message] of errors){
    if(failed){formFeedback(message);fields[field].focus();return null;}
  }
  if(selectedEmblem && (!["image/png","image/jpeg","image/webp"].includes(selectedEmblem.type)||selectedEmblem.size>2*1024*1024||!selectedEmblem.size)){
    formFeedback("Для эмблемы выберите PNG, JPG или WebP до 2 МБ.");
    $("el-emblem-input").focus();
    return null;
  }
  formFeedback("");
  return {name,short_name:abbreviation,program};
}
function button(label,action,id,secondary=false){const n=make("button","el-button"+(secondary?" secondary":""),label);n.type="button";n.dataset.action=action;if(id!==undefined)n.dataset.id=String(id);return n;}
async function request(path="",payload){
  if(!tg?.initData)throw Error("Откройте выборы через кнопку в Telegram.");
  const r=await fetch(API+path,{method:payload===undefined?"GET":"POST",headers:{"X-Telegram-Init-Data":tg.initData,...(payload===undefined?{}:{"Content-Type":"application/json"})},body:payload===undefined?undefined:JSON.stringify(payload),cache:"no-store"});
  let data=null;try{data=await r.json();}catch(_){}
  if(!r.ok){
    const detail=data?.detail;
    if(r.status===503 && (detail==="maintenance" || data?.maintenance))throw Error("Сейчас включены технические работы. Попробуйте после их завершения.");
    if(r.status===413)throw Error("Изображение слишком большое. Максимум 2 МБ.");
    if(Array.isArray(detail)){
      const messages=detail.slice(0,3).map(item=>item?.msg||"Недопустимое значение");
      throw Error("Проверьте данные заявки: "+messages.join("; "));
    }
    throw Error(typeof detail==="string"?detail:"Не удалось отправить заявку (HTTP "+r.status+").");
  }
  return data;
}
function partyCard(p){
  const card=make("article","el-party"),head=make("div","el-party-head");
  head.append(make("div","el-party-title",p.name),make("span","el-party-short",p.short_name));card.append(head);
  card.append(make("div","el-party-meta","Председатель: "+p.chair_label+" · Участников: "+p.member_count));
  if(p.emblem_url){
    const img=make("img","el-party-emblem");
    img.alt="Эмблема партии «"+p.name+"»";
    img.loading="lazy";
    try {
      const candidate=new URL(p.emblem_url,new URL(API).origin);
      if(candidate.protocol==="https:")img.src=candidate.href;
    }catch(_){}
    if(img.src)card.append(img);
  }
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
  if(state.initial_rollback==="empty_initial_season_rolled_back"){
    area.append(make("p","el-muted","Предыдущий пустой сезон отменён. Можно создать новый."));
  }else if(state.initial_rollback==="skipped_contains_party_data"){
    area.append(make("p","el-muted","Автоматический откат остановлен: в сезоне уже есть партии или участники. Их данные не удалены."));
  }
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
function showEmblem(file){
  if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl=null;}
  selectedEmblem=null;
  const preview=$("el-emblem-preview");
  const previewImg=$("el-emblem-img");
  if(!file){
    preview.hidden=true;
    previewImg.removeAttribute("src");
    return;
  }
  if(!["image/png","image/jpeg","image/webp"].includes(file.type)){
    alertUser("Для эмблемы выберите PNG, JPG или WebP.");
    $("el-emblem-input").value="";
    preview.hidden=true;
    return;
  }
  if(file.size>2*1024*1024||file.size===0){
    alertUser("Размер изображения должен быть от 1 байта до 2 МБ.");
    $("el-emblem-input").value="";
    preview.hidden=true;
    return;
  }
  selectedEmblem=file;
  previewUrl=URL.createObjectURL(file);
  previewImg.src=previewUrl;
  preview.hidden=false;
  alertUser("");
}
function fileToDataUrl(file){
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>resolve(String(reader.result||""));
    reader.onerror=()=>reject(Error("Не удалось прочитать изображение"));
    reader.readAsDataURL(file);
  });
}
async function submitParty(form){
  if(busy||readingImage)return;
  readingImage=true;
  const payload=validateParty(form);
  if(!payload){readingImage=false;return;}
  const sendButton=$("el-party-submit");
  const defaultText=sendButton.textContent;
  sendButton.disabled=true;
  sendButton.textContent="Отправляем заявку…";
  try{
    if(selectedEmblem)payload.emblem_data=await fileToDataUrl(selectedEmblem);
    await mutate("/parties",payload);
  }catch(e){
    formFeedback(e.message||"Не удалось прочитать изображение");
  }finally{
    readingImage=false;
    sendButton.disabled=false;
    sendButton.textContent=defaultText;
  }
}
$("el-create").addEventListener("input",()=>{
  formFeedback("");
  programCount();
});
programCount();
$("el-emblem-input").addEventListener("change",event=>{
  showEmblem(event.target.files?.[0]||null);
});
$("el-emblem-remove").addEventListener("click",()=>{
  $("el-emblem-input").value="";
  showEmblem(null);
});
document.addEventListener("paste",event=>{
  if($("el-create-section").hidden)return;
  const items=Array.from(event.clipboardData?.items||[]);
  const entry=items.find(item=>item.kind==="file"&&item.type.startsWith("image/"));
  if(entry){
    const image=entry.getAsFile();
    if(image){event.preventDefault();showEmblem(image);}
  }
});
async function mutate(path,payload={}){
  if(busy)return;busy=true;
  document.querySelectorAll("#el-main button").forEach(n=>n.disabled=true);
  try{await request(path,payload);await reload("Изменения сохранены.");}
  catch(e){
    const message=e?.name==="TypeError" ? "Не удалось подключиться к серверу. Проверьте соединение и повторите." : e.message;
    if(path==="/parties")formFeedback(message);
    else alertUser(message);
    if(state)render();
  }
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
  event.preventDefault();
  if(form.id==="el-season-form"){
    if(!form.reportValidity())return;
    const data=Object.fromEntries(new FormData(form));
    mutate("/owner/seasons",{title:data.title});
  }else submitParty(form);
});
$("el-back").addEventListener("click",()=>{
  if(history.length>1)history.back();
  else location.assign(new URL("./",location.href).toString());
});
reload();
})();