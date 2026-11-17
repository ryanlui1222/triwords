'use strict';
// Vanilla JavaScript: no npm, no framework, no AI secrets in the browser.
const state={tab:'today', lang:'all', date:'', selected:0, revealed:false, words:[], stats:null, q:'', bookmarked:false, page:0, speed: Number(localStorage.getItem('speechSpeed')||'0.88')};
const $=(id)=>document.getElementById(id);
const escapeHTML=(v)=>String(v??'').replace(/[&<>"']/g, x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const langs={en:'English',ja:'日本語',es:'Español'};
const voiceLangs={en:'en-US',ja:'ja-JP',es:'es-ES'};
let toastTimer;
function notice(msg){const n=$('notice');n.textContent=msg;n.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>n.hidden=true,6800)}
async function api(url, options={}){
  let response;
  try{response=await fetch(url,{...options,credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})}})}
  catch{throw new Error('無法連線。請檢查網絡或稍後重試。')}
  let body={};try{body=await response.json()}catch{}
  if(response.status===401){showLogin();throw new Error(body.detail||'登入已過期，請重新登入。')}
  if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:`伺服器錯誤：${response.status}`);
  return body;
}
function showLogin(){ $('shell').hidden=true;$('login').hidden=false;$('password').value=''; }
function showApp(){ $('login').hidden=true;$('shell').hidden=false; }
async function init(){
  try{const me=await api('/api/me');state.date=me.today;$('date-label').textContent=me.today;showApp();await reload()}
  catch(e){showLogin();if(!String(e.message).includes('請先登入'))notice(e.message)}
}
$('login-form').addEventListener('submit',async e=>{
  e.preventDefault();const btn=e.target.querySelector('button');btn.disabled=true;
  try{await api('/api/login',{method:'POST',body:JSON.stringify({password:$('password').value})});await init()}
  catch(err){alert(err.message)}finally{btn.disabled=false}
});

