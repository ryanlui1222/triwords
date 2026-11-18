'use strict';
// TriWords v0.2: no AI keys in the browser. All writes require a signed login cookie.
const state={tab:'today',lang:'all',date:'',selected:0,revealed:false,words:[],stats:null,q:'',bookmarked:false,page:0,libraryStatus:'active',speed:Number(localStorage.getItem('speechSpeed')||'0.88'),editId:null};
// In-memory GET cache: avoid repeated network trips when switching tabs.
const pageCache=new Map();
let dashboardCache=null;
let dashboardInflight=null;
let reloadSequence=0;
let cacheEpoch=0;
const CACHE_MS=30000;
function invalidateReadCache(){cacheEpoch++;pageCache.clear();dashboardCache=null;dashboardInflight=null;}
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
const langNames={en:'English',ja:'日本語',es:'Español'};
const speechCodes={en:'en-US',ja:'ja-JP',es:'es-ES'};
let noticeTimeout;
function toast(message){const n=$('notice');n.textContent=message;n.hidden=false;clearTimeout(noticeTimeout);noticeTimeout=setTimeout(()=>n.hidden=true,8000)}
async function api(url,options={}){
 let response;try{response=await fetch(url,{...options,credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})}})}
 catch{throw new Error('無法連接伺服器，請檢查網絡。')}
 let body={};try{body=await response.json()}catch{}
 if(response.status===401){showLogin();throw new Error(body.detail||'登入已過期')}
 if(!response.ok){const detail=body.detail;throw new Error(typeof detail==='string'?detail:(detail?.message||`伺服器錯誤 ${response.status}`))}
 // After adding, editing, reviewing, bookmarking or generating vocabulary,
 // do not keep showing any previously cached pages or counters.
 if(options.method && options.method.toUpperCase()!=='GET')invalidateReadCache();
 return body;
}
function showLogin(){$('shell').hidden=true;$('login').hidden=false;$('password').value=''}
function showApp(){$('login').hidden=true;$('shell').hidden=false}
async function init(){try{const me=await api('/api/me');state.date=me.today;$('date-label').textContent=me.today;showApp();await reload()}catch(err){showLogin();if(!String(err.message).includes('請先登入'))toast(err.message)}}
$('login-form').addEventListener('submit',async e=>{e.preventDefault();const btn=e.target.querySelector('button');btn.disabled=true;try{await api('/api/login',{method:'POST',body:JSON.stringify({password:$('password').value})});await init()}catch(err){alert(err.message)}finally{btn.disabled=false}});
function filters(){return `<div class="lang-tabs">${[['all','全部'],['en','英語'],['ja','日語'],['es','西班牙語']].map(([key,label])=>`<button type="button" class="chip ${state.lang===key?'selected':''}" data-lang="${key}">${label}</button>`).join('')}</div>`}
function heading(title,sub,right=''){return `<div class="page-heading"><div><h1>${esc(title)}</h1><p class="small muted">${esc(sub)}</p></div>${right}</div>`}
function summary(){const s=state.stats||{new_words:0,due_reviews:0,pending:0};return `<div class="stats"><div class="stat"><strong>${s.new_words}</strong><span>今日新詞</span></div><div class="stat"><strong>${s.due_reviews}</strong><span>待複習</span></div><div class="stat"><strong>${s.pending}</strong><span>待 AI 補全</span></div></div>`}
function score(w){if(w.status==='pending')return '<p class="small muted">待補全，尚未進入複習</p>';if(w.status==='known')return '<p class="mastery-label">✓ 已認識 · 不再排程複習</p>';return `<div class="mastery-line"><span>熟習指數</span><strong>${Number(w.mastery_percent||0)}%</strong></div><div class="mastery-track"><div class="mastery-fill" style="width:${Math.min(100,Math.max(0,Number(w.mastery_percent||0)))}%"></div></div>${w.due_date?`<p class="small muted">下次複習：${esc(w.due_date)}</p>`:''}`}
function card(w){return `<section class="card flashcard"><div class="card-head"><span class="tag">${esc(langNames[w.language])} · ${esc(w.level)}</span><div class="row-actions"><button class="icon-btn ${w.bookmarked?'is-saved':''}" title="收藏" data-bookmark="${esc(w.id)}" data-enabled="${w.bookmarked?'false':'true'}">${w.bookmarked?'★':'☆'}</button><button class="secondary" data-edit="${esc(w.id)}">編輯</button><button class="secondary" data-known="${esc(w.id)}">已認識</button></div></div><h2 class="term">${esc(w.term)}</h2><div class="reading">${esc(w.reading)}</div><div class="pronounce-row"><button class="secondary" data-speak="term">▶ 單字發音</button>${state.revealed?'<button class="secondary" data-speak="example">▶ 朗讀例句</button>':''}</div>${state.revealed?`<div class="answer"><strong>${esc(w.meaning_zh)}</strong><p class="small muted">${esc(w.part_of_speech)}</p><p class="example">${esc(w.example)}</p><p class="translation">${esc(w.example_zh)}</p></div>`:'<div class="hint">先回想意思，再顯示答案</div>'}<div class="spacer"></div>${score(w)}<button class="outline wide" data-reveal="1">${state.revealed?'隱藏答案':'顯示答案與例句'}</button>${state.revealed?`<p class="rating-title">這個詞，你記得多少？</p><div class="rating-buttons"><button class="rating again" data-rating="again">忘記</button><button class="rating hard" data-rating="hard">困難</button><button class="rating good" data-rating="good">記得</button><button class="rating easy" data-rating="easy">容易</button></div>`:''}</section>`}
function cardArea(){if(!state.words.length)return `<div class="empty">${state.tab==='review'?'目前沒有到期的單字。':'這一天尚無可學習的新詞。可以到 GitHub Actions 生成每日詞包。'}</div>`;state.selected=Math.max(0,Math.min(state.selected,state.words.length-1));const w=state.words[state.selected];return `<div class="toolbar"><span class="small">第 ${state.selected+1} / ${state.words.length} 詞</span><span class="small">${esc(langNames[w.language])}</span></div>${card(w)}<div class="card-nav"><button class="secondary" data-move="-1" ${state.selected===0?'disabled':''}>← 上一詞</button><button class="secondary" data-move="1" ${state.selected>=state.words.length-1?'disabled':''}>下一詞 →</button></div>`}
function libraryItems(){if(!state.words.length)return '<div class="empty">這個條件下沒有單字。</div>';return state.words.map(w=>`<article class="list-card"><div class="line-between"><div><span class="tag light">${esc(langNames[w.language])}</span> <strong class="list-word">${esc(w.term)}</strong></div><div class="row-actions"><button class="icon-btn" data-library-speak="${esc(w.id)}">▶</button><button class="icon-btn" data-bookmark="${esc(w.id)}" data-enabled="${w.bookmarked?'false':'true'}">${w.bookmarked?'★':'☆'}</button><button class="secondary" data-edit="${esc(w.id)}">編輯</button>${w.status==='active'?`<button class="secondary" data-known="${esc(w.id)}">已認識</button>`:''}</div></div><p class="list-meaning">${esc(w.meaning_zh||'尚未填寫')}</p>${score(w)}<details><summary>讀音及雙語例句</summary><div class="details-body">${esc(w.reading)}<p>${esc(w.example)}</p><p class="muted">${esc(w.example_zh)}</p></div></details></article>`).join('')+`<div class="card-nav"><button class="secondary" data-page="-1" ${state.page===0?'disabled':''}>上一頁</button><button class="secondary" data-page="1" ${state.words.length<100?'disabled':''}>下一頁</button></div>`}
function customPage(){return heading('我的生字','手動保存單字，或存入待補全清單並按鈕生成')+summary()+`<section class="setting-card"><h3>新增生字</h3><form id="custom-form" class="vocab-form"><label>語言<select name="language" class="select-input"><option value="en">英語</option><option value="ja">日語</option><option value="es">西班牙語</option></select></label><label>單字／詞組 <input name="term" required maxlength="120" class="search-input" placeholder="輸入遇上的生字"/></label><label>原句或語境（選填）<textarea name="context_sentence" rows="2" maxlength="1200" placeholder="貼上原句，可讓 AI 更準確理解詞義"></textarea></label><label>錄入方式<select name="mode" id="custom-mode" class="select-input"><option value="ai">AI 補全：先存入我的生字</option><option value="manual">自行填寫：直接加入複習</option></select></label><div id="manual-fields" hidden><label>繁體中文詞義（必填）<textarea name="meaning_zh" rows="2" maxlength="1000"></textarea></label><label>讀音 <input name="reading" maxlength="1000" class="search-input"/></label><label>詞性 <input name="part_of_speech" maxlength="1000" class="search-input"/></label><label>外語例句 <textarea name="example" rows="2" maxlength="1000"></textarea></label><label>例句中譯 <textarea name="example_zh" rows="2" maxlength="1000"></textarea></label><label>程度 <input name="level" maxlength="1000" class="search-input"/></label><label>主題 <input name="topic" maxlength="1000" class="search-input"/></label></div><button class="primary wide" type="submit">儲存生字</button></form></section><section class="setting-card"><div class="line-between"><div><h3>等待 AI 補全</h3><p class="small muted">每次只取清單最前面的5個生字；不會自動執行。</p></div><span class="tag">${state.words.length}詞（最多顯示150）</span></div><button class="primary wide" data-generate="1" ${!state.words.length?'disabled':''}>用 Gemini 補全前 ${Math.min(5,state.words.length)} 詞</button><p class="small muted">一次提交最多5詞，可能同時包含三種語言；生成成功後自動加入複習。請檢查 AI 回傳內容。</p>${state.words.length?state.words.map((w,i)=>`<article class="pending-item"><div><span class="small muted">${i<5?'本批':'候補'} · ${esc(langNames[w.language])}</span><strong>${esc(w.term)}</strong>${w.context_sentence?`<div class="small muted">${esc(w.context_sentence)}</div>`:''}</div><button class="secondary" data-edit="${esc(w.id)}">編輯</button></article>`).join(''):'<div class="empty">暫時沒有等待補全的生字。</div>'}</section>`}
function settingsPage(){return heading('設定','語音及學習方式')+`<section class="setting-card"><h3>朗讀速度</h3><label for="speech-rate">${state.speed.toFixed(2)}× <span id="speed-label"></span></label><input type="range" id="speech-rate" min="0.65" max="1.2" step="0.05" value="${state.speed}"/><p>使用裝置的系統語音朗讀單字和例句。</p></section><section class="setting-card"><h3>熟習指數說明</h3><p>0–99% 是根據連續成功次數、複習間隔、難易系數和逾期天數估算的啟發式指標，不等於科學校準的記憶概率。標記「已認識」會顯示100%，但只代表你的自行判斷。</p></section><section class="setting-card"><h3>永久防重複</h3><p>詞庫和「已認識」單字會一直保留；單字經過編輯後，舊寫法亦保留在歷史排除清單中，不會被每日產詞重新加入。</p></section><section class="setting-card"><h3>登入安全</h3><p>AI 金鑰只放在 Vercel 和 GitHub 的環境變數；不會送至瀏覽器。</p><button class="outline" data-logout="1">登出</button></section>`}
function render(){document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n.dataset.tab===state.tab));const root=$('main-view');if(state.tab==='today')root.innerHTML=heading('今日新詞','每日英、日、西各10詞',`<input type="date" class="date-input" id="lesson-date" value="${esc(state.date)}"/>`)+summary()+filters()+cardArea();else if(state.tab==='review')root.innerHTML=heading('間隔複習','到期詞彙及新加入的自訂詞')+summary()+filters()+cardArea();else if(state.tab==='library')root.innerHTML=heading('詞庫','可搜尋正常學習、已認識及待補全的詞彙')+filters()+`<div class="search-row"><input id="search" class="search-input" value="${esc(state.q)}" placeholder="搜尋詞義或單字"/><button class="outline" data-search="1">搜尋</button></div><div class="search-row"><select id="library-status" class="select-input"><option value="active" ${state.libraryStatus==='active'?'selected':''}>學習中</option><option value="known" ${state.libraryStatus==='known'?'selected':''}>已認識</option><option value="pending" ${state.libraryStatus==='pending'?'selected':''}>待補全</option><option value="all" ${state.libraryStatus==='all'?'selected':''}>全部詞彙</option></select><label class="check-row"><input id="star-only" type="checkbox" ${state.bookmarked?'checked':''}/>僅收藏</label></div>`+libraryItems();else if(state.tab==='custom')root.innerHTML=customPage();else root.innerHTML=settingsPage()}
function pageCacheKey(){return JSON.stringify([state.tab,state.lang,state.date,state.q,state.bookmarked,state.page,state.libraryStatus]);}
function showLoading(){
 document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n.dataset.tab===state.tab));
 $('main-view').innerHTML='<div class="empty" role="status" aria-live="polite">正在載入詞彙…</div>';
}
async function getDashboard(){
 if(dashboardCache && Date.now()-dashboardCache.saved<CACHE_MS)return dashboardCache.data;
 if(dashboardInflight)return dashboardInflight;
 const epoch=cacheEpoch;
 const request=api('/api/dashboard').then(data=>{
   if(epoch===cacheEpoch)dashboardCache={data,saved:Date.now()};
   return data;
 }).finally(()=>{if(dashboardInflight===request)dashboardInflight=null});
 dashboardInflight=request;
 return request;
}
async function reload(){
 const ticket=++reloadSequence;
 const tab=state.tab,lang=state.lang,date=state.date;
 const key=pageCacheKey();
 if(tab==='settings'){state.words=[];render();return;}
 const cached=pageCache.get(key);
 if(cached && Date.now()-cached.saved<CACHE_MS){state.words=cached.words;state.stats=cached.stats;render();return;}
 // Immediately acknowledge tab/filter changes, rather than leaving an old tab
 // visible until both Vercel requests and all database queries finish.
 showLoading();
 try{
   let words=[],stats=state.stats;
   if(tab==='today'){
     const [d,a]=await Promise.all([getDashboard(),api(`/api/lesson?date=${encodeURIComponent(date)}${lang==='all'?'':`&lang=${lang}`}`)]);
     stats=d;words=a.words;
   }else if(tab==='review'){
     const [d,a]=await Promise.all([getDashboard(),api(`/api/reviews${lang==='all'?'':`?lang=${lang}`}`)]);
     stats=d;words=a.words;
   }else if(tab==='library'){
     const q=new URLSearchParams({q:state.q,bookmarked:String(state.bookmarked),offset:String(state.page*100),limit:'100',status:state.libraryStatus});
     if(lang!=='all')q.set('lang',lang);
     words=(await api('/api/library?'+q)).words;
   }else if(tab==='custom'){
     const [d,a]=await Promise.all([getDashboard(),api('/api/pending')]);
     stats=d;words=a.words;
   }
   // Discard a slow response if the user has switched tabs meanwhile.
   if(ticket!==reloadSequence)return;
   state.stats=stats;state.words=words;
   pageCache.set(key,{saved:Date.now(),words,stats});
   render();
 }catch(err){
   if(ticket!==reloadSequence)return;
   state.words=[];
   toast(err.message);render();
 }
}
function speak(text,lang){if(!('speechSynthesis' in window)){toast('此瀏覽器不支援語音合成');return}window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang=speechCodes[lang]||'en-US';u.rate=state.speed;const voices=window.speechSynthesis.getVoices();const v=voices.find(v=>v.lang.toLowerCase()===u.lang.toLowerCase())||voices.find(v=>v.lang.toLowerCase().startsWith(lang));if(v)u.voice=v;window.speechSynthesis.speak(u)}
function editInput(label,name,value='',multiline=false){return `<label>${esc(label)}${multiline?`<textarea name="${name}" rows="2" maxlength="1000">${esc(value)}</textarea>`:`<input class="search-input" name="${name}" maxlength="1000" value="${esc(value)}"/>`}</label>`}
async function openEditor(id){const {word:w}=await api('/api/words/'+encodeURIComponent(id));state.editId=id;const dialog=$('editor-dialog');$('editor-content').innerHTML=`<div class="line-between"><h2>編輯詞彙</h2><button type="button" class="secondary" data-close-editor="1">關閉</button></div><p class="small muted">${esc(langNames[w.language])} · ${w.status==='known'?'已認識':w.status==='pending'?'待補全':'學習中'} · 來源：${w.source==='manual'?'個人輸入':'每日生成'}</p><form id="edit-form" class="vocab-form">${editInput('單字／詞組','term',w.term)}${editInput('繁體中文詞義','meaning_zh',w.meaning_zh,true)}${editInput('讀音','reading',w.reading)}${editInput('詞性','part_of_speech',w.part_of_speech)}${editInput('外語例句','example',w.example,true)}${editInput('例句中譯','example_zh',w.example_zh,true)}${editInput('程度','level',w.level)}${editInput('主題','topic',w.topic)}<label>遇見的原句（供 AI 參考）<textarea name="context_sentence" rows="2" maxlength="1200">${esc(w.context_sentence)}</textarea></label><button class="primary wide" type="submit">儲存修改</button>${w.status==='pending'?'<button class="outline wide" type="button" data-editor-activate="1">儲存並加入複習（不使用 AI）</button>':''}</form><div class="editor-danger"><p class="small muted">如果 AI 生成錯誤，可將詞彙退回待補全清單；如你已經認識，就標記為「已認識」，不再出現在每日學習或複習。</p><div class="editor-buttons"><button type="button" class="outline" data-requeue="${esc(w.id)}" ${w.status==='pending'?'disabled':''}>重新加入待生成</button><button type="button" class="secondary" data-known="${esc(w.id)}" ${w.status==='known'?'disabled':''}>標記為已認識</button></div></div>`;if(typeof dialog.showModal==='function')dialog.showModal();else dialog.setAttribute('open','')}
function closeEditor(){const d=$('editor-dialog');if(d.open&&d.close)d.close();else d.removeAttribute('open');state.editId=null}
function editorPayload(){const form=$('edit-form');const fields=['term','reading','part_of_speech','meaning_zh','example','example_zh','level','topic','context_sentence'];return Object.fromEntries(fields.map(k=>[k,form.elements[k].value.trim()]))}
async function submitEditor(activate=false){if(!state.editId)return;const payload={...editorPayload(),activate};const r=await api('/api/words/'+encodeURIComponent(state.editId),{method:'PATCH',body:JSON.stringify(payload)});closeEditor();toast(activate?'已加入複習清單':'修改已儲存');await reload();return r.word}
async function setKnown(id){if(!confirm('將詞彙標記為已認識？它會退出每日詞包及複習，但仍可在「詞庫 → 已認識」找到，並永久排除 AI 再生成。'))return;await api(`/api/words/${encodeURIComponent(id)}/known`,{method:'POST',body:'{}'});closeEditor();toast('已加入已認識字庫，永久排除重複生成');await reload()}
async function requeue(id){if(!confirm('將這個詞彙退回「我的生字」待補全？目前的複習排程將重設，歷史紀錄仍保留。'))return;await api(`/api/words/${encodeURIComponent(id)}/requeue`,{method:'POST',body:'{}'});closeEditor();toast('已放回待 AI 補全清單');await reload()}
$('shell').addEventListener('click',async e=>{const t=e.target.closest('button');if(!t)return;try{
 if(t.dataset.tab){state.tab=t.dataset.tab;state.lang='all';state.page=0;state.selected=0;state.revealed=false;await reload();return}
 if(t.dataset.lang){state.lang=t.dataset.lang;state.page=0;state.selected=0;state.revealed=false;await reload();return}
 if(t.dataset.move){state.selected+=Number(t.dataset.move);state.revealed=false;render();return}
 if(t.dataset.reveal){state.revealed=!state.revealed;render();return}
 if(t.dataset.rating){const w=state.words[state.selected];if(!w)return;t.disabled=true;await api('/api/review',{method:'POST',body:JSON.stringify({word_id:w.id,rating:t.dataset.rating,request_id:crypto.randomUUID()})});state.revealed=false;const current=state.selected;await reload();state.selected=Math.min(current+(state.tab==='review'?0:1),Math.max(0,state.words.length-1));render();return}
 if(t.dataset.bookmark){await api('/api/bookmark/'+encodeURIComponent(t.dataset.bookmark),{method:'POST',body:JSON.stringify({enabled:t.dataset.enabled==='true'})});await reload();return}
 if(t.dataset.speak){const w=state.words[state.selected];if(w)speak(t.dataset.speak==='term'?w.term:w.example,w.language);return}
 if(t.dataset.librarySpeak){const w=state.words.find(w=>w.id===t.dataset.librarySpeak);if(w)speak(w.term,w.language);return}
 if(t.dataset.edit){await openEditor(t.dataset.edit);return}
 if(t.dataset.known){await setKnown(t.dataset.known);return}
 if(t.dataset.requeue){await requeue(t.dataset.requeue);return}
 if(t.dataset.closeEditor){closeEditor();return}
 if(t.dataset.editorActivate){await submitEditor(true);return}
 if(t.dataset.generate){t.disabled=true;t.textContent='Gemini 正在補全（最多5詞）…';try{const out=await api('/api/pending/generate',{method:'POST',body:'{}'});toast(`已補全 ${out.generated} 詞並加入複習，可在詞庫中檢查或編輯`);await reload()}finally{t.disabled=false}return}
 if(t.dataset.search){state.q=$('search').value.trim();state.page=0;await reload();return}
 if(t.dataset.page){state.page=Math.max(0,state.page+Number(t.dataset.page));await reload();return}
 if(t.dataset.logout){await api('/api/logout',{method:'POST',body:'{}'});showLogin();return}
 }catch(err){toast(err.message)}});
