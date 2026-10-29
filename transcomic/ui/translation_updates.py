"""Detached read-only snapshots for the text workspace, never a translation owner."""
import json
from pathlib import Path
import sqlite3
import threading
import time
from PySide6.QtCore import QObject,Signal,Qt,QTimer
from ..documents import translatable
from ..status import usable


def document_status(rows,job_state=None,*,pending_work=False,structural=False):
    required=[r for r in rows if translatable(r['source'])]
    done=sum(usable(r) for r in required)
    errors=sum(r['state'] in ('error','wrong_target_language','stale') for r in required)
    unknown=sum(r['state']=='unknown' for r in required)
    complete=not structural and not pending_work and all(usable(r) and r['state']=='done' for r in required)
    if complete:state='Đã xong'
    elif job_state in ('stopped','stopping'):state='Đã dừng' if job_state=='stopped' else 'Đang dừng an toàn'
    elif job_state=='interrupted':state='Bị gián đoạn'
    elif job_state in ('user_paused','paused','pausing'):state='Tạm dừng'
    elif any(r['state']=='processing' for r in required):state='Đang dịch'
    elif job_state=='retry_scheduled':state='Đang chờ thử lại'
    elif job_state=='waiting_rate_limit':state='Chờ giới hạn'
    elif job_state=='provider_recovering':state='Đang hồi phục'
    elif job_state=='network_waiting':state='Chờ mạng phục hồi'
    elif job_state=='parked':state='Chờ slot dịch'
    elif job_state=='blocked_auth':state='Key không hợp lệ'
    elif job_state in ('blocked_quota','quota_exhausted'):state='Hết quota'
    elif job_state=='blocked_budget':state='Đã đạt giới hạn phục hồi'
    elif structural:state='Cần kiểm tra cấu trúc'
    elif job_state=='running' and pending_work:state='Đang dịch'
    elif unknown or job_state=='needs_reconciliation':state='Cần đối chiếu kết quả'
    elif errors:state='Còn lỗi'
    elif job_state=='running':state='Đang dịch'
    else:state='Đang chờ'
    return dict(total=len(required),done=done,errors=errors,unknown=unknown,missing=len(required)-done,
                progress=int(done*100/len(required)) if required else 100,state=state,complete=complete)


