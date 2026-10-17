(() => {
  "use strict";
  const tg = window.Telegram?.WebApp;
  const API = "https://nyan-wallet.tail327bb6.ts.net";
  const input = document.getElementById("suggestion-text");
  const counter = document.getElementById("counter");
  const button = document.getElementById("submit");
  const status = document.getElementById("status");

  tg?.ready?.();
  tg?.expand?.();

  function headers(json=false){
    const h={"X-Telegram-Init-Data":tg?.initData||""};
    if(json) h["Content-Type"]="application/json";
    return h;
  }
  async function readJson(res){ try{return await res.json()}catch{return {}} }
  function setStatus(text,type=""){ status.textContent=text||""; status.className="status"+(type?" "+type:""); }
  function setLocked(locked,label){
    input.disabled=locked;
    button.disabled=locked;
    if(label) button.textContent=label;
  }
  function prettyState(item){
    if(!item) return;
    if(item.status==="pending"){
      setLocked(true,"На модерации");
      input.value=item.text||"";
      counter.textContent=input.value.length;
      setStatus("Предложение отправлено и сейчас ожидает проверки.","pending");
    } else if(item.status==="approved"){
      setLocked(true,"Награда получена");
      input.value=item.text||"";
      counter.textContent=input.value.length;
      setStatus("Предложение одобрено. +300 🐾 начислено на баланс.","ok");
    } else if(item.status==="rejected"){
      setLocked(false,"Отправить новое предложение");
      input.value="";
      counter.textContent="0";
      const note=item.moderator_note ? " Причина: "+item.moderator_note : "";
      setStatus("Прошлое предложение отклонено."+note+" Можно отправить новое.","error");
    }
  }

  input.addEventListener("input",()=>{ counter.textContent=String(input.value.length); });

  async function load(){
    if(!tg?.initData){
      setLocked(true,"Откройте через Telegram");
      setStatus("Эта страница работает только как Mini App в Telegram.","error");
      return;
    }
    try{
      const res=await fetch(API+"/api/suggestions/me",{headers:headers()});
      const data=await readJson(res);
      if(!res.ok) throw new Error(typeof data.detail==="string"?data.detail:(data.detail?.message||"Не удалось загрузить статус."));
      if(data.latest) prettyState(data.latest);
    }catch(e){
      setStatus(e.message||"Ошибка загрузки.","error");
    }
  }

  async function submit(){
    const text=input.value.trim();
    if(text.length<20){ setStatus("Нужно минимум 20 символов.","error"); return; }
    setLocked(true,"Отправляем…");
    setStatus("");
    try{
      const res=await fetch(API+"/api/suggestions",{
        method:"POST",headers:headers(true),body:JSON.stringify({text})
      });
      const data=await readJson(res);
      if(!res.ok) throw new Error(typeof data.detail==="string"?data.detail:(data.detail?.message||"Не удалось отправить."));
      tg?.HapticFeedback?.notificationOccurred?.("success");
      prettyState(data.suggestion);
    }catch(e){
      setLocked(false,"Отправить на модерацию");
      setStatus(e.message||"Ошибка отправки.","error");
      tg?.HapticFeedback?.notificationOccurred?.("error");
    }
  }

  button.addEventListener("click",()=>void submit());
  void load();
})();