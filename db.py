"""Turso/libSQL or SQLite adapter; no credentials ever go to the browser."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import uuid

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("LOCAL_DB_PATH", str(ROOT / "local-vocab.db")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS vocabulary (
  id TEXT PRIMARY KEY,
  language TEXT NOT NULL CHECK(language IN ('en','ja','es')),
  term TEXT NOT NULL,
  reading TEXT NOT NULL DEFAULT '',
  part_of_speech TEXT NOT NULL DEFAULT '',
  meaning_zh TEXT NOT NULL,
  example TEXT NOT NULL,
  example_zh TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT '',
  topic TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(language,term)
);
CREATE TABLE IF NOT EXISTS daily_lessons (
  lesson_date TEXT NOT NULL,
  language TEXT NOT NULL CHECK(language IN ('en','ja','es')),
  word_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  PRIMARY KEY(lesson_date, language, ordinal),
  UNIQUE(lesson_date, word_id)
);
CREATE TABLE IF NOT EXISTS review_progress (
  word_id TEXT PRIMARY KEY,
  repetitions INTEGER NOT NULL DEFAULT 0,
  interval_days INTEGER NOT NULL DEFAULT 0,
  ease REAL NOT NULL DEFAULT 2.5,
  due_date TEXT NOT NULL,
  last_reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_history (
  id TEXT PRIMARY KEY,
  word_id TEXT NOT NULL,
  rating TEXT NOT NULL CHECK(rating IN ('again','hard','good','easy')),
  reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bookmarks (
  word_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);
"""

