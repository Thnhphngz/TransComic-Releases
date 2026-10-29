"""Small detached presentation snapshots; no workflow or translation ownership."""
import json
from pathlib import Path
import sqlite3
import threading
import time
from PySide6.QtCore import QObject,Signal,Qt,QTimer
from ..documents import translatable


class AutomationReader:
    def __init__(self,path,tts_path):
        self.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.1);self.db.row_factory=sqlite3.Row
        self.db.create_function('ui_translatable',1,translatable,deterministic=True)
        self.tts=sqlite3.connect(Path(tts_path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.1);self.tts.row_factory=sqlite3.Row
        self.sql=0;self.db.set_trace_callback(self.trace);self.tts.set_trace_callback(self.trace)
    def trace(self,_):self.sql+=1
    def close(self):self.db.close();self.tts.close()
    def rows(self,sql,args=()):return [dict(r) for r in self.db.execute(sql,args)]
    def read(self,id,active_id=None):
        start=time.perf_counter();initial=self.sql
        self.db.execute('BEGIN')
        try:
            active=self.rows("SELECT id FROM automation_worksets WHERE state IN ('running','stopping')")
            active=active[0]['id'] if active else None
            scope_id=active_id or active or id
            works=self.rows('SELECT * FROM automation_worksets WHERE id IN (?,?)',(id,scope_id))
            works={r['id']:{**r,'config':json.loads(r['config']),'checkpoint':json.loads(r['checkpoint'])} for r in works}
            groups=self.rows('SELECT g.id,g.workset_id,g.document_id,g.position,d.path,g.data FROM automation_groups g JOIN documents d ON d.id=g.document_id WHERE g.workset_id IN (?,?) ORDER BY g.position,g.id',(id,scope_id))
            docs=[g['document_id'] for g in groups];stats={}
            for offset in range(0,len(docs),400):
                chunk=docs[offset:offset+400]
                for r in self.rows("SELECT document_id,SUM(ui_translatable(source)) total,SUM(ui_translatable(source) AND state='done' AND translation_source_revision=source_revision AND length(trim(COALESCE(translation,'')))>0) done FROM lines WHERE document_id IN ("+','.join('?'*len(chunk))+') GROUP BY document_id',chunk):stats[r['document_id']]=r
            job_ids=[r['id'] for r in self.rows("SELECT id FROM jobs WHERE json_extract(config,'$.automation_owner')=?",(scope_id,))]
            self.db.commit()
        except BaseException:self.db.rollback();raise
        for g in groups:
            g['data']=json.loads(g['data']);g['translated']=stats.get(g['document_id'],{}).get('done') or 0;g['translation_total']=stats.get(g['document_id'],{}).get('total') or 0;g['waves']=0
        runs={g['data'].get('tts_run') for g in groups}-{None,''};waves={}
        for offset in range(0,len(runs),400):
            chunk=list(runs)[offset:offset+400]
            for r in self.tts.execute("SELECT d.run_id,SUM(s.state='success' AND s.skip=0) success FROM documents d LEFT JOIN segments s ON s.document_id=d.id WHERE d.run_id IN ("+','.join('?'*len(chunk))+') GROUP BY d.run_id',chunk):waves[r['run_id']]=r['success'] or 0
        for g in groups:g['waves']=waves.get(g['data'].get('tts_run'),0)
        return dict(id=id,active=active,work=works.get(id),groups=[g for g in groups if g['workset_id']==id],
                    scope_work=works.get(scope_id),scope_groups=[g for g in groups if g['workset_id']==scope_id],scope_docs=[g['document_id'] for g in groups if g['workset_id']==scope_id],scope_jobs=job_ids,
                    sql=self.sql-initial,read_ms=(time.perf_counter()-start)*1000)


class AutomationSnapshots(QObject):
    ready=Signal(object)
    def __init__(self,page):
        super().__init__(page);self.page=page;self.path=page.repo.store.path;self.tts_path=page.services.tts_store.path
        self.last=None;self.closed=False;self.thread=None;self.condition=threading.Condition();self.pending=None;self.serial=0;self.busy=False;self.apply_ms=[]
        self.ready.connect(self.apply,Qt.QueuedConnection)
    def request(self):
        if self.closed or self.page.owner._closed or self.page.owner._exit_pending:return
        with self.condition:
            self.serial+=1;self.pending=(self.page.current,self.page.controller.current,self.serial)
            if self.thread is None:self.thread=threading.Thread(target=self.run,daemon=True,name='AutomationUISnapshots');self.thread.start()
            self.condition.notify()
    def read_now(self):
        # Explicit idle UI actions only; compact metadata/aggregate reads, no
        # filesystem, DOCX, validation, media inspection or shared Store lock.
        reader=AutomationReader(self.path,self.tts_path)
        try:
            payload=reader.read(self.page.current,self.page.controller.current);self.serial+=1;payload['serial']=self.serial;self.apply(payload)
        finally:reader.close()
    def run(self):
        reader=None
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda:self.closed or self.pending is not None)
                    if self.closed:return
                    id,active,serial=self.pending;self.pending=None;self.busy=True
                try:
                    if reader is None:reader=AutomationReader(self.path,self.tts_path)
                    payload=reader.read(id,active);payload['serial']=serial
                except (sqlite3.Error,OSError,ValueError):payload={'error':True,'serial':serial,'id':id}
                self.busy=False
                if self.closed:return
                try:self.ready.emit(payload)
                except RuntimeError:return
        finally:
            if reader:reader.close()
    def apply(self,payload):
        p=self.page
        if self.closed or p.owner._closed or p.owner._exit_pending:return
        if payload['id']!=p.current or self.last and payload['serial']<self.last['serial']:return
        if payload.get('error'):QTimer.singleShot(150,self.request);return
        self.last=payload;start=time.perf_counter();p.refresh(payload);self.apply_ms.append((time.perf_counter()-start)*1000)
        if len(self.apply_ms)>500:self.apply_ms=self.apply_ms[-500:]
    def shutdown(self):
        with self.condition:self.closed=True;self.pending=None;self.condition.notify()
    def wait_for_idle(self,seconds=5):
        from PySide6.QtWidgets import QApplication
        until=time.monotonic()+seconds;serial=self.serial
        while time.monotonic()<until:
            QApplication.processEvents()
            if self.last and self.last['serial']>=serial and not self.busy and self.pending is None:return True
            time.sleep(.002)
        return False
