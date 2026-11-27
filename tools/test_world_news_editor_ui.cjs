const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const {JSDOM}=require("jsdom"),{randomUUID}=require("node:crypto");
const root=path.resolve(__dirname,".."),tick=()=>new Promise(r=>setTimeout(r,0));
async function settle(){await tick();await tick();await tick()}
async function fixture(role="owner"){
 const dom=new JSDOM(fs.readFileSync(path.join(root,"nyan-world-news-editor.html"),"utf8"),{url:"https://example.test/nyan-world-news-editor.html?x=1#tgWebAppData=signed",runScripts:"outside-only"});
 const w=dom.window,calls=[];let failNext=false;
 w.Telegram={WebApp:{initData:role,ready(){},expand(){}}};
 Object.defineProperty(w.crypto,"randomUUID",{value:randomUUID});w.confirm=()=>true;
 let records=[{id:1,category:"A // B",title:"Published",body:"Original",revision:1,is_published:true,has_changes:false}];
 w.fetch=async(url,options)=>{
  assert.equal(options.headers["X-Telegram-Init-Data"],role);
  if(role!=="owner")return {ok:false,status:403,json:async()=>({detail:"owner"})};
  if(url.endsWith("/actions")){
   const p=JSON.parse(options.body);calls.push(p);
   if(failNext){failNext=false;throw Error("network")}
   if(p.kind==="save"){
    const r={...p,id:p.id||2,revision:(p.expected_revision||0)+1,is_published:false,has_changes:true};
    records=records.filter(x=>x.id!==r.id);records.unshift(r);
    return {ok:true,json:async()=>({ok:true,id:r.id})};
   }
   const r=records.find(x=>x.id===p.id);r.is_published=p.kind==="publish";r.has_changes=false;r.revision++;
   return {ok:true,json:async()=>({ok:true,id:r.id})};
  }
  return {ok:true,json:async()=>({items:JSON.parse(JSON.stringify(records))})};
 };
 w.eval(fs.readFileSync(path.join(root,"nyan-world-news-editor.js"),"utf8"));await settle();
 const click=text=>{const b=[...w.document.querySelectorAll("button")].find(x=>x.textContent===text);assert.ok(b,text);b.click()};
 return {w,dom,calls,click,fail(){failNext=true}};
}
(async()=>{
 const f=await fixture();const $=id=>f.w.document.getElementById(id);
 assert.equal($("editor-workspace").hidden,false);
 assert.equal($("editor-back").href,"https://example.test/nyan-world.html?x=1#tgWebAppData=signed");
 f.click("Новая новость");
 for(const [key,value] of [["category","КИТАЙ • ФРАНЦИЯ"],["title","<img src=x onerror=alert(1)>"],["body","First\n\n<script>alert(1)</script>"]]){
  $("post-"+key).value=value;$("post-"+key).dispatchEvent(new f.w.Event("input"));
 }
 f.click("Предпросмотр");
 assert.equal($("post-preview").querySelectorAll("img,script").length,0);
 assert.equal($("post-preview").querySelectorAll("p").length,2);
 f.fail();$("post-form").dispatchEvent(new f.w.Event("submit",{cancelable:true}));await settle();
 assert.ok($("editor-status").textContent.includes("Нет связи"));
 assert.equal($("post-body").value,"First\n\n<script>alert(1)</script>");
 $("post-form").dispatchEvent(new f.w.Event("submit",{cancelable:true}));await settle();
 assert.equal(f.calls[0].operation_id,f.calls[1].operation_id);
 assert.equal(f.calls.filter(x=>x.kind==="publish").length,0);
 f.click("Опубликовать");assert.equal($("publish-confirm").hidden,false);
 assert.equal(f.calls.filter(x=>x.kind==="publish").length,0);
 f.click("Подтвердить");await settle();
 assert.equal(f.calls.at(-1).kind,"publish");assert.equal(f.calls.at(-1).id,2);
 f.click("Снять с публикации");f.click("Подтвердить");await settle();
 assert.equal(f.calls.at(-1).kind,"unpublish");
 f.dom.window.close();
 const p=await fixture("player");assert.equal(p.w.document.getElementById("editor-workspace").hidden,true);assert.match(p.w.document.getElementById("editor-status").textContent,/только организатору/);p.dom.window.close();
 console.log("OK: editor owner access, safe preview, draft retry, explicit publication and unpublication");
})().catch(e=>{console.error(e);process.exit(1)});
