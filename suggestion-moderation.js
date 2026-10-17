(() => {
  "use strict";
  const tg=window.Telegram?.WebApp;
  const API="https://nyan-wallet.tail327bb6.ts.net";
  const list=document.getElementById("list");
  const statusEl=document.getElementById("status");
  const refresh=document.getElementById("refresh");
  const tabs=[...document.querySelectorAll(".tab")];
  let current="pending";

  tg?.ready?.();
  tg?.expand?.();

  function headers(json=false){
    const h={"X-Telegram-Init-Data":tg?.initData||""};
    if(json) h["Content-Type"]="application/json";
    return h;
  }
  async function readJson(res){try{return await res.json()}catch{return {}}}
  function labelUser(x){
    if(x.username) return "@"+x.username;
    const name=[x.first_name,x.last_name].filter(Boolean).join(" ").trim();
    return name||("ID "+x.telegram_id);
  }
  function fmt(d){
    if(!d) return "";
    try{return new Date(d).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}catch{return d}
  }
  function setStatus(t){statusEl.textContent=t||""}
  function escapeHtml(v){
    return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }
  function card(x){
    const el=document.createElement("article");
    el.className="card";
    const reviewed=x.status!=="pending";
    el.innerHTML=
      '<div class="meta">'+
        '<span class="user">'+escapeHtml(labelUser(x))+'</span>'+
        '<span>ID '+escapeHtml(x.telegram_id)+'</span>'+
        '<span class="badge">#'+escapeHtml(x.id)+'</span>'+
        '<span>'+escapeHtml(fmt(x.created_at))+'</span>'+
      '</div>'+
      '<div class="text">'+escapeHtml(x.text)+'</div>'+
      (x.moderator_note?'<div class="note">Комментарий: '+escapeHtml(x.moderator_note)+'</div>':'')+
      (reviewed
        ? '<div class="reviewed '+escapeHtml(x.status)+'">'+(x.status==="approved"?"Одобрено · +300 🐾":"Отклонено")+'</div>'
        : '<div class="actions"><button class="action approve">Одобрить +300 🐾</button><button class="action reject">Отказать</button></div>'
      );
    if(!reviewed){
      el.querySelector(".approve").addEventListener("click",()=>void review(x.id,"approve"));
      el.querySelector(".reject").addEventListener("click",()=>void review(x.id,"reject"));
    }
    return el;
  }

  async function load(){
    if(!tg?.initData){
      setStatus("Открой страницу как Mini App в Telegram.");
      list.innerHTML="";
      return;
    }
    setStatus("Загрузка…");
    try{
      const res=await fetch(API+"/api/owner/suggestions?status="+encodeURIComponent(current),{headers:headers()});
      const data=await readJson(res);
      if(!res.ok) throw new Error(typeof data.detail==="string"?data.detail:(data.detail?.message||"Ошибка загрузки"));
      list.innerHTML="";
      const items=data.suggestions||[];
      if(!items.length) list.innerHTML='<div class="empty">Здесь пока пусто</div>';
      else items.forEach(x=>list.appendChild(card(x)));
      setStatus(items.length?"Заявок: "+items.length:"");
    }catch(e){
      list.innerHTML="";
      setStatus(e.message||"Ошибка загрузки");
    }
  }

  async function review(id,decision){
    let note="";
    if(decision==="reject"){
      note=prompt("Причина отказа — необязательно:","")||"";
    }
    setStatus("Сохраняем решение…");
    try{
      const res=await fetch(API+"/api/owner/suggestions/"+id+"/review",{
        method:"POST",
        headers:headers(true),
        body:JSON.stringify({decision,note:note||null})
      });
      const data=await readJson(res);
      if(!res.ok) throw new Error(typeof data.detail==="string"?data.detail:(data.detail?.message||"Не удалось обработать заявку"));
      tg?.HapticFeedback?.notificationOccurred?.("success");
      await load();
    }catch(e){
      setStatus(e.message||"Ошибка");
      tg?.HapticFeedback?.notificationOccurred?.("error");
    }
  }

  tabs.forEach(btn=>btn.addEventListener("click",()=>{
    current=btn.dataset.status||"pending";
    tabs.forEach(x=>x.classList.toggle("active",x===btn));
    void load();
  }));
  refresh.addEventListener("click",()=>void load());
  void load();
})();