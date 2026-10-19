"""One authorized synthetic campaign. Never reset its durable ledger to rerun.

Authorization: attachment fcc4d7bc, <=30 distinct lines, <=60 actual requests,
<=5 attempts/batch/cycle, configured Kira model/keys, 1 worker. This campaign
selects only THREE lines and at most TWO cycles (10 attempts total).
The production DB is opened read-only for settings/ciphertexts/quota snapshot.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'artifacts/release-2.0.2/live'
TEXT=('Trên bàn có một cuốn sách màu xanh.',
      'Cô ấy mở cửa sổ để đón ánh nắng buổi sáng.',
      'Chúng tôi sẽ trở về nhà trước khi trời tối.')


def save(path,data):
    temporary=path.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    temporary.replace(path)


class Ledger:
    def __init__(self,path):
        self.path=path;self.lock=threading.RLock();self.phase='initial'
        self.data=dict(authorization='fcc4d7bc-6e0c-4e0e-bb63-6eeecd16638e',max_distinct_lines=30,max_requests=60,
                       selected_lines=3,campaign_request_cap=10,workers=1,requests=[],state='reserved',real_http=True)
        with path.open('x',encoding='utf-8') as f:json.dump(self.data,f);f.flush();os.fsync(f.fileno())
    def reserve(self,request):
        body=json.loads(request.content);payload=json.loads(body['messages'][1]['content'])
        lines=payload['lines']
        assert lines and len(lines)<=3 and all(r['text'] in TEXT for r in lines)
        assert request.url.scheme=='https'
        from transcomic.providers import KIRA_CHAT_URL
        assert str(request.url)==KIRA_CHAT_URL and body['model']==self.data['model']
        with self.lock:
            records=self.data['requests']
            if self.data.get('stop_reason') or len(records)>=10 or sum(r['phase']==self.phase for r in records)>=5:
                raise RuntimeError('Campaign request fence')
            record=dict(number=len(records)+1,phase=self.phase,line_ids=[r['id'] for r in lines],reserved=time.time(),state='outcome_unknown')
            records.append(record);save(self.path,self.data);return record


def configured_snapshot():
    from transcomic.app import data_path
    path=data_path()
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        settings=dict(db.execute("SELECT key,value FROM settings WHERE key LIKE 'kira_%' OR key IN ('provider','timeout','request_interval','auto_retries','rate_wait_budget','rate_cooldown_limit','rate_backoff_max')"))
        if settings.get('provider','kira')!='kira':raise RuntimeError('Configured provider is not Kira')
        model=settings.get('kira_model')
        if not model:raise RuntimeError('Configured Kira model absent')
        keys=[dict(r) for r in db.execute('SELECT * FROM kira_keys WHERE enabled=1')]
        if not any(k['status']=='READY' for k in keys):raise RuntimeError('No configured READY key')
        reservations=[dict(r) for r in db.execute('SELECT * FROM kira_reservations WHERE created_at>?',(time.time()-65,))]
    return settings,keys,reservations,model


def execute(ledger,root,snapshot):
    import httpx
    from PySide6.QtWidgets import QApplication,QMessageBox
    from PySide6.QtTest import QTest
    from transcomic.storage import Store
    from transcomic.documents import decode_txt
    from transcomic.translation import Scheduler
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.ui.main import MainWindow
    from transcomic.ui.tts_page import TtsPage
    from transcomic.models import KIRA_MODELS
    from transcomic.status import usable
    settings,keys,reservations,model=snapshot
    if model not in {value for _,value in KIRA_MODELS}:raise RuntimeError('Configured model unavailable; no fallback authorized')
    ledger.data.update(provider='kira',model=model,configured_enabled_keys=len(keys));save(ledger.path,ledger.data)
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            record=ledger.reserve(request)
            try:
                # A new transport per send avoids retaining an asyncio loop across
                # scheduler cycles. HTTPX retries/redirects are never enabled.
                async with httpx.AsyncHTTPTransport(retries=0) as inner:
                    result=await inner.handle_async_request(request);raw=await result.aread()
                    usage={}
                    try:
                        value=json.loads(raw).get('usage',{})
                        if isinstance(value,dict):usage={k:v for k,v in value.items() if isinstance(v,(int,float)) and not isinstance(v,bool)}
                    except (ValueError,AttributeError):pass
                    with ledger.lock:
                        record.update(http_status=result.status_code,elapsed_seconds=time.time()-record['reserved'],state='response_received',usage=usage)
                        if usage.get('total_tokens',0)>16384:ledger.data['stop_reason']='abnormal_token_usage'
                        save(ledger.path,ledger.data)
                    headers={k:v for k,v in result.headers.items() if k.lower() not in ('content-encoding','content-length','transfer-encoding')}
                    return httpx.Response(result.status_code,headers=headers,content=raw,request=request)
            except BaseException as exc:
                with ledger.lock:record['exception_type']=type(exc).__name__;save(ledger.path,ledger.data)
                raise
    app=QApplication.instance() or QApplication([]);TtsPage.check_runtime=lambda self:None
    store=Store(root/'synthetic.sqlite3');window=None
    try:
        with store.transaction():
            for key,value in settings.items():store.set_setting(key,value)
            for table,values in (('kira_keys',keys),('kira_reservations',reservations)):
                for row in values:
                    names=list(row);store.db.execute('INSERT OR REPLACE INTO '+table+' ('+','.join(names)+') VALUES ('+','.join('?' for _ in names)+')',[row[k] for k in names])
        store.set_setting('update_auto_check','0');store.set_setting('concurrency','1')
        def provider(job,*args):
            return KiraPoolProvider(store,model,timeout=job['timeout'],prompt_version=job['prompt_version'],transport=Transport())
        doc=store.import_document(root/'synthetic-only.txt',decode_txt('\n'.join(TEXT).encode()),'vi','en')[0]
        ids=[r['id'] for r in store.lines(doc)];ledger.data['selected_line_ids']=ids;save(ledger.path,ledger.data)
        job=store.create_job(doc,model,'vi','en',1,ids,timeout=min(90,max(30,float(settings.get('timeout','90')))),provider='kira',config={'kira_multi_key':True,'kira_recovery_version':3})
        scheduler=Scheduler(store,provider(store.job(job)));scheduler.start(job);scheduler.join(480)
        if scheduler._thread.is_alive():scheduler.stop();scheduler.join(100);raise RuntimeError('Campaign time fence')
        if not all(usable(r) for r in store.lines(doc)):raise RuntimeError('Initial live batch not fully valid')
        count=len(ledger.data['requests']);ledger.phase='manual_retry'
        window=MainWindow(store);window.workspace_ids=[doc];window.open_document(doc);window.model.selected_ids={ids[1]}
        window.concurrency.setValue(1);window.make_provider=provider
        question=QMessageBox.question;QMessageBox.question=lambda *a,**k:QMessageBox.Yes
        try:window.retry_selected()
        finally:QMessageBox.question=question
        if not window.scheduler:raise RuntimeError('Manual retry did not create its scheduler')
        deadline=time.monotonic()+480
        while window.scheduler._thread.is_alive() and time.monotonic()<deadline:app.processEvents();QTest.qWait(25)
        if window.scheduler._thread.is_alive():window.scheduler.stop();window.scheduler.join(100);raise RuntimeError('Manual retry time fence')
        if len(ledger.data['requests'])<=count or not all(usable(r) for r in store.lines(doc)):raise RuntimeError('Manual retry dispatch or persistence failed')
        assert all(r['line_ids']==[ids[1]] for r in ledger.data['requests'][count:])
        total={}
        for r in ledger.data['requests']:
            for k,v in r.get('usage',{}).items():total[k]=total.get(k,0)+v
        diagnostics=[a.get('diagnostics') or {} for j in store.jobs() for b in store.batches(j['id']) for a in store.attempts(b['id'])]
        ledger.data.update(state='PASS',schema_parse=True,canonical_saved=True,manual_retry_new_dispatch=True,
                           request_attempts=len(ledger.data['requests']),total_usage=total,cost='API numeric usage fields only; no price estimate',
                           natural_504=any(d.get('http_status')==504 for d in diagnostics),
                           natural_json_error=any(d.get('failure_kind') in ('invalid_schema','invalid_line_response') for d in diagnostics),
                           synthetic_only=True,production_database_readonly=True)
    finally:
        if window:
            window._exit_authorized=True;window.close();app.processEvents()
        else:store.close()


def main():
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'authorization-ledger.json'
    if path.exists():
        print(json.dumps({'not_replayed':True,'state':json.loads(path.read_text(encoding='utf-8'))['state']}));return 2
    ledger=Ledger(path)
    try:
        snapshot=configured_snapshot()
        os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_OPENGL']='software';os.environ['QT_QUICK_BACKEND']='software'
        from scripts.test_runtime import TemporaryDirectory
        with TemporaryDirectory(prefix='TransComic-live-202-') as directory:execute(ledger,Path(directory),snapshot)
    except BaseException as exc:
        ledger.data.update(state='NOT VERIFIED',failure_type=type(exc).__name__)
    save(path,ledger.data)
    public={k:ledger.data[k] for k in ('state','provider','model','selected_lines','request_attempts','total_usage','failure_type') if k in ledger.data}
    print(json.dumps(public));return 0 if ledger.data['state']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
