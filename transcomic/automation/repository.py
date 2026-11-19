"""Automation metadata in the translation database; line text stays in lines."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
import threading

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
'''
ACTIVE=('running','stopping')
IMMUTABLE=('voice','variant','speed','tts_language','device')
CONFIG_KEYS={'source_lang','target_lang','provider','model','workers','voice','speed','variant','tts_language','device','format','capcut_mode','part_count','project_name','part_names','output'}
CONFIG_KEYS.add('deepseek_batch_size')
CONFIG_KEYS.add('kira_recovery_version')
CONFIG_KEYS.update(('kira_completion_policy','kira_dispatch_policy'))
CONFIG_KEYS.add('translation_completion_policy')
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
        from .session import initialize
        self.session_id=initialize(store);self.session_closing=threading.Event();self.session_closed=False
        self.cleanup=None;self.stale_cleanup=None
        self.unfinished_worksets=set()
        self._folder_drafts={}
        self._folder_lock=threading.Lock()
        store.automation=self

    def rows(self,sql,args=()):
        with self.store.lock:return [dict(r) for r in self.store.db.execute(sql,args)]
    def execute(self,sql,args=()):
        with self.store.lock:return self.store.db.execute(sql,args)
    def recover(self):
        # Compatibility entry point: prior sessions are never resumable.
        return None
    def start_stale_cleanup(self):
        from .session import Cleanup
        if not self.stale_cleanup:self.stale_cleanup=Cleanup(self,self.tts_store.path).start()
        return self.stale_cleanup
    def begin_close(self):
        self.session_closing.set()
    def discard_session(self):
        """Call only after all session workers have released database/output leases."""
        from .session import Cleanup
        self.begin_close()
        if not self.cleanup:
            self.cleanup=Cleanup(self,self.tts_store.path,current=True).start()
        return self.cleanup
    def require_open(self):
        if self.session_closing.is_set():raise ValueError('Phiên Tự động hóa đã đóng; không nhận thêm công việc.')
    def owns(self,id):
        return bool(self.rows('SELECT 1 FROM automation_worksets WHERE id=? AND session_id=?',(id,self.session_id)))
    def archive(self,id):
        from .session import archive
        with self.store.transaction():self.workset(id);archive(self.store.db,id)
    def completed_history(self):return self.rows('SELECT * FROM automation_history ORDER BY created DESC')
    def register_staging(self,path,root,kind):
        from .session import path_identity
        path=Path(path).resolve();root=Path(root).resolve()
        if path_identity(path.parent)!=path_identity(root) or kind not in ('audio-part','capcut-stage'):raise ValueError('Staging không thuộc phiên.')
        self.execute('INSERT INTO automation_staging VALUES (?,?,?,?)',(self.session_id,str(path),str(root),kind))
    def unregister_staging(self,path):
        self.execute('DELETE FROM automation_staging WHERE session_id=? AND path=?',(self.session_id,str(Path(path).resolve())))
    def worksets(self):return [self.workset(r['id']) for r in self.workset_summaries()]
    def workset_summaries(self):return self.rows('SELECT id,name,state FROM automation_worksets WHERE session_id=? ORDER BY created DESC',(self.session_id,))
    def group_summaries(self,id):
        self.workset(id)
        rows=self.rows('''SELECT g.id,g.workset_id,g.document_id,g.position,d.path,
            json_extract(g.data,'$.state') state,json_extract(g.data,'$.error') error,
            json_extract(g.data,'$.tts_run') tts_run,json_extract(g.data,'$.image_folder') image_folder,
            COALESCE(json_extract(g.data,'$.image_word_count'),0) image_word_count,
            COALESCE(json_extract(g.data,'$.image_count'),json_array_length(g.data,'$.images'),0) image_count,
            COALESCE(json_extract(g.data,'$.slot_count'),json_array_length(g.data,'$.slots'),0) slot_count,json_extract(g.data,'$.project') project,
            json_extract(g.data,'$.audio_folder') audio_folder,
            json_extract(g.data,'$.translation_recovery_state') translation_recovery_state,
            json_extract(g.data,'$.translation_recovery_reason') translation_recovery_reason,
            json_extract(g.data,'$.next_retry_at') next_retry_at
            FROM automation_groups g JOIN documents d ON d.id=g.document_id WHERE g.workset_id=? ORDER BY g.position,g.id''',(id,))
        for row in rows:row['data']={key:row.pop(key) for key in ('state','error','tts_run','image_folder','image_word_count','image_count','slot_count','project','audio_folder','translation_recovery_state','translation_recovery_reason','next_retry_at')}
        return rows
    def workset(self,id):
        rows=self.rows('SELECT * FROM automation_worksets WHERE id=? AND session_id=?',(id,self.session_id))
        if not rows:raise KeyError(id)
        row=rows[0];row['config']=json.loads(row['config']);row['config'].setdefault('deepseek_batch_size',3);row['checkpoint']=json.loads(row['checkpoint']);return row
    def groups(self,id):
        self.workset(id)
        values=self.rows('SELECT * FROM automation_groups WHERE workset_id=? ORDER BY position,id',(id,))
        fields={r['id']:{} for r in values}
        for r in self.rows('SELECT f.group_id,f.field,f.value FROM automation_group_fields f JOIN automation_groups g ON g.id=f.group_id WHERE g.workset_id=?',(id,)):
            fields[r['group_id']][r['field']]=json.loads(r['value'])
        for r in values:
            r['data']={**json.loads(r['data']),**fields[r['id']]}
            for key in LARGE_FIELDS:r['data'].setdefault(key,[] if key in ('images','slots') else {})
        return values
    def group(self,id):
        row=self.rows('SELECT g.* FROM automation_groups g JOIN automation_worksets w ON w.id=g.workset_id WHERE g.id=? AND w.session_id=?',(id,self.session_id))[0];row['data']=self.enrich(id,json.loads(row['data']));return row
    def group_state(self,id):
        rows=self.rows('SELECT g.data FROM automation_groups g JOIN automation_worksets w ON w.id=g.workset_id WHERE g.id=? AND w.session_id=?',(id,self.session_id))
        if not rows:raise KeyError(id)
        return json.loads(rows[0]['data'])
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
        rows=self.rows("SELECT id FROM automation_worksets WHERE session_id=? AND state IN ('running','stopping')",(self.session_id,))
        return rows[0]['id'] if rows else None
    def editable(self,id):
        self.require_open()
        if self.workset(id)['state'] in ACTIVE:raise ValueError('Cấu hình đã khóa. Dừng an toàn để chỉnh sửa.')
    def create(self,name,config):
        self.require_open()
        config={'deepseek_batch_size':3,'kira_recovery_version':4,'kira_completion_policy':0,'kira_dispatch_policy':0,'translation_completion_policy':0,**config}
        if set(config)!=CONFIG_KEYS:raise ValueError('Cấu hình Automation chỉ chứa các trường được hỗ trợ; không lưu API key/token.')
        # Creation-only, provider-scoped metadata. A new workset may select DeepSeek
        # later; old rows (including draft rows) are deliberately never backfilled.
        from ..deepseek_rolling import ROLLING
        checkpoint={'deepseek_admission_policy':dict(ROLLING)}
        id=str(uuid.uuid4());self.execute('INSERT INTO automation_worksets(id,name,config,created,checkpoint,session_id) VALUES (?,?,?,?,?,?)',(id,name.strip() or 'Bộ truyện',json.dumps(config),time.time(),json.dumps(checkpoint),self.session_id));self.unfinished_worksets.add(id);return id
    def configure(self,id,config,name=None):
        config={'deepseek_batch_size':3,'kira_recovery_version':self.workset(id)['config'].get('kira_recovery_version',2),'kira_completion_policy':0,'kira_dispatch_policy':0,'translation_completion_policy':0,**config}
        if set(config)!=CONFIG_KEYS:raise ValueError('Cấu hình Automation không hợp lệ; không lưu API key/token.')
        with self.store.transaction():
            self.editable(id);old=self.workset(id)
            if old['started'] and config['kira_recovery_version']!=old['config'].get('kira_recovery_version',2):
                raise ValueError('Giữ policy phục hồi đã chốt cho bộ công việc đã bắt đầu.')
            if old['started'] and any(config.get(k,0)!=old['config'].get(k,0) for k in ('kira_completion_policy','kira_dispatch_policy','translation_completion_policy')):
                raise ValueError('Giữ policy điều phối/phục hồi đã chốt; hãy tạo bộ mới.')
            if old['started'] and config['provider']=='deepseek' and config['deepseek_batch_size']!=old['config'].get('deepseek_batch_size',3):
                raise ValueError('Batch DeepSeek của bộ đã chạy được giữ nguyên; hãy tạo bộ mới.')
            if old['started'] and any(config.get(k)!=old['config'].get(k) for k in IMMUTABLE):raise ValueError('Voice/model/speed/runtime đã cố định; hãy tạo bộ mới.')
            if old['started'] and any(config.get(k)!=old['config'].get(k) for k in ('source_lang','target_lang','provider','model')):
                raise ValueError('Ngôn ngữ và provider/model của bộ đã chạy được giữ nguyên; hãy tạo bộ mới.')
            self.execute('UPDATE automation_worksets SET name=?,config=? WHERE id=?',(name or old['name'],json.dumps(config),id))
    def folder_drafts(self,workset):
        with self._folder_lock:return tuple(d for d in self._folder_drafts.values() if d.workset==workset)

    def folder_draft(self,id):
        with self._folder_lock:return self._folder_drafts.get(id)

    def has_pending_folders(self,workset):
        return any(d.state!='folder_scan_cancelled' for d in self.folder_drafts(workset))

    def reserve_folder(self,workset,path):
        from .folder_inputs import FolderDraft
        path=Path(path).resolve()
        with self.store.lock:
            self.editable(workset)
            if any(d.path==path for d in self.folder_drafts(workset)):return None
            linked=self.rows("""SELECT json_extract(data,'$.image_folder') folder,
                json_extract(data,'$.origin_folder') origin FROM automation_groups WHERE workset_id=?""",(workset,))
            if any(Path(row[k])==path for row in linked for k in ('folder','origin') if row[k]):return None
            draft=FolderDraft(workset,path)
            with self._folder_lock:self._folder_drafts[draft.id]=draft
            return draft

    def finish_folder(self,draft):
        with self._folder_lock:
            if self._folder_drafts.get(draft.id) is draft:
                del self._folder_drafts[draft.id]

    def add(self,id,paths,*,cancelled=None,auto_images=False,folder=None):
        from ..bulk import natural_key
        from ..documents import import_txt,ImportedText,TextLine
        from ..docx_document import import_docx
        self.editable(id);cfg=self.workset(id)['config'];added=[]
        for path in sorted((Path(p).resolve() for p in paths),key=lambda p:natural_key(p.name)):
            from .validation import check_current
            check_current(cancelled)
            if not path.is_file() or path.suffix.lower() not in ('.docx','.txt'):raise ValueError('Chỉ nhận file DOCX/TXT; không quét thư mục tài liệu.')
            key=source_key(path)
            if self.rows('SELECT id FROM automation_groups WHERE workset_id=? AND source_key=?',(id,key)):continue
            obj=import_docx(path) if path.suffix.lower()=='.docx' else None
            data=ImportedText(tuple(TextLine(u.text,'') for u in obj.units),'docx',obj.raw) if obj else import_txt(path)
            draft,inspection=folder if folder else (None,None)
            image_root=draft.path if draft else path.parent
            image_error=''
            if obj and (auto_images or draft):
                from .folder_inputs import scan_folder
                from .validation import image_stamp
                try:
                    if inspection is None or inspection.stamp!=image_stamp(image_root,cancelled):
                        inspection=scan_folder(image_root,cancelled=cancelled,inspection=True)
                except (OSError,ValueError) as exc:
                    if draft:raise
                    image_error=str(exc)
            group=draft.id if draft else str(uuid.uuid4())
            from .validation import input_stamp,speakable
            slot_positions=[i for i,line in enumerate(data.lines) if speakable(line.text)] if obj and (auto_images or draft) else []
            with self.store.transaction():
                check_current(cancelled)
                self.editable(id)
                if self.rows('SELECT id FROM automation_groups WHERE workset_id=? AND source_key=?',(id,key)):continue
                if draft and (draft.cancelled.is_set() or self.folder_draft(draft.id) is not draft):continue
                doc,_=self.store.import_document(path,data,cfg['source_lang'],cfg['target_lang'],'docx' if obj else 'txt',[u.locator for u in obj.units] if obj else None)
                meta={'source_sha256':hashlib.sha256(data.raw).hexdigest(),'image_folder':'','image_sort':'name','images':[], 'state':'draft','error':'','batch_jobs':{},'tts_run':None,'slots':[]}
                position=self.rows('SELECT COALESCE(MAX(position)+1,0) next FROM automation_groups WHERE workset_id=?',(id,))[0]['next']
                if obj and (auto_images or draft):
                    meta.update(folder_import=True,slot_count=len(slot_positions),error=image_error)
                    if draft:meta['origin_folder']=str(image_root)
                    if inspection:
                        meta['image_word_count']=len(inspection.words)
                        meta['image_count']=len(inspection.images)
                        meta['error']=inspection.error
                        if inspection.images or inspection.error:
                            meta['image_folder']=str(image_root)
                        if meta['image_folder']:
                            rows=self.store.lines(doc)
                            stamp=input_stamp(dict(data=meta),path,rows,images=inspection.stamp)
                            meta['image_inspection']=dict(version=1,stamp=stamp,error=inspection.error)
                check_current(cancelled)
                self.execute('INSERT INTO automation_groups VALUES (?,?,?,?,?,?)',(group,id,doc,position,key,json.dumps(meta)))
                if inspection and meta['image_folder']:
                    self.update_group(group,images=inspection.manifest,slots=[rows[i]['id'] for i in slot_positions])
                if draft:check_current(cancelled)
            added.append(group)
        with self.store.transaction():
            if folder:check_current(cancelled)
            self.editable(id)
            if not self.workset(id)['checkpoint'].get('manual_order'):
                ordered=sorted(self.rows('SELECT g.id,d.path FROM automation_groups g JOIN documents d ON d.id=g.document_id WHERE g.workset_id=? ORDER BY g.position,g.id',(id,)),key=lambda g:natural_key(Path(g['path']).name))
                for n,g in enumerate(ordered):self.execute('UPDATE automation_groups SET position=? WHERE id=?',(n,g['id']))
        return added
    def update_group(self,id,**changes):
        if changes.get('state') and changes['state']!='completed':
            rows=self.rows('SELECT workset_id FROM automation_groups WHERE id=?',(id,))
            if rows:self.unfinished_worksets.add(rows[0]['workset_id'])
        if not (LARGE_FIELDS&changes.keys()):
            with self.store.lock:
                current=self.group_state(id)
                if all(current.get(k)==v for k,v in changes.items()):return
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
    def pair_images(self,id,folder,sort='name',*,inspection=None):
        if sort not in ('name','created'):raise ValueError('Cách sắp ảnh không hợp lệ')
        with self.store.transaction():
            group=self.group(id);self.editable(group['workset_id'])
            changes=dict(image_folder=str(Path(folder).resolve()),image_sort=sort,images=[],input_validation={},image_inspection={},state='draft',error='',image_word_count=0)
            if inspection:
                changes.update(images=inspection['images'],image_count=len(inspection['images']),slots=inspection['slots'],image_inspection=dict(version=1,stamp=inspection['stamp']),image_word_count=inspection.get('word_count',0))
            self.update_group(id,**changes)
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
    def remove_group(self,id,*,keep_folder=False):
        draft=self.folder_draft(id)
        if draft:
            draft.cancelled.set()
        with self.store.transaction():
            if draft:
                self.editable(draft.workset)
                if not keep_folder:self.finish_folder(draft)
                self.execute('DELETE FROM automation_groups WHERE id=? AND workset_id=?',(id,draft.workset))
            else:
                self.editable(self.group(id)['workset_id'])
                self.execute('DELETE FROM automation_groups WHERE id=?',(id,))
    def delete(self,id):
        with self.store.transaction():
            self.editable(id)
            unlinked={row['document_id'] for row in self.rows('''
                SELECT g.document_id FROM automation_groups g WHERE g.workset_id=?
                AND NOT EXISTS (
                    SELECT 1 FROM automation_groups other JOIN automation_worksets w ON w.id=other.workset_id
                    WHERE other.document_id=g.document_id AND w.session_id=? AND w.id!=g.workset_id
                )''',(id,self.session_id))}
            for draft in self.folder_drafts(id):
                draft.cancelled.set()
                self.finish_folder(draft)
            self.execute('DELETE FROM automation_worksets WHERE id=?',(id,))
        self.unfinished_worksets.discard(id)
        return unlinked
    def activate(self,id):
        import psutil
        with self.store.transaction():
            self.editable(id)
            if self.active():raise ValueError('Một bộ Tự động hóa khác đang chạy.')
            # Keep the existing cross-process single-workset resource guard.
            # Dead checkpoints do not count; a different live instance does.
            for owner in self.rows("SELECT owner_pid,owner_started FROM automation_worksets WHERE session_id!=? AND state IN ('running','stopping')",(self.session_id,)):
                alive=False
                try:alive=abs(psutil.Process(owner['owner_pid']).create_time()-owner['owner_started'])<.1
                except psutil.AccessDenied:alive=True
                except (psutil.Error,TypeError,ValueError):pass
                if alive:raise ValueError('Một bộ Tự động hóa khác đang chạy.')
            self.execute("UPDATE automation_worksets SET state='running',started=1,cycle=cycle+1,owner_pid=?,owner_started=? WHERE id=?",(os.getpid(),psutil.Process().create_time(),id))
        self.unfinished_worksets.add(id)
    def state(self,id,state):
        self.execute('UPDATE automation_worksets SET state=?,owner_pid=CASE WHEN ? IN (\'running\',\'stopping\') THEN owner_pid ELSE NULL END WHERE id=?',(state,state,id))
        if state=='completed':self.unfinished_worksets.discard(id)
        else:self.unfinished_worksets.add(id)
    def event(self,id,group,stage,message):
        # Never accept credentials/configuration objects into durable logs.
        self.execute('INSERT INTO automation_events(workset_id,group_id,created,stage,message) VALUES (?,?,?,?,?)',(id,group,time.time(),stage,self.store.log.clean(str(message))))
    def events(self,id):return self.rows('SELECT * FROM automation_events WHERE workset_id=? ORDER BY id DESC LIMIT 500',(id,))
    def artifact(self,id,unit,kind,fp,path):
        aid=str(uuid.uuid4());self.execute('INSERT INTO automation_artifacts VALUES (?,?,?,?,?,?,?,?,?)',(aid,id,unit,kind,fp,str(path),'intent',None,time.time()));return aid
    def artifacts(self,id):return self.rows('SELECT * FROM automation_artifacts WHERE workset_id=? ORDER BY created',(id,))
    def complete_artifact(self,id,digest):self.execute("UPDATE automation_artifacts SET state='complete',sha256=? WHERE id=?",(digest,id))
    def line_owner(self,line_id):
        rows=self.rows('SELECT g.id,g.workset_id,w.state FROM automation_groups g JOIN lines l ON l.document_id=g.document_id JOIN automation_worksets w ON w.id=g.workset_id WHERE l.id=? AND w.session_id=?',(line_id,self.session_id))
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
        # Also protect stale TTS runs while asynchronous retirement is pending.
        rows=self.rows("SELECT g.id,g.workset_id,g.data FROM automation_groups g WHERE json_extract(g.data,'$.tts_run')=? LIMIT 1",(run,))
        return rows[0] if rows else None
