(() => {
  'use strict';
  const API = 'https://nyan-wallet-bridge.qwertsyik.workers.dev';
  const IMAGES = './assets/nyan-mafia/';
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) { tg.ready(); tg.expand(); }
  const initData = tg ? tg.initData || '' : '';
  const ownId = Number(tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.id || 0);
  const byId = id => document.getElementById(id);
  const phaseNames = {idle:'ожидание',registration:'набор игроков',night:'ночь',day:'день',vote:'голосование',finished:'игра окончена'};
  const phaseHints = {
    idle:'ведущий ещё не открыл набор.',
    registration:'запишись, чтобы получить секретную роль.',
    night:'город засыпает. специальные роли выбирают свои действия.',
    day:'обсуждай события вместе с другими игроками.',
    vote:'выбери подозреваемого. голосование тайное.',
    finished:'все роли раскрыты. спасибо за игру!'
  };
  const roleNames = {
    civilian:'мирный житель',mafia:'мафия',don:'дон',commissioner:'комиссар',doctor:'доктор',
    maniac:'маньяк',lover:'любовница',bodyguard:'телохранитель',journalist:'журналист',
    immortal:'бессмертный',kamikaze:'камикадзе',lawyer:'адвокат'
  };
  const roleActions = {
    mafia:'выбери ночную цель мафии',don:'выбери ночную цель мафии',maniac:'выбери жертву',
    doctor:'выбери, кого вылечить',commissioner:'выбери, кого проверить',
    bodyguard:'выбери, кого защитить',journalist:'выбери двух игроков',
    lover:'выбери, кого заблокировать',kamikaze:'выбери цель мести',lawyer:'выбери, кого защитить от изгнания'
  };
  let state = null, currentRound = 0, lastPhase = null, busy = false, polling = false;
  let revealed = false, selected = [], hydratedChoice = false, channel = 'public', fetchingChat = false;
  const messages = {public:[],mafia:[]}, cursors = {public:0,mafia:0};

  async function request(path,method='GET',body) {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 14000);
    try {
      const response = await fetch(API+path,{
        method,cache:'no-store',signal:abort.signal,
        headers:{'X-Telegram-Init-Data':initData,...(body?{'Content-Type':'application/json'}:{})},
        body:body?JSON.stringify(body):undefined
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'ошибка '+response.status);
      return data;
    } finally { clearTimeout(timer); }
  }
  function warning(message) {
    byId('error').hidden = !message;
    byId('error').textContent = message || '';
    byId('retry').hidden = !message;
  }
  function show(id,visible) { byId(id).hidden = !visible; }
  function make(tag,cls,txt) {
    const el=document.createElement(tag);
    if(cls)el.className=cls;
    if(txt!==undefined)el.textContent=String(txt);
    return el;
  }
  function openProfile(player) {
    if (!/^[a-zA-Z0-9_]{5,32}$/.test(player.username||'')) return;
    const url='https://t.me/'+player.username;
    if(tg&&tg.openTelegramLink)tg.openTelegramLink(url);
    else window.open(url,'_blank','noopener,noreferrer');
  }
  function avatar(player) {
    const initial=(player.name||'?').slice(0,1).toUpperCase();
    if (!player.photo_url) return make('span','avatar',initial);
    const img=make('img','avatar');
    img.src=player.photo_url;img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';
    img.addEventListener('error',()=>img.replaceWith(make('span','avatar',initial)),{once:true});
    return img;
  }
  function resetRound(id) {
    currentRound=id;lastPhase=null;selected=[];hydratedChoice=false;revealed=false;channel='public';
    for(const name of ['public','mafia']){messages[name]=[];cursors[name]=0;}
  }
  function players() {
    const root=byId('players');root.replaceChildren();
    const list=state.players||[];
    byId('player-total').textContent=list.length+' / 20';
    if(!list.length)root.append(make('div','chat-empty','здесь появятся участники'));
    for(const p of list){
      const link=/^[a-zA-Z0-9_]{5,32}$/.test(p.username||'');
      const item=make(link?'button':'div','player'+(!p.alive?' is-dead':'')+(Number(p.id)===ownId?' self':''));
      if(link){item.type='button';item.addEventListener('click',()=>openProfile(p));}
      item.append(avatar(p));
      const info=make('span','player-name'),title=make('strong','',p.name||'участник');
      const handle=p.username?'@'+p.username:'ID '+p.id;
      const note=make('small','',Number(p.id)===ownId?'ты':handle);
      if(state.mafia_team&&state.mafia_team.includes(p.id)&&Number(p.id)!==ownId) note.textContent+=' · союзник';
      if(!p.alive)note.textContent+=' · выбыл';
      if(state.phase==='finished'&&state.revealed_roles){
        const r=state.revealed_roles[String(p.id)];
        if(roleNames[r]) note.textContent+=' · '+roleNames[r];
      }
      info.append(title,note);item.append(info);root.append(item);
    }
  }
  function roleCard() {
    const hasRole=Boolean(state.joined&&state.my_role);
    show('role-section',hasRole);
    if(!hasRole)return;
    const name=Object.prototype.hasOwnProperty.call(roleNames,state.my_role)?state.my_role:'civilian';
    const image=byId('role-image');
    const source=revealed?name:'card-back';
    image.src=IMAGES+source+'.png';
    image.alt=revealed?'твоя роль: '+(state.my_role_title||roleNames[name]):'закрытая карта роли';
    byId('role-action').textContent=revealed?'скрыть карточку':'нажми, чтобы раскрыть';
    byId('role-reveal').setAttribute('aria-pressed',String(revealed));
    show('role-hint',revealed);
    byId('role-hint').textContent=revealed?(state.my_role_hint||''):'';
  }
  function targetOptions() {
    const allowSelf=state.phase==='night'&&['doctor','lawyer'].includes(state.my_role);
    const team=new Set(state.mafia_team||[]);
    return (state.players||[]).filter(p=>p.alive&&(Number(p.id)!==ownId||allowSelf)&&
      !(state.phase==='night'&&['mafia','don'].includes(state.my_role)&&team.has(p.id)));
  }
  function targets() {
    const active=Boolean(state.joined&&state.alive&&(
      state.phase==='vote'||(state.phase==='night'&&roleActions[state.my_role])));
    show('select-panel',active);
    if(!active)return;
    const max=(state.phase==='night'&&state.my_role==='journalist')?2:1;
    const options=targetOptions(),ids=new Set(options.map(p=>p.id));
    if(!hydratedChoice&&state.my_choice){
      selected=[state.my_choice.target_id,state.my_choice.second_target_id].filter(id=>ids.has(id)).slice(0,max);
    }
    hydratedChoice=true;
    selected=selected.filter(id=>ids.has(id)).slice(0,max);
    byId('select-title').textContent=state.phase==='vote'?'твой голос':'ночное действие';
    byId('select-hint').textContent=state.phase==='vote'?'кого считаешь подозреваемым?':roleActions[state.my_role];
    byId('select-count').textContent=selected.length+' / '+max;
    const list=byId('target-list');list.replaceChildren();
    for(const p of options){
      const button=make('button','target'+(selected.includes(p.id)?' selected':''));button.type='button';
      button.setAttribute('aria-pressed',String(selected.includes(p.id)));
      button.append(avatar(p),make('span','',p.name||'участник'));
      button.addEventListener('click',()=>{
        if(selected.includes(p.id))selected=selected.filter(id=>id!==p.id);
        else if(max===1)selected=[p.id];
        else selected=[...selected,p.id].slice(-max);
        targets();
      });
      list.append(button);
    }
    byId('submit-choice').disabled=selected.length!==max||busy;
    byId('submit-choice').textContent=state.my_choice?'изменить выбор':'подтвердить выбор';
    byId('choice-note').textContent='до конца фазы выбор можно изменить';
  }
  function chatSettings() {
    const active=['night','day','vote','finished'].includes(state.phase);
    const mafia=state.alive&&['mafia','don'].includes(state.my_role);
    show('chat-panel',active);
    show('mafia-tab',mafia&&state.phase!=='finished');
    if(channel==='mafia'&&(!mafia||state.phase==='finished'))channel='public';
    for(const tab of document.querySelectorAll('.chat-tab')){
      const activeTab=tab.dataset.channel===channel;
      tab.classList.toggle('is-active',activeTab);
      tab.setAttribute('aria-selected',String(activeTab));
    }
    byId('chat-privacy').textContent=channel==='mafia'?'ТОЛЬКО МАФИЯ':'ОБЩИЙ';
    byId('message-list').classList.toggle('mafia',channel==='mafia');
    const writable=state.joined&&state.alive&&(
      (channel==='public'&&['day','vote'].includes(state.phase))||
      (channel==='mafia'&&state.phase==='night'&&mafia));
    show('compose',writable);
    show('chat-lock',!writable);
  }
  function renderMessages() {
    const root=byId('message-list');
    const nearBottom=root.scrollHeight-root.scrollTop-root.clientHeight<75;
    root.replaceChildren();
    if(!messages[channel].length){
      root.append(make('div','chat-empty','пока сообщений нет'));
      return;
    }
    for(const m of messages[channel]){
      const item=make('article','msg'+(m.system?' system':'')+(Number(m.sender_id)===ownId?' mine':''));
      if(!m.system){
        const title=make('div','msg-name',m.name||'участник');
        const time=make('span','msg-time',new Date(m.created_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}));
        title.append(time);item.append(title);
      }
      item.append(make('div','msg-body',m.text||''));root.append(item);
    }
    if(nearBottom)root.scrollTop=root.scrollHeight;
  }
  async function loadChat() {
    if(fetchingChat||!state||!['night','day','vote','finished'].includes(state.phase))return;
    if(channel==='mafia'&&!(state.alive&&['don','mafia'].includes(state.my_role)))return;
    fetchingChat=true;const requested=channel,round=currentRound;
    try {
      const data=await request('/api/nyan-mafia/messages?channel='+encodeURIComponent(requested)+'&after='+cursors[requested]);
      if(!state||channel!==requested||currentRound!==round)return;
      const seen=new Set(messages[requested].map(m=>m.id));
      for(const m of data.messages||[]){
        if(!seen.has(m.id))messages[requested].push(m);
        cursors[requested]=Math.max(cursors[requested],m.id);
      }
      messages[requested]=messages[requested].slice(-120);
      renderMessages();
    } catch(_){} finally{fetchingChat=false;}
  }
  function render() {
    if(!state)return;
    const round=Number(state.round_id||0);
    if(round!==currentRound)resetRound(round);
    if(state.phase!==lastPhase){lastPhase=state.phase;selected=[];hydratedChoice=false;}
    const count=(state.players||[]).length;
    const phase=state.phase||'idle';
    byId('top-state').textContent=phaseNames[phase]||'игра';
    byId('round-mark').textContent=round?'РАУНД #'+round:'РАУНД —';
    byId('phase-mark').textContent=(phaseNames[phase]||'игра').toUpperCase();
    byId('phase-name').textContent=phaseNames[phase]||'игра';
    byId('phase-description').textContent=phaseHints[phase]||'';
    show('clock',Boolean(state.ends_at));
    show('join-controls',phase==='registration');
    show('join',!state.joined);
    show('leave',Boolean(state.joined));
    show('registration-progress',phase==='registration');
    if(phase==='registration'){
      const min=Number(state.min_players||4);
      byId('registration-count').textContent=count+' / '+min;
      byId('registration-caption').textContent=count>=min?'можно начинать!':'собираем игроков';
      byId('registration-hint').textContent=count>=min?'достаточно игроков для старта':'нужно ещё '+(min-count)+' участников';
      byId('registration-fill').style.width=Math.min(100,Math.round(count/min*100))+'%';
      byId('registration-track').setAttribute('aria-valuenow',String(Math.min(min,count)));
      byId('registration-track').setAttribute('aria-valuemax',String(min));
    }
    show('room',Boolean(round));
    show('event-strip',Boolean(state.last_event)&&phase!=='registration');
    byId('event-text').textContent=state.last_event||'';
    const hasPrivate=Boolean(state.joined&&state.night_result&&['day','vote'].includes(phase));
    show('private-result',hasPrivate);
    byId('private-result-text').textContent=hasPrivate?state.night_result:'';
    const inGame=['night','day','vote'].includes(phase);
    show('game-panel',inGame);
    if(inGame){
      byId('stage').className='illustrated-stage '+(state.joined&&!state.alive?'spectator':phase);
      byId('stage-label').textContent=state.joined&&!state.alive?'НАБЛЮДАТЕЛЬ':(phaseNames[phase]||'NYAN MAFIA').toUpperCase();
    }
    players();roleCard();targets();chatSettings();renderMessages();
    show('result-panel',phase==='finished');
    if(phase==='finished'){
      byId('result-image').className='result-image '+(state.winner||'draw');
      const labels={civilians:'победа мирных',mafia:'победа мафии',maniac:'победа маньяка',draw:'ничья'};
      byId('result-title').textContent=labels[state.winner]||'игра завершена';
      byId('result-description').textContent='роли всех игроков раскрыты в списке участников.';
    }
    show('host-panel',Boolean(state.is_owner));
    // Registration is opened exclusively by the Telegram owner's /mafia command.
    show('host-open',false);
    show('host-start',Boolean(state.is_owner&&phase==='registration'));
    byId('host-start').disabled=count<4||busy;
    show('host-next',Boolean(state.is_owner&&inGame));
    show('host-finish',Boolean(state.is_owner&&['registration','night','day','vote'].includes(phase)));
    byId('host-info').textContent=phase==='registration'
      ?'записано '+count+' игроков. нужно от 4 до 20.'
      :'новый набор открывается командой /mafia в личном чате бота.';
    updateClock();
  }
  function updateClock(){
    if(!state||!state.ends_at)return;
    const seconds=Math.max(0,Math.ceil((new Date(state.ends_at).getTime()-Date.now())/1000));
    byId('clock').textContent=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');
  }
  async function refresh(){
    if(!initData||polling||busy)return;
    polling=true;
    try{state=await request('/api/nyan-mafia/status');warning('');render();void loadChat();}
    catch(error){warning(error.name==='AbortError'?'сервер долго не отвечает':error.message||'сбой соединения');}
    finally{polling=false;}
  }
  async function act(path,body,confirmText){
    if(busy||(confirmText&&!window.confirm(confirmText)))return;
    busy=true;
    try{
      await request(path,'POST',body);
      warning('');state=await request('/api/nyan-mafia/status');
      render();void loadChat();
      if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred('success');
    }catch(error){
      warning(error.name==='AbortError'?'сервер долго не отвечает':error.message||'ошибка');
      if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred('error');
    }finally{busy=false;if(state)render();}
  }
  byId('join').addEventListener('click',()=>void act('/api/nyan-mafia/join'));
  byId('leave').addEventListener('click',()=>void act('/api/nyan-mafia/leave',undefined,'отменить запись?'));
  byId('retry').addEventListener('click',()=>void refresh());
  byId('host-start').addEventListener('click',()=>void act('/api/owner/nyan-mafia/start',undefined,'начать игру и раздать роли?'));
  byId('host-next').addEventListener('click',()=>void act('/api/owner/nyan-mafia/advance',undefined,'завершить эту фазу?'));
  byId('host-finish').addEventListener('click',()=>void act('/api/owner/nyan-mafia/finish',undefined,'завершить игру?'));
  byId('role-reveal').addEventListener('click',()=>{revealed=!revealed;roleCard();});
  byId('submit-choice').addEventListener('click',()=>{
    const max=state.phase==='night'&&state.my_role==='journalist'?2:1;
    if(selected.length!==max)return;
    void act('/api/nyan-mafia/action',{target_id:selected[0],second_target_id:selected[1]||null});
  });
  for(const tab of document.querySelectorAll('.chat-tab')){
    tab.addEventListener('click',()=>{channel=tab.dataset.channel;chatSettings();renderMessages();void loadChat();});
  }
  byId('compose').addEventListener('submit',async event=>{
    event.preventDefault();
    const input=byId('message-text'),value=input.value.trim();
    if(!value||busy)return;
    busy=true;byId('send').disabled=true;
    try{
      await request('/api/nyan-mafia/messages','POST',{text:value,channel});
      input.value='';await loadChat();
    }catch(error){warning(error.message||'не удалось отправить');}
    finally{busy=false;byId('send').disabled=false;}
  });
  if(!initData){
    byId('phase-name').textContent='нужен Telegram';
    byId('phase-description').textContent='открой игру по кнопке в Nyan Games';
    byId('top-state').textContent='ВНЕ ИГРЫ';byId('phase-mark').textContent='ВХОД';
    show('telegram-link',true);
  }else{
    void refresh();
    setInterval(()=>{if(!document.hidden)void refresh();},3300);
    setInterval(()=>{if(!document.hidden)void loadChat();},2100);
    setInterval(updateClock,500);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)void refresh();});
  }
})();