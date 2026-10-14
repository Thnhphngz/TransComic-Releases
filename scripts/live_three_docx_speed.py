"""User-authorized round: exact three DOCX, at most two whole-file passes each.

No separate monetary/token ceiling requested by user. Six attempts maximum per
batch, ledger reserved before each HTTP call; unfinished reservations never replay.
Pass 1 executes the saved pre-change scheduler, pass 2 the current scheduler.
No Gemini, no model change, and source files are never modified.
"""
import argparse
import importlib.util
import json
import math
import os
import re
import time
import hashlib
from pathlib import Path
import httpx
from lxml import html
from transcomic.storage import Store
from transcomic.documents import ImportedText,TextLine,translatable
from transcomic.docx_document import import_docx
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler
from transcomic.bulk import plan_exports,write_exports
from scripts.live_kira_three import key_readonly,save

OUT=Path('artifacts/retry-speed/live')
MODEL='deepseek-v4.1-flash'
SOURCES=[Path(r'D:\word 50 cach\3-4.docx'),Path(r'D:\word 50 cach\5-6.docx'),Path(r'D:\Sourch Code\TransComic\7-8.docx')]


class LedgerTransport(httpx.AsyncBaseTransport):
    def __init__(self,ledger,entry,scheduler,store):
        self.ledger=ledger;self.entry=entry;self.scheduler=scheduler;self.store=store
        self.transport=httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self,request):
        body=json.loads(request.content);assert body['model']==MODEL and 'max_tokens' not in body
        rows=json.loads(body['messages'][1]['content'])['lines'];assert 1<=len(rows)<=3
        line_ids=[r['id'] for r in rows]
        job=self.entry['job_id'];batch=next(b for b in self.store.batches(job) if line_ids[0] in {r['id'] for r in b['payload']})
        attempt=self.store.attempts(batch['id'])[-1]
        assert attempt['state']=='prepared' and 1<=attempt['attempt_number']<=6
        all_requests=[r for e in self.ledger['passes'] for r in e['requests']]
        assert attempt['id'] not in {r['correlation_id'] for r in all_requests}
        if len(self.entry['requests'])>=self.entry['max_requests']:
            self.scheduler._stopped.set();raise RuntimeError('Authorized pass request bound exhausted; no HTTP sent')
        record={'correlation_id':attempt['id'],'batch_id':batch['id'],'attempt_number':attempt['attempt_number'],'line_ids':line_ids,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'state':'reserved_before_http'}
        self.entry['requests'].append(record);save(OUT/'authorization-ledger.json',self.ledger)
        started=time.monotonic();record['started_monotonic']=started;record['active_at_http_start']=self.scheduler.active
        try:
            response=await self.transport.handle_async_request(request);await response.aread()
            record.update(state='response_received',http_status=response.status_code,http_seconds=time.monotonic()-started,ended_monotonic=time.monotonic())
            try:record['usage']=response.json().get('usage')
            except ValueError:record['usage']=None
            usage=record['usage'] or {}
            # Anomaly stop, not a normal budget: guard runaway provider output.
            if usage.get('completion_tokens',0)>100000:
                record['halt_reason']='abnormal_output_usage';self.scheduler._stopped.set()
            return response
        except Exception as exc:
            record.update(state='uncertain_no_replay',exception=type(exc).__name__);self.scheduler._stopped.set();raise
        finally:save(OUT/'authorization-ledger.json',self.ledger)

    async def aclose(self):await self.transport.aclose()


