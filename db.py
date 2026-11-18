"""Turso/SQLite schema and TriWords v0.2 data operations."""
import math, os, sqlite3, threading, unicodedata, uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DB_PATH=Path(os.getenv('LOCAL_DB_PATH',str(ROOT/'local-vocab.db')))
_READY=False
_LOCK=threading.Lock()
LANGS=('en','ja','es')
FIELDS=('term','reading','part_of_speech','meaning_zh','example','example_zh','level','topic')
SCHEMA="""
CREATE TABLE IF NOT EXISTS vocabulary (id TEXT PRIMARY KEY,language TEXT NOT NULL CHECK(language IN ('en','ja','es')),term TEXT NOT NULL,reading TEXT NOT NULL DEFAULT '',part_of_speech TEXT NOT NULL DEFAULT '',meaning_zh TEXT NOT NULL,example TEXT NOT NULL,example_zh TEXT NOT NULL,level TEXT NOT NULL DEFAULT '',topic TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,UNIQUE(language,term));
CREATE TABLE IF NOT EXISTS daily_lessons (lesson_date TEXT NOT NULL,language TEXT NOT NULL CHECK(language IN ('en','ja','es')),word_id TEXT NOT NULL,ordinal INTEGER NOT NULL,PRIMARY KEY(lesson_date,language,ordinal),UNIQUE(lesson_date,word_id));
CREATE TABLE IF NOT EXISTS review_progress (word_id TEXT PRIMARY KEY,repetitions INTEGER NOT NULL DEFAULT 0,interval_days INTEGER NOT NULL DEFAULT 0,ease REAL NOT NULL DEFAULT 2.5,due_date TEXT NOT NULL,last_reviewed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_history (id TEXT PRIMARY KEY,word_id TEXT NOT NULL,rating TEXT NOT NULL CHECK(rating IN ('again','hard','good','easy')),reviewed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bookmarks (word_id TEXT PRIMARY KEY,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS term_registry (language TEXT NOT NULL,normalized_term TEXT NOT NULL,word_id TEXT NOT NULL,registered_at TEXT NOT NULL,PRIMARY KEY(language,normalized_term));
CREATE TABLE IF NOT EXISTS schema_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""
@contextmanager
def connection():
    url=os.getenv('TURSO_DATABASE_URL','').strip()
    if url:
        token=os.getenv('TURSO_AUTH_TOKEN','').strip()
        if not token:raise RuntimeError('缺少 TURSO_AUTH_TOKEN')
        driver=os.getenv('TURSO_DRIVER','libsql').lower()
        if driver=='libsql':
            import libsql
            c=libsql.connect(database=url,auth_token=token)
        elif driver=='turso':
            import turso_serverless
            c=turso_serverless.connect(url,auth_token=token)
        else:raise RuntimeError('TURSO_DRIVER 必須是 libsql 或 turso')
    else:
        if os.getenv('VERCEL'):raise RuntimeError('Vercel 尚未設定 TURSO_DATABASE_URL')
        DB_PATH.parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(str(DB_PATH),timeout=20)
        c.execute('PRAGMA busy_timeout=20000')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback();raise
    finally:c.close()

def now():return datetime.now(timezone.utc).isoformat()
def normalize(term):return ' '.join(unicodedata.normalize('NFKC',term).casefold().split())

class DuplicateTerm(ValueError):
    def __init__(self,word_id,term):
        self.word_id=word_id
        super().__init__(f'「{term}」已存在或曾經存在於詞庫，不能重複新增')

def init_db():
    """Non-destructive migration: old lessons, progress, bookmarks remain intact."""
    global _READY
    with connection() as c:
        for statement in SCHEMA.split(';'):
            if statement.strip():c.execute(statement)
        version=c.execute("SELECT value FROM schema_metadata WHERE key='schema_version'").fetchone()
        if version and version[0]=='2':
            _READY=True
            return
        columns={row[1] for row in c.execute('PRAGMA table_info(vocabulary)').fetchall()}
        additions={'normalized_term':"TEXT NOT NULL DEFAULT ''",'source':"TEXT NOT NULL DEFAULT 'daily'",'status':"TEXT NOT NULL DEFAULT 'active'",'context_sentence':"TEXT NOT NULL DEFAULT ''",'known_at':"TEXT NOT NULL DEFAULT ''",'updated_at':"TEXT NOT NULL DEFAULT ''"}
        for key,definition in additions.items():
            if key not in columns:
                try:c.execute(f'ALTER TABLE vocabulary ADD COLUMN {key} {definition}')
                except Exception:
                    if key not in {r[1] for r in c.execute('PRAGMA table_info(vocabulary)').fetchall()}:raise
        legacy=c.execute('SELECT id,language,term,normalized_term FROM vocabulary').fetchall()
        encountered={}
        for wid,lang,term,stored in legacy:
            norm=normalize(term)
            if not norm:raise RuntimeError(f'資料庫有空白詞彙 {wid}')
            if (lang,norm) in encountered and encountered[(lang,norm)]!=wid:
                raise RuntimeError(f'舊資料存在標準化重複：{lang}/{term}。為保護複習歷史，請人工合併後再升級。')
            encountered[(lang,norm)]=wid
            if stored!=norm:c.execute('UPDATE vocabulary SET normalized_term=? WHERE id=?',(norm,wid))
            existing=c.execute('SELECT word_id FROM term_registry WHERE language=? AND normalized_term=?',(lang,norm)).fetchone()
            if existing and existing[0]!=wid:raise RuntimeError(f'詞彙保留鍵衝突：{lang}/{term}')
            c.execute('INSERT OR IGNORE INTO term_registry(language,normalized_term,word_id,registered_at) VALUES(?,?,?,?)',(lang,norm,wid,now()))
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_vocabulary_norm ON vocabulary(language,normalized_term)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_vocab_status ON vocabulary(status,created_at)')
        c.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES('schema_version','2')")
    _READY=True

def ensure_ready():
    if not _READY:
        with _LOCK:
            if not _READY:init_db()

def reserve(c,lang,term,wid):
    key=normalize(term)
    if not key:raise ValueError('單字不得為空白')
    row=c.execute('SELECT word_id FROM term_registry WHERE language=? AND normalized_term=?',(lang,key)).fetchone()
    if row:
        if row[0]==wid:return key
        raise DuplicateTerm(row[0],term)
    c.execute('INSERT INTO term_registry(language,normalized_term,word_id,registered_at) VALUES(?,?,?,?)',(lang,key,wid,now()))
    return key

WORDS=('id','language','term','reading','part_of_speech','meaning_zh','example','example_zh','level','topic','created_at','source','status','context_sentence','known_at')
COLUMNS=WORDS+('bookmarked','repetitions','interval_days','ease','due_date')
QSELECT=','.join('v.'+x for x in WORDS)+",CASE WHEN b.word_id IS NULL THEN 0 ELSE 1 END,COALESCE(r.repetitions,0),COALESCE(r.interval_days,0),COALESCE(r.ease,2.5),r.due_date"
QFROM=' FROM vocabulary v LEFT JOIN bookmarks b ON v.id=b.word_id LEFT JOIN review_progress r ON r.word_id=v.id'
def dicts(cursor):return [dict(zip(COLUMNS,row)) for row in cursor.fetchall()]
def mastery(w,today):
    """Transparent heuristic, not a scientifically calibrated recall probability."""
    if w['status']=='known':return 100
    if w['status']!='active' or not w.get('due_date'):return 0
    reps=max(0,int(w['repetitions']));days=max(0,int(w['interval_days']));ease=float(w['ease'])
    score=12*min(reps,5)+7*math.log2(1+days)+6*max(0,min(1,ease-1.8))
    overdue=max(0,(date.fromisoformat(today)-date.fromisoformat(w['due_date'])).days)
    return max(0,min(99,round(score-min(45,overdue*2))))
def decorate(rows,today):
    for row in rows:row['mastery_percent']=mastery(row,today)
    return rows

def fetch_lesson(day,lang=None):
    with connection() as c:
        q=f'SELECT {QSELECT}{QFROM} JOIN daily_lessons d ON d.word_id=v.id WHERE d.lesson_date=? AND v.status=\'active\''
        args=[day]
        if lang:q+=' AND d.language=?';args.append(lang)
        q+=" ORDER BY CASE d.language WHEN 'en' THEN 0 WHEN 'ja' THEN 1 ELSE 2 END,d.ordinal"
        return decorate(dicts(c.execute(q,args)),day)
def fetch_due(today,lang=None):
    with connection() as c:
        q=f'SELECT {QSELECT}{QFROM} WHERE v.status=\'active\' AND r.due_date<=?';args=[today]
        if lang:q+=' AND v.language=?';args.append(lang)
        q+=' ORDER BY r.due_date,v.language,v.term LIMIT 250'
        return decorate(dicts(c.execute(q,args)),today)
def fetch_library(lang=None,query='',starred=False,limit=100,offset=0,status='active',today=None):
    with connection() as c:
        q=f'SELECT {QSELECT}{QFROM} WHERE 1=1';args=[]
        if status!='all':q+=' AND v.status=?';args.append(status)
        if lang:q+=' AND v.language=?';args.append(lang)
        if query:q+=' AND (v.term LIKE ? OR v.meaning_zh LIKE ? OR v.example LIKE ?)';args.extend(['%'+query+'%']*3)
        if starred:q+=' AND b.word_id IS NOT NULL'
        q+=' ORDER BY v.created_at DESC,v.term LIMIT ? OFFSET ?';args.extend([limit,offset])
        return decorate(dicts(c.execute(q,args)),today or date.today().isoformat())
def fetch_pending(limit=100):
    with connection() as c:
        return decorate(dicts(c.execute(f"SELECT {QSELECT}{QFROM} WHERE v.status='pending' ORDER BY v.created_at,v.id LIMIT ?",(limit,))),date.today().isoformat())
def get_word(wid,today=None):
    with connection() as c:
        rows=dicts(c.execute(f'SELECT {QSELECT}{QFROM} WHERE v.id=?',(wid,)))
        return decorate(rows,today or date.today().isoformat())[0] if rows else None

def registry_keys(lang):
    with connection() as c:return {r[0] for r in c.execute('SELECT normalized_term FROM term_registry WHERE language=?',(lang,)).fetchall()}
def recent_terms(lang,limit=180):
    with connection() as c:
        return [r[0] for r in c.execute('SELECT v.term FROM term_registry k JOIN vocabulary v ON v.id=k.word_id WHERE k.language=? ORDER BY k.registered_at DESC LIMIT ?',(lang,limit)).fetchall()]

def start_review(c,wid,today):
    c.execute('INSERT OR IGNORE INTO review_progress(word_id,repetitions,interval_days,ease,due_date,last_reviewed_at) VALUES(?,0,0,2.5,?,?)',(wid,today,now()))

def add_manual(lang,term,mode,context='',values=None,today=None):
    if lang not in LANGS or mode not in ('ai','manual'):raise ValueError('語言或錄入方式不正確')
    values=values or {}
    if mode=='manual' and not str(values.get('meaning_zh','')).strip():raise ValueError('手動錄入必須提供中文釋義')
    wid=str(uuid.uuid4());created=now()
    contents={k:str(values.get(k,'')).strip() for k in FIELDS};contents['term']=term.strip()
    with connection() as c:
        norm=reserve(c,lang,term,wid)
        status='pending' if mode=='ai' else 'active'
        c.execute('INSERT INTO vocabulary(id,language,term,reading,part_of_speech,meaning_zh,example,example_zh,level,topic,created_at,normalized_term,source,status,context_sentence,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (wid,lang,*(contents[k] for k in FIELDS),created,norm,'manual',status,context.strip(),created))
        if status=='active':start_review(c,wid,today or date.today().isoformat())
    return wid,status

def update_word(wid,values,context=None,activate=False,today=None):
    if set(values)-set(FIELDS):raise ValueError('包含不支援的編輯欄位')
    with connection() as c:
        old=c.execute('SELECT language,term,normalized_term,status,meaning_zh FROM vocabulary WHERE id=?',(wid,)).fetchone()
        if not old:raise KeyError('詞彙不存在')
        lang,term,old_norm,status,old_meaning=old
        new_term=str(values.get('term',term)).strip()
        if not new_term:raise ValueError('單字不得留空')
        norm=normalize(new_term)
        if norm!=old_norm:reserve(c,lang,new_term,wid) # never release old spelling
        updates={'term':new_term,'normalized_term':norm,'updated_at':now()}
        updates.update({k:str(v).strip() for k,v in values.items() if k!='term'})
        if context is not None:updates['context_sentence']=context.strip()
        if activate and status=='pending':
            if not str(updates.get('meaning_zh',old_meaning)).strip():raise ValueError('需要中文釋義才能開始背誦')
            updates['status']='active';start_review(c,wid,today or date.today().isoformat())
        clauses=','.join(k+'=?' for k in updates)
        c.execute(f'UPDATE vocabulary SET {clauses} WHERE id=?',(*updates.values(),wid))
    return wid

def mark_known(wid):
    with connection() as c:
        if not c.execute('SELECT 1 FROM vocabulary WHERE id=?',(wid,)).fetchone():raise KeyError('詞彙不存在')
        c.execute("UPDATE vocabulary SET status='known',known_at=?,updated_at=? WHERE id=?",(now(),now(),wid))
    return wid

def requeue(wid):
    with connection() as c:
        if not c.execute('SELECT 1 FROM vocabulary WHERE id=?',(wid,)).fetchone():raise KeyError('詞彙不存在')
        c.execute("UPDATE vocabulary SET status='pending',known_at='',updated_at=? WHERE id=?",(now(),wid))
        c.execute('DELETE FROM review_progress WHERE word_id=?',(wid,)) # preserve history for auditing
    return wid

def save_ai_completed(items,expected,day):
    """Single transaction: all first-five IDs must still be pending."""
    with connection() as c:
        actual=[tuple(r) for r in c.execute("SELECT id,language,term FROM vocabulary WHERE status='pending' ORDER BY created_at,id LIMIT 5").fetchall()]
        if actual!=expected:raise RuntimeError('生字清單已有變化，請重新整理後再按生成')
        for wid,lang,term in expected:
            d=items[wid]
            c.execute("UPDATE vocabulary SET reading=?,part_of_speech=?,meaning_zh=?,example=?,example_zh=?,level=?,topic=?,status='active',known_at='',updated_at=? WHERE id=? AND status='pending'",
                      (d['reading'],d['part_of_speech'],d['meaning_zh'],d['example'],d['example_zh'],d['level'],d['topic'],now(),wid))
            start_review(c,wid,day)
    return len(expected)

def save_daily(day,lang,words):
    if len(words)!=10:raise ValueError('每個語言每日應有10詞')
    with connection() as c:
        count=c.execute('SELECT count(*) FROM daily_lessons WHERE lesson_date=? AND language=?',(day,lang)).fetchone()[0]
        if count==10:return 'skip'
        if count:raise RuntimeError('該日詞包不完整；為保護既有資料不自動覆蓋')
        for i,w in enumerate(words,1):
            wid=str(uuid.uuid4());norm=reserve(c,lang,w['term'],wid);created=now()
            c.execute('INSERT INTO vocabulary(id,language,term,reading,part_of_speech,meaning_zh,example,example_zh,level,topic,created_at,normalized_term,source,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (wid,lang,*(w[k] for k in FIELDS),created,norm,'daily','active',created))
            c.execute('INSERT INTO daily_lessons(lesson_date,language,word_id,ordinal) VALUES(?,?,?,?)',(day,lang,wid,i))
    return 'saved'

def set_bookmark(wid,enabled):
    with connection() as c:
        if not c.execute('SELECT 1 FROM vocabulary WHERE id=?',(wid,)).fetchone():raise KeyError('詞彙不存在')
        if enabled:c.execute('INSERT OR IGNORE INTO bookmarks(word_id,created_at) VALUES(?,?)',(wid,now()))
        else:c.execute('DELETE FROM bookmarks WHERE word_id=?',(wid,))
    return {'id':wid,'bookmarked':enabled}

def calculate_next(previous,rating,today):
    reps=int(previous[0]) if previous else 0;prior=int(previous[1]) if previous else 0;ease=float(previous[2]) if previous else 2.5
    if rating=='again':reps,interval,ease=0,1,max(1.3,ease-0.2)
    elif rating=='hard':reps,interval,ease=reps+1,max(1,round(prior*1.25)) if prior else 1,max(1.3,ease-0.15)
    elif rating=='good':
        reps+=1;interval=1 if reps==1 else (6 if reps==2 else max(1,round(prior*ease)))
    elif rating=='easy':
        reps+=1;ease+=0.15;interval=4 if reps==1 else max(5,round(max(prior,1)*ease*1.3))
    else:raise ValueError('未知評分')
    return reps,interval,round(ease,3),(date.fromisoformat(today)+timedelta(days=interval)).isoformat()

def review_word(wid,rating,request_id,today):
    if rating not in ('again','hard','good','easy'):raise ValueError('未知評分')
    if not request_id or len(request_id)>120:raise ValueError('request_id 格式不正確')
    with connection() as c:
        row=c.execute('SELECT status FROM vocabulary WHERE id=?',(wid,)).fetchone()
        if not row:raise KeyError('詞彙不存在')
        if row[0]!='active':raise ValueError('待補全／已認識單字不可評分')
        if c.execute('SELECT 1 FROM review_history WHERE id=?',(request_id,)).fetchone():
            old=c.execute('SELECT due_date,interval_days FROM review_progress WHERE word_id=?',(wid,)).fetchone()
            return {'word_id':wid,'due_date':old[0] if old else None,'interval_days':old[1] if old else None,'duplicate':True}
        prev=c.execute('SELECT repetitions,interval_days,ease FROM review_progress WHERE word_id=?',(wid,)).fetchone()
        reps,interval,ease,due=calculate_next(prev,rating,today)
        c.execute('INSERT INTO review_progress(word_id,repetitions,interval_days,ease,due_date,last_reviewed_at) VALUES(?,?,?,?,?,?) ON CONFLICT(word_id) DO UPDATE SET repetitions=excluded.repetitions,interval_days=excluded.interval_days,ease=excluded.ease,due_date=excluded.due_date,last_reviewed_at=excluded.last_reviewed_at',(wid,reps,interval,ease,due,now()))
        c.execute('INSERT INTO review_history(id,word_id,rating,reviewed_at) VALUES(?,?,?,?)',(request_id,wid,rating,now()))
    return {'word_id':wid,'due_date':due,'interval_days':interval,'duplicate':False}

def today_stats(today):
    with connection() as c:
        new=c.execute("SELECT count(*) FROM daily_lessons d JOIN vocabulary v ON v.id=d.word_id WHERE d.lesson_date=? AND v.status='active'",(today,)).fetchone()[0]
        due=c.execute("SELECT count(*) FROM review_progress r JOIN vocabulary v ON v.id=r.word_id WHERE r.due_date<=? AND v.status='active'",(today,)).fetchone()[0]
        done=c.execute('SELECT count(DISTINCT h.word_id) FROM review_history h JOIN daily_lessons d ON d.word_id=h.word_id WHERE d.lesson_date=?',(today,)).fetchone()[0]
        pending=c.execute("SELECT count(*) FROM vocabulary WHERE status='pending'").fetchone()[0]
        known=c.execute("SELECT count(*) FROM vocabulary WHERE status='known'").fetchone()[0]
    return {'new_words':new,'due_reviews':due,'studied_today':done,'pending':pending,'known':known}
