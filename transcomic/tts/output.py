"""Owned output directories, durable manifests, attempt fencing and recovery.

Filesystem commits precede DB commits. The manifest is the recovery authority
only when run/document/segment/revision and the decoded file hash all agree.
"""
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4
from .audio import validate
from .models import digest

MANIFEST='.transcomic-tts.json'


def safe_path(path):
    path=Path(os.path.abspath(path))
    for part in (path,*path.parents):
        if part.exists() or part.is_symlink():
            stat=part.lstat()
            if part.is_symlink() or getattr(stat,'st_file_attributes',0)&0x400:
                raise ValueError('Không dùng symlink/junction/reparse point: '+str(part))
    return path


def base_name(value):
    value=value.strip()
    if not value or value in ('.','..') or len(value)>100 or value[-1] in ' .' or re.search(r'[<>:"/\\|?*\x00-\x1f]',value):
        raise ValueError('Tên thư mục không hợp lệ')
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',value,re.I):raise ValueError('Tên Windows được dành riêng')
    return value


def atomic_json(path,data):
    path=safe_path(path);part=path.with_name(path.name+'.'+str(uuid4())+'.part')
    with part.open('x',encoding='utf8') as stream:
        json.dump(data,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
    os.replace(part,path)


class Outputs:
    def __init__(self,store):self.store=store

    def owned(self,folder,doc):
        try:
            _,data=self.manifest(dict(doc,folder=str(folder)))
            known={i['id'] for i in self.store.rows('SELECT id FROM segments WHERE document_id=?',(doc['id'],))}
            return isinstance(data.get('segments'),dict) and set(data['segments']).issubset(known)
        except (OSError,ValueError,TypeError):return False

    def plan(self,run,mode,root,format):
        if mode not in ('custom','beside','last') or format not in ('wav','mp3'):raise ValueError('Lựa chọn xuất không hợp lệ')
        plans=[];used=set()
        for doc in self.store.docs(run):
            if doc['folder']:
                folder,_=self.manifest(doc);used.add(os.path.normcase(str(folder.parent/doc['base'])));continue
            parent=safe_path(Path(doc['path']).parent if mode=='beside' and doc['path'] else root or '')
            if mode=='beside' and not doc['path']:raise ValueError('Văn bản dán cần thư mục xuất cụ thể')
            if mode!='beside' and not root:raise ValueError('Chọn thư mục xuất cụ thể')
            if not parent.is_dir():raise FileNotFoundError('Thư mục xuất không tồn tại: '+str(parent))
            count=self.store.one('SELECT COUNT(*) n FROM segments WHERE document_id=? AND skip=0',(doc['id'],))['n']
            if not count:continue
            base=base_name(doc['base']);candidate=base;index=2
            while True:
                folder=safe_path(parent/(candidate+'_TTS_inprogress'));final=safe_path(parent/(candidate+f'_{count}tts'))
                if os.path.normcase(str(parent/candidate)) not in used:
                    if folder.exists() and self.owned(folder,doc):break
                    if final.exists() and self.owned(final,doc):folder=final;break
                    if not folder.exists() and not final.exists():break
                candidate=f'{base}_{index}';index+=1
            used.add(os.path.normcase(str(parent/candidate)))
            probe=parent/('.tts-write-probe-'+str(uuid4()))
            try:
                with probe.open('xb') as stream:stream.write(b'TTS');stream.flush();os.fsync(stream.fileno())
            finally:
                if probe.exists():probe.unlink()
            plans.append(dict(id=doc['id'],parent=str(parent),folder=str(folder),base=candidate,count=count,format=format))
        if not plans and not any(d['folder'] for d in self.store.docs(run)):raise ValueError('Không có đoạn hợp lệ để tạo âm thanh')
        return plans

    def confirm(self,run,config,plans):
        state=self.store.run(run)['state']
        if state in ('running','pausing','stopping','completed','cancelled'):raise ValueError('Lượt đang chạy hoặc đã kết thúc; tạo lượt mới')
        saved=json.loads(self.store.run(run)['config'])
        docs={d['id']:d for d in self.store.docs(run)}
        if any(d['folder'] for d in docs.values()):
            if saved!=config:raise ValueError('Giữ cấu hình đã lưu khi tiếp tục lượt cũ')
            for doc in docs.values():
                if doc['folder']:self.manifest(doc)
        if len({p['id'] for p in plans})!=len(plans) or any(p['id'] not in docs or docs[p['id']]['folder'] for p in plans):raise ValueError('Kế hoạch xuất không thuộc tài liệu chưa được cấp thư mục')
        # Persist the snapshot before filesystem allocation. If a later folder
        # fails, Resume can finish allocation without reassigning existing audio.
        self.store.execute("UPDATE runs SET state='paused',config=? WHERE id=?",(json.dumps(config),run))
        # Recheck collisions immediately before reserving. Never merge existing folders.
        for plan in plans:
            folder=safe_path(plan['folder']);doc=docs[plan['id']];base=plan['base'];index=2
            while True:
                try:
                    folder.mkdir(exist_ok=False);atomic_json(folder/MANIFEST,dict(run=run,document=plan['id'],segments={}));break
                except FileExistsError:
                    if self.owned(folder,doc):break
                    # Another job may reserve a folder after planning. Allocate
                    # another name atomically; never delete/merge that folder.
                    candidate=base_name(base+f'_{index}');index+=1
                    if safe_path(folder.parent/(candidate+f'_{plan["count"]}tts')).exists():continue
                    folder=safe_path(folder.parent/(candidate+'_TTS_inprogress'));plan['base']=candidate
            with self.store.transaction():
                self.store.execute('UPDATE documents SET folder=?,base=? WHERE id=?',(str(folder),plan['base'],plan['id']))
                items=self.store.rows('SELECT id,position FROM segments WHERE document_id=?',(plan['id'],))
                width=max(4,len(str(max((i['position'] for i in items),default=0))))
                for item in items:self.store.execute('UPDATE segments SET filename=? WHERE id=?',(f'{item["position"]:0{width}d}.'+config['format'],item['id']))
        self.store.execute("UPDATE runs SET state='ready',config=? WHERE id=?",(json.dumps(config),run))

    def manifest(self,doc):
        folder=safe_path(doc['folder'])
        if not folder.is_dir():raise FileNotFoundError('Mất thư mục xuất; hãy kết nối ổ hoặc liên kết lại: '+str(folder))
        data=json.loads((folder/MANIFEST).read_text(encoding='utf8'))
        if data.get('run')!=doc['run_id'] or data.get('document')!=doc['id']:raise ValueError('Thư mục thuộc tác vụ khác')
        return folder,data

    def commit(self,item,temp,info,backend):
        with self.store.transaction():
            if not self.store.owns(item):return False
            doc=self.store.doc(item['document_id']);folder,data=self.manifest(doc)
            current=self.store.segment(item['id']);target=safe_path(folder/current['filename'])
            if safe_path(temp).parent!=folder:raise ValueError('File tạm không cùng thư mục đích')
            previous=data['segments'].get(item['id'])
            if target.exists():
                if not current['overwrite_allowed'] or not previous or previous['filename']!=target.name or digest(target)!=previous['sha256']:
                    raise FileExistsError('Chưa cho phép thay thế audio hoặc file đã bị thay đổi')
            # Intent includes new hash so a crash after replace can be reconciled.
            record=dict(info,filename=target.name,revision=item['revision'],attempt=item['attempt'],backend=backend)
            if previous:record['previous']=previous
            data['segments'][item['id']]=record
            atomic_json(folder/MANIFEST,data)
            os.replace(temp,target)
            record.pop('previous',None)
            atomic_json(folder/MANIFEST,data)
            self.store.execute("UPDATE segments SET state='success',sha256=?,duration=?,rate=?,backend=?,error='',overwrite_allowed=0 WHERE id=?",
                (info['sha256'],info['duration'],info['rate'],backend,item['id']))
            return True

    def reconcile(self,run):
        # Never schedule unknown output before examining its manifest and file.
        for doc in self.store.docs(run):
            if not doc['folder']:continue
            if doc['rename_intent']:
                intent=json.loads(doc['rename_intent'])
                for candidate in (intent['new'],intent['old']):
                    if Path(candidate).is_dir():
                        check=dict(doc,folder=candidate);self.manifest(check)
                        self.store.execute('UPDATE documents SET folder=?,rename_intent=NULL WHERE id=?',(candidate,doc['id']));doc=self.store.doc(doc['id']);break
            folder,data=self.manifest(doc)
            for item in self.store.rows('SELECT * FROM segments WHERE document_id=?',(doc['id'],)):
                if item['state']=='pending' and item['overwrite_allowed'] and not item['attempt']:
                    # Explicit regeneration must not be cancelled by finding
                    # the previous, still valid audio with the same revision.
                    continue
                record=data['segments'].get(item['id']);valid=False
                if record and record.get('previous') and item['filename']:
                    target=safe_path(folder/item['filename'])
                    if target.is_file() and digest(target)==record['previous']['sha256']:
                        data['segments'][item['id']]=record=record['previous'];atomic_json(folder/MANIFEST,data)
                if record and record.get('revision')==item['revision'] and record.get('filename')==item['filename']:
                    try:
                        info=validate(safe_path(folder/item['filename']))
                        valid=info['sha256']==record['sha256']
                    except (OSError,ValueError,RuntimeError):pass
                if valid:
                    self.store.execute("UPDATE segments SET state='success',sha256=?,duration=?,rate=?,backend=?,error='' WHERE id=?",
                        (info['sha256'],info['duration'],info['rate'],record['backend'],item['id']))
                elif item['state'] in ('success','running','unknown'):
                    self.store.execute("UPDATE segments SET state='error',error='Audio thiếu/hỏng hoặc revision khác; xác nhận tạo lại' WHERE id=?",(item['id'],))

    def finalize(self,run):
        for doc in self.store.docs(run):
            items=self.store.rows('SELECT * FROM segments WHERE document_id=? AND skip=0',(doc['id'],))
            if not items or any(i['state']!='success' for i in items):continue
            folder,data=self.manifest(doc)
            for item in items:
                info=validate(safe_path(folder/item['filename']))
                if info['sha256']!=item['sha256']:raise ValueError('Audio đã thay đổi; không finalize')
            target=safe_path(folder.parent/(doc['base']+f'_{len(items)}tts'))
            if target==folder:
                self.store.execute('UPDATE documents SET ended=COALESCE(ended,?) WHERE id=?',(time.time(),doc['id']));continue
            original=doc['base'];candidate=original;index=2
            while True:
                if target.exists():candidate=base_name(original+f'_{index}');index+=1;target=safe_path(folder.parent/(candidate+f'_{len(items)}tts'));continue
                self.store.execute('UPDATE documents SET base=?,rename_intent=? WHERE id=?',(candidate,json.dumps(dict(old=str(folder),new=str(target))),doc['id']))
                try:folder.rename(target);break
                except FileExistsError:continue
            self.store.execute('UPDATE documents SET folder=?,rename_intent=NULL WHERE id=?',(str(target),doc['id']))
            self.store.execute('UPDATE documents SET ended=? WHERE id=?',(time.time(),doc['id']))

    def relink(self,document,folder):
        doc=self.store.doc(document);replacement=dict(doc,folder=str(safe_path(folder)));root,data=self.manifest(replacement)
        for item in self.store.rows("SELECT * FROM segments WHERE document_id=? AND state='success'",(document,)):
            record=data['segments'].get(item['id'])
            if not record or record['revision']!=item['revision'] or record['filename']!=item['filename'] or validate(safe_path(root/item['filename']))['sha256']!=item['sha256']:
                raise ValueError('Không khớp manifest/audio; không liên kết')
        self.store.execute('UPDATE documents SET folder=?,rename_intent=NULL WHERE id=?',(str(root),document))

    def retry(self,run,ids):
        if self.store.run(run)['state'] in ('running','pausing','stopping','cancelled'):raise ValueError('Tạm dừng trước khi tạo lại; lượt đã hủy không thể tiếp tục')
        for doc in self.store.docs(run):
            if not doc['folder'] or not any(self.store.segment(id)['document_id']==doc['id'] for id in ids if self.store.segment(id)):continue
            folder,_=self.manifest(doc);target=safe_path(folder.parent/(doc['base']+'_TTS_inprogress'))
            if folder!=target:
                if target.exists():raise FileExistsError('Thư mục đang xử lý đã tồn tại')
                self.store.execute('UPDATE documents SET rename_intent=? WHERE id=?',(json.dumps(dict(old=str(folder),new=str(target))),doc['id']))
                folder.rename(target);self.store.execute('UPDATE documents SET folder=?,rename_intent=NULL WHERE id=?',(str(target),doc['id']))
        with self.store.transaction():
            for id in ids:
                item=self.store.segment(id)
                if not item or self.store.doc(item['document_id'])['run_id']!=run:raise ValueError('Đoạn thuộc lượt khác')
                self.store.execute("UPDATE segments SET state='pending',attempt=NULL,error='',overwrite_allowed=1 WHERE id=?",(id,))