def summarize(store,job,elapsed,scheduler,entry):
    rows=store.lines(store.job(job)['document_id']);phases={}
    attempts=[a for b in store.batches(job) for a in store.attempts(b['id'])]
    for name,initial in [('initial',True),('retry',False)]:
        selected=[a for a in attempts if (a['attempt_number']==1)==initial]
        ds=[a['diagnostics'] or {} for a in selected]
        phases[name]={'requests':len(selected),'attempt_lines':sum(d.get('line_count',0) for d in ds),
            'queue_wait_seconds_sum':sum(d.get('queue_wait_seconds',0) for d in ds),
            'cooldown_wait_seconds_sum':sum(d.get('cooldown_wait_seconds',0) for d in ds),
            'semaphore_wait_seconds_sum':sum(d.get('semaphore_wait_seconds',0) for d in ds),
            'http_seconds_sum':sum(d.get('http_seconds',0) for d in ds),
            'parse_seconds_sum':sum(d.get('parse_seconds',0) for d in ds),
            'database_seconds_sum':sum(d.get('database_seconds',0) for d in ds),
            'elapsed_seconds_sum':sum(d.get('elapsed_seconds',0) for d in ds),
            'peak_active':max((d.get('active_at_dispatch',0) for d in ds),default=0)}
        observed=[r for r in entry['requests'] if (r['attempt_number']==1)==initial and r.get('ended_monotonic')]
        if observed:
            span=max(r['ended_monotonic'] for r in observed)-min(r['started_monotonic'] for r in observed)
            phases[name].update(phase_span_seconds=span,average_http_concurrency=sum(r['http_seconds'] for r in observed)/span,peak_http_concurrency=max(r['active_at_http_start'] for r in observed),attempt_lines_per_minute=sum(len(r['line_ids']) for r in observed)*60/span)
        phases[name]['wait_metadata_available']=all('cooldown_wait_seconds' in d for d in ds) if ds else False
    done=sum(r['state']=='done' for r in rows)
    return {'state':store.job(job)['state'],'lines':len(rows),'done':done,'missing':len(rows)-done,'requests':len(entry['requests']),'429':sum(r.get('http_status')==429 for r in entry['requests']),'504':sum(r.get('http_status')==504 for r in entry['requests']),'retry_requests':scheduler.retry_count,'elapsed_seconds':elapsed,'throughput_lines_minute':done*60/elapsed,'configured_concurrency':30,'effective_final':scheduler.effective_concurrency,'usage':scheduler.usage,'phases':phases,'max_attempt':max((a['attempt_number'] for a in attempts),default=0)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pass-number',type=int,choices=(1,2),required=True);args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'authorization-ledger.json'
    sources=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in SOURCES]
    if path.exists():
        ledger=json.loads(path.read_text(encoding='utf-8'));assert ledger['sources']==sources
        if any(e['state'] not in ('completed','stopped') for e in ledger['passes']):raise RuntimeError('Unfinished pass reservation: no replay')
    else:
        ledger={'authorization':'2026-10-13 new three-DOCX round; user explicitly requested no separate money/token cap','model':MODEL,'max_passes_per_file':2,'sources':sources,'passes':[]}
        with path.open('x',encoding='utf-8') as f:json.dump(ledger,f);f.flush();os.fsync(f.fileno())
    url='https://kiraai.vn/models/'+MODEL+'/'
    response=httpx.get(url,timeout=25,follow_redirects=True);response.raise_for_status()
    tree=html.fromstring(response.text);prices=[' '.join(x.text_content().split()) for x in tree.xpath('//*[contains(@class,"mdp-price-raw")]/../..')]
    rates={}
    for key,label in [('input','Đầu vào'),('output','Đầu ra')]:
        text=next(r for r in prices if r.startswith(label));numbers=[int(n.replace('.','')) for n in re.findall(r'([\d.]+)đ',text)];rates[key]=numbers[0];rates[key+'_sale']=numbers[-1]
    save(OUT/f'prices-pass-{args.pass_number}.json',{'source':url,'observed_rows':prices,'vnd_per_million':rates})
    cls=Scheduler
    if args.pass_number==1:
        spec=importlib.util.spec_from_file_location('transcomic._baseline','artifacts/retry-speed/baseline_scheduler.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);cls=m.Scheduler
    key=key_readonly();store=Store(OUT/'results.sqlite3');store.set_setting('auto_retries','5')
    try:
        for source in SOURCES:
            if any(e['source']==str(source) and e['pass_number']==args.pass_number for e in ledger['passes']):continue
            assert sum(e['source']==str(source) for e in ledger['passes'])<2
            if args.pass_number==2:assert any(e['source']==str(source) and e['pass_number']==1 for e in ledger['passes'])
            obj=import_docx(source);needed=sum(translatable(u.text) for u in obj.units)
            doc,_=store.import_document(source,ImportedText(tuple(TextLine(u.text,'') for u in obj.units),'docx',obj.raw),'Tiếng Việt','Tiếng Anh',document_format='docx',locators=[u.locator for u in obj.units])
            maximum=math.ceil(needed/3)*6
            job=store.create_job(doc,MODEL,'Tiếng Việt','Tiếng Anh',30,retry_504=True,max_requests=maximum)
            entry={'source':str(source),'pass_number':args.pass_number,'scheduler':'baseline' if args.pass_number==1 else 'current','document_id':doc,'job_id':job,'max_requests':maximum,'state':'reserved_before_start','requests':[],'configuration':store.job(job)}
            ledger['passes'].append(entry);save(path,ledger)
            s=cls(store,None);transport=LedgerTransport(ledger,entry,s,store);s.provider=KiraProvider(key,MODEL,timeout=90,transport=transport)
            start=time.monotonic();s.start(job)
            while s._thread.is_alive():
                s.join(1)
                if time.monotonic()-start>900:s.stop()
            elapsed=time.monotonic()-start
            summary=summarize(store,job,elapsed,s,entry);entry['summary']=summary;entry['state']='stopped' if s._stopped.is_set() or s.intervention_reason else 'completed'
            summary['estimated_vnd_original_reported_usage']=sum(((r.get('usage') or {}).get('prompt_tokens',0)*rates['input']+(r.get('usage') or {}).get('completion_tokens',0)*rates['output'])/1e6 for r in entry['requests'])
            summary['estimated_vnd_sale_reported_usage']=sum(((r.get('usage') or {}).get('prompt_tokens',0)*rates['input_sale']+(r.get('usage') or {}).get('completion_tokens',0)*rates['output_sale'])/1e6 for r in entry['requests'])
            summary['requests_without_usage']=sum(not r.get('usage') for r in entry['requests'])
            summary['source_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==next(p['sha256'] for p in sources if p['path']==str(source))
            save(path,ledger)  # Completion survives an export/report failure; never replay HTTP.
            exports=write_exports(store,plan_exports(store.export_snapshot([doc]),OUT/f'pass-{args.pass_number}'/source.stem,mode='custom'),allow_incomplete=True)
            assert exports and all(e['state']=='exported' for e in exports)
            entry['exports']=exports;save(path,ledger);save(OUT/f'{source.stem}-pass-{args.pass_number}-lines.json',store.lines(doc));save(OUT/f'{source.stem}-pass-{args.pass_number}-console.json',store.log.snapshot())
            print(json.dumps({'file':source.name,'pass_number':args.pass_number,**summary}),flush=True)
            if entry['state']=='stopped':break
    finally:store.close()


if __name__=='__main__':main()
