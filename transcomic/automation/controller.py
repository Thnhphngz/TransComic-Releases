"""One user-started workset; overlapping translation, serial TTS and projects."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import threading
import time
from .adapters import Stopped
from .repository import file_hash,fingerprint
from .validation import validate,read_source,speakable
from ..status import usable
from ..documents import translatable
from .retranslation import Retranslation
from .reconciliation import Reconciliation


class StagePool(ThreadPoolExecutor):
    def __init__(self,controller):
        super().__init__(max_workers=3,thread_name_prefix='automation-stage');self.controller=controller
    def __exit__(self,kind,value,trace):
        if kind:
            self.controller.internal_abort=True;self.controller.stop_event.set();self.controller.services.translation.stop()
        return super().__exit__(kind,value,trace)


class Controller(Retranslation,Reconciliation):
    def __init__(self,repo,services,changed=lambda:None,finished=lambda *args:None,resource_check=lambda:None,editor_check=lambda:None):
        self.repo=repo;self.services=services;self.changed=changed;self.finished=finished
        self.resource_check=resource_check;self.editor_check=editor_check;self.thread=None;self.stop_event=threading.Event();self.lock=threading.RLock();self.current=None
        self.pending_terminal=None;self.internal_abort=False;repo.controller=self
    @property
    def busy(self):return bool(self.thread and self.thread.is_alive())
    def validate(self,id,*,reuse_inputs=True,force_config=False):
        if self.pending_terminal and not self.busy and self.current==id:
            self.repo.state(id,self.pending_terminal);self.pending_terminal=None
        self.repo.editable(id);self.reconcile_sources(id)
        proof=validate(self.repo,id,self.services,reuse_inputs=reuse_inputs,force_config=force_config)
        self.reconcile_stages(id)
        proof['pending']=self.has_pending(id,proof) if proof['passed'] and self.repo.workset(id)['state']=='completed' else True
        self.checkpoint(id,validation=dict(passed=proof['passed'],errors=proof['errors'],config_fingerprint=proof['config_fingerprint'],pending=proof['pending']),validation_sections=proof['sections'])
        return proof
    def start(self,id,selected=None):
        with self.lock:
            if self.busy or self.repo.active():raise ValueError('Chỉ một bộ Automation được chạy.')
            work=self.repo.workset(id);proof=work['checkpoint'].get('validation',{})
            from .validation import project_name_error
            if error:=project_name_error(work['config']):raise ValueError(error)
            if proof.get('config_fingerprint')!=fingerprint(work['config']) or proof.get('errors') or not work['started'] and not proof.get('passed'):
                raise ValueError('Kiểm tra trước khi bắt đầu chưa PASS hoặc cấu hình đã thay đổi.')
            if work['state']=='completed' and proof.get('pending') is False:raise ValueError('Đã hoàn thành, không có công việc cần cập nhật.')
            from .repository import IMMUTABLE
            tts_fp=fingerprint({k:work['config'][k] for k in (*IMMUTABLE,'format')})
            if work['checkpoint'].get('tts_config_fingerprint',tts_fp)!=tts_fp:raise ValueError('Fingerprint Kokoro thay đổi; tạo bộ công việc mới.')
            if selected is not None and not set(selected)<={g['id'] for g in self.repo.groups(id)}:raise ValueError('Nhóm được chọn không thuộc bộ công việc.')
            if not work['started']:selected=None
            self.editor_check();self.resource_check()
            with self.repo.store.transaction():self.repo.activate(id);self.checkpoint(id,tts_config_fingerprint=tts_fp)
            self.current=id;self.stop_event.clear();self.internal_abort=False;self.closing_translation=False
            if hasattr(self.services.translation,'reset'):self.services.translation.reset()
            self.changed()
            self.thread=threading.Thread(target=self._run,args=(id,selected),daemon=True,name='TransComic-Automation')
            try:self.thread.start()
            except BaseException:
                try:self.repo.state(id,'needs_attention')
                except Exception:self.pending_terminal='needs_attention'
                raise
    def stop(self):
        # Fence assignment immediately; never join or wait on SQLite on Qt's thread.
        with self.lock:
            if not self.busy or self.repo.active()!=self.current:return
            self.stop_event.set();self.services.translation.stop()
            if self.current:self.repo.state(self.current,'stopping')
        self.changed()
    def join(self,timeout=None):
        if self.thread:self.thread.join(timeout)
    def checkpoint(self,id,**changes):
        with self.repo.store.transaction():
            data=self.repo.workset(id)['checkpoint'];data.update(changes)
            self.repo.execute('UPDATE automation_worksets SET checkpoint=? WHERE id=?',(json.dumps(data,ensure_ascii=False),id))
    def reconcile_sources(self,id):
        """Stable IDs survive equal-layout edits; ambiguous/manual conflicts block."""
        self.repo.editable(id)
        for group in self.repo.groups(id):
            path=Path(self.repo.store.document(group['document_id'])['path']);meta=group['data']
            try:
                digest=file_hash(path)
                if digest==meta['source_sha256']:continue
                data,locators=read_source(path);rows=self.repo.store.units(group['document_id'])
                if len(data.lines)!=len(rows) or locators is not None and locators!=[r['locator'] for r in rows]:raise ValueError(f'Nguồn thay đổi cấu trúc/mapping: {sum(speakable(l.text) for l in data.lines)} dòng mới / {len(meta.get("images",[]))} ảnh đã ghép; giữ nguyên dòng cũ, cần kiểm tra nhóm.')
                changed=[(r,l.text) for r,l in zip(rows,data.lines) if r['source']!=l.text]
                if any(r['attempt_kind']=='manual' and r['translation'] for r,text in changed):raise ValueError('Xung đột nguồn và bản dịch sửa tay; giữ nguyên bản dịch, cần xử lý nguồn.')
                if any(speakable(r['source'])!=speakable(text) for r,text in changed):raise ValueError('Nguồn thay đổi số dòng cần voice; kiểm tra mapping ảnh.')
                changed_ids={r['id'] for r,text in changed};affected=set(changed_ids)
                for candidates in ([r['id'] for r in rows if translatable(r['source'])],
                                   [r['id'] for r,line in zip(rows,data.lines) if translatable(line.text)]):
                    for offset in range(0,len(candidates),3):
                        chunk=candidates[offset:offset+3]
                        if changed_ids.intersection(chunk):affected.update(chunk)
                with self.repo.store.transaction():
                    for r,text in changed:
                        self.repo.store.db.execute("UPDATE lines SET source=?,source_revision=source_revision+1,state='pending',updated_at=CURRENT_TIMESTAMP WHERE id=?",(text,r['id']))
                    for r in rows:
                        if r['id'] in affected and r['attempt_kind']!='manual' and translatable(self.repo.store.line(r['id'])['source']):
                            self.repo.store.db.execute("UPDATE lines SET state='pending',translation_source_revision=NULL WHERE id=?",(r['id'],))
                    self.repo.store.db.execute('UPDATE documents SET snapshot=?,digest=?,encoding=? WHERE id=?',(data.raw,digest,data.encoding,group['document_id']))
                    self.repo.update_group(group['id'],source_sha256=digest,state='stale',error='')
                self.repo.event(id,group['id'],'source','Đã đối chiếu nguồn; chỉ batch liên quan cần dịch lại.')
            except (OSError,ValueError,UnicodeError) as exc:self.repo.update_group(group['id'],state='needs_attention',error=str(exc))
    def _run(self,id,selected=None):
        errors=[];groups=[];parts=[];terminal='needs_attention'
        try:
            work=self.repo.workset(id);cfg=work['config'];first=work['cycle']==1
            proof=validate(self.repo,id,self.services)
            groups=[g for g in proof['groups'] if g['valid'] and (selected is None or g['id'] in selected or g['data']['state']=='completed')]
            if proof['errors'] or first and not proof['passed']:raise ValueError(' · '.join(proof['errors']+[g['name']+': '+', '.join(g['errors']) for g in proof['groups'] if not g['valid']]))
            # Keep failed groups in part definitions so merged export cannot omit them.
            parts=[dict(p,id=fingerprint(p['group_ids']),state='waiting') for p in proof['parts']]
            self.checkpoint(id,started=time.time(),ended=None,parts=parts)
            audio_ready,_=self.reconcile_stages(id)
            for group in proof['groups']:
                if not group['valid']:self.repo.update_group(group['id'],state='needs_attention')
            self.repo.store.set_setting('automation_last_config',json.dumps(cfg))
            ready=[];rescue_queue=[];queued=set();tts_done=set();tts_failed=set();exported=set();tts_future=None;cap_future=None;tts_group=None;cap_part=None;tts_blocked=False;rescuing=False
            with StagePool(self) as pool:
                cycle=self.repo.workset(id)['cycle']
                eligible={g['id']:g for g in groups}
                for group in groups:
                    if all(usable(r) for r in self.repo.store.lines(group['document_id']) if translatable(r['source'])):
                        self.repo.update_group(group['id'],translation_ready_cycle=cycle,translation_ready_at=time.monotonic_ns())
                translation=pool.submit(self.normal_translation,id,groups,cfg)
                while True:
                    pending_groups=self.pending_retry_groups(id)
                    # A request waits for the current translation scheduler and any
                    # dependent stage using its old snapshot. No second lane starts.
                    if translation.done() and not self.stop_event.is_set():
                        translation.result()
                        for request in self.retry_requests(id):
                            if request['state'] not in ('pending','running'):continue
                            requested_docs={self.repo.store.line(i)['document_id'] for i in request['line_ids']}
                            targets=[g for g in proof['groups'] if g['valid'] and g['document_id'] in requested_docs]
                            for target in targets:eligible[target['id']]=target
                            target_ids={g['id'] for g in targets}
                            if not targets:continue
                            if tts_future and tts_group['id'] in target_ids or cap_future and target_ids.intersection(cap_part['group_ids']):continue
                            for gid in target_ids:
                                queued.discard(gid);tts_done.discard(gid);tts_failed.discard(gid);audio_ready.discard(gid)
                                self.repo.update_group(gid,translation_ready_cycle=None,error='')
                            ready[:]=[g for g in ready if g not in target_ids]
                            rescue_queue[:]=[g for g in rescue_queue if g not in target_ids]
                            for part in parts:
                                if target_ids.intersection(part['group_ids']):exported.discard(part['id']);part.update(state='waiting')
                            translation=pool.submit(self.run_retry,id,request,targets,cfg);break
                    completed=self.repo.rows("SELECT id FROM automation_groups WHERE workset_id=? AND json_extract(data,'$.translation_ready_cycle')=? ORDER BY json_extract(data,'$.translation_ready_at')",(id,cycle))
                    for entry in completed:
                        gid=entry['id']
                        if gid in pending_groups:continue
                        if gid not in eligible:continue
                        if gid in queued:continue
                        queued.add(gid)
                        if gid in audio_ready:
                            self.export_translation(id,eligible[gid],cfg)
                            tts_done.add(gid);self.repo.update_group(gid,state='waiting_capcut')
                        else:
                            ready.append(gid);self.repo.update_group(gid,state='waiting_tts');self.repo.event(id,gid,'translation','Dịch hợp lệ; đã xếp hàng Kokoro.')
                    if tts_future and tts_future.done():
                        try:
                            folder=tts_future.result();tts_done.add(tts_group['id']);self.repo.update_group(tts_group['id'],state='waiting_capcut',audio_folder=folder)
                        except Stopped:pass
                        except Exception as exc:
                            from ..tts.process_engine import EngineFailure
                            from .adapters import NeedsRescue
                            if isinstance(exc,NeedsRescue) and not rescuing:
                                rescue_queue.append(tts_group['id']);self.repo.update_group(tts_group['id'],state='waiting_tts_rescue')
                            else:
                                if isinstance(exc,(EngineFailure,MemoryError)):tts_blocked=True
                                tts_failed.add(tts_group['id']);self.fail(id,tts_group['id'],'kokoro',exc);errors.append(type(exc).__name__)
                        tts_future=None
                    if cap_future and cap_future.done():
                        try:
                            path=cap_future.result();exported.add(cap_part['id']);cap_part.update(state='completed',path=path)
                            for gid in cap_part['group_ids']:self.repo.update_group(gid,state='completed',project=path)
                        except Stopped:pass
                        except Exception as exc:
                            exported.add(cap_part['id']);cap_part.update(state='needs_attention',error=str(exc));errors.append(type(exc).__name__)
                            for gid in cap_part['group_ids']:self.fail(id,gid,'capcut',exc)
                        cap_future=None;self.checkpoint(id,parts=parts)
                    if not self.stop_event.is_set():
                        next_ready=next((gid for gid in ready if gid not in pending_groups),None)
                        if next_ready and not tts_future and not tts_blocked:
                            gid=next_ready;ready.remove(gid);tts_group=self.repo.group(gid);rescuing=False
                            try:self.export_translation(id,tts_group,cfg)
                            except Exception as exc:
                                tts_failed.add(gid);self.fail(id,gid,'translation_export',exc);errors.append(type(exc).__name__)
                            else:tts_future=pool.submit(self.services.kokoro.run,tts_group,cfg,self.stop_event,self.changed)
                        elif not ready and translation.done() and rescue_queue and not tts_future and not tts_blocked:
                            gid=rescue_queue.pop(0);tts_group=self.repo.group(gid);rescuing=True
                            self.repo.event(id,gid,'kokoro','Cứu lỗi cuối sau các nhóm TTS thông thường.')
                            tts_future=pool.submit(self.services.kokoro.run,tts_group,cfg,self.stop_event,self.changed,rescue=True)
                        if not cap_future:
                            for part in parts:
                                if part['id'] in exported or not set(part['group_ids'])<=tts_done:continue
                                if pending_groups.intersection(part['group_ids']):continue
                                cap_part=part;part['state']='exporting';self.checkpoint(id,parts=parts)
                                for gid in part['group_ids']:self.repo.update_group(gid,state='exporting')
                                payload=dict(part,groups=[self.repo.group(gid) for gid in part['group_ids']])
                                cap_future=pool.submit(self.services.capcut.run,id,payload,cfg,self.stop_event,self.changed);break
                    self.changed()
                    if translation.done() and not tts_future and not cap_future:
                        with self.lock:
                            if self.stop_event.is_set() or (not ready and not rescue_queue or tts_blocked) and not self.pending_retry_groups(id):
                                self.closing_translation=True;break
                    time.sleep(.05)
                translation.result()
            for group in self.repo.groups(id):
                if group['data']['state'] not in ('completed','needs_attention') and not self.stop_event.is_set():
                    self.repo.update_group(group['id'],state='needs_attention',error='Còn bản dịch/WAV hoặc project phụ thuộc chưa hợp lệ.')
            terminal='stopped' if self.stop_event.is_set() else 'completed' if all(g['data']['state']=='completed' for g in self.repo.groups(id)) else 'needs_attention'
            self.checkpoint(id,ended=time.time(),parts=parts)
        except Exception as exc:
            self.services.translation.stop();terminal='stopped' if self.stop_event.is_set() and not self.internal_abort else 'needs_attention'
            try:self.fail(id,None,'pipeline',exc);self.checkpoint(id,ended=time.time())
            except Exception:self.repo.store.log.emit('gui_error',reason='automation_checkpoint_failed',exception=type(exc).__name__)
        finally:
            try:
                self.reconcile_stages(id)
                if terminal=='completed' and any(g['data']['state']!='completed' for g in self.repo.groups(id)):terminal='needs_attention'
            except Exception:self.repo.store.log.emit('gui_error',reason='automation_stage_reconcile_failed')
            from .reports import write
            try:self.checkpoint(id,reports=write(self.repo,id,self.services.tts_store,state=terminal))
            except Exception as exc:
                try:self.repo.event(id,None,'report','Không ghi được báo cáo ngoài; checkpoint nội bộ còn nguyên. '+type(exc).__name__)
                except Exception:self.repo.store.log.emit('gui_error',reason='automation_report_failed',exception=type(exc).__name__)
            with self.lock:
                try:self.repo.state(id,terminal)
                except Exception:
                    self.pending_terminal='needs_attention';terminal='needs_attention'
                    self.repo.store.log.emit('gui_error',reason='automation_terminal_checkpoint_failed')
            self.changed();self.finished(id,terminal)
    def has_pending(self,id,proof):
        from ..tts.documents import segments
        from .adapters import project_hash
        cfg=self.repo.workset(id)['config'];artifacts=self.repo.artifacts(id)
        if self.pending_retry_groups(id):return True
        try:
            for group in proof['groups']:
                meta=self.repo.group(group['id'])['data'];rows=self.repo.store.units(group['document_id'])
                if any(not usable(r) for r in rows if translatable(r['source'])):return True
                fp=fingerprint([(r['id'],r['source_revision'],r['translation_revision'],r['translation']) for r in rows])
                if not any(a['kind']=='translation' and a['unit']==group['id'] and a['fingerprint']==fp and a['state']=='complete' and Path(a['path']).is_file() and file_hash(a['path'])==a['sha256'] for a in artifacts):return True
                if not meta.get('tts_run'):return True
                items=self.services.tts_store.items(meta['tts_run']);docs=self.services.tts_store.docs(meta['tts_run'])
                if not docs or len(items)!=len(meta['slots']):return True
                for line_id,item in zip(meta['slots'],items):
                    line=self.repo.store.line(line_id);text=line['translation'] if line['translation'] is not None else line['source']
                    if not speakable(text) or segments(text,'none')[0]['text']!=item['text'] or item['state']!='success':return True
                    path=Path(docs[0]['folder'])/item['filename']
                    if not path.is_file() or file_hash(path)!=item['sha256']:return True
            for part in proof['parts']:
                unit=fingerprint(part['group_ids']);payload=dict(part,groups=[self.repo.group(gid) for gid in part['group_ids']])
                scans=self.services.capcut.scans(payload['groups']);fp=self.services.capcut.fingerprint(scans,payload,cfg)
                if not any(a['kind']=='capcut' and a['unit']==unit and a['fingerprint']==fp and a['state']=='complete' and Path(a['path']).is_dir() and project_hash(Path(a['path']))==a['sha256'] for a in artifacts):return True
            return False
        except (OSError,ValueError,KeyError):return True
    def fail(self,id,group,stage,exc):
        message=self.repo.store.log.clean(str(exc) or type(exc).__name__)
        if group:self.repo.update_group(group,state='needs_attention',error=message)
        self.repo.event(id,group,stage,message)
    def export_translation(self,id,group,cfg):
        from ..documents import render_export
        from ..docx_document import render_docx
        from ..bulk import write_exports
        store=self.repo.store;doc=store.document(group['document_id']);rows=store.units(doc['id']);source=Path(doc['path'])
        fp=fingerprint([(r['id'],r['source_revision'],r['translation_revision'],r['translation']) for r in rows]);owned=[a for a in self.repo.artifacts(id) if a['unit']==group['id'] and a['kind']=='translation']
        for a in reversed(owned):
            if a['fingerprint']==fp and Path(a['path']).is_file() and file_hash(a['path'])==a['sha256']:return a['path']
        from ..languages import language
        base=source.with_name(source.stem+'.'+language(cfg['target_lang']).locale+source.suffix.lower());path=base;n=2
        while path.exists():path=base.with_name(base.stem+f'_v{n}'+base.suffix);n+=1
        content,missing=render_docx(doc['snapshot'],rows) if doc['format']=='docx' else render_export(rows)
        if missing:raise ValueError('Bản dịch chưa hoàn chỉnh.')
        import hashlib
        digest=hashlib.sha256(content).hexdigest()
        # Intent records enough to recognize a crash between publish and DB commit.
        aid=self.repo.artifact(id,group['id'],'translation',fp,path)
        self.repo.execute('UPDATE automation_artifacts SET sha256=? WHERE id=?',(digest,aid))
        result=write_exports(store,[dict(document=doc,rows=rows,target=path,mode='direct')],existing='cancel')
        if result[0]['state']!='exported':raise ValueError('Xuất bản dịch bị chặn: '+str(result[0]))
        if file_hash(path)!=digest:raise ValueError('Bản dịch xuất không đúng snapshot.')
        self.repo.complete_artifact(aid,digest);return str(path)
