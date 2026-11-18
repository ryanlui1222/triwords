"""Scheduled daily vocabulary. Permanent dedup via Turso term_registry.
Run: python generate_daily.py [--date YYYY-MM-DD]
"""
import argparse, json, os, random, time
from datetime import datetime
from zoneinfo import ZoneInfo
import db

LANGS={
 'en':('English','C1–C2','Academic English, literature, humanities; idiomatic collocations'),
 'ja':('Japanese','N2–N1','Common intermediate-to-advanced vocabulary, verbs, adverbs, compounds'),
 'es':('Spanish','A2–B1','Frequent practical vocabulary, verbs, everyday expressions'),
}
FIELDS=db.FIELDS

def existing_day(lang,day):
    with db.connection() as c:
        return c.execute('SELECT count(*) FROM daily_lessons WHERE language=? AND lesson_date=?',(lang,day)).fetchone()[0]

def generated_words(client,model,lang,exclusions):
    from google.genai import types, errors
    name,level,focus=LANGS[lang]
    prompt=f'''You are an expert {name} language educator. Generate 15 DIFFERENT {level} vocabulary entries.
Focus: {focus}. Only authentic, correctly spelled vocabulary. Include culturally natural usage.
Avoid previously studied examples: {json.dumps(exclusions[:180],ensure_ascii=False)}.
Output ONLY a JSON object with a "words" array of 15 objects. Each object MUST contain exactly these string keys:
term, reading, part_of_speech, meaning_zh, example, example_zh, level, topic.
meaning_zh and example_zh MUST be Traditional Chinese; example must be an authentic {name} example sentence and translated accurately. English reading is IPA, Japanese reading is kana; Spanish reading may be empty. No Markdown.'''
    for attempt in range(3):
        try:
            res=client.models.generate_content(model=model,contents=prompt,config=types.GenerateContentConfig(response_mime_type='application/json',temperature=0.7))
            result=json.loads(res.text or '{}')
            if not isinstance(result,dict) or not isinstance(result.get('words'),list):raise RuntimeError(f'{lang}: 無效 Gemini JSON')
            return result['words']
        except errors.ServerError as exc:
            if getattr(exc,'code',None) not in (500,502,503,504) or attempt==2:raise
            delay=(8 if attempt==0 else 20)+random.uniform(0,2)
            print(f'{lang}: Gemini {exc.code}; {delay:.1f}秒後重試',flush=True);time.sleep(delay)

def filter_candidates(candidates,existing,need=10):
    seen={db.normalize(w) for w in existing}
    out=[]
    for item in candidates:
        if not isinstance(item,dict) or any(not isinstance(item.get(k),str) for k in FIELDS):continue
        if any(not item[k].strip() for k in ('term','meaning_zh','example','example_zh')):continue
        if any(len(item[k])>1000 for k in FIELDS):continue
        key=db.normalize(item['term'])
        if not key or key in seen:continue
        seen.add(key);out.append({k:item[k].strip() for k in FIELDS})
        if len(out)==need:break
    return out

def validate(candidates,lang,existing):
    out=filter_candidates(candidates,existing)
    if len(out)!=10:raise RuntimeError(f'{lang}: 只找到{len(out)}個不重複合格單字')
    return out

def run(day=None):
    if not os.getenv('TURSO_DATABASE_URL'):raise RuntimeError('避免誤寫本地資料庫：請設定 TURSO_DATABASE_URL')
    if not os.getenv('GEMINI_API_KEY'):raise RuntimeError('缺少 GEMINI_API_KEY')
    day=day or datetime.now(ZoneInfo(os.getenv('APP_TIMEZONE','Asia/Hong_Kong'))).date().isoformat()
    from google import genai
    client=genai.Client(api_key=os.environ['GEMINI_API_KEY'])
    db.init_db()
    for lang in LANGS:
        count=existing_day(lang,day)
        if count==10:
            print(day,lang,'已存在10詞，略過',flush=True);continue
        if count:raise RuntimeError(f'{lang}：詞包不完整（{count}），請先檢查資料庫')
        # Full historical exclusion, including known cards, pending cards and renamed terms.
        all_keys=db.registry_keys(lang)
        collected=[]; exclude_recent=db.recent_terms(lang)
        for attempt in range(5):
            raw=generated_words(client,os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite'),lang,exclude_recent+[w['term'] for w in collected])
            got=filter_candidates(raw,all_keys,10-len(collected))
            collected.extend(got)
            all_keys.update(db.normalize(w['term']) for w in got)
            if len(collected)==10:break
            print(f'{lang}: 第{attempt+1}批候選後有{len(collected)}個新詞，補充候選中',flush=True)
        if len(collected)<10:raise RuntimeError(f'{lang}: 五輪候選後仍不足10個新詞，沒有寫入不完整詞包')
        print(day,lang,db.save_daily(day,lang,collected),'10詞',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--date');args=parser.parse_args();run(args.date)
