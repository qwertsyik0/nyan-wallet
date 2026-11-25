(() => {
"use strict";
const tg=window.Telegram?.WebApp;
function userId(){
 if(tg?.initDataUnsafe?.user?.id)return String(tg.initDataUnsafe.user.id);
 try{return String(JSON.parse(new URLSearchParams(tg?.initData||"").get("user")||"{}").id||"guest")}catch{return "guest"}
}
const key=season=>"nyan-world:rules:v1:"+userId()+":"+season;
function get(season){try{return localStorage.getItem(key(season))}catch{return null}}
function set(season,value){try{localStorage.setItem(key(season),value)}catch{}}
function cabinetURL(){const url=new URL("./nyan-world.html",location.href);url.search=location.search;url.hash=location.hash;url.searchParams.delete("world_rules_season");return url.href}
if(document.body.hasAttribute("data-world-rules-page")){
 tg?.ready();tg?.expand();
 const season=new URL(location.href).searchParams.get("world_rules_season");
 if(season&&/^\d+$/.test(season))set(season,"opened");
 for(const id of ["world-rules-back","world-rules-return"])document.getElementById(id).href=cabinetURL();
 return;
}
let overlay=null,active=false,previousFocus=null;
const background=[document.querySelector("main"),document.getElementById("editor")].filter(Boolean);
function show(season){
 if(!overlay){
  overlay=document.createElement("div");overlay.id="world-rules-gate";overlay.className="world-rules-gate";
  overlay.innerHTML='<section class="world-rules-window" role="dialog" aria-modal="true" aria-labelledby="world-rules-title" aria-describedby="world-rules-description"><img class="world-rules-mascot" src="./assets/nyan-world/nyanik-hold.webp" width="210" height="210" alt="" aria-hidden="true"><div class="world-rules-titlebar">NYAN WORLD</div><div class="world-rules-copy"><h2 id="world-rules-title">ознакомься с правилами</h2><p id="world-rules-description">Заявка отправлена. Пока организатор её рассматривает, прочитай правила участия.</p><a id="world-rules-open" class="world-rules-link" href="./nyan-world-rules.html">ознакомиться с правилами</a></div></section>';
  document.body.append(overlay);
 }
 const url=new URL("./nyan-world-rules.html",location.href);url.search=location.search;url.hash=location.hash;url.searchParams.set("world_rules_season",season);
 overlay.querySelector("a").href=url.href;overlay.dataset.season=season;overlay.hidden=false;
 if(!active)previousFocus=document.activeElement;
 active=true;background.forEach(n=>n.inert=true);document.documentElement.classList.add("world-rules-locked");
 tg?.BackButton?.hide();overlay.querySelector("a").focus();
}
function restore(season){
 if(get(season)==="pending")show(season);
 else if(active&&get(overlay.dataset.season)==="opened"){
  active=false;overlay.hidden=true;background.forEach(n=>n.inert=false);document.documentElement.classList.remove("world-rules-locked");
  if(previousFocus?.isConnected)previousFocus.focus();
 }
}
document.addEventListener("keydown",e=>{
 if(!active)return;
 if(e.key==="Escape"||e.key==="Tab"){e.preventDefault();e.stopImmediatePropagation();overlay.querySelector("a").focus()}
},true);
document.addEventListener("focusin",e=>{if(active&&!overlay.contains(e.target))overlay.querySelector("a").focus()},true);
window.addEventListener("pageshow",()=>{if(overlay)restore(overlay.dataset.season)});
window.NyanWorldRules={require(season){set(season,"pending");show(season)},restore};
})();
