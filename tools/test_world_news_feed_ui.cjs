const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),{JSDOM}=require("jsdom");
const root=path.resolve(__dirname,".."),tick=()=>new Promise(r=>setTimeout(r,0));
async function check(mode){
 const dom=new JSDOM(fs.readFileSync(path.join(root,"nyan-world-news.html"),"utf8"),{url:"https://example.test/nyan-world-news.html",runScripts:"outside-only"});
 const w=dom.window;
 w.fetch=async()=>mode==="failure"?{ok:false,status:503}:{
  ok:true,json:async()=>({ok:true,items:mode==="empty"?[]:[{id:1,category:"A • B",title:"<img src=x>",body:"One\n\n<script>bad()</script>"}]})
 };
 w.eval(fs.readFileSync(path.join(root,"nyan-world-news.js"),"utf8"));await tick();await tick();
 const list=w.document.querySelector(".news-stories");
 if(mode==="failure"){assert.equal(list.querySelectorAll("article").length,19);assert.equal(w.document.getElementById("news-feed-status").hidden,false)}
 else if(mode==="empty"){assert.equal(list.querySelectorAll("article").length,0);assert.match(list.textContent,/скоро/)}
 else{assert.equal(list.querySelectorAll("article").length,1);assert.equal(list.querySelectorAll("img,script").length,0);assert.equal(list.querySelectorAll("p").length,2);assert.equal(list.querySelector(".news-category").textContent,"A // B")}
 dom.window.close();
}
(async()=>{await check("published");await check("empty");await check("failure");console.log("OK: public feed, empty publication, safe text and fallback")})().catch(e=>{console.error(e);process.exit(1)});