$('shell').addEventListener('submit',async e=>{if(e.target.id==='custom-form'){
 e.preventDefault();const form=e.target,mode=form.elements.mode.value;const data={language:form.elements.language.value,term:form.elements.term.value.trim(),context_sentence:form.elements.context_sentence.value.trim(),mode};if(!data.term){toast('請輸入單字');return}
 if(mode==='manual'){for(const k of ['meaning_zh','reading','part_of_speech','example','example_zh','level','topic'])data[k]=form.elements[k].value.trim()}
 const button=form.querySelector('[type=submit]');button.disabled=true;try{await api('/api/words',{method:'POST',body:JSON.stringify(data)});toast(mode==='ai'?'已加入我的生字，等待手動生成':'已加入詞庫及複習清單');await reload()}catch(err){toast(err.message);button.disabled=false}
 }else if(e.target.id==='edit-form'){e.preventDefault();try{await submitEditor(false)}catch(err){toast(err.message)}}});
$('shell').addEventListener('change',async e=>{try{if(e.target.id==='lesson-date'){state.date=e.target.value;state.selected=0;state.revealed=false;await reload()}if(e.target.id==='star-only'){state.bookmarked=e.target.checked;state.page=0;await reload()}if(e.target.id==='library-status'){state.libraryStatus=e.target.value;state.page=0;await reload()}if(e.target.id==='custom-mode'){$('manual-fields').hidden=e.target.value!=='manual'}}catch(err){toast(err.message)}});
$('shell').addEventListener('input',e=>{if(e.target.id==='speech-rate'){state.speed=Number(e.target.value);localStorage.setItem('speechSpeed',String(state.speed));$('speed-label').textContent=state.speed.toFixed(2)+'×'}});
$('shell').addEventListener('keydown',async e=>{if(e.target.id==='search'&&e.key==='Enter'){e.preventDefault();state.q=e.target.value.trim();state.page=0;await reload()}});
init();