function buttons(){return `<div class="lang-tabs">${[['all','全部'],['en','英語'],['ja','日語'],['es','西班牙語']].map(([id,label])=>`<button class="chip ${state.lang===id?'selected':''}" type="button" data-lang="${id}">${label}</button>`).join('')}</div>`}
function header(title, description, right=''){
 return `<div class="page-heading"><div><h1>${escapeHTML(title)}</h1><div class="muted small">${escapeHTML(description)}</div></div>${right}</div>`;
}
function statsHtml(){const a=state.stats||{new_words:0,due_reviews:0,studied_today:0};return `<div class="stats"><div class="stat"><strong>${a.new_words}</strong><span>當日新詞</span></div><div class="stat"><strong>${a.studied_today}</strong><span>當日已練習</span></div><div class="stat"><strong>${a.due_reviews}</strong><span>待複習</span></div></div>`}
function ratingHTML(){return `<div class="rating-title">這個詞，你記得多少？</div><div class="rating-buttons"><button class="rating again" data-rating="again">忘記</button><button class="rating hard" data-rating="hard">困難</button><button class="rating good" data-rating="good">記得</button><button class="rating easy" data-rating="easy">容易</button></div>`}
function cardHTML(w){
 const language=langs[w.language]||w.language;
 return `<section class="card flashcard"><div class="card-head"><span class="tag">${escapeHTML(language)} · ${escapeHTML(w.level)}</span><div class="row-actions"><button class="icon-btn ${w.bookmarked?'is-saved':''}" data-bookmark="${escapeHTML(w.id)}" data-enabled="${w.bookmarked?'false':'true'}" title="收藏">${w.bookmarked?'★':'☆'}</button><span class="tag light">${w.practiced?'已練習':'新詞'}</span></div></div>
 <h2 class="term">${escapeHTML(w.term)}</h2><div class="reading">${escapeHTML(w.reading)}</div>
 <div class="pronounce-row"><button class="secondary" data-speak="term">▶ 朗讀單字</button>${state.revealed?'<button class="secondary" data-speak="example">▶ 朗讀例句</button>':''}</div>
 ${state.revealed?`<div class="answer"><strong>${escapeHTML(w.meaning_zh)}</strong><p class="muted small">${escapeHTML(w.part_of_speech)}</p><p class="example">${escapeHTML(w.example)}</p><p class="translation">${escapeHTML(w.example_zh)}</p></div>`:'<div class="hint">先回想詞義，再揭示答案</div>'}
 <div class="spacer"></div><button class="outline wide" data-reveal="1">${state.revealed?'隱藏答案':'顯示答案與例句'}</button>
 ${state.revealed?ratingHTML():''}</section>`;
}
function render(){
  document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n.dataset.tab===state.tab));
  const root=$('main-view');
  if(state.tab==='today'){
    const dayBox=`<input class="date-input" aria-label="詞包日期" type="date" value="${escapeHTML(state.date)}" id="lesson-date"/>`;
    root.innerHTML=header('每日新詞','英、日、西各10詞 · 點擊卡片開始學習', dayBox)+statsHtml()+buttons()+renderCardArea();
  }else if(state.tab==='review'){
    root.innerHTML=header('間隔複習','根據每次評分，自動安排下次重溫')+statsHtml()+buttons()+renderCardArea();
  }else if(state.tab==='library'){
    root.innerHTML=header('我的詞庫','搜尋、收藏並隨時重讀已學單字')+buttons()+`<div class="search-row"><input id="search" class="search-input" aria-label="搜尋詞彙" placeholder="搜尋單字或中文釋義..." value="${escapeHTML(state.q)}"/><button class="outline" data-search="1">搜尋</button></div><label class="check-row"><input id="star-only" type="checkbox" ${state.bookmarked?'checked':''}/> 只顯示收藏詞彙</label>`+renderLibrary();
  }else{
    root.innerHTML=header('設定','個人化學習與使用說明')+`<section class="setting-card"><h3>每日詞彙</h3><p>英語10詞（C1–C2）、日語10詞（N2–N1）、西班牙語10詞（A2–B1）。每次打開網頁時讀取已生成的詞包；不會推送通知。</p><p>每日產詞時間及模型可在 GitHub Actions 和環境變數中調整。</p></section><section class="setting-card"><h3>朗讀速度</h3><label for="speech-rate">語速：<span id="speed-label">${state.speed.toFixed(2)}×</span></label><input type="range" id="speech-rate" min="0.65" max="1.2" step="0.05" value="${state.speed}"/><p>朗讀採用手機或瀏覽器可使用的系統聲音。初次使用日語或西班牙語時，請確認裝置安裝了該語言的語音資源。</p></section><section class="setting-card"><h3>加入 Android 主畫面</h3><p>使用 Chrome 開啟部署後的網址，透過選單選擇「安裝應用程式」或「加入主畫面」（實際名稱視手機和瀏覽器而定）。此版本需要網絡讀取及保存學習資料。</p></section><section class="setting-card"><h3>帳號安全</h3><p>單人密碼登入；Turso 與 Gemini 金鑰只在伺服器及 GitHub Secrets 保存，不會傳至瀏覽器。</p><button class="outline" data-logout="1">登出</button></section>`;
  }
}
function renderCardArea(){
 if(!state.words.length){return `<div class="empty">${state.tab==='review'?'目前沒有到期的單字。完成今日新詞後，日後會自動排入複習。':'這個日期目前沒有詞包。請先執行示範資料或到 GitHub Actions 手動執行每日生成。'}</div>`}
 state.selected=Math.max(0,Math.min(state.selected,state.words.length-1));
 const w=state.words[state.selected];
 return `<div class="toolbar"><span class="small">${state.tab==='review'?'到期詞彙':'詞彙'} ${state.selected+1} / ${state.words.length}</span><span class="small">${escapeHTML(langs[w.language])}</span></div>`+cardHTML(w)+`<div class="card-nav"><button class="secondary" data-move="-1" ${state.selected<=0?'disabled':''}>← 上一張</button><button class="secondary" data-move="1" ${state.selected>=state.words.length-1?'disabled':''}>下一張 →</button></div>`;
}
function renderLibrary(){
 if(!state.words.length)return '<div class="empty">找不到符合條件的單字。<p class="small">你可以切換語言或取消收藏篩選。</p></div>';
 return `<div class="toolbar"><span class="small">第 ${state.page+1} 頁 · 每頁最多100詞</span></div>`+state.words.map(w=>`<article class="list-card"><div class="line-between"><div><span class="tag light">${escapeHTML(langs[w.language])}</span> <span class="list-word">${escapeHTML(w.term)}</span></div><div class="row-actions"><button class="icon-btn" data-library-speak="${escapeHTML(w.id)}" title="朗讀">▶</button><button class="icon-btn ${w.bookmarked?'is-saved':''}" data-bookmark="${escapeHTML(w.id)}" data-enabled="${w.bookmarked?'false':'true'}" title="收藏">${w.bookmarked?'★':'☆'}</button></div></div><div class="list-meaning">${escapeHTML(w.meaning_zh)}</div><details><summary>例句和讀音</summary><div class="details-body">${escapeHTML(w.reading)}<p>${escapeHTML(w.example)}</p><p class="muted">${escapeHTML(w.example_zh)}</p></div></details></article>`).join('')+`<div class="card-nav"><button class="secondary" data-page="-1" ${state.page===0?'disabled':''}>上一頁</button><button class="secondary" data-page="1" ${state.words.length<100?'disabled':''}>下一頁</button></div>`;
}
async function reload(){
  try{
    if(state.tab==='today'){
      const [d,lesson]=await Promise.all([api('/api/dashboard'),api(`/api/lesson?date=${encodeURIComponent(state.date)}${state.lang==='all'?'':`&lang=${state.lang}`}`)]);
      state.stats=d;state.words=lesson.words;
    }else if(state.tab==='review'){
      const [d,review]=await Promise.all([api('/api/dashboard'),api(`/api/reviews${state.lang==='all'?'':`?lang=${state.lang}`}`)]);
      state.stats=d;state.words=review.words;
    }else if(state.tab==='library'){
      const query=new URLSearchParams({q:state.q,bookmarked:String(state.bookmarked),offset:String(state.page*100),limit:'100'});
      if(state.lang!=='all')query.set('lang',state.lang);
      state.words=(await api('/api/library?'+query.toString())).words;
    }
    render();
  }catch(e){notice(e.message);render()}
}
function speak(text,lang){
  if(!('speechSynthesis' in window)){notice('這個瀏覽器不支援語音合成');return}
  window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang=voiceLangs[lang]||'en-US';u.rate=state.speed;
  const voices=window.speechSynthesis.getVoices();const v=voices.find(v=>v.lang.toLowerCase()===u.lang.toLowerCase())||voices.find(v=>v.lang.toLowerCase().startsWith(lang));if(v)u.voice=v;
  window.speechSynthesis.speak(u);
}
$('shell').addEventListener('click',async e=>{
 const target=e.target.closest('button');if(!target)return;
 try{
  if(target.dataset.tab){state.tab=target.dataset.tab;state.selected=0;state.revealed=false;state.lang='all';state.page=0;await reload();return}
  if(target.dataset.lang){state.lang=target.dataset.lang;state.selected=0;state.revealed=false;state.page=0;await reload();return}
  if(target.dataset.move){state.selected+=Number(target.dataset.move);state.revealed=false;render();return}
  if(target.dataset.reveal){state.revealed=!state.revealed;render();return}
  if(target.dataset.rating){
    const word=state.words[state.selected];if(!word)return;target.disabled=true;
    await api('/api/review',{method:'POST',body:JSON.stringify({word_id:word.id,rating:target.dataset.rating,request_id:crypto.randomUUID()})});
    if(state.tab==='review'){state.words.splice(state.selected,1);state.selected=Math.min(state.selected,state.words.length-1)}
    else{word.practiced=1;state.selected=Math.min(state.selected+1,state.words.length-1)}
    state.revealed=false;state.stats=await api('/api/dashboard');render();return;
  }
  if(target.dataset.bookmark){
    const enabled=target.dataset.enabled==='true';await api('/api/bookmark/'+encodeURIComponent(target.dataset.bookmark),{method:'POST',body:JSON.stringify({enabled})});
    const word=state.words.find(w=>w.id===target.dataset.bookmark);if(word)word.bookmarked=enabled?1:0;
    if(state.tab==='library'&&state.bookmarked){await reload()}else render();return;
  }
  if(target.dataset.speak){const w=state.words[state.selected];if(w)speak(target.dataset.speak==='term'?w.term:w.example,w.language);return}
  if(target.dataset.librarySpeak){const w=state.words.find(w=>w.id===target.dataset.librarySpeak);if(w)speak(w.term,w.language);return}
  if(target.dataset.search){state.q=$('search').value.trim();state.page=0;await reload();return}
  if(target.dataset.page){state.page=Math.max(0,state.page+Number(target.dataset.page));await reload();return}
  if(target.dataset.logout){await api('/api/logout',{method:'POST',body:'{}'});showLogin();return}
 }catch(err){notice(err.message)}
});
$('shell').addEventListener('change',async e=>{
 try{
  if(e.target.id==='lesson-date'){state.date=e.target.value;state.selected=0;state.revealed=false;await reload()}
  if(e.target.id==='star-only'){state.bookmarked=e.target.checked;state.page=0;await reload()}
 }catch(err){notice(err.message)}
});
$('shell').addEventListener('input',e=>{
 if(e.target.id==='speech-rate') {state.speed=Number(e.target.value);localStorage.setItem('speechSpeed',String(state.speed));$('speed-label').textContent=state.speed.toFixed(2)+'×'}
});
$('shell').addEventListener('keydown',async e=>{
 if(e.target.id==='search' && e.key==='Enter'){state.q=e.target.value.trim();state.page=0;await reload()}
});
init();