class SnapshotReader:
    """One connection, created/used/closed on its worker thread; no Store writes."""
    def __init__(self,path):
        self.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.15)
        self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA query_only=ON')
        self.has_automation=self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='automation_worksets'").fetchone() is not None
        self.docs={};self.rows={};self.layouts={};self.summaries={};self.policies={};self.notes={};self.sql_count=0
        self.db.set_trace_callback(self.trace)
    def trace(self,_):self.sql_count+=1
    def close(self):self.db.close()
    def query(self,sql,args=()):return [dict(r) for r in self.db.execute(sql,args)]
    def read(self,ids,changed,full,view):
        from ..line_structure import source_layout,validate_snapshot
        started=time.perf_counter();initial_sql=self.sql_count;wanted=set(ids)
        new=wanted-self.docs.keys();dirty=set();updates=[]
        # A single read transaction prevents completion being inferred from an
        # uncommitted/inconsistent pair of line and pending-batch states.
        self.db.execute('BEGIN')
        try:
            if full or new:
                fetch=ids if full else list(new)
                for start in range(0,len(fetch),400):
                    chunk=fetch[start:start+400];marks=','.join('?'*len(chunk))
                    documents=self.query('SELECT * FROM documents WHERE id IN ('+marks+')',chunk)
                    for doc in documents:
                        key=doc['id'];self.docs[key]=doc;self.rows[key]={};dirty.add(key)
                    for row in self.query('SELECT l.*,u.locator FROM lines l LEFT JOIN document_units u ON u.line_id=l.id WHERE l.document_id IN ('+marks+') ORDER BY l.ordinal',chunk):
                        self.rows[row['document_id']][row['id']]=row;updates.append(row)
            for start in range(0,len(changed),400):
                chunk=changed[start:start+400]
                found=self.query('SELECT l.*,u.locator FROM lines l LEFT JOIN document_units u ON u.line_id=l.id WHERE l.id IN ('+','.join('?'*len(chunk))+')',chunk)
                for row in found:
                    doc=row['document_id']
                    if doc in wanted:
                        self.rows.setdefault(doc,{})[row['id']]=row;dirty.add(doc);updates.append(row)
                for missing in set(chunk)-{r['id'] for r in found}:
                    for doc,rows in self.rows.items():
                        if missing in rows:rows.pop(missing);dirty.add(doc)
            # Read compact state once, without fetching any batch JSON payload.
            jobs={};pending=set()
            for start in range(0,len(ids),400):
                chunk=ids[start:start+400];marks=','.join('?'*len(chunk))
                for job in self.query('SELECT j.id,j.document_id,j.state,j.mode,j.provider,j.model,j.target_lang FROM jobs j JOIN (SELECT document_id,MAX(rowid) latest FROM jobs WHERE document_id IN ('+marks+') GROUP BY document_id) k ON j.rowid=k.latest',chunk):jobs[job['document_id']]=job
                pending.update(r['document_id'] for r in self.query("SELECT DISTINCT j.document_id FROM jobs j JOIN batches b ON b.job_id=j.id WHERE j.document_id IN ("+marks+") AND j.state IN ('ready','parked','running','waiting_rate_limit','provider_recovering','retry_scheduled','network_waiting','user_paused','paused','pausing','stopping','interrupted') AND (b.state IN ('pending','inflight') OR b.state IN ('error','unknown','partial') AND json_extract(b.diagnostics,'$.auto_retry_scheduled')=1)",chunk))
            changed_lines=[r['id'] for r in updates]
            for start in range(0,len(changed_lines),400):
                chunk=changed_lines[start:start+400]
                for r in self.query('SELECT v.line_id,v.warnings,j.prompt_version FROM api_text_versions v JOIN request_attempts a ON a.id=v.attempt_id JOIN batches b ON b.id=a.original_batch_id JOIN jobs j ON j.id=b.job_id WHERE v.accepted=1 AND v.line_id IN ('+','.join('?'*len(chunk))+') ORDER BY a.rowid',chunk):
                    self.policies[r['line_id']]=r['prompt_version'];self.notes[r['line_id']]=json.loads(r['warnings'])
            export=self.db.execute('SELECT value FROM settings WHERE key=?',('export_revision_'+str(view),)).fetchone()
            locked={r['document_id'] for r in self.query("SELECT g.document_id FROM automation_groups g JOIN automation_worksets w ON w.id=g.workset_id WHERE w.state IN ('running','stopping')")} if self.has_automation else set()
            self.db.commit()
        except BaseException:self.db.rollback();raise
        for doc in set(self.docs)-wanted:
            for rid in self.rows.pop(doc,{}):self.policies.pop(rid,None);self.notes.pop(rid,None)
            self.docs.pop(doc,None);self.summaries.pop(doc,None);self.layouts.pop(doc,None)
        reports={}
        for doc in wanted & self.docs.keys():
            if doc in dirty or doc not in self.summaries:
                info=self.docs[doc];key=(info['digest'],info['format'])
                if self.layouts.get(doc,(None,))[0]!=key:
                    try:layout=source_layout(info)
                    except (ValueError,UnicodeError):layout=None
                    self.layouts[doc]=(key,layout)
                report=validate_snapshot(info,sorted(self.rows[doc].values(),key=lambda r:r['ordinal']),self.layouts[doc][1])
                self.summaries[doc]=dict(structural=bool(report.structural),report=report)
            reports[doc]=self.summaries[doc]['report']
        statuses={doc:document_status(list(self.rows[doc].values()),jobs.get(doc,{}).get('state'),pending_work=doc in pending,structural=self.summaries[doc]['structural']) for doc in wanted & self.docs.keys()}
        period=[]
        from ..translation_policy import SEMANTIC_VERSIONS
        from .period_warning import preview
        for doc in ids:
            for row in self.rows.get(doc,{}).values():
                if '.' in (row['translation'] or '') and self.policies.get(row['id']) not in SEMANTIC_VERSIONS:
                    period.append(dict(id=row['id'],document_id=doc,ordinal=row['ordinal'],preview=preview(row['translation']),document=Path(self.docs[doc]['path']).name,language=self.docs[doc]['target_lang']))
        editor=None
        if view in dirty or full:
            from ..quality import collect,language_evidence
            info=self.docs.get(view)
            if info:
                rows=sorted(self.rows[view].values(),key=lambda r:r['ordinal'])
                editorial=collect([{**r,'source_lang':info['source_lang'],'target_lang':info['target_lang'],'translation_policy':self.policies.get(r['id'])} for r in rows])
                for row in rows:
                    if row.get('attempt_kind')=='manual':continue
                    notes=self.notes.get(row['id'],[])
                    if notes:
                        item=next((r for r in editorial if r['id']==row['id']),None)
                        if item is None:item={**row,'warnings':[]};editorial.append(item)
                        item['warnings'].extend(('Hậu xử lý',note) for note in notes)
                evidence=[language_evidence(r['source'],r['translation'] or '',info['source_lang'],info['target_lang'])[0] for r in rows if r['translation']]
                editor=dict(document=info,rows=rows,editorial=editorial,evidence=evidence,report=reports[view],export_revision=export[0] if export else None)
        return dict(ids=tuple(ids),view=view,documents={d:{k:v for k,v in self.docs[d].items() if k!='snapshot'} for d in ids if d in self.docs},statuses=statuses,jobs=jobs,
                    rows_by_document={d:tuple(self.rows[d].values()) for d in ids if d in self.rows},
                    automation_locked=locked,updates=updates,dirty=dirty,editor=editor,period=tuple(period),sql=self.sql_count-initial_sql,read_ms=(time.perf_counter()-started)*1000)