@contextmanager
def connection():
    url = os.getenv("TURSO_DATABASE_URL", "").strip()
    if url:
        token = os.getenv("TURSO_AUTH_TOKEN", "").strip()
        if not token:
            raise RuntimeError("已設定 TURSO_DATABASE_URL，但缺少 TURSO_AUTH_TOKEN")
        driver = os.getenv("TURSO_DRIVER", "libsql").strip().lower()
        if driver == "libsql":
            import libsql
            db = libsql.connect(database=url, auth_token=token)
        elif driver == "turso":
            import turso_serverless
            db = turso_serverless.connect(url, auth_token=token)
        else:
            raise RuntimeError("TURSO_DRIVER 必須為 libsql 或 turso")
    else:
        if os.getenv("VERCEL"):
            raise RuntimeError("Vercel 環境尚未設定 TURSO_DATABASE_URL；請在專案環境變數中加入 Turso 連接資訊")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(DB_PATH), timeout=20)
        db.execute("PRAGMA busy_timeout = 20000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with connection() as db:
        # Separate execute calls work across all DB-API drivers (no executescript dependency).
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                db.execute(stmt)


def as_dicts(cursor, columns):
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

WORD_COLUMNS = ('id','language','term','reading','part_of_speech','meaning_zh','example','example_zh','level','topic','created_at')
WORD_SELECT = 'v.id,v.language,v.term,v.reading,v.part_of_speech,v.meaning_zh,v.example,v.example_zh,v.level,v.topic,v.created_at'

def fetch_lesson(lesson_date, language=None):
    with connection() as db:
        args = [lesson_date]
        q = f"SELECT {WORD_SELECT}, CASE WHEN b.word_id IS NULL THEN 0 ELSE 1 END AS bookmarked, CASE WHEN r.word_id IS NULL THEN 0 ELSE 1 END AS practiced FROM daily_lessons d JOIN vocabulary v ON v.id=d.word_id LEFT JOIN bookmarks b ON b.word_id=v.id LEFT JOIN review_progress r ON r.word_id=v.id WHERE d.lesson_date=?"
        if language:
            q += ' AND d.language=?'
            args.append(language)
        q += " ORDER BY CASE d.language WHEN 'en' THEN 0 WHEN 'ja' THEN 1 ELSE 2 END, d.ordinal"
        return as_dicts(db.execute(q, args), WORD_COLUMNS + ('bookmarked','practiced'))

def fetch_due(today, language=None):
    with connection() as db:
        args = [today]
        q = f"SELECT {WORD_SELECT}, CASE WHEN b.word_id IS NULL THEN 0 ELSE 1 END AS bookmarked, r.due_date AS due_date FROM review_progress r JOIN vocabulary v ON v.id=r.word_id LEFT JOIN bookmarks b ON b.word_id=v.id WHERE r.due_date<=?"
        if language:
            q += ' AND v.language=?'; args.append(language)
        q += " ORDER BY r.due_date, v.language, v.term LIMIT 250"
        return as_dicts(db.execute(q, args), WORD_COLUMNS + ('bookmarked','due_date'))

def fetch_library(language=None, query='', starred=False, limit=100, offset=0):
    with connection() as db:
        args = []
        q = f"SELECT {WORD_SELECT}, CASE WHEN b.word_id IS NULL THEN 0 ELSE 1 END AS bookmarked FROM vocabulary v LEFT JOIN bookmarks b ON b.word_id=v.id WHERE 1=1"
        if language: q += ' AND v.language=?'; args.append(language)
        if query:
            q += ' AND (v.term LIKE ? OR v.meaning_zh LIKE ? OR v.example LIKE ?)'
            args.extend(['%'+query+'%']*3)
        if starred: q += ' AND b.word_id IS NOT NULL'
        q += ' ORDER BY v.created_at DESC, v.term LIMIT ? OFFSET ?'; args.extend([limit, offset])
        return as_dicts(db.execute(q,args), WORD_COLUMNS + ('bookmarked',))

def set_bookmark(word_id, enabled):
    with connection() as db:
        if db.execute('SELECT 1 FROM vocabulary WHERE id=?', (word_id,)).fetchone() is None:
            raise KeyError('詞彙不存在')
        if enabled:
            db.execute('INSERT OR IGNORE INTO bookmarks(word_id,created_at) VALUES(?,?)', (word_id,datetime.now(timezone.utc).isoformat()))
        else:
            db.execute('DELETE FROM bookmarks WHERE word_id=?',(word_id,))
    return {'id':word_id,'bookmarked':enabled}


def calculate_next(previous, rating, today):
    """Transparent MVP scheduling (not FSRS): day-granular, no intra-day queue."""
    reps = int(previous[0]) if previous else 0
    last_interval = int(previous[1]) if previous else 0
    ease = float(previous[2]) if previous else 2.5
    if rating == 'again':
        reps, interval, ease = 0, 1, max(1.3, ease - 0.2)
    elif rating == 'hard':
        reps, interval, ease = reps+1, max(1, round(last_interval * 1.25)) if last_interval else 1, max(1.3,ease-0.15)
    elif rating == 'good':
        reps += 1
        interval = 1 if reps == 1 else (6 if reps == 2 else max(1,round(last_interval * ease)))
    else:  # easy
        reps += 1
        ease += 0.15
        interval = 4 if reps == 1 else max(5,round(max(last_interval,1) * ease * 1.3))
    return reps, interval, round(ease, 3), (date.fromisoformat(today)+timedelta(days=interval)).isoformat()


def review_word(word_id, rating, request_id, today):
    if rating not in ('again','hard','good','easy'):
        raise ValueError('未知評分')
    if not request_id or len(request_id)>120:
        raise ValueError('request_id 格式不正確')
    now = datetime.now(timezone.utc).isoformat()
    with connection() as db:
        if db.execute('SELECT 1 FROM vocabulary WHERE id=?',(word_id,)).fetchone() is None:
            raise KeyError('詞彙不存在')
        if db.execute('SELECT id FROM review_history WHERE id=?',(request_id,)).fetchone():
            row=db.execute('SELECT due_date,interval_days FROM review_progress WHERE word_id=?',(word_id,)).fetchone()
            return {'word_id':word_id,'due_date':row[0], 'interval_days':row[1], 'duplicate':True}
        prev = db.execute('SELECT repetitions,interval_days,ease FROM review_progress WHERE word_id=?',(word_id,)).fetchone()
        reps, interval, ease, due = calculate_next(prev, rating, today)
        db.execute('INSERT INTO review_progress(word_id,repetitions,interval_days,ease,due_date,last_reviewed_at) VALUES(?,?,?,?,?,?) ON CONFLICT(word_id) DO UPDATE SET repetitions=excluded.repetitions,interval_days=excluded.interval_days,ease=excluded.ease,due_date=excluded.due_date,last_reviewed_at=excluded.last_reviewed_at', (word_id,reps,interval,ease,due,now))
        db.execute('INSERT INTO review_history(id,word_id,rating,reviewed_at) VALUES(?,?,?,?)',(request_id,word_id,rating,now))
    return {'word_id':word_id, 'due_date':due,'interval_days':interval,'duplicate':False}


def today_stats(today):
    with connection() as db:
        lesson_n = db.execute('SELECT count(*) FROM daily_lessons WHERE lesson_date=?',(today,)).fetchone()[0]
        due_n = db.execute('SELECT count(*) FROM review_progress WHERE due_date<=?', (today,)).fetchone()[0]
        completed_n = db.execute('SELECT count(DISTINCT h.word_id) FROM review_history h JOIN daily_lessons d ON d.word_id=h.word_id WHERE d.lesson_date=?', (today,)).fetchone()[0]
        return {'new_words': lesson_n,'due_reviews':due_n,'studied_today':completed_n}
