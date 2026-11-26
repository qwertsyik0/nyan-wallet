const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),{JSDOM}=require("jsdom");
const root=path.resolve(__dirname,".."),tick=()=>new Promise(r=>setTimeout(r,0));
(async()=>{
 for(const [state,expected] of [
  [{season:{status:"active"},countries:[{name:"Британия",occupied:false},{name:"Россия",occupied:true}]},"Британия"],
  [{season:{status:"active"},countries:[]},"все страны заняты"],
  [{season:{status:"finished"},countries:[]},"набор на страны закрыт"],
  [{season:{status:"active"},my_country_id:1,countries:[]},"У тебя уже есть страна"]
 ]){
  const dom=new JSDOM(fs.readFileSync(path.join(root,"nyan-world-news.html"),"utf8"),{url:"https://example.test/nyan-world-news.html?test=1#tgWebAppData=signed",runScripts:"outside-only"});
  const w=dom.window;w.Telegram={WebApp:{initData:"signed",ready(){},expand(){}}};
  w.fetch=async()=>({ok:true,json:async()=>state});
  w.eval(fs.readFileSync(path.join(root,"nyan-world-news.js"),"utf8"));await tick();await tick();
  assert.ok(w.document.getElementById("news-vacancies").textContent.includes(expected));
  assert.equal(w.document.getElementById("news-join").href,"https://example.test/nyan-world.html?test=1#tgWebAppData=signed");
  assert.equal(w.document.querySelectorAll(".news-stories article").length,3);
  dom.window.close();
 }
 console.log("OK: news briefing, real vacancies, closed season, own country and Telegram context");
})().catch(e=>{console.error(e);process.exit(1)});
