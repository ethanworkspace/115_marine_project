"""Personal notes persisted separately from all RAG and evaluation databases."""
from __future__ import annotations
import json, os, sqlite3, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOPICS = ['養殖管理', '水質環境', '魚種認識', '氣候防寒', '疾病觀察', '其他']
SPECIES = ['通用', '虱目魚', '吳郭魚', '石斑魚', '鱸魚', '烏魚', '鰻魚']

class KnowledgeNotes:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('MARINE_NOTES_PATH') or Path(__file__).parent/'user_data/knowledge_notes.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS knowledge_notes (
                note_id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
                species TEXT NOT NULL, topic TEXT NOT NULL, origin TEXT NOT NULL,
                provenance_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    def connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def list(self, query='', species='全部魚種', topic='全部主題'):
        with self.connect() as con:
            rows = [dict(r) for r in con.execute('SELECT * FROM knowledge_notes ORDER BY updated_at DESC, note_id')]
        needle = query.strip().casefold()
        return [r for r in rows if (not needle or needle in (r['title']+' '+r['body']).casefold())
                and (species=='全部魚種' or r['species']==species) and (topic=='全部主題' or r['topic']==topic)]

    def get(self, note_id):
        with self.connect() as con:
            row = con.execute('SELECT * FROM knowledge_notes WHERE note_id=?', (note_id,)).fetchone()
        return dict(row) if row else None

    def save(self, title, body, species='通用', topic='其他', note_id=None, origin='PERSONAL_NOTE', provenance=None):
        title, body = str(title).strip(), str(body).strip()
        if not title or not body: raise ValueError('請填寫標題與小知識內容。')
        if len(title)>80 or len(body)>8000: raise ValueError('標題限80字，內容限8,000字。')
        if species not in SPECIES or topic not in TOPICS: raise ValueError('請選擇有效的魚種與主題。')
        stamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='microseconds')
        if note_id:
            with self.connect() as con:
                changed = con.execute('''UPDATE knowledge_notes SET title=?,body=?,species=?,topic=?,updated_at=?
                    WHERE note_id=?''', (title,body,species,topic,stamp,note_id)).rowcount
                if not changed: raise ValueError('找不到這張小知識，請重新整理頁面。')
            return note_id
        note_id = uuid.uuid4().hex
        with self.connect() as con:
            con.execute('INSERT INTO knowledge_notes VALUES (?,?,?,?,?,?,?,?,?)',
                (note_id,title,body,species,topic,origin,json.dumps(provenance or {},ensure_ascii=False),stamp,stamp))
        return note_id
