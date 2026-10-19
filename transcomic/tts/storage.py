"""Dedicated TTS database avoids contention with translation transactions.

Only snapshots/metadata live here; audio and models have explicit external owners.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
from uuid import uuid4,uuid5,NAMESPACE_URL
from .documents import segments

SCHEMA='''
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,state TEXT NOT NULL DEFAULT 'draft',config TEXT NOT NULL DEFAULT '{}',created REAL NOT NULL,started REAL,ended REAL,error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,position INTEGER NOT NULL,name TEXT NOT NULL,path TEXT,text TEXT NOT NULL,locators TEXT NOT NULL,line_count INTEGER NOT NULL,mode TEXT NOT NULL DEFAULT 'lines',folder TEXT,base TEXT,rename_intent TEXT);
CREATE TABLE IF NOT EXISTS segments(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,position INTEGER NOT NULL,text TEXT NOT NULL,start INTEGER,end INTEGER,line_start INTEGER,line_end INTEGER,revision INTEGER NOT NULL DEFAULT 0,skip INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'pending',attempt TEXT,filename TEXT,sha256 TEXT,duration REAL,rate INTEGER,backend TEXT,error TEXT NOT NULL DEFAULT '',overwrite_allowed INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS tts_segment_queue ON segments(document_id,state,position);
CREATE TABLE IF NOT EXISTS presets(name TEXT PRIMARY KEY,config TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS preferences(name TEXT PRIMARY KEY,value TEXT NOT NULL);
'''

RECOVERABLE=('ready','paused','interrupted','partial','stopped')
TERMINAL=('completed','cancelled','failed')


class TtsStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.db=sqlite3.connect(self.path,check_same_thread=False,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript(SCHEMA)
        run_columns={r[1] for r in self.db.execute('PRAGMA table_info(runs)')}
        if 'history_accepted' not in run_columns:
            with self.transaction():
                self.db.execute('ALTER TABLE runs ADD COLUMN history_accepted INTEGER NOT NULL DEFAULT 0')
                # Legacy checkpoints cannot always distinguish output preparation
                # from Start. Preserve non-draft history and all audio evidence.
                self.db.execute("""UPDATE runs SET history_accepted=1 WHERE
                    state!='draft' OR started IS NOT NULL OR EXISTS
                    (SELECT 1 FROM segments s JOIN documents d ON d.id=s.document_id
                     WHERE d.run_id=runs.id AND (s.state='success' OR s.sha256 IS NOT NULL))""")
        columns={r[1] for r in self.db.execute('PRAGMA table_info(documents)')}
        for column in ('started','ended'):
            if column not in columns:self.db.execute(f'ALTER TABLE documents ADD COLUMN {column} REAL')
        with self.transaction():
            self.db.execute("UPDATE runs SET state='interrupted' WHERE state IN ('running','pausing','stopping')")
            self.db.execute("UPDATE segments SET state='unknown',error='Kiểm tra file/manifest trước khi tiếp tục' WHERE state='running'")
            # V4 adds a terminal cancellation policy without rewriting legacy
            # stopped checkpoints or removing any exported audio.
            self.db.execute("INSERT OR REPLACE INTO preferences VALUES ('job_cancel_policy','2')")

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:yield;self.db.execute('COMMIT')
            except BaseException:self.db.execute('ROLLBACK');raise

    def rows(self,sql,args=()):
        with self.lock:return [dict(r) for r in self.db.execute(sql,args)]
    def one(self,sql,args=()):
        values=self.rows(sql,args);return values[0] if values else None
    def execute(self,sql,args=()):
        with self.lock:return self.db.execute(sql,args)
    def run(self,id):return self.one('SELECT * FROM runs WHERE id=?',(id,))
    def runs(self):return self.rows("SELECT * FROM runs WHERE state!='draft' ORDER BY created DESC")
    def history_runs(self):return self.rows('SELECT * FROM runs WHERE history_accepted=1 ORDER BY created DESC')
    def docs(self,run):return self.rows('SELECT * FROM documents WHERE run_id=? ORDER BY position,id',(run,))
    def doc(self,id):return self.one('SELECT * FROM documents WHERE id=?',(id,))
    def segment(self,id):return self.one('SELECT * FROM segments WHERE id=?',(id,))
    def items(self,run):return self.rows('SELECT s.*,d.name,d.path,d.folder,d.run_id FROM segments s JOIN documents d ON d.id=s.document_id WHERE d.run_id=? ORDER BY d.position,s.position,s.id',(run,))
    def draft(self):
        row=self.one("SELECT id FROM runs WHERE state='draft' ORDER BY created DESC LIMIT 1")
        if row:return row['id']
        id=str(uuid4());self.execute('INSERT INTO runs(id,created) VALUES (?,?)',(id,time.time()));return id

    def add_document(self,run,data,mode='lines'):
        if self.run(run)['state']!='draft':raise ValueError('Tạo lượt mới để thêm tài liệu')
        if data.get('path') and any(Path(d['path'])==Path(data['path']) for d in self.docs(run) if d['path']):return None
        id=str(uuid4())
        with self.transaction():
            self.db.execute('INSERT INTO documents(id,run_id,position,name,path,text,locators,line_count,base,mode) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (id,run,len(self.docs(run)),data['name'],data.get('path'),data['text'],json.dumps(data.get('locators',[])),data['line_count'],data['name'],mode))
            self._split(id,data['text'],mode)
        return id

    def _split(self,doc,text,mode):
        self.db.execute('DELETE FROM segments WHERE document_id=?',(doc,))
        for i,item in enumerate(segments(text,mode),1):
            id=str(uuid5(NAMESPACE_URL,f'{doc}:{mode}:{item["start"]}:{item["end"]}:{item["text"]}'))
            self.db.execute('INSERT INTO segments(id,document_id,position,text,start,end,line_start,line_end) VALUES (?,?,?,?,?,?,?,?)',
                (id,doc,i,item['text'],item['start'],item['end'],item['line_start'],item['line_end']))

    def resplit(self,run,mode):
        if self.run(run)['state']!='draft':raise ValueError('Không tách lại lượt đã xác nhận')
        with self.transaction():
            for doc in self.docs(run):self._split(doc['id'],doc['text'],mode)
            self.db.execute('UPDATE documents SET mode=? WHERE run_id=?',(mode,run))

    def edit(self,id,text,*,automation_owner=None):
        repo=getattr(self,'automation',None)
        owner=repo.tts_owner(self.doc(self.segment(id)['document_id'])['run_id']) if repo else None
        if owner and owner['workset_id']!=automation_owner:raise ValueError('Sửa bản dịch qua tab Dịch để đồng bộ Automation.')
        if not text.strip() or not any(c.isalnum() for c in text):raise ValueError('Đoạn cần có nội dung đọc được')
        with self.transaction():
            if self.run(self.doc(self.segment(id)['document_id'])['run_id'])['state']=='cancelled':raise ValueError('Lượt đã hủy; tạo lượt mới để sửa văn bản')
            self.db.execute("UPDATE segments SET text=?,revision=revision+1,state='pending',attempt=NULL,error='',overwrite_allowed=0 WHERE id=?",(text,id))

    def manual_split(self,id,offset):
        item=self.segment(id);doc=self.doc(item['document_id'])
        if self.run(doc['run_id'])['state']!='draft':raise ValueError('Chỉ chia/gộp trước khi bắt đầu')
        if not 0<offset<len(item['text']):raise ValueError('Vị trí chia không hợp lệ')
        if not all(any(c.isalnum() for c in part) for part in (item['text'][:offset],item['text'][offset:])):raise ValueError('Cả hai đoạn phải có nội dung đọc được')
        with self.transaction():
            self.db.execute('UPDATE segments SET position=position+1 WHERE document_id=? AND position>?',(doc['id'],item['position']))
            self.db.execute('UPDATE segments SET text=?,revision=revision+1 WHERE id=?',(item['text'][:offset],id))
            self.db.execute('INSERT INTO segments(id,document_id,position,text,line_start,line_end) VALUES (?,?,?,?,?,?)',
                (str(uuid4()),doc['id'],item['position']+1,item['text'][offset:],item['line_start'],item['line_end']))

    def merge(self,ids):
        items=[self.segment(id) for id in ids];items.sort(key=lambda r:r['position'])
        if len(items)<2 or len({i['document_id'] for i in items})!=1:raise ValueError('Chọn ít nhất hai đoạn trong cùng tài liệu')
        doc=self.doc(items[0]['document_id'])
        if self.run(doc['run_id'])['state']!='draft':raise ValueError('Chỉ chia/gộp trước khi bắt đầu')
        if [i['position'] for i in items]!=list(range(items[0]['position'],items[-1]['position']+1)):raise ValueError('Chỉ gộp các đoạn liên tiếp')
        with self.transaction():
            self.db.execute('UPDATE segments SET text=?,line_end=?,revision=revision+1 WHERE id=?',(' '.join(i['text'] for i in items),items[-1]['line_end'],items[0]['id']))
            self.db.executemany('DELETE FROM segments WHERE id=?',[(i['id'],) for i in items[1:]])
            for n,row in enumerate(self.rows('SELECT id FROM segments WHERE document_id=? ORDER BY position',(doc['id'],)),1):
                self.db.execute('UPDATE segments SET position=? WHERE id=?',(n,row['id']))

    def claim(self,run,documents=None):
        with self.transaction():
            if self.run(run)['state']=='cancelled':return None
            if documents is not None and not documents:return None
            clause=' AND d.id IN ('+','.join('?' for _ in documents)+')' if documents is not None else ''
            row=self.db.execute("SELECT s.* FROM segments s JOIN documents d ON d.id=s.document_id WHERE d.run_id=? AND s.state='pending' AND s.skip=0"+clause+" ORDER BY d.position,s.position LIMIT 1",(run,*(documents or []))).fetchone()
            if row is None:return None
            item=dict(row);item['attempt']=str(uuid4())
            self.db.execute("UPDATE segments SET state='running',attempt=?,error='' WHERE id=?",(item['attempt'],item['id']))
            self.db.execute('UPDATE documents SET started=COALESCE(started,?),ended=NULL WHERE id=?',(time.time(),item['document_id']))
            return item

    def owns(self,item):
        current=self.segment(item['id'])
        return current is not None and self.run(self.doc(current['document_id'])['run_id'])['state']!='cancelled' and current['attempt']==item['attempt'] and current['revision']==item['revision'] and current['state']=='running'

    def status(self,run,state,error=''):
        with self.transaction():
            if self.run(run)['state']=='cancelled' and state!='cancelled':raise ValueError('Không thể tiếp tục lượt đã hủy')
            self.execute('UPDATE runs SET state=?,error=?,ended=? WHERE id=?',(state,error,time.time() if state in (*TERMINAL,'partial','stopped') else None,run))

    def cancel_run(self,run):
        repo=getattr(self,'automation',None)
        if repo and repo.tts_owner(run):raise ValueError('Dùng Dừng an toàn trong Automation; không hủy riêng checkpoint TTS.')
        with self.transaction():
            if self.run(run)['state'] in TERMINAL:return
            self.execute("UPDATE runs SET state='cancelled',ended=?,error='' WHERE id=?",(time.time(),run))
            self.execute("UPDATE segments SET state='cancelled',attempt=NULL,error='' WHERE state!='success' AND document_id IN (SELECT id FROM documents WHERE run_id=?)",(run,))

    def progress(self,run):
        return {r['state']:r['n'] for r in self.rows('SELECT s.state,COUNT(*) n FROM segments s JOIN documents d ON d.id=s.document_id WHERE d.run_id=? AND skip=0 GROUP BY s.state',(run,))}

    def document_stats(self,run):
        return self.rows("SELECT d.id,d.name,d.started,d.ended,COUNT(s.id) total,SUM(s.state='success') success,SUM(s.state='running') busy,SUM(s.state='pending') pending,SUM(s.state IN ('error','unknown')) errors FROM documents d LEFT JOIN segments s ON s.document_id=d.id AND s.skip=0 WHERE d.run_id=? GROUP BY d.id ORDER BY d.position",(run,))

    def delete_history(self,ids):
        repo=getattr(self,'automation',None)
        if repo and any(repo.tts_owner(id) for id in ids):raise ValueError('Lượt TTS thuộc Automation; quản lý metadata trong bộ công việc.')
        with self.transaction():
            for id in ids:
                if self.run(id)['state'] in ('running','pausing','stopping'):raise ValueError('Dừng tác vụ trước khi xóa lịch sử')
                self.db.execute('DELETE FROM runs WHERE id=?',(id,))

    def close(self):
        with self.lock:self.db.close()
