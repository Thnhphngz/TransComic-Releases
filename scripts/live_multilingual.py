"""New user authorization: exactly three DOCX, <=3 file/locale translations each.

No budget question or additional monetary cap. Frozen DeepSeek, five retries,
ledger before HTTP, no uncertain replay. Does not share previous round ledgers.
"""
import json,time,math,hashlib,os
from pathlib import Path
import httpx
from transcomic.storage import Store
from transcomic.bulk import import_many,plan_exports,write_exports
from transcomic.languages import language
from transcomic.translation import Scheduler
from transcomic.providers import KiraProvider
from transcomic.quality import language_evidence
from scripts.live_kira_three import key_readonly,save
import scripts.live_three_docx_speed as previous

OUT=Path('artifacts/multilingual/live')
MODEL='deepseek-v4.1-flash'
ASSIGNMENTS=[(Path(r'D:\word 50 cach\3-4.docx'),['ja','id','hi']),
             (Path(r'D:\word 50 cach\5-6.docx'),['de','ms','zh-CN']),
             (Path(r'D:\Sourch Code\TransComic\7-8.docx'),['fil','en-CA','fr-CA'])]

class Router(httpx.AsyncBaseTransport):
    def __init__(self,ledger,entries,scheduler,store):
        self.ledger,self.entries,self.scheduler,self.store=ledger,entries,scheduler,store
        self.by_line={r['id']:e for e in entries for b in store.batches(e['job_id']) for r in b['payload']}
        self.network=None;self.active=0;self.peak=0;self.last_locale=None
    async def handle_async_request(self,request):
        body=json.loads(request.content);rows=json.loads(body['messages'][1]['content'])['lines']
        entry=self.by_line[rows[0]['id']]
        assert all(self.by_line[r['id']] is entry for r in rows)
        assert 'Target locale: '+entry['locale']+';' in body['messages'][0]['content']
        assert not self.active or self.last_locale==entry['locale']
        self.last_locale=entry['locale'];self.active+=1;self.peak=max(self.peak,self.active)
        if self.network is None:self.network=httpx.AsyncHTTPTransport(retries=0)
        delegate=object.__new__(previous.LedgerTransport)
        delegate.ledger=self.ledger;delegate.entry=entry;delegate.scheduler=self.scheduler;delegate.store=self.store;delegate.transport=self.network
        try:return await delegate.handle_async_request(request)
        finally:self.active-=1
    async def aclose(self):
        if self.network:await self.network.aclose();self.network=None

def main():
    OUT.mkdir(parents=True,exist_ok=True);previous.OUT=OUT
    ledger_path=OUT/'authorization-ledger.json'
    sources=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'locales':targets} for p,targets in ASSIGNMENTS]
    if ledger_path.exists():
        ledger=json.loads(ledger_path.read_text(encoding='utf-8'));assert ledger['sources']==sources
        if any(e['state'] not in ('completed','stopped') for e in ledger['passes']):raise RuntimeError('Reserved/unfinished round: do not replay')
    else:
        ledger={'authorization':'2026-10-13 multilingual round: user permits Kira <=3 tests per exact DOCX; no budget question','model':MODEL,'max_passes_per_file':3,'sources':sources,'passes':[]}
        with ledger_path.open('x',encoding='utf-8') as f:json.dump(ledger,f);f.flush();os.fsync(f.fileno())
    key=key_readonly();store=Store(OUT/'results.sqlite3')
    try:
        for source,targets in ASSIGNMENTS:
            already=[e for e in ledger['passes'] if e['source']==str(source)]
            if already:
                assert len(already)==3
                continue
            doc=import_many(store,[source],'Tiếng Việt',language(targets[0]).name)['document_ids'][0]
            run,jobs=store.create_run([doc],targets,provider='kira',model=MODEL,source_lang='vi',concurrency=30)
            entries=[]
            for ordinal,jid in enumerate(jobs,1):
                j=store.job(jid);needed=len(store.lines(j['document_id']))
                entry={'source':str(source),'locale':language(j['target_lang']).locale,'pass_number':ordinal,'job_id':jid,'document_id':j['document_id'],'run_id':run,'max_requests':math.ceil(needed/3)*6,'state':'reserved_before_start','requests':[],'configuration':j}
                entries.append(entry);ledger['passes'].append(entry)
            assert sum(e['source']==str(source) for e in ledger['passes'])==3
            save(ledger_path,ledger)
            scheduler=Scheduler(store,None);router=Router(ledger,entries,scheduler,store)
            scheduler.provider=KiraProvider(key,MODEL,transport=router,prompt_version=store.job(jobs[0])['prompt_version'])
            start=time.monotonic();scheduler.start_many(jobs,run)
            while scheduler._thread.is_alive():
                scheduler.join(1)
                if time.monotonic()-start>1800:scheduler.stop()
            for entry in entries:
                rows=store.lines(entry['document_id']);attempts=[a for b in store.batches(entry['job_id']) for a in store.attempts(b['id'])]
                usage={k:sum((r.get('usage') or {}).get(k,0) for r in entry['requests']) for k in ('prompt_tokens','completion_tokens','total_tokens')}
                observed=[r for r in entry['requests'] if r.get('ended_monotonic')]
                span=max(r['ended_monotonic'] for r in observed)-min(r['started_monotonic'] for r in observed) if observed else None
                evidence={k:sum(language_evidence(r['source'],r.get('translation') or '','vi',entry['locale'])[0]==k for r in rows if r.get('translation')) for k in ('compatible','suspected','insufficient')}
                warnings=store.warning_rows(entry['document_id'])
                summary={'state':store.job(entry['job_id'])['state'],'lines':len(rows),'done':sum(r['state']=='done' for r in rows),'requests':len(entry['requests']),'retries':sum(a['attempt_number']>1 for a in attempts),'max_attempt':max((a['attempt_number'] for a in attempts),default=0),'429':sum(r.get('http_status')==429 for r in entry['requests']),'504':sum(r.get('http_status')==504 for r in entry['requests']),'usage':usage,'requests_without_usage':sum(not r.get('usage') for r in entry['requests']),'http_phase_span_seconds':span,'language_evidence':evidence,'warning_rows':len(warnings),'peak_global_http':router.peak,'source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==next(s['sha256'] for s in sources if s['path']==str(source))}
                entry['summary']=summary;entry['state']='completed' if summary['state']=='finished' else 'stopped'
                save(ledger_path,ledger) # Never replay HTTP after an export/report error.
                exports=write_exports(store,plan_exports(store.export_snapshot([entry['document_id']]),OUT/source.stem,mode='custom'),allow_incomplete=True)
                assert all(e['state']=='exported' for e in exports)
                entry['exports']=exports;save(ledger_path,ledger)
                save(OUT/f'{source.stem}-{entry["locale"]}-lines.json',rows);save(OUT/f'{source.stem}-{entry["locale"]}-warnings.json',warnings)
                print(json.dumps({'file':source.name,'locale':entry['locale'],**summary}),flush=True)
            save(OUT/f'{source.stem}-console.json',store.log.snapshot())
            if scheduler._stopped.is_set() or scheduler.intervention_reason or store.run(run)['state']!='finished':break
    finally:store.close()

if __name__=='__main__':main()
