const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {JSDOM}=require("jsdom");
const root=path.resolve(__dirname,"..");
const tick=()=>new Promise(r=>setTimeout(r,0));
async function fixture(owner,fallback){
 const dom=new JSDOM(fs.readFileSync(path.join(root,"nyan-world.html"),"utf8"),{url:"https://example.test/nyan-world.html",runScripts:"outside-only"});
 const w=dom.window,d=w.document,calls=[];
 w.Telegram={WebApp:{initData:"signed",ready(){},expand(){}}};
 if(!fallback){w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event("close"))}}
 else {w.HTMLDialogElement.prototype.showModal=undefined;w.HTMLDialogElement.prototype.close=undefined;Object.defineProperty(w.crypto,"randomUUID",{value:undefined})}
 const country={id:1,name:"Китай",leader:"<img src=x>",occupied:true,frozen:0};
 if(owner)Object.assign(country,{player_id:2,budget:18000,income:2400,expense:1900,debt:0,indicators:{"стабильность":80},notes:"Private notes"});
 const data={is_owner:owner,season:{id:1,name:"Season",currency:"WU",status:"registration",rules:""},seasons:[],active_season_id:1,countries:[country],my_country_id:owner?null:undefined,requests:[],ledger:[],audit:[],notices:[]};
 w.fetch=async(url,options)=>{if(url.endsWith("/actions")){calls.push(JSON.parse(options.body));return {ok:true,json:async()=>({ok:true})}}return {ok:true,json:async()=>data}};
 w.eval(fs.readFileSync(path.join(root,"nyan-world.js"),"utf8"));await tick();await tick();
 function click(text){const b=[...d.querySelectorAll("button")].find(x=>x.textContent===text);assert.ok(b,text);b.click()}
 click("Страны");return {w,d,click,calls,dom};
}
(async()=>{
 for(const fallback of [false,true]){
  for(const owner of [false,true]){
   const a=await fixture(owner,fallback),{w,d,click}=a;
   click("Информация о стране");
   const dialog=d.getElementById("editor"),fields=d.getElementById("fields");
   assert.equal(dialog.open,true);
   assert.equal(d.getElementById("submit").hidden,true);
   assert.match(fields.textContent,/Китай/);
   assert.match(fields.textContent,/Игрок назначен/);
   assert.equal(fields.querySelector("img"),null,"leader string must not become HTML");
   if(owner){assert.match(fields.textContent,/18.?000/);assert.match(fields.textContent,/Private notes/);assert.match(fields.textContent,/стабильность/)}
   else{assert.match(fields.textContent,/доступны руководителю/);assert.doesNotMatch(fields.textContent,/18.?000|Private notes/)}
   d.getElementById("form").dispatchEvent(new w.Event("submit",{cancelable:true}));await tick();
   assert.equal(a.calls.length,0,"read-only details cannot mutate data");
   d.getElementById("close").click();assert.equal(dialog.open,false);
   assert.equal(d.documentElement.classList.contains("world-dialog-open"),false);
   click("Информация о стране");assert.equal(dialog.open,true);d.getElementById("close").click();
   if(owner){
    click("Настройки");
    assert.equal(d.getElementById("submit").hidden,false,"normal editor must restore Save");
    d.getElementById("form").dispatchEvent(new w.Event("submit",{cancelable:true}));await tick();await tick();
    assert.equal(a.calls.length,1);assert.match(a.calls[0].operation_id,/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i);
   }
   a.dom.window.close();
  }
 }
 console.log("OK: explicit country info button, owner/player details, privacy, no mutations, close/reopen, dialog fallback and secure UUID fallback");
})().catch(e=>{console.error(e);process.exit(1)});