class TranslationUpdates(QObject):
    ready=Signal(object)
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.path=owner.store.path
        self.store=owner.store;self.validated_manual=None
        self.condition=threading.Condition();self.pending=None;self.closed=False;self.busy=False;self.thread=None;self.generation=0
        self.last=None;self.read_sql=0;self.apply_ms=[];self.recently_active=False
        self.automation_scope=None
        self.ready.connect(self.apply,Qt.QueuedConnection)
    def active(self):
        w=self.owner
        if self.closed or w._closed or w._exit_pending:return False
        context=self.context();s=context['scheduler']
        return self.handles_scheduler() and (getattr(w,'translation_preparing',False) or context['busy'] or bool(s and s._thread and s._thread.is_alive()))
    def set_automation_scope(self,payload):
        page=getattr(self.owner,'automation_page',None);work=payload.get('scope_work')
        if page and work and work['id']==page.controller.current:
            self.automation_scope=dict(id=work['id'],cycle=work['cycle'],docs=tuple(payload['scope_docs']),name=work['name'])
    def context(self):
        w=self.owner;page=getattr(w,'automation_page',None);direct=w.scheduler
        if page and page.controller.current:
            scope=self.automation_scope;native=page.services.translation.scheduler;busy=page.controller.busy
            if busy or scope and scope['id']==page.controller.current and native and (not direct or (native.started_at or 0)>(direct.started_at or 0)):
                if not scope or scope['id']!=page.controller.current:
                    work=(page.snapshots.last or {}).get('work')
                    docs=tuple(g['document_id'] for g in (page.proof or {}).get('groups',()))
                    scope=dict(id=page.controller.current,cycle=work['cycle'] if work else 0,docs=docs,name=work['name'] if work else 'Automation')
                return dict(kind='automation',key=('automation',scope['id'],scope['cycle']),scheduler=native,busy=busy,docs=scope['docs'],line_ids=(),name=scope['name'],controller=page.controller)
        return dict(kind='direct',key=('direct',getattr(direct,'run_id',None) or tuple(getattr(direct,'job_ids',()))),scheduler=direct,busy=False,docs=(),line_ids=tuple(w.current_job_ids),name='Dịch trực tiếp',controller=None)
    def handles_scheduler(self):
        from ..providers import KiraProvider
        context=self.context()
        if context['kind']=='automation':return True
        provider=getattr(context['scheduler'],'provider',None)
        return isinstance(provider,KiraProvider) or getattr(provider,'multi_key',False) if provider is not None else self.owner.provider_id() in ('kira','deepseek')
    def request(self,changed=(),*,full=False,validate_editor=False):
        w=self.owner
        if self.closed or w._closed or w._exit_pending:return
        ids=tuple(dict.fromkeys(w.workspace_ids));view=w.doc_id
        with self.condition:
            old=self.pending
            full=full or self.last is None or self.last['ids']!=ids
            lines=set(changed)
            if old:lines.update(old['changed']);full=full or old['full'];validate_editor=validate_editor or old['validate_editor']
            self.generation+=1
            context=self.context();scope={k:context[k] for k in ('kind','key','docs','line_ids','name')}
            self.pending=dict(ids=ids,view=view,changed=list(lines),full=full,generation=self.generation,validate_editor=validate_editor,scope=scope,
                              idle_revision=None if self.active() else self.store.db.total_changes)
            if self.thread is None:
                self.thread=threading.Thread(target=self.run,daemon=True,name='TranslationUISnapshots');self.thread.start()
            self.condition.notify()
    def run(self):
        reader=None
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda:self.closed or self.pending is not None)
                    if self.closed:return
                    request=self.pending;self.pending=None;self.busy=True
                try:
                    if reader is None:reader=SnapshotReader(self.path)
                    if request['validate_editor'] and request['view']:
                        # Preserve the existing manual-edit validation, off Qt's
                        # thread. API commits already run this validator. Reuse
                        # Store's locked transaction; the read connection never
                        # writes or owns a translation request.
                        rows=self.store.lines(request['view'])
                        signature=(request['view'],tuple((r['id'],r['source_revision'],r['translation_revision']) for r in rows if r.get('attempt_kind')=='manual'))
                        if signature[1] and signature!=self.validated_manual:
                            self.store.warning_rows(request['view']);self.validated_manual=signature
                    payload=reader.read(request['ids'],request['changed'],request['full'],request['view']);payload['generation']=request['generation'];payload['scope']=request['scope'];payload['idle_revision']=request['idle_revision']
                except (sqlite3.Error,OSError,ValueError,KeyError):payload={'error':True,'request':request}
                with self.condition:self.busy=False
                if self.closed:return
                try:self.ready.emit(payload)
                except RuntimeError:return
        finally:
            if reader:reader.close()
    def apply(self,payload):
        w=self.owner
        if self.closed or w._closed or w._exit_pending:return
        if payload.get('error'):
            # Keep the last committed view on a short SQLite busy interval.
            request=payload['request']
            QTimer.singleShot(100,lambda:self.request(request['changed'],full=request['full'],validate_editor=request['validate_editor']))
            return
        if self.last and payload['generation']<self.last['generation']:return
        if not self.active() and payload.get('idle_revision')!=self.store.db.total_changes:
            # A manual edit/import may commit while an idle snapshot is queued.
            # Active translation uses its existing delta stream instead.
            self.request((),full=True);return
        if payload['scope']['key']!=self.context()['key']:
            self.request((),full=True);return
        if payload['ids']!=tuple(dict.fromkeys(w.workspace_ids)) or payload['view']!=w.doc_id:
            self.request((),full=True);return
        self.last=payload;self.read_sql+=payload['sql']
        start=time.perf_counter();w._apply_translation_snapshot(payload);self.apply_ms.append((time.perf_counter()-start)*1000)
        if len(self.apply_ms)>500:self.apply_ms=self.apply_ms[-500:]
    def wait_for_idle(self,seconds=5):
        """Test/profiling helper. The application's GUI never waits for workers."""
        from PySide6.QtWidgets import QApplication
        limit=time.monotonic()+seconds;generation=self.generation
        while time.monotonic()<limit:
            QApplication.processEvents()
            if self.last and self.last.get('generation',0)>=generation and not self.busy and self.pending is None:return True
            time.sleep(.002)
        return False
    def shutdown(self):
        with self.condition:self.closed=True;self.pending=None;self.condition.notify()
