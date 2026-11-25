const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {JSDOM}=require("jsdom");
const {randomUUID}=require("node:crypto");
const root=path.resolve(__dirname,"..");
const html=fs.readFileSync(path.join(root,"nyan-world.html"),"utf8");
const script=fs.readFileSync(path.join(root,"nyan-world.js"),"utf8");
const tick=()=>new Promise(r=>setTimeout(r,0));
async function fixture(owner,options={}){
 const dom=new JSDOM(html,{url:"https://example.test/nyan-world.html",runScripts:"outside-only"});
 const w=dom.window, calls=[];
 w.Telegram={WebApp:{initData:"signed",initDataUnsafe:{user:{id:42}},ready(){},expand(){},BackButton:{hide(){}}}};
 const storage=options.storage||new Map();Object.defineProperty(w,"localStorage",{value:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)}});
 Object.defineProperty(w.crypto,"randomUUID",{value:randomUUID});
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
 w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const data={is_owner:owner,season:{id:1,name:"Season",status:"active",currency:"WU",rules:"",chat_url:""},active_season_id:1,seasons:[{id:1,name:"Season"}],my_country_id:owner?null:1,
 countries:[{id:1,name:"A",leader:"Leader",player_id:2,budget:1000,income:10,expense:5,debt:0,frozen:0,indicators:{stability:50},notes:"",occupied:true},{id:2,name:"B",player_id:null,budget:500,income:0,expense:0,debt:0,indicators:{},occupied:false}],
 requests:[],ledger:[],audit:[],notices:[]};
 if(options.applicant)data.my_country_id=null;
 if(options.initialFailure)data.season.status="registration";
 let failNext=false;
 w.fetch=async (url,options)=>{
  if(url.endsWith("/actions")){
   calls.push(JSON.parse(options.body));
   if(failNext){failNext=false;throw Error("connection lost")}
   return {ok:true,json:async()=>({ok:true})};
  }
  return {ok:true,json:async()=>JSON.parse(JSON.stringify(data))};
 };
 w.eval(fs.readFileSync(path.join(root,"nyan-world-rules.js"),"utf8"));
 w.eval(script);await tick();await tick();
 const find=(text)=>[...w.document.querySelectorAll("button")].find(b=>b.textContent===text);
 const click=(text)=>{const b=find(text);assert.ok(b,"button "+text);b.click()};
 const fill=(prefix,value)=>{
  const l=[...w.document.querySelectorAll("#fields label")].find(l=>l.firstChild.textContent.startsWith(prefix));
  assert.ok(l,"field "+prefix);l.querySelector("input,textarea,select").value=value;
 };
 const save=async()=>{w.document.getElementById("form").dispatchEvent(new w.Event("submit",{cancelable:true}));await tick();await tick()};
 return {w,data,calls,storage,click,fill,save,fail(){failNext=true},close(){dom.window.close()}};
}

(async()=>{
 const p=await fixture(false,{applicant:true});
 assert.equal(p.w.document.getElementById("world-rules-gate"),null,"no prompt before success");
 p.click("Страны");p.click("Подать заявку на страну");
 p.fill("Заголовок","Application");p.fill("Опиши","I want to lead");
 p.fail();await p.save();
 assert.equal(p.w.document.getElementById("world-rules-gate"),null,"failed request must not show prompt");
 await p.save();
 assert.equal(p.calls.at(-1).data.kind,"registration");
 const gate=p.w.document.getElementById("world-rules-gate");
 assert.ok(gate&&!gate.hidden,"successful registration opens gate");
 assert.equal(gate.querySelectorAll("button").length,0,"no dismiss control");
 assert.ok(gate.querySelector("img").src.endsWith("/assets/nyan-world/nyanik-hold.webp"));
 const link=gate.querySelector("a");
 const target=new URL(link.href);assert.equal(target.pathname,"/nyan-world-rules.html");
 assert.equal(target.searchParams.get("world_rules_season"),"1");
 gate.click();assert.equal(gate.hidden,false,"backdrop does not dismiss");
 const event=new p.w.KeyboardEvent("keydown",{key:"Escape",bubbles:true,cancelable:true});
 p.w.document.dispatchEvent(event);assert.ok(event.defaultPrevented);assert.equal(gate.hidden,false);
 p.w.document.dispatchEvent(new p.w.KeyboardEvent("keydown",{key:"Tab",bubbles:true,cancelable:true}));
 assert.equal(p.w.document.activeElement,link);
 assert.equal(p.w.document.querySelector("main").inert,true);
 const key="nyan-world:rules:v1:42:1";assert.equal(p.storage.get(key),"pending");
 const storage=p.storage;p.close();
 const reloaded=await fixture(false,{applicant:true,storage});
 assert.equal(reloaded.w.document.getElementById("world-rules-gate").hidden,false,"reload preserves pending prompt");
 const rulesHTML=fs.readFileSync(path.join(root,"nyan-world-rules.html"),"utf8");
 const rulesDOM=new JSDOM(rulesHTML,{url:target.href+"#tgWebAppData=signed",runScripts:"outside-only"});
 rulesDOM.window.Telegram={WebApp:{initDataUnsafe:{user:{id:42}},ready(){},expand(){}}};
 Object.defineProperty(rulesDOM.window,"localStorage",{value:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)}});
 rulesDOM.window.eval(fs.readFileSync(path.join(root,"nyan-world-rules.js"),"utf8"));
 assert.equal(storage.get(key),"opened","only rules page clears pending prompt");
 assert.equal(rulesDOM.window.document.querySelectorAll("section.card").length,8);
 for(const phrase of ["72 часов","21 ДЕНЬ","только с разрешения организатора","Бюджет пополняется по ситуации","Дискриминация"])
  assert.ok(rulesDOM.window.document.body.textContent.includes(phrase),phrase);
 const back=new URL(rulesDOM.window.document.getElementById("world-rules-return").href);
 assert.equal(back.pathname,"/nyan-world.html");assert.equal(back.searchParams.has("world_rules_season"),false);
 assert.equal(back.hash,"#tgWebAppData=signed","Telegram context survives navigation");
 reloaded.w.dispatchEvent(new reloaded.w.PageTransitionEvent("pageshow",{persisted:true}));
 assert.equal(reloaded.w.document.getElementById("world-rules-gate").hidden,true,"browser back after reading unlocks cabinet");
 assert.equal(reloaded.w.document.querySelector("main").inert,false);
 reloaded.close();rulesDOM.window.close();
 const player=await fixture(false);player.click("Подать действие");player.fill("Заголовок","Reform");player.fill("Опиши","Details");await player.save();
 assert.equal(player.w.document.getElementById("world-rules-gate"),null,"ordinary actions do not trigger registration prompt");
 player.close();
 console.log("OK: successful registration gate, failure and retry, mascot, no dismiss, focus trap, reload, rules, return and ordinary actions");
})().catch(e=>{console.error(e);process.exit(1)});
