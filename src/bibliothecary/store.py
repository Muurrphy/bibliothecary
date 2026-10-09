"""Local transactional records. JSON and Markdown are recoverable exports, never a second writer.

All model input is selected by callers; this module never contacts a network service.
"""
from __future__ import annotations
import contextlib
import datetime as dt
import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from . import library, safe


def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def dump(data): return json.dumps(data, ensure_ascii=False, sort_keys=True)
def digest(data): return hashlib.sha256(dump(data).encode()).hexdigest()
def canonical(value: str) -> str:
    value = value.strip()
    doi = re.search(r'(10\.\d{4,9}/[^\s?#]+)', value, re.I)
    if doi: return 'doi:' + doi[1].rstrip('/').lower()
    if not value.startswith(('http://', 'https://')): return value
    u = urlsplit(value)
    query = [(k,v) for k,v in parse_qsl(u.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
    path = re.sub(r'^/abs/', '/pdf/', u.path) if 'arxiv.org' in u.netloc else u.path
    if 'arxiv.org' in u.netloc: path = re.sub(r'v\d+(?:\.pdf)?$', '', path).removesuffix('.pdf')
    return urlunsplit(('https', u.netloc.lower(), path.rstrip('/'), urlencode(sorted(query)), ''))

def tokens(text):
    text = text.lower()
    return set(re.findall(r'[a-z0-9]{2,}', text) + re.findall(r'[\u3400-\u9fff]{1,2}', text) +
               [text[i:i+2] for i in range(len(text)-1) if all('\u3400' <= c <= '\u9fff' for c in text[i:i+2])])


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or library.home())
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'library.sqlite3'
        with safe.locked(self.root / '.store.lock'):
            with self.connect() as db:
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS documents(kind TEXT, key TEXT, data TEXT NOT NULL,
                        PRIMARY KEY(kind,key));
                    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, reading TEXT NOT NULL,
                        data TEXT NOT NULL, origin TEXT UNIQUE);
                    CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY, text TEXT NOT NULL,
                        category TEXT NOT NULL, source TEXT NOT NULL, created TEXT NOT NULL,
                        basis TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active');
                    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL,
                        status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                        updated TEXT NOT NULL, error TEXT NOT NULL DEFAULT '');
                    CREATE INDEX IF NOT EXISTS event_reading ON events(reading,id);
                    CREATE INDEX IF NOT EXISTS memory_status ON memories(status);
                ''')
                ready = db.execute('PRAGMA user_version').fetchone()[0]
            if not ready:
                self._migrate()

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db: yield db
        finally: db.close()

    def _migrate(self):
        files = []
        for name in ('reader.json','telegram.json','chat.jsonl'):
            if (self.root/name).is_file(): files.append(self.root/name)
        for name in ('readings','books'):
            if (self.root/name).exists():
                files.extend(p for p in (self.root/name).rglob('*') if p.is_file() and p.suffix in ('.json','.jsonl','.md','.txt'))
        backup = None
        if files:
            backup = self.root / 'backups' / ('before-sqlite-' + uuid.uuid4().hex[:12])
            for p in files:
                dest=backup/p.relative_to(self.root); dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest)
            safe.write_json(backup/'manifest.json', {'files': {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
        imported, errors = 0, []
        with self.connect() as db:
            for p in files:
                rel=p.relative_to(self.root)
                try:
                    if p.suffix == '.jsonl':
                        for n,line in enumerate(p.read_text().splitlines()):
                            try: event=json.loads(line)
                            except ValueError:
                                errors.append(f'{rel}:{n+1}'); continue
                            reading='chat' if p.name=='chat.jsonl' else p.parent.name
                            db.execute('INSERT OR IGNORE INTO events(reading,data,origin) VALUES(?,?,?)',
                                       (reading,dump(event),f'{rel}:{n}'))
                            imported += 1
                    elif p.suffix == '.json':
                        data=json.loads(p.read_text())
                        if not isinstance(data,dict): raise ValueError('not an object')
                        kind,key = ('settings',p.stem) if len(rel.parts)==1 else (p.stem,p.parent.name)
                        if rel.parts[0]=='books' and p.name=='book.json': kind='book'
                        if rel.parts[0]=='readings' and p.name=='book.json': kind='book_marker'
                        db.execute('INSERT OR IGNORE INTO documents VALUES(?,?,?)',(kind,key,dump(data)))
                        if p.name=='reader.json':
                            for note in data.get('notes',[]):
                                db.execute('INSERT INTO memories(text,category,source,created,basis,scope) VALUES(?,?,?,?,?,?)',
                                           (note['text'],'preference','legacy reader.json',note.get('t') or stamp(),'inferred','reader'))
                        imported += 1
                except (ValueError,KeyError,TypeError) as err:
                    errors.append(f'{rel}: {type(err).__name__}')
            manifest={'imported':imported,'errors':errors,'backup':str(backup) if backup else None,'at':stamp()}
            db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?)',('system','migration',dump(manifest)))
            db.execute('PRAGMA user_version=1')

    def get(self, kind, key, default=None):
        with self.connect() as db:
            row=db.execute('SELECT data FROM documents WHERE kind=? AND key=?',(kind,str(key))).fetchone()
        return json.loads(row[0]) if row else ({} if default is None else default)

    def all(self, kind):
        with self.connect() as db:
            rows=db.execute('SELECT key,data FROM documents WHERE kind=? ORDER BY key',(kind,)).fetchall()
        return [(r['key'],json.loads(r['data'])) for r in rows]

    def put(self, kind, key, data):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?)',(kind,str(key),dump(data)))

    def patch(self, kind, key, data, baseline):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM documents WHERE kind=? AND key=?',(kind,key)).fetchone()
            latest=json.loads(row[0]) if row else dict(data)
            for field,value in data.items():
                if row and value==baseline.get(field): continue
                if field=='sessions':
                    old={x['reading']:x for x in baseline.get(field,[])}
                    merged={x['reading']:x for x in latest.get(field,[])}
                    for session in value:
                        name=session['reading']; merged.setdefault(name,{}).update({k:v for k,v in session.items() if v!=old.get(name,{}).get(k)})
                    latest[field]=list(merged.values())
                else: latest[field]=value
            db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?)',(kind,key,dump(latest)))
        return latest

    def append(self, reading, event, origin=None):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO events(reading,data,origin) VALUES(?,?,?)',(reading,dump(event),origin))

    def events(self, reading):
        with self.connect() as db:
            rows=db.execute('SELECT data FROM events WHERE reading=? ORDER BY id',(reading,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def memory(self, text, *, category='preference', source='conversation', basis='inferred', scope='reader'):
        text=str(text).strip()
        if not text: return None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT id,status FROM memories WHERE text=? ORDER BY id DESC LIMIT 1',(text,)).fetchone()
            if row: return row['id'] if row['status']=='active' else None
            return db.execute('INSERT INTO memories(text,category,source,created,basis,scope) VALUES(?,?,?,?,?,?)',
                              (text,category,source,stamp(),basis,scope)).lastrowid

    def memories(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM memories WHERE status='active' ORDER BY id")]

    def revise_memory(self, number, text=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM memories WHERE id=? AND status='active'",(int(number),)).fetchone()
            if not row: raise ValueError('没有这条有效记忆')
            db.execute('UPDATE memories SET status=? WHERE id=?',('superseded' if text else 'forgotten',int(number)))
            if text:
                db.execute('INSERT INTO memories(text,category,source,created,basis,scope) VALUES(?,?,?,?,?,?)',
                           (text,row['category'],f'correction:{number}',stamp(),'explicit',row['scope']))
        self.export_profile()

    def export_profile(self):
        safe.write_json(self.root/'reader.json', {'notes':[{'id':r['id'],'text':r['text'],'t':r['created'],
            'source':r['source'],'basis':r['basis']} for r in self.memories()]})

    def retrieve(self, query, limit=8):
        wanted=tokens(query); candidates=[]
        with self.connect() as db:
            redacted=[r[0] for r in db.execute("SELECT text FROM memories WHERE status!='active'")]
            rows=db.execute('SELECT id,reading,data FROM events ORDER BY id DESC').fetchall()
        for row in rows:
            event=json.loads(row['data'])
            if event.get('who')=='librarian': continue
            text=' '.join(str(event.get(k) or '') for k in ('text','question','answer','review'))
            if any(t in text for t in redacted): continue
            score=len(wanted & tokens(text))
            if score:
                candidates.append({'score':score,'source':f"{row['reading']}#event-{row['id']}",
                                   'text':text,'focus':event.get('focus'),'at':event.get('t')})
        for key,summary in self.all('summary'):
            text=' '.join(str(x) for k in ('unclear','threads') for x in summary.get(k,[]))
            if any(t in text for t in redacted): continue
            score=len(wanted & tokens(text))
            if score: candidates.append({'score':score,'source':key+'#summary','text':text,'basis':'inferred'})
        return sorted(candidates,key=lambda r:r['score'],reverse=True)[:limit]

    def enqueue(self, kind, data, key=None):
        key=key or uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO jobs(id,kind,data,status,updated) VALUES(?,?,?,?,?)',
                       (key,kind,dump(data),'pending',stamp()))
        return key

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY CASE WHEN kind='navigate' THEN 0 WHEN kind='adapt' THEN 2 ELSE 1 END, rowid LIMIT 1").fetchone()
            if not row: return None
            db.execute("UPDATE jobs SET status='running',attempts=attempts+1,updated=? WHERE id=?",(stamp(),row['id']))
        return {**dict(row),'data':json.loads(row['data'])}

    def job_state(self, key, status, error=''):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?,error=?,updated=? WHERE id=? AND status!='cancelled'",(status,error,stamp(),key))

    def jobs(self):
        with self.connect() as db: return [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY rowid DESC LIMIT 20')]

    def recover(self):
        # In-flight sends may have reached Telegram. Do not retry uncertain deliveries automatically.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='uncertain',error='Restarted during execution; inspect before retrying' WHERE status='running'")

    def cancel(self, key=None):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='cancelled' WHERE status IN ('pending','running')" + (' AND id=?' if key else ''), (key,) if key else ())

    def export_events(self, reading, path):
        safe.atomic(path, ''.join(dump(e)+'\n' for e in self.events(reading)))

    def backup(self, destination):
        dest=Path(destination).expanduser().resolve()
        if dest==self.root.resolve() or self.root.resolve() in dest.parents:
            raise ValueError('Choose a backup directory outside the library')
        dest.mkdir(parents=True,exist_ok=False)
        with self.connect() as db:
            target=sqlite3.connect(dest/'library.sqlite3')
            try: db.backup(target)
            finally: target.close()
        for name in ('books','readings','inbox'):
            if (self.root/name).exists(): shutil.copytree(self.root/name,dest/name)
        for name in ('reader.json','telegram.json','chat.jsonl','shelves.toml','catalog.toml'):
            if (self.root/name).exists(): shutil.copy2(self.root/name,dest/name)
        safe.write_json(dest/'backup.json',{'version':1,'at':stamp(),'includes':'database, books, readings, inbox and settings; no audio cache'})
        return dest
