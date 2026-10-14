"""New authorization only: <=5 file passes; explicit approved VND ceiling required.

Does not modify the user's database. Each HTTP request has a durable prepaid
reservation including retries. An existing ledger refuses automatic replay.
Prices and token bounds are estimates; missing usage or a bound violation stops
the test. This is not a provider-enforced billing cap.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
import httpx
from lxml import html
from transcomic.docx_document import import_docx
from transcomic.documents import ImportedText, TextLine
from transcomic.providers import KiraProvider
from transcomic.storage import Store
from transcomic.translation import Scheduler
from scripts.live_kira_three import key_readonly, save

MODEL='deepseek-v4.1-flash'
SOURCE=Path(r'D:\word 50 cach\7-8.docx')
OUT=Path('artifacts/retry-management/live-deepseek')


class BudgetTransport(httpx.AsyncBaseTransport):
    def __init__(self, ledger, scheduler, price):
        self.ledger=ledger; self.scheduler=scheduler; self.price=price
        self.transport=httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        data=json.loads(request.content)
        assert data['model']==MODEL and data['max_tokens']==2048
        rows=json.loads(data['messages'][1]['content'])['lines']; assert len(rows)<=3
        bound=(len(request.content)+256)*self.price['input']/1e6+2048*self.price['output']/1e6
        ledger=self.ledger
        used=sum(r['reserved_vnd'] for r in ledger['requests'])
        if used+bound>ledger['max_vnd'] or len(ledger['requests'])>=ledger['max_requests']:
            self.scheduler._stopped.set()
            raise RuntimeError('Test request or prepaid cost budget exhausted; no HTTP sent')
        record={'pass':ledger['current_pass'],'number':len(ledger['requests'])+1,'line_ids':[r['id'] for r in rows], 'input_token_bound':len(request.content)+256,'output_token_limit':2048,'reserved_vnd':bound,'state':'reserved_before_http'}
        ledger['requests'].append(record); save(OUT/'authorization-ledger.json',ledger)
        try:
            response=await self.transport.handle_async_request(request)
            await response.aread()
            record['http_status']=response.status_code; record['state']='response_received'
            try: usage=response.json().get('usage')
            except ValueError: usage=None
            record['usage']=usage
            if response.status_code==200:
                if not usage or not isinstance(usage.get('prompt_tokens'),int) or not isinstance(usage.get('completion_tokens'),int):
                    self.scheduler._stopped.set(); record['halt_reason']='missing_usage_cost_unverified'
                else:
                    record['estimated_reported_vnd']=(usage['prompt_tokens']*self.price['input']+usage['completion_tokens']*self.price['output'])/1e6
                    if usage['prompt_tokens']>record['input_token_bound'] or usage['completion_tokens']>2048:
                        self.scheduler._stopped.set(); record['halt_reason']='provider_usage_exceeds_reserved_bound'
                        record['reserved_vnd']=max(bound,record['estimated_reported_vnd'])
            return response
        except Exception as exc:
            record['state']='uncertain_no_replay'; record['exception']=type(exc).__name__
            self.scheduler._stopped.set(); raise
        finally: save(OUT/'authorization-ledger.json',ledger)

    async def aclose(self): await self.transport.aclose()


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--approved-max-vnd',type=float,required=True); parser.add_argument('--passes',type=int,default=1)
    args=parser.parse_args(); assert 1<=args.passes<=5 and args.approved_max_vnd>0
    OUT.mkdir(parents=True,exist_ok=True); ledger_path=OUT/'authorization-ledger.json'
    if ledger_path.exists(): raise RuntimeError('Existing authorization ledger: no automatic replay')
    obj=import_docx(SOURCE); assert len(obj.units)==125
    url='https://kiraai.vn/models/'+MODEL+'/'
    page=httpx.get(url,timeout=25,follow_redirects=True); page.raise_for_status(); tree=html.fromstring(page.text)
    rows=[' '.join(x.text_content().split()) for x in tree.xpath('//*[contains(@class,"mdp-price-raw")]/../..')]
    price={}
    for kind,label in [('input','\u0110\u1ea7u v\u00e0o'),('output','\u0110\u1ea7u ra')]:
        row=next(r for r in rows if r.startswith(label)); price[kind]=int(re.findall(r'([\d.]+)\u0111',row)[0].replace('.',''))
    save(OUT/'prices.json',{'source':url,'checked_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'original_vnd_per_million':price,'observed_rows':rows})
    key=key_readonly()
    ledger={'model':MODEL,'source_sha256':hashlib.sha256(obj.raw).hexdigest(),'max_passes':5,'requested_passes':args.passes,'max_vnd':args.approved_max_vnd,'max_requests':5*42*6,'current_pass':0,'requests':[],'passes':[]}
    with ledger_path.open('x',encoding='utf-8') as f: json.dump(ledger,f); f.flush(); os.fsync(f.fileno())
    store=Store(OUT/'results.sqlite3'); store.set_setting('auto_retries','5')
    try:
        for n in range(1,args.passes+1):
            ledger['current_pass']=n; save(ledger_path,ledger)
            doc,_=store.import_document(SOURCE,ImportedText(tuple(TextLine(u.text,'') for u in obj.units),'docx',obj.raw),'Tiếng Việt','Tiếng Anh',document_format='docx',locators=[u.locator for u in obj.units])
            job=store.create_job(doc,MODEL,'Tiếng Việt','Tiếng Anh',30,retry_504=True,max_requests=252,config={'rate_wait_budget':90})
            s=Scheduler(store,None); transport=BudgetTransport(ledger,s,price); s.provider=KiraProvider(key,MODEL,max_tokens=2048,transport=transport)
            s.start(job); s.join(600)
            if s._thread.is_alive(): s.stop(); s.join(100)
            assert not s._thread.is_alive()
            lines=store.lines(doc)
            result={'pass':n,'job_id':job,'document_id':doc,'state':store.job(job)['state'],'done':sum(r['state']=='done' for r in lines),'errors':sum(r['state']=='error' for r in lines),'unknown':sum(r['state']=='unknown' for r in lines),'retry_requests':s.retry_count,'http_429':s.rate_limits,'request_count':s.request_count,'usage':s.usage,'user_paused':s._paused.is_set()}
            ledger['passes'].append(result); save(ledger_path,ledger); save(OUT/f'pass-{n}-lines.json',lines)
            print(json.dumps(result))
            if s._stopped.is_set() or s.intervention_reason: break
        save(OUT/'events.json',store.log.snapshot())
    finally: store.close()


if __name__=='__main__': main()
