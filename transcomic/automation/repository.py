"""Automation metadata in the translation database; line text stays in lines."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

SCHEMA='''
CREATE TABLE IF NOT EXISTS automation_worksets(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,config TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'draft',
 started INTEGER NOT NULL DEFAULT 0,cycle INTEGER NOT NULL DEFAULT 0,owner_pid INTEGER,
 owner_started REAL,created REAL NOT NULL,checkpoint TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS automation_groups(
 id TEXT PRIMARY KEY,workset_id TEXT NOT NULL REFERENCES automation_worksets(id) ON DELETE CASCADE,
 document_id TEXT NOT NULL REFERENCES documents(id),position INTEGER NOT NULL,
 source_key TEXT NOT NULL,data TEXT NOT NULL DEFAULT '{}',UNIQUE(workset_id,source_key));
CREATE TABLE IF NOT EXISTS automation_events(
 id INTEGER PRIMARY KEY,workset_id TEXT NOT NULL REFERENCES automation_worksets(id) ON DELETE CASCADE,
 group_id TEXT,created REAL NOT NULL,stage TEXT NOT NULL,message TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS automation_group_fields(
 group_id TEXT NOT NULL REFERENCES automation_groups(id) ON DELETE CASCADE,
 field TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(group_id,field));
CREATE TABLE IF NOT EXISTS automation_artifacts(
 id TEXT PRIMARY KEY,workset_id TEXT NOT NULL REFERENCES automation_worksets(id) ON DELETE CASCADE,
 unit TEXT NOT NULL,kind TEXT NOT NULL,fingerprint TEXT NOT NULL,path TEXT NOT NULL,
 state TEXT NOT NULL,sha256 TEXT,created REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS automation_one_active ON automation_worksets((1)) WHERE state IN ('running','stopping');
'''
ACTIVE=('running','stopping')
IMMUTABLE=('voice','variant','speed','tts_language','device')
CONFIG_KEYS={'source_lang','target_lang','provider','model','workers','voice','speed','variant','tts_language','device','format','capcut_mode','part_count','project_name','part_names','output'}
LARGE_FIELDS={'images','slots','batch_jobs','wave_attempts','wave_attempt_history'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def source_key(path):return os.path.normcase(str(Path(path).resolve())).casefold()


class Repository:
    def __init__(self,store):
        self.store=store;self.listeners=[];self.group_listeners=[]
        with store.lock:store.db.executescript(SCHEMA)
        from ..documents import translatable
        store.db.create_function('automation_translatable',1,translatable,deterministic=True)
        # Separate immutable manifests from frequently changing stage state.
        # Idempotently preserve worksets saved by an earlier development snapshot.
        with store.transaction():
            for row in self.rows('SELECT id,data FROM automation_groups'):
                data=json.loads(row['data']);large={k:data.pop(k) for k in LARGE_FIELDS if k in data}
                for k,v in large.items():self.execute('INSERT OR IGNORE INTO automation_group_fields VALUES (?,?,?)',(row['id'],k,json.dumps(v,ensure_ascii=False)))
                if large:
                    data.setdefault('slot_count',len(large.get('slots',[])))
                    self.execute('UPDATE automation_groups SET data=? WHERE id=?',(json.dumps(data,ensure_ascii=False),row['id']))
        self.recover()
        store.automation=self

    def rows(self,sql,args=()):
        with self.store.lock:return [dict(r) for r in self.store.db.execute(sql,args)]
    def execute(self,sql,args=()):
        with self.store.lock:return self.store.db.execute(sql,args)
    def recover(self):
        import psutil
        for row in self.rows("SELECT * FROM automation_worksets WHERE state IN ('running','stopping')"):
            alive=False
            try:alive=abs(psutil.Process(row['owner_pid']).create_time()-row['owner_started'])<.1
            except (psutil.Error,TypeError):pass
            if not alive:self.execute("UPDATE automation_worksets SET state='interrupted',owner_pid=NULL,owner_started=NULL WHERE id=?",(row['id'],))
    def worksets(self):return [self.workset(r['id']) for r in self.rows('SELECT id FROM automation_worksets ORDER BY created DESC')]
    def workset_summaries(self):return self.rows('SELECT id,name,state FROM automation_worksets ORDER BY created DESC')
    def group_summaries(self,id):
        rows=self.rows('''SELECT g.id,g.workset_id,g.document_id,g.position,d.path,
            json_extract(g.data,'$.state') state,json_extract(g.data,'$.error') error,
            json_extract(g.data,'$.tts_run') tts_run,json_extract(g.data,'$.image_folder') image_folder,
            COALESCE(json_extract(g.data,'$.image_count'),json_array_length(g.data,'$.images'),0) image_count,
            COALESCE(json_extract(g.data,'$.slot_count'),json_array_length(g.data,'$.slots'),0) slot_count,json_extract(g.data,'$.project') project,
            json_extract(g.data,'$.audio_folder') audio_folder
            FROM automation_groups g JOIN documents d ON d.id=g.document_id WHERE g.workset_id=? ORDER BY g.position,g.id''',(id,))
        for row in rows:row['data']={key:row.pop(key) for key in ('state','error','tts_run','image_folder','image_count','slot_count','project','audio_folder')}
        return rows
    def workset(self,id):
        rows=self.rows('SELECT * FROM automation_worksets WHERE id=?',(id,))
        if not rows:raise KeyError(id)
        row=rows[0];row['config']=json.loads(row['config']);row['checkpoint']=json.loads(row['checkpoint']);return row
    def groups(self,id):
        values=self.rows('SELECT * FROM automation_groups WHERE workset_id=? ORDER BY position,id',(id,))
        for r in values:r['data']=self.enrich(r['id'],json.loads(r['data']))
        return values
    def group(self,id):
        row=self.rows('SELECT * FROM automation_groups WHERE id=?',(id,))[0];row['data']=self.enrich(id,json.loads(row['data']));return row
    def group_state(self,id):return json.loads(self.rows('SELECT data FROM automation_groups WHERE id=?',(id,))[0]['data'])
    def field(self,id,key,default=None):
        rows=self.rows('SELECT value FROM automation_group_fields WHERE group_id=? AND field=?',(id,key))
        return json.loads(rows[0]['value']) if rows else self.group_state(id).get(key,default)
    def batch_ids(self,entries):
        result=[]
        for entry in entries:
            rows=self.rows('SELECT id FROM batches WHERE id=? OR job_id=?',(entry,entry))
            if not rows:raise ValueError('Thiếu checkpoint batch; không tự gửi lại khi chưa rõ lineage.')
            result.extend(r['id'] for r in rows)
        return list(dict.fromkeys(result))
    def enrich(self,id,data):
        for row in self.rows('SELECT field,value FROM automation_group_fields WHERE group_id=?',(id,)):data[row['field']]=json.loads(row['value'])
        for key in LARGE_FIELDS:data.setdefault(key,[] if key in ('images','slots') else {})
        return data
    def active(self):
        rows=self.rows("SELECT id FROM automation_worksets WHERE state IN ('running','stopping')")
        return rows[0]['id'] if rows else None
    def editable(self,id):
        if self.workset(id)['state'] in ACTIVE:raise ValueError('Cấu hình đã khóa. Dừng an toàn để chỉnh sửa.')
    def create(self,name,config):
        if set(config)!=CONFIG_KEYS:raise ValueError('Cấu hình Automation chỉ chứa các trường được hỗ trợ; không lưu API key/token.')
        id=str(uuid.uuid4());self.execute('INSERT INTO automation_worksets(id,name,config,created) VALUES (?,?,?,?)',(id,name.strip() or 'Bộ truyện',json.dumps(config),time.time()));return id
    def configure(self,id,config,name=None):
        if set(config)!=CONFIG_KEYS:raise ValueError('Cấu hình Automation không hợp lệ; không lưu API key/token.')
        with self.store.transaction():
            self.editable(id);old=self.workset(id)
            if old['started'] and any(config.get(k)!=old['config'].get(k) for k in IMMUTABLE):raise ValueError('Voice/model/speed/runtime đã cố định; hãy tạo bộ mới.')
            if old['started'] and any(config.get(k)!=old['config'].get(k) for k in ('source_lang','target_lang','provider','model')):
                raise ValueError('Ngôn ngữ và provider/model của bộ đã chạy được giữ nguyên; hãy tạo bộ mới.')
            self.execute('UPDATE automation_worksets SET name=?,config=? WHERE id=?',(name or old['name'],json.dumps(config),id))
    def add(self,id,paths):
        from ..bulk import natural_key
        from ..documents import import_txt,ImportedText,TextLine
        from ..docx_document import import_docx
        self.editable(id);cfg=self.workset(id)['config'];added=[]
        for path in sorted((Path(p).resolve() for p in paths),key=lambda p:natural_key(p.name)):
            if not path.is_file() or path.suffix.lower() not in ('.docx','.txt'):raise ValueError('Chỉ nhận file DOCX/TXT; không quét thư mục tài liệu.')
            key=source_key(path)
            if self.rows('SELECT id FROM automation_groups WHERE workset_id=? AND source_key=?',(id,key)):continue
            obj=import_docx(path) if path.suffix.lower()=='.docx' else None
            data=ImportedText(tuple(TextLine(u.text,'') for u in obj.units),'docx',obj.raw) if obj else import_txt(path)
            group=str(uuid.uuid4())
            with self.store.transaction():
                self.editable(id)
                doc,_=self.store.import_document(path,data,cfg['source_lang'],cfg['target_lang'],'docx' if obj else 'txt',[u.locator for u in obj.units] if obj else None)
                meta={'source_sha256':hashlib.sha256(data.raw).hexdigest(),'image_folder':'','image_sort':'name','images':[], 'state':'draft','error':'','batch_jobs':{},'tts_run':None,'slots':[]}
                self.execute('INSERT INTO automation_groups VALUES (?,?,?,?,?,?)',(group,id,doc,len(self.groups(id)),key,json.dumps(meta)))
            added.append(group)
        with self.store.transaction():
            self.editable(id)
            if not self.workset(id)['checkpoint'].get('manual_order'):
                ordered=sorted(self.groups(id),key=lambda g:natural_key(Path(self.store.document(g['document_id'])['path']).name))
                for n,g in enumerate(ordered):self.execute('UPDATE automation_groups SET position=? WHERE id=?',(n,g['id']))
        return added
    def update_group(self,id,**changes):
        with self.store.transaction():
            data=self.group_state(id)
            for key in LARGE_FIELDS&changes.keys():
                value=changes.pop(key);self.execute('INSERT OR REPLACE INTO automation_group_fields VALUES (?,?,?)',(id,key,json.dumps(value,ensure_ascii=False)))
                data.pop(key,None)
                if key=='slots':changes['slot_count']=len(value)
            data.update(changes);self.execute('UPDATE automation_groups SET data=? WHERE id=?',(json.dumps(data,ensure_ascii=False),id))
        self.progress(id)
    def progress(self,id):
        for callback in self.group_listeners:callback(id)
    def pair_images(self,id,folder,sort='name'):
        if sort not in ('name','created'):raise ValueError('Cách sắp ảnh không hợp lệ')
        with self.store.transaction():
            group=self.group(id);self.editable(group['workset_id'])
            self.update_group(id,image_folder=str(Path(folder).resolve()),image_sort=sort,images=[],state='draft',error='')
    def move(self,id,delta):
        with self.store.transaction():
            group=self.group(id)
            self.editable(group['workset_id'])
            groups=self.groups(group['workset_id']);i=next(i for i,g in enumerate(groups) if g['id']==id);j=i+delta
            if not 0<=j<len(groups):return
            groups[i],groups[j]=groups[j],groups[i]
            for n,g in enumerate(groups):self.execute('UPDATE automation_groups SET position=? WHERE id=?',(n,g['id']))
            data=self.workset(group['workset_id'])['checkpoint'];data['manual_order']=True
            self.execute('UPDATE automation_worksets SET checkpoint=? WHERE id=?',(json.dumps(data),group['workset_id']))
    def remove_group(self,id):
        with self.store.transaction():
            self.editable(self.group(id)['workset_id']);self.execute('DELETE FROM automation_groups WHERE id=?',(id,))
    def delete(self,id):
        with self.store.transaction():self.editable(id);self.execute('DELETE FROM automation_worksets WHERE id=?',(id,))
    def activate(self,id):
        import psutil
        with self.store.transaction():
            self.editable(id)
            if self.active():raise ValueError('Một bộ Tự động hóa khác đang chạy.')
            self.execute("UPDATE automation_worksets SET state='running',started=1,cycle=cycle+1,owner_pid=?,owner_started=? WHERE id=?",(os.getpid(),psutil.Process().create_time(),id))
    def state(self,id,state):
        self.execute('UPDATE automation_worksets SET state=?,owner_pid=CASE WHEN ? IN (\'running\',\'stopping\') THEN owner_pid ELSE NULL END WHERE id=?',(state,state,id))
    def event(self,id,group,stage,message):
        # Never accept credentials/configuration objects into durable logs.
        self.execute('INSERT INTO automation_events(workset_id,group_id,created,stage,message) VALUES (?,?,?,?,?)',(id,group,time.time(),stage,self.store.log.clean(str(message))))
    def events(self,id):return self.rows('SELECT * FROM automation_events WHERE workset_id=? ORDER BY id DESC LIMIT 500',(id,))
    def artifact(self,id,unit,kind,fp,path):
        aid=str(uuid.uuid4());self.execute('INSERT INTO automation_artifacts VALUES (?,?,?,?,?,?,?,?,?)',(aid,id,unit,kind,fp,str(path),'intent',None,time.time()));return aid
    def artifacts(self,id):return self.rows('SELECT * FROM automation_artifacts WHERE workset_id=? ORDER BY created',(id,))
    def complete_artifact(self,id,digest):self.execute("UPDATE automation_artifacts SET state='complete',sha256=? WHERE id=?",(digest,id))
    def line_owner(self,line_id):
        rows=self.rows('SELECT g.id,g.workset_id,w.state FROM automation_groups g JOIN lines l ON l.document_id=g.document_id JOIN automation_worksets w ON w.id=g.workset_id WHERE l.id=?',(line_id,))
        return rows[0] if rows else None
    def assert_editable_line(self,line_id):
        owner=self.line_owner(line_id)
        if owner and owner['state'] in ACTIVE:raise ValueError('Nhóm thuộc Automation đang chạy; dừng an toàn trước khi sửa.')
    def line_edited(self,line_id):
        owner=self.line_owner(line_id)
        if not owner:return
        group=self.group(owner['id']);meta=group['data'];tts=getattr(self,'tts_store',None)
        if tts and meta.get('tts_run') and line_id in meta.get('slots',[]):
            from .validation import speakable
            from ..tts.documents import segments
            line=self.store.line(line_id);text=line['translation'] if line['translation'] is not None else line['source'];items=tts.items(meta['tts_run'])
            position=meta['slots'].index(line_id)
            if position<len(items):
                if speakable(text) and segments(text,'none')[0]['text']==items[position]['text'] and line['state']=='done':return
                tts.execute("UPDATE segments SET state='stale' WHERE id=?",(items[position]['id'],))
        self.update_group(owner['id'],state='stale',error='Bản dịch đã sửa; cần kiểm tra voice/project.')
        for callback in self.listeners:callback(owner['workset_id'],line_id)
    def tts_owner(self,run):
        for row in self.rows('SELECT id,workset_id,data FROM automation_groups'):
            if json.loads(row['data']).get('tts_run')==run:return row
        return None
