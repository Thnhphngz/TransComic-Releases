"""Explicitly authorized, bounded synthetic probe. Never reads translation data.

Run one round at a time. A durable, process-safe ledger counts reservations as
sent even after crashes. It cannot grant a fourth round or new keys/models.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from transcomic.security import unprotect_key
from transcomic.providers import KiraProvider, KIRA_CHAT_URL
from transcomic.kira_pool import KiraPoolProvider
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.translation import Scheduler

ROOT=Path(__file__).resolve().parents[1]/'artifacts/kira-false-quota'
MODEL='longcat-2.5-preview-free'


class Budget:
    def __init__(self,path,identities):
        if len(set(identities))!=3:raise ValueError('Exactly three approved keys required')
        self.path=path
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS allowed(key TEXT PRIMARY KEY)')
            existing={r[0] for r in db.execute('SELECT key FROM allowed')}
            if existing and existing!=set(identities):raise ValueError('Configured keys changed')
            db.executemany('INSERT OR IGNORE INTO allowed VALUES (?)',[(k,) for k in identities])
            db.execute('CREATE TABLE IF NOT EXISTS sent(id INTEGER PRIMARY KEY,round INTEGER,key TEXT,lines INTEGER,at REAL,status INTEGER,code TEXT,seconds REAL)')

    def reserve(self,round,key,lines):
        if round not in (1,2,3) or not 1<=lines<=3:raise ValueError('Probe limit')
        with sqlite3.connect(self.path,timeout=30) as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM allowed WHERE key=?',(key,)).fetchone():raise ValueError('Unapproved key')
            if db.execute("SELECT 1 FROM sent WHERE key=? AND (status IN (401,403) OR code IN ('vnd_balance_exhausted','insufficient_quota','quota_exhausted','billing_hard_limit_reached','pro_membership_required'))",(key,)).fetchone():raise ValueError('Key requires verification; no further probe')
            per=db.execute('SELECT COALESCE(SUM(lines),0) FROM sent WHERE round=? AND key=?',(round,key)).fetchone()[0]
            total=db.execute('SELECT COALESCE(SUM(lines),0) FROM sent').fetchone()[0]
            if per+lines>30 or total+lines>270:raise ValueError('Probe budget exhausted')
            return db.execute('INSERT INTO sent(round,key,lines,at) VALUES (?,?,?,?)',(round,key,lines,time.time())).lastrowid

    def finish(self,id,status,code,seconds):
        with sqlite3.connect(self.path) as db:db.execute('UPDATE sent SET status=?,code=?,seconds=? WHERE id=?',(status,code,seconds,id))


class Guard(httpx.AsyncBaseTransport):
    def __init__(self,budget,round,identities):
        self.inner=httpx.AsyncHTTPTransport(retries=0)
        self.budget=budget;self.round=round;self.identities=identities
        self.results=[];self.busy=0;self.peak=0

    async def handle_async_request(self,request):
        assert request.method=='POST' and str(request.url)==KIRA_CHAT_URL
        body=json.loads(request.content)
        assert body['model']==MODEL and body['max_tokens']<=1024
        rows=json.loads(body['messages'][1]['content'])['lines']
        secret=request.headers['authorization'].removeprefix('Bearer ')
        key=hashlib.sha256(secret.encode()).hexdigest()
        assert key in self.identities
        claim=self.budget.reserve(self.round,key,len(rows))
        started=time.monotonic();self.busy+=1;self.peak=max(self.peak,self.busy)
        try:
            response=await self.inner.handle_async_request(request)
            await response.aread()
            try:j=response.json()
            except ValueError:j={}
            error=j.get('error') if isinstance(j,dict) else None
            code=error.get('code') if isinstance(error,dict) else None
            import re
            if not isinstance(code,str) or not re.fullmatch('[a-zA-Z0-9_.:-]{1,80}',code) or secret in code:code=None
            self.budget.finish(claim,response.status_code,code,time.monotonic()-started)
            self.results.append({'key':self.identities[key],'lines':len(rows),'http_status':response.status_code,'code':code,'seconds':round(time.monotonic()-started,3)})
            return response
        finally:self.busy-=1

    async def aclose(self):await self.inner.aclose()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--round',type=int,choices=(1,2,3),required=True)
    args=parser.parse_args();ROOT.mkdir(parents=True,exist_ok=True)
    # Official documentation explicitly renders is_free models as 100% free,
    # taking priority over generic price fields in the catalog.
    with httpx.Client(timeout=20,follow_redirects=False) as client:
        catalog=client.get('https://kiraai.vn/api/v1/models');catalog.raise_for_status()
        m=next(x for x in catalog.json()['data'] if x['id']==MODEL)
        doc=client.get('https://kiraai.vn/documents/');doc.raise_for_status()
        assert m['is_free'] is True and m['status']=='active'
        assert "if (isFree)" in doc.text and '100% Free' in doc.text
        (ROOT/'free-verification.json').write_text(json.dumps({'model':MODEL,'is_free':True,'catalog_url':str(catalog.url),'documentation_url':str(doc.url),'documentation_free_priority':True}),encoding='utf8')
    path=Path(os.environ['LOCALAPPDATA'])/'TransComic/transcomic.sqlite3'
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        blobs=db.execute('SELECT encrypted FROM kira_keys WHERE enabled=1 ORDER BY rowid').fetchall()
    assert len(blobs)==3
    secrets=[unprotect_key(r[0]) for r in blobs]
    identities={hashlib.sha256(secret.encode()).hexdigest():f'Key {i+1}' for i,secret in enumerate(secrets)}
    assert len(identities)==3
    budget=Budget(ROOT/'live-budget.sqlite3',identities)
    guard=Guard(budget,args.round,identities)
    report={'round':args.round,'model':MODEL}
    if args.round==1:
        async def probe():
            result=[]
            for i,secret in enumerate(secrets):
                with sqlite3.connect(budget.path) as db:
                    prior=db.execute('SELECT status,lines FROM sent WHERE round=1 AND key=?',(hashlib.sha256(secret.encode()).hexdigest(),)).fetchall()
                if prior:
                    result.append({'key':f'Key {i+1}','previous_reserved_requests':len(prior),'previous_http_status':[r[0] for r in prior],'accepted':'not recorded before local reporting error; not resent'})
                    continue
                p=KiraProvider(secret,MODEL,transport=guard,max_tokens=1024,timeout=45)
                r=await p.translate([{'id':str(n),'source':text} for n,text in enumerate(
                    ['Xin chào mọi người','Hôm nay trời đẹp','Tôi thích đọc sách'])],'vi','en')
                result.append({'key':f'Key {i+1}','accepted':len(r.values),'failure_kind':(r.diagnostics or {}).get('failure_kind'),'unknown':r.unknown,'translations':r.values})
            return result
        report['outcomes']=asyncio.run(probe())
    else:
        # Full scheduler path, isolated from user progress and preferences.
        isolated=ROOT/f'round-{args.round}-state.sqlite3'
        if isolated.exists():raise ValueError('Round state exists; inspect instead of rerunning')
        s=Store(isolated)
        try:
            for i,secret in enumerate(secrets):s.add_kira_keys(secret,name=f'Key {i+1}')
            d=s.import_document(ROOT/'synthetic.txt',decode_txt(('\n'.join(['Hôm nay trời đẹp']*9)).encode()),'vi','en')[0]
            run,jobs=s.create_run([d],['en'],provider='kira',model=MODEL,source_lang='vi',concurrency=30,config={'kira_multi_key':True,'kira_recovery_version':2,'kira_batch_retry_limit':2,'kira_retry_budget':6})
            for i,row in enumerate(s.kira_keys()):
                digest=hashlib.sha256(secrets[i].encode()).hexdigest()
                with sqlite3.connect(budget.path) as db:
                    denied=db.execute("SELECT 1 FROM sent WHERE key=? AND code='pro_membership_required'",(digest,)).fetchone()
                if denied:s.kira_key_status(row['id'],'PERMISSION_DENIED',reason='permission',model=MODEL)
            pool=KiraPoolProvider(s,MODEL,transport=guard,max_tokens=1024,timeout=45)
            scheduler=Scheduler(s,pool);scheduler.start_many(jobs,run);scheduler.join(100)
            if scheduler._thread.is_alive():scheduler.stop();scheduler.join(50)
            assert not scheduler._thread.is_alive()
            report['state']=s.run(run)['state']
            report['rows']=[{'position':i+1,'state':r['state'],'translation':r['translation']} for i,r in enumerate(s.lines(d))]
            report['per_key']=[{'key':r['name'],'requests':pool.stats[k]['requests'],'busy':pool.busy[k],'status':r['status']} for k,r in pool.keys.items()]
        finally:s.close()
    report['requests']=guard.results;report['peak_http']=guard.peak
    with sqlite3.connect(budget.path) as db:
        report['total_reserved_line_attempts']=db.execute('SELECT COALESCE(SUM(lines),0) FROM sent').fetchone()[0]
    report['remaining']=270-report['total_reserved_line_attempts']
    (ROOT/f'live-round-{args.round}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
