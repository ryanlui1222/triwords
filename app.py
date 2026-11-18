"""Single-user FastAPI web app. Run with: uvicorn app:app --reload."""
import base64
import json
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from typing import Literal

from fastapi import FastAPI, Depends, HTTPException, Request, Response, Cookie
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="三語日課 API", docs_url=None, redoc_url=None)
# Vercel serves public/static/* via its CDN. Do not force a public/ directory
# to exist inside the Python function bundle at import time.
if not os.getenv('VERCEL'):
    app.mount('/static', StaticFiles(directory=str(ROOT / 'public')), name='static')

def current_date():
    return datetime.now(ZoneInfo(os.getenv('APP_TIMEZONE','Asia/Hong_Kong'))).date().isoformat()

def credentials():
    pwd = os.getenv('APP_PASSWORD', '')
    secret = os.getenv('SESSION_SECRET', '')
    if len(pwd)<12 or len(secret)<32:
        raise HTTPException(503,'尚未設定 APP_PASSWORD（至少12字元）及 SESSION_SECRET（至少32字元）')
    return pwd, secret

def signed_cookie(secret, max_age=30*86400):
    stamp=str(int(time.time()+max_age))
    digest=hmac.new(secret.encode(), stamp.encode(), hashlib.sha256).hexdigest()
    return f'{stamp}.{digest}'

