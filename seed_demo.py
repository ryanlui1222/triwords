"""Insert an example 30-word lesson into local SQLite. NEVER run on production Turso."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

import db


def seed(target_date=None):
    if os.getenv('TURSO_DATABASE_URL'):
        raise SystemExit('安全限制：示範詞庫不會寫入遠端 Turso；請移除 TURSO_DATABASE_URL 後再試。')
    day = target_date or datetime.now(ZoneInfo(os.getenv('APP_TIMEZONE','Asia/Hong_Kong'))).date().isoformat()
    demo=json.loads((Path(__file__).parent/'demo_words.json').read_text(encoding='utf-8'))
    assert len(demo)==30 and all(sum(w['lang']==l for w in demo)==10 for l in ('en','ja','es'))
    db.init_db()
    now=datetime.now(timezone.utc).isoformat()
    counts={'en':0,'ja':0,'es':0}
    with db.connection() as conn:
        for word in demo:
            lang=word['lang']; counts[lang]+=1
            word_id=str(uuid.uuid5(uuid.NAMESPACE_DNS,f"demo:{lang}:{word['term']}"))
            conn.execute('INSERT OR IGNORE INTO vocabulary(id,language,term,reading,part_of_speech,meaning_zh,example,example_zh,level,topic,created_at,normalized_term) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (word_id,lang,word['term'],word['reading'],word['part_of_speech'],word['meaning_zh'],word['example'],word['example_zh'], {'en':'C1','ja':'N2','es':'A2'}[lang], 'demo', now, db.normalize(word['term'])))
            conn.execute('INSERT OR IGNORE INTO term_registry(language,normalized_term,word_id,registered_at) VALUES(?,?,?,?)',(lang,db.normalize(word['term']),word_id,now))
            conn.execute('INSERT OR IGNORE INTO daily_lessons(lesson_date,language,word_id,ordinal) VALUES(?,?,?,?)', (day,lang,word_id,counts[lang]))
    db.init_db()  # Rebuild the permanent term registry for newly seeded words.
    print(f'示範詞包：{day}，英文／日文／西文各10詞。')

if __name__=='__main__':
    seed()
