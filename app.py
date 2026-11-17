"""Single-user FastAPI web app. Run with: uvicorn app:app --reload."""
import base64
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
app.mount('/static',StaticFiles(directory=str(ROOT/'public')),name='static')

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
def dashboard(_=Depends(auth)):
    return {'date':current_date(), **db.today_stats(current_date())}

@app.get('/api/lesson')
def lesson(date:str|None=None,lang:str|None=None,_=Depends(auth)):
    valid_lang(lang)
    requested=date or current_date()
    try: datetime.strptime(requested,'%Y-%m-%d')
    except ValueError: raise HTTPException(400,'日期必須為 YYYY-MM-DD')
    if len(requested)!=10: raise HTTPException(400,'日期必須為 YYYY-MM-DD')
    return {'date':requested,'words':db.fetch_lesson(requested,lang)}

@app.get('/api/reviews')
def reviews(lang:str|None=None,_=Depends(auth)):
    valid_lang(lang)
    return {'date':current_date(),'words':db.fetch_due(current_date(),lang)}

@app.get('/api/library')
def library(lang:str|None=None,q:str='',bookmarked:bool=False,limit:int=100,offset:int=0,_=Depends(auth)):
    valid_lang(lang)
    if len(q)>100: raise HTTPException(400,'搜尋字詞過長')
    if limit<1 or limit>250 or offset<0 or offset>100000: raise HTTPException(400,'分頁參數不正確')
    return {'words':db.fetch_library(lang,q,bookmarked,limit,offset)}

@app.post('/api/review')
def review(data:Review,request:Request,_=Depends(auth)):
    same_origin(request)
    try: return db.review_word(data.word_id,data.rating,data.request_id,current_date())
    except KeyError: raise HTTPException(404,'詞彙不存在')
    except ValueError as e: raise HTTPException(400,str(e))

@app.post('/api/bookmark/{word_id}')
def bookmark(word_id:str, data:Bookmark, request:Request,_=Depends(auth)):
    same_origin(request)
    try: return db.set_bookmark(word_id,data.enabled)
    except KeyError: raise HTTPException(404,'詞彙不存在')