def read_cookie(value, secret):
    try:
        stamp,mac=value.split('.',1)
        if not stamp.isdecimal() or int(stamp)<time.time(): return False
        expect=hmac.new(secret.encode(),stamp.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(expect,mac)
    except Exception: return False

def auth(session: str|None=Cookie(None,alias='tri_session')):
    _, secret=credentials()
    if not session or not read_cookie(session, secret):
        raise HTTPException(401,'請先登入')
    return True

def same_origin(request:Request):
    origin=request.headers.get('origin','')
    if origin and urlparse(origin).netloc != request.headers.get('host',''):
        raise HTTPException(403,'跨網域操作已拒絕')
    if request.headers.get('sec-fetch-site') not in (None,'same-origin','none'):
        raise HTTPException(403,'跨網站操作已拒絕')

class Login(BaseModel):
    password: str

class Review(BaseModel):
    word_id: str
    rating: Literal['again','hard','good','easy']
    request_id: str = Field(min_length=1,max_length=120)

class Bookmark(BaseModel):
    enabled: bool

class ManualWord(BaseModel):
    language: Literal['en','ja','es']
    term: str = Field(min_length=1,max_length=120)
    mode: Literal['ai','manual']
    context_sentence: str = Field(default='',max_length=1200)
    reading: str = Field(default='',max_length=1000)
    part_of_speech: str = Field(default='',max_length=1000)
    meaning_zh: str = Field(default='',max_length=1000)
    example: str = Field(default='',max_length=1000)
    example_zh: str = Field(default='',max_length=1000)
    level: str = Field(default='',max_length=1000)
    topic: str = Field(default='',max_length=1000)

class WordEdit(BaseModel):
    term: str | None = Field(default=None,min_length=1,max_length=120)
    reading: str | None = Field(default=None,max_length=1000)
    part_of_speech: str | None = Field(default=None,max_length=1000)
    meaning_zh: str | None = Field(default=None,max_length=1000)
    example: str | None = Field(default=None,max_length=1000)
    example_zh: str | None = Field(default=None,max_length=1000)
    level: str | None = Field(default=None,max_length=1000)
    topic: str | None = Field(default=None,max_length=1000)
    context_sentence: str | None = Field(default=None,max_length=1200)
    activate: bool = False

def ready():
    db.ensure_ready()

@app.middleware('http')
async def no_api_cache(request:Request,call_next):
    response=await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response

@app.get('/')
def index():
    return FileResponse(ROOT/'public'/'index.html')

@app.get('/health')
def health(): return {'ok':True}

@app.post('/api/login')
def login(data:Login, response:Response, request:Request):
    same_origin(request)
    password,secret=credentials()
    if not hmac.compare_digest(data.password,password):
        raise HTTPException(401,'密碼錯誤')
    secure=request.headers.get('x-forwarded-proto',request.url.scheme)=='https'
    response.set_cookie('tri_session',signed_cookie(secret),max_age=30*86400,httponly=True,secure=secure,samesite='strict',path='/')
    return {'ok':True}

@app.post('/api/logout')
def logout(response:Response, request:Request):
    same_origin(request)
    response.delete_cookie('tri_session', path='/',samesite='strict')
    return {'ok':True}

@app.get('/api/me')
def me(_=Depends(auth)):
    return {'ok':True,'today':current_date(), 'timezone':os.getenv('APP_TIMEZONE','Asia/Hong_Kong')}

def valid_lang(lang):
    if lang not in ('en','ja','es',None): raise HTTPException(400,'不支援的語言')
    return lang

@app.get('/api/dashboard')
def dashboard(_=Depends(auth), __=Depends(ready)):
    return {'date':current_date(), **db.today_stats(current_date())}

@app.get('/api/lesson')
def lesson(date:str|None=None,lang:str|None=None,_=Depends(auth), __=Depends(ready)):
    valid_lang(lang)
    requested=date or current_date()
    try: datetime.strptime(requested,'%Y-%m-%d')
    except ValueError: raise HTTPException(400,'日期必須為 YYYY-MM-DD')
    if len(requested)!=10: raise HTTPException(400,'日期必須為 YYYY-MM-DD')
    return {'date':requested,'words':db.fetch_lesson(requested,lang)}

@app.get('/api/reviews')
def reviews(lang:str|None=None,_=Depends(auth), __=Depends(ready)):
    valid_lang(lang)
    return {'date':current_date(),'words':db.fetch_due(current_date(),lang)}

@app.get('/api/library')
def library(lang:str|None=None,q:str='',bookmarked:bool=False,limit:int=100,offset:int=0,status:str='active',_=Depends(auth), __=Depends(ready)):
    valid_lang(lang)
    if len(q)>100: raise HTTPException(400,'搜尋字詞過長')
    if limit<1 or limit>250 or offset<0 or offset>100000: raise HTTPException(400,'分頁參數不正確')
    if status not in ('active','known','pending','all'): raise HTTPException(400,'詞庫狀態不正確')
    return {'words':db.fetch_library(lang,q,bookmarked,limit,offset,status,current_date())}

@app.post('/api/review')
def review(data:Review,request:Request,_=Depends(auth), __=Depends(ready)):
    same_origin(request)
    try: return db.review_word(data.word_id,data.rating,data.request_id,current_date())
    except KeyError: raise HTTPException(404,'詞彙不存在')
    except ValueError as e: raise HTTPException(400,str(e))

@app.post('/api/bookmark/{word_id}')
def bookmark(word_id:str, data:Bookmark, request:Request,_=Depends(auth), __=Depends(ready)):
    same_origin(request)
    try: return db.set_bookmark(word_id,data.enabled)
    except KeyError: raise HTTPException(404,'詞彙不存在')

@app.get('/api/pending')
def pending(_=Depends(auth), __=Depends(ready)):
    words=db.fetch_pending(150)
    return {'words':words,'batch_count':min(5,len(words))}

@app.get('/api/words/{word_id}')
def get_word(word_id:str,_=Depends(auth), __=Depends(ready)):
    word=db.get_word(word_id,current_date())
    if not word:raise HTTPException(404,'找不到這個詞彙')
    return {'word':word}

@app.post('/api/words')
def add_word(data:ManualWord,request:Request,_=Depends(auth), __=Depends(ready)):
    same_origin(request)
    fields={name:getattr(data,name) for name in db.FIELDS if name!='term'}
    try:
        word_id,status=db.add_manual(data.language,data.term,data.mode,data.context_sentence,fields,current_date())
    except db.DuplicateTerm as exc:
        raise HTTPException(409,{'message':str(exc),'existing_word_id':exc.word_id})
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    return {'word':db.get_word(word_id,current_date()),'status':status}

@app.patch('/api/words/{word_id}')
def edit_word(word_id:str,data:WordEdit,request:Request,_=Depends(auth), __=Depends(ready)):
    same_origin(request)
    supplied=data.model_dump(exclude_unset=True)
    activate=bool(supplied.pop('activate',False))
    context=supplied.pop('context_sentence',None)
    fields={name:value for name,value in supplied.items() if value is not None}
    try:
        db.update_word(word_id,fields,context,activate,current_date())
    except db.DuplicateTerm as exc:
        raise HTTPException(409,{'message':str(exc),'existing_word_id':exc.word_id})
    except KeyError:raise HTTPException(404,'詞彙不存在')
    except ValueError as exc:raise HTTPException(400,str(exc))
    return {'word':db.get_word(word_id,current_date())}

@app.post('/api/words/{word_id}/known')
def mark_known(word_id:str,request:Request,_=Depends(auth), __=Depends(ready)):
    same_origin(request)
    try:db.mark_known(word_id)
    except KeyError:raise HTTPException(404,'詞彙不存在')
    return {'word':db.get_word(word_id,current_date())}

@app.post('/api/words/{word_id}/requeue')
def requeue_word(word_id:str,request:Request,_=Depends(auth), __=Depends(ready)):
    same_origin(request)
    try:db.requeue(word_id)
    except KeyError:raise HTTPException(404,'詞彙不存在')
    return {'word':db.get_word(word_id,current_date())}


def complete_with_gemini(words):
    """One API request for up to five oldest pending words, in any languages.

    IDs and original terms must match exactly; a partial/invalid response writes NOTHING.
    """
    key=os.getenv('GEMINI_API_KEY','').strip()
    if not key:raise HTTPException(503,'Vercel 尚未設定 GEMINI_API_KEY，請在環境變數加入並重新部署')
    from google import genai
    from google.genai import types,errors
    original={w['id']:w for w in words}
    prompts=[{'id':w['id'],'language':w['language'],'term':w['term'],'source_sentence':w['context_sentence']} for w in words]
    instruction=("You are a multilingual vocabulary educator. Complete EACH of the following flashcards. "
      "Preserve EXACT id, language and term; do not translate or correct the original term. "
      "Context sentence may be empty; if present, prefer the meaning in that context. "
      "Return exactly one JSON object {\"items\": [{\"id\":\"...\",\"language\":\"en|ja|es\",\"term\":\"...\","
      "\"reading\":\"...\",\"part_of_speech\":\"...\",\"meaning_zh\":\"...\",\"example\":\"...\",\"example_zh\":\"...\",\"level\":\"...\",\"topic\":\"...\"}]} "
      "where the number of items exactly matches the input. meanings and translations MUST be Traditional Chinese. "
      "Write an idiomatic example in the corresponding language with a faithful translation. "
      "English reading: IPA; Japanese reading: kana; Spanish reading: natural pronunciation hint or empty string. "
      "Use strings for all fields, no Markdown. INPUT: "+json.dumps(prompts,ensure_ascii=False))
    client=genai.Client(api_key=key)
    try:
        response=client.models.generate_content(
            model=os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite'),
            contents=instruction,
            config=types.GenerateContentConfig(response_mime_type='application/json',temperature=0.35),
        )
    except errors.ServerError:
        raise HTTPException(503,'Gemini 暫時過載，詞彙仍在生字庫，稍後可再次按生成')
    except errors.ClientError as exc:
        code=getattr(exc,'code',None)
        if code==429:
            raise HTTPException(429,'Gemini 的請求速率或每日配額已達上限。待生成生字仍保留，請稍後重試')
        raise HTTPException(502,f'Gemini API 無法使用（HTTP {code or "未知"}），請檢查模型與 API 額度')
    try:
        payload=json.loads(response.text or '{}')
        items=payload['items']
        if not isinstance(items,list) or len(items)!=len(words):raise ValueError('生成筆數不正確')
        result={}
        for item in items:
            if not isinstance(item,dict):raise ValueError('格式不正確')
            wid=item.get('id')
            if wid not in original or wid in result:raise ValueError('詞彙 ID 不正確或重複')
            if item.get('term')!=original[wid]['term'] or item.get('language')!=original[wid]['language']:
                raise ValueError('Gemini 修改了原詞或語言')
            fields={}
            for k in db.FIELDS:
                if k=='term':continue
                v=item.get(k)
                if not isinstance(v,str) or len(v)>1000:raise ValueError(f'欄位{k}格式錯誤')
                fields[k]=v.strip()
            if not fields['meaning_zh'] or not fields['example'] or not fields['example_zh']:
                raise ValueError('缺少詞義或例句')
            result[wid]=fields
        if set(result)!=set(original):raise ValueError('缺少詞彙')
        return result
    except (ValueError,KeyError,TypeError,AttributeError) as exc:
        raise HTTPException(502,f'Gemini 回傳內容不完整：{exc}。未更動任何單字，可重新生成')

@app.post('/api/pending/generate')
def generate_pending(request:Request,_=Depends(auth), __=Depends(ready)):
    same_origin(request)
    words=db.fetch_pending(5)
    if not words:return {'generated':0,'words':[],'message':'沒有待補全的生字'}
    completed=complete_with_gemini(words)
    ids=[w['id'] for w in words]
    expected=[(w['id'],w['language'],w['term']) for w in words]
    try:db.save_ai_completed(completed,expected,current_date())
    except RuntimeError as exc:raise HTTPException(409,str(exc))
    return {'generated':len(ids),'words':[db.get_word(wid,current_date()) for wid in ids]}
