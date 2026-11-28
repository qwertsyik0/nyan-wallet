const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {JSDOM}=require("jsdom");
const {randomUUID}=require("node:crypto");
const root=path.resolve(__dirname,"..");
const html=fs.readFileSync(path.join(root,"nyan-world.html"),"utf8");
const script=fs.readFileSync(path.join(root,"nyan-world.js"),"utf8");
const tick=()=>new Promise(r=>setTimeout(r,0));
async function fixture(owner,applicant=false){
 const dom=new JSDOM(html,{url:"https://example.test/nyan-world.html",runScripts:"outside-only"});
 const w=dom.window, calls=[];
 w.Telegram={WebApp:{initData:"signed",ready(){},expand(){}}};
 Object.defineProperty(w.crypto,"randomUUID",{value:randomUUID});
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
 w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const data={is_owner:owner,season:{id:1,name:"Season",status:"active",currency:"WU",rules:"",chat_url:""},active_season_id:1,seasons:[{id:1,name:"Season"}],my_country_id:owner?null:1,
 countries:[{id:1,name:"A",leader:"Leader",player_id:2,budget:1000,income:10,expense:5,debt:0,frozen:0,indicators:{stability:50},notes:"",occupied:true},{id:2,name:"B",player_id:null,budget:500,income:0,expense:0,debt:0,indicators:{},occupied:false}],
 requests:[],ledger:[],audit:[],notices:[]};
 if(applicant){data.my_country_id=null;delete data.countries[1].budget}
 let failNext=false;
 w.fetch=async (url,options)=>{
  if(url.endsWith("/actions")){
   calls.push(JSON.parse(options.body));
   if(failNext){failNext=false;throw Error("connection lost")}
   return {ok:true,json:async()=>({ok:true})};
  }
  return {ok:true,json:async()=>JSON.parse(JSON.stringify(data))};
 };
 w.eval(script);await tick();await tick();
 const find=(text)=>[...w.document.querySelectorAll("button")].find(b=>b.textContent===text);
 const click=(text)=>{const b=find(text);assert.ok(b,"button "+text);b.click()};
 const fill=(prefix,value)=>{
  const l=[...w.document.querySelectorAll("#fields label")].find(l=>l.firstChild.textContent.startsWith(prefix));
  assert.ok(l,"field "+prefix);l.querySelector("input,textarea,select").value=value;
 };
 const save=async()=>{w.document.getElementById("form").dispatchEvent(new w.Event("submit",{cancelable:true}));await tick();await tick()};
 return {w,data,calls,click,fill,save,fail(){failNext=true},close(){dom.window.close()}};
}
(async()=>{
 const a=await fixture(true);
 a.click("Новый сезон");a.fill("Название","New");a.fill("Название игровой","Test");
 a.fail();await a.save();assert.equal(a.calls.length,1);const id=a.calls[0].operation_id;
 await a.save();assert.equal(a.calls[1].operation_id,id,"retry must retain idempotency ID");
 assert.equal(a.calls[1].data.name,"New");
 a.click("Страны");
 const countryNames=()=>[...a.w.document.querySelectorAll("#country-list > .card > h2")].map(n=>n.textContent);
 assert.deepEqual(countryNames(),["A","B"]);
 const filter=a.w.document.getElementById("country-filter");filter.value="free";filter.dispatchEvent(new a.w.Event("change"));
 assert.deepEqual(countryNames(),["B"]);
 a.click("Кабинет");a.click("Страны");assert.equal(a.w.document.getElementById("country-filter").value,"free");
 a.data.countries[1].occupied=true;
 a.click("Обновить");await tick();await tick();
 assert.ok(a.w.document.getElementById("country-list").textContent.includes("Свободных стран пока нет"));
 a.data.countries[1].occupied=false;
 a.click("Добавить страну");
 a.fill("Страна","C");a.fill("Telegram ID","123");a.fill("Начальный бюджет","200");
 await a.save();assert.equal(a.calls.at(-1).kind,"country");assert.equal(a.calls.at(-1).data.opening_budget,200);
 a.data.requests=[{id:7,country_id:1,kind:"decision",title:"Build",body:"Details",status:"submitted",revision:1,comment:"",effects:{},updated_at:"2026-11-25T10:00:00Z"}];
 a.click("Обновить");await tick();await tick();a.click("Заявки");a.click("Рассмотреть");
 a.fill("Комментарий","approved");a.fill("Изменение бюджета","-20");await a.save();
 assert.equal(a.calls.at(-1).kind,"review");assert.equal(a.calls.at(-1).data.effects.budget_delta,-20);
 assert.equal(a.calls.filter(c=>c.kind==="apply").length,0,"approval must not apply effects");
 a.data.requests[0].status="approved";a.click("Обновить");await tick();await tick();
 a.click("Применить последствия");await a.save();assert.equal(a.calls.at(-1).kind,"apply");
 a.close();
 const p=await fixture(false);p.click("Первое решение");p.fill("Заголовок","Reform");p.fill("Опиши","Reform details");await p.save();
 assert.equal(p.calls.at(-1).kind,"submit");assert.equal(p.calls.at(-1).data.country_id,1);
 assert.equal([...p.w.document.querySelectorAll("button")].some(b=>b.textContent==="Управление"),false);
 p.close();
 const join=await fixture(false,true);
 join.click("Выбрать страну");
 assert.equal(join.w.document.getElementById("country-filter").value,"free");
 assert.deepEqual([...join.w.document.querySelectorAll("#country-list > .card > h2")].map(n=>n.textContent),["B"]);
 join.click("Подать заявку на страну");
 assert.equal(join.w.document.querySelectorAll("#fields textarea,#fields select,#fields input:not([type=checkbox])").length,0,"signup needs no written fields");
 const rulesLink=join.w.document.querySelector("#fields a");
 assert.equal(new URL(rulesLink.href).searchParams.get("world_rules_season"),"1");
 await join.save();assert.equal(join.calls.length,0,"rules acknowledgement is required");
 join.w.document.querySelector("#fields input[type=checkbox]").checked=true;
 join.fail();await join.save();const joinId=join.calls.at(-1).operation_id;
 await join.save();assert.equal(join.calls.at(-1).operation_id,joinId);
 assert.equal(join.calls.at(-1).data.country_id,2);
 assert.equal(join.calls.at(-1).data.kind,"registration");
 assert.match(join.calls.at(-1).data.body,/С правилами/);
 join.data.requests=[{id:15,country_id:2,kind:"registration",status:"submitted",title:"Участие: B",body:"",revision:1,effects:{}}];
 join.click("Обновить");await tick();await tick();join.click("Кабинет");
 assert.match(join.w.document.getElementById("app").textContent,/Заявка отправлена/);
 join.click("Страны");assert.equal([...join.w.document.querySelectorAll("button")].some(b=>b.textContent==="Подать заявку на страну"),false,"pending signup blocks another signup");
 join.data.requests=[];join.data.countries[1].frozen=1;
 join.click("Обновить");await tick();await tick();
 assert.match(join.w.document.getElementById("country-list").textContent,/Свободных стран пока нет/);
 join.data.my_country_id=2;join.data.countries[1].frozen=0;join.data.countries[1].occupied=true;
 join.click("Обновить");await tick();await tick();join.click("Кабинет");join.click("Первое решение");
 assert.ok(join.w.document.querySelector("#fields textarea"),"approved player gets ordinary decision form");
 join.close();console.log("OK: owner forms, player request, moderation, explicit apply, retry ID and role navigation");
})().catch(e=>{console.error(e);process.exit(1)});
