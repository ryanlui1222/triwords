"""Scheduled Gemini word generation -> Turso. Idempotent per language and date.
Use with GitHub Actions workflow or manually: python generate_daily.py
"""
import argparse
from datetime import datetime, timezone
import json
import os
import uuid
from zoneinfo import ZoneInfo

import db

LANGS = {
    'en': ('English','C1–C2','Academic English, literary criticism, humanities; widely usable natural collocations and idiomatic usage'),
    'ja': ('Japanese','N2–N1','Common N2–N1 vocabulary, verbs, adverbs, useful compound words and collocations'),
    'es': ('Spanish','A2–B1','Practical high-frequency Spanish, everyday expressions and useful verbs'),
}

FIELDS = ('term','reading','part_of_speech','meaning_zh','example','example_zh','level','topic')

def existing_terms(lang):
    with db.connection() as conn:
        return [x[0] for x in conn.execute('SELECT term FROM vocabulary WHERE language=? ORDER BY created_at DESC LIMIT 400',(lang,)).fetchall()]

def existing_day(lang, day):
    with db.connection() as conn:
        return conn.execute('SELECT COUNT(*) FROM daily_lessons WHERE lesson_date=? AND language=?', (day,lang)).fetchone()[0]

def generated_words(client, model, lang, exclusions):
    from google.genai import types
    long_name,level,focus=LANGS[lang]
    prompt = f'''You are a precise language educator creating a daily personal flashcard set. Create 15 DIFFERENT candidate terms (the system will select 10) in {long_name} at {level}.
Focus: {focus}. No fake words. Choose words useful for authentic language learning; Japanese use natural kanji/kana when appropriate, Spanish include accent marks and correct inflections.
Avoid terms already studied: {json.dumps(exclusions[:250],ensure_ascii=False)}.
Return ONLY JSON object {{"words": [{{"term":"...","reading":"...","part_of_speech":"...","meaning_zh":"...","example":"...","example_zh":"...","level":"...","topic":"..."}}]}}.
Requirements: exactly 15 objects; all meaning_zh and example_zh in Traditional Chinese (繁體中文); one accurate, idiomatic {long_name} original example for each; examples and translations must agree; include reasonable word class. 'reading' is IPA for English, kana for Japanese, optional pronunciation hint for Spanish. Do not add Markdown.'''
    response=client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type='application/json',temperature=0.65)
    )
    data=json.loads(response.text or '{}')
    if not isinstance(data,dict) or not isinstance(data.get('words'),list):
        raise RuntimeError(f'{lang}: Gemini 未回傳正確詞彙 JSON')
    return data['words']

def validate(candidates, lang, existing):
    clean=[]
    seen={w.strip().casefold() for w in existing}
    for item in candidates:
        if not isinstance(item,dict): continue
        if any(not isinstance(item.get(k),str) for k in FIELDS): continue
        if any(not item[k].strip() for k in ('term','meaning_zh','example','example_zh')):continue
        norm=item['term'].strip().casefold()
        if norm in seen:continue
        if any(len(item[k])>1000 for k in FIELDS):continue
        clean.append({k:item[k].strip() for k in FIELDS})
        seen.add(norm)
        if len(clean)>=10:break
    if len(clean)!=10:
        raise RuntimeError(f'{lang}: 僅有 {len(clean)} 個合格且不重複詞彙；未寫入資料庫，請重試或檢查 AI 回傳')
    return clean

def save_words(day, lang, words):
    if len(words)!=10:raise ValueError('每種語言必須剛好10詞')
    now=datetime.now(timezone.utc).isoformat()
    with db.connection() as conn:
        count=conn.execute('SELECT count(*) FROM daily_lessons WHERE lesson_date=? AND language=?',(day,lang)).fetchone()[0]
        if count:
            if count==10: return 'skip'
            raise RuntimeError(f'{day}/{lang} 已有不完整詞包（{count}），請檢查資料表')
        for i,w in enumerate(words,1):
            word_id=str(uuid.uuid4())
            conn.execute('INSERT INTO vocabulary(id,language,term,reading,part_of_speech,meaning_zh,example,example_zh,level,topic,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (word_id,lang,w['term'],w['reading'],w['part_of_speech'],w['meaning_zh'],w['example'],w['example_zh'],w['level'],w['topic'],now))
            conn.execute('INSERT INTO daily_lessons(lesson_date,language,word_id,ordinal) VALUES(?,?,?,?)',(day,lang,word_id,i))
    return 'saved'

def run(day=None):
    if not os.getenv('TURSO_DATABASE_URL'):
        raise RuntimeError('此腳本僅在有 TURSO_DATABASE_URL 時執行，避免誤用本地資料庫')
    if not os.getenv('GEMINI_API_KEY'):
        raise RuntimeError('缺少 GEMINI_API_KEY')
    day=day or datetime.now(ZoneInfo(os.getenv('APP_TIMEZONE','Asia/Hong_Kong'))).date().isoformat()
    from google import genai
    client=genai.Client(api_key=os.environ['GEMINI_API_KEY'])
    db.init_db()
    for lang in LANGS:
        n=existing_day(lang,day)
        if n==10:
            print(day,lang,'已存在10詞，略過');continue
        if n:
            raise RuntimeError(f'{lang} 詞包不完整：{n}詞；停止避免重複')
        prev=existing_terms(lang)
        candidates=generated_words(client,os.getenv('GEMINI_MODEL','gemini-2.5-flash-lite'),lang,prev)
        words=validate(candidates,lang,prev)
        result=save_words(day,lang,words)
        print(day,lang,result,'10詞')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--date',help='以 YYYY-MM-DD 指定詞包日期（測試用）')
    args=parser.parse_args()
    run(args.date)
