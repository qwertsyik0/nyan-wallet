(() => {
"use strict";
const tg=window.Telegram?.WebApp;
tg?.ready();tg?.expand();
const BASE="https://nyan-wallet-bridge.qwertsyik.workers.dev/api/world/news";
const $=id=>document.getElementById(id);
for(const [id,path] of [["editor-back","nyan-world.html"],["editor-news","nyan-world-news.html"]])$(id).href="./"+path+location.search+location.hash;
let items=[],busy=false,current=null,dirty=false,saveAttempt=null,publication=null;
const uuid=()=>{
 if(crypto.randomUUID)return crypto.randomUUID();
 const b=crypto.getRandomValues(new Uint8Array(16));b[6]=b[6]&15|64;b[8]=b[8]&63|128;
 return [...b].map((v,i)=>([4,6,8,10].includes(i)?"-":"")+v.toString(16).padStart(2,"0")).join("");
};
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function status(text,error=false){$("editor-status").textContent=text;$("editor-status").className=error?"editor-error":""}
function disable(value){busy=value;document.querySelectorAll("#editor-workspace button,#post-form input,#post-form textarea").forEach(n=>n.disabled=value)}
async function api(path,body){
 if(!tg?.initData)throw Error("Открой редактор внутри Telegram через Nyan Wallet");
 let response;
 try{response=await fetch(BASE+path,{method:body?"POST":"GET",headers:{"Content-Type":"application/json","X-Telegram-Init-Data":tg.initData},body:body?JSON.stringify(body):undefined,cache:"no-store"})}
 catch(_){throw Error("Нет связи с сервером. Текст сохранён в форме. Можно повторить действие")}
 let data;try{data=await response.json()}catch(_){throw Error("Сервер не вернул ответ. Можно повторить действие")}
 if(!response.ok){
  const error=Error(response.status===403?"Редактор доступен только организатору":response.status===404?"Редактор ещё не установлен на сервере":typeof data.detail==="string"?data.detail:"Не удалось выполнить действие");
  error.status=response.status;throw error;
 }
 return data;
}
async function run(fn){if(busy)return;disable(true);try{await fn()}catch(e){status(e.message,true)}finally{disable(false)}}
function preview(target,post){
 target.replaceChildren(node("div",post.category.replace(/[•·]/g,"//"),"editor-category"),node("h2",post.title));
 for(const paragraph of post.body.split(/\n\s*\n/))if(paragraph.trim())target.append(node("p",paragraph));
}
function formValue(){return {category:$("post-category").value.trim(),title:$("post-title").value.trim(),body:$("post-body").value.trim()}}
function mayLeave(){return !dirty||window.confirm("Закрыть несохранённый текст?")}
function edit(post){
 if(!mayLeave())return;
 current=post?{...post}:null;dirty=false;saveAttempt=null;publication=null;
 $("publish-confirm").hidden=true;
 $("post-heading").textContent=post?"Изменить новость":"Новая новость";
 for(const key of ["category","title","body"])$("post-"+key).value=post?.[key]||"";
 $("post-preview").hidden=true;$("post-form").hidden=false;
 $("post-category").focus();
}
function render(){
 const list=$("post-list");list.replaceChildren();
 if(!items.length){list.append(node("p","Новостей пока нет. Создай первую.","empty"));return}
 for(const p of items){
  const card=node("article",undefined,"card"),labels=node("div",undefined,"post-status");
  labels.append(node("span",p.is_published?"Опубликовано":"Черновик","chip"));
  if(p.is_published&&p.has_changes)labels.append(node("span","Есть неопубликованные правки","chip"));
  card.append(labels,node("div",p.category,"editor-category"),node("h2",p.title),node("p",p.body.length>200?p.body.slice(0,200)+"…":p.body,"post-excerpt"));
  const actions=node("div",undefined,"actions");
  function button(text,fn){const b=node("button",text);b.type="button";b.onclick=fn;actions.append(b)}
  button("Редактировать",()=>edit(p));
  if(!p.is_published||p.has_changes)button(p.is_published?"Опубликовать правки":"Опубликовать",()=>askPublish(p,"publish"));
  if(p.is_published)button("Снять с публикации",()=>askPublish(p,"unpublish"));
  card.append(actions);list.append(card);
 }
}
async function load(){const data=await api("/editor");items=data.items;$("editor-workspace").hidden=false;render()}
function askPublish(post,kind){
 if(!mayLeave())return;
 $("post-form").hidden=true;dirty=false;current=null;saveAttempt=null;
 publication={operation_id:uuid(),kind,id:post.id,expected_revision:post.revision};
 $("publish-heading").textContent=kind==="publish"?"Опубликовать новость?":"Снять новость с публикации?";
 $("publish-description").textContent=kind==="publish"?"Этот текст станет доступен всем читателям сводки.":"Новость исчезнет из сводки и останется в редакторе.";
 preview($("publish-preview"),post);$("publish-confirm").hidden=false;
}
$("post-form").onsubmit=e=>{e.preventDefault();run(async()=>{
 const values=formValue();if(!values.category||!values.title||!values.body)throw Error("Заполни рубрику, заголовок и текст");
 const payload={kind:"save",...values,...(current?{id:current.id,expected_revision:current.revision}:{})};
 const serialized=JSON.stringify(payload);
 if(!saveAttempt||saveAttempt.serialized!==serialized)saveAttempt={serialized,body:{operation_id:uuid(),...payload}};
 const result=await api("/actions",saveAttempt.body);
 dirty=false;
 // Once acknowledged, bind the form to this record even if list refresh fails.
 current={...values,id:result.id,revision:(current?.revision||0)+1};
 saveAttempt=null;
 status("Черновик сохранён. Для публикации используй кнопку в списке.");
 await load();current=items.find(p=>p.id===result.id)||current;
})};
$("confirm-publish").onclick=()=>run(async()=>{
 if(!publication)return;
 await api("/actions",publication);const kind=publication.kind;publication=null;
 $("publish-confirm").hidden=true;status(kind==="publish"?"Новость опубликована":"Новость снята с публикации");await load();
});
$("cancel-publish").onclick=()=>{$("publish-confirm").hidden=true;publication=null};
$("new-post").onclick=()=>edit(null);
$("reload-posts").onclick=()=>run(async()=>{await load();status("Список обновлён")});
$("close-post").onclick=()=>{if(mayLeave()){$("post-form").hidden=true;dirty=false;current=null;saveAttempt=null}};
$("preview-post").onclick=()=>{preview($("post-preview"),formValue());$("post-preview").hidden=false};
for(const key of ["category","title","body"])$("post-"+key).oninput=()=>{dirty=true};
window.addEventListener("beforeunload",e=>{if(dirty){e.preventDefault();e.returnValue=""}});
run(async()=>{await load();status("Редактор готов")});
})();
