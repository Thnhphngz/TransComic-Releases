"""Repeatable offline initial/retry comparison, no paid requests."""
import argparse
import asyncio
import importlib.util
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import httpx
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler


def run(cls, limited):
    with TemporaryDirectory() as directory:
        store=Store(Path(directory)/'state.db'); jobs=[]
        for file in range(3):
            doc,_=store.import_document(Path(directory)/f'{file}.txt',decode_txt(('\n'.join(f'Source {i}' for i in range(120))).encode()))
            jobs.append(store.create_job(doc,'mock','VI','EN',30,config={'recovery_successes':3,'recovery_step':5,'recovery_quiet_seconds':.05,'rate_recovery_interval':.01}))
        calls={}; active=peak=0; intervals=[]; requests=[]
        async def handler(req):
            nonlocal active,peak
            rows=json.loads(json.loads(req.content)['messages'][1]['content'])['lines']; key=rows[0]['id']; calls[key]=calls.get(key,0)+1
            start=time.monotonic(); active+=1; peak=max(peak,active); before=active
            await asyncio.sleep(.025); active-=1
            status=429 if limited and len(requests)<30 and calls[key]==1 else 200
            content='bad' if not limited and calls[key]==1 else json.dumps({'lines':[{'id':r['id'],'text':'Translation'} for r in rows]})
            requests.append({'started':start,'ended':time.monotonic(),'attempt':calls[key],'status':status,'active':before,'lines':len(rows)})
            return httpx.Response(status, headers={'Retry-After':'.05'} if status==429 else {}, json={'choices':[{'message':{'content':content}}]})
        s=cls(store,KiraProvider('fake',transport=httpx.MockTransport(handler))); start=time.monotonic(); s.start_many(jobs); s.join(60)
        assert not s._thread.is_alive()
        elapsed=time.monotonic()-start; done=sum(r['state']=='done' for j in jobs for r in store.lines(store.job(j)['document_id']))
        phases={}
        for name,number in [('initial',1),('retry',2)]:
            selected=[r for r in requests if (r['attempt']==1)==(number==1)]
            if selected:
                duration=max(r['ended'] for r in selected)-min(r['started'] for r in selected)
                phases[name]={'requests':len(selected),'lines':sum(r['lines'] for r in selected),'phase_span_seconds':duration,'http_seconds_sum':sum(r['ended']-r['started'] for r in selected),'peak':max(r['active'] for r in selected),'average_concurrency':sum(r['ended']-r['started'] for r in selected)/duration}
        report={'scenario':'429 recovery' if limited else 'invalid JSON retries','elapsed_seconds':elapsed,'done_lines':done,'peak':peak,'request_count':len(requests),'retry_count':s.retry_count,'effective_final':s.effective_concurrency,'throughput_lines_minute':done*60/elapsed,'phases':phases,'cooldown_seconds':s.cooldown_seconds}
        store.close(); return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',action='store_true');args=p.parse_args()
    cls=Scheduler
    if args.baseline:
        spec=importlib.util.spec_from_file_location('transcomic._baseline','artifacts/retry-speed/baseline_scheduler.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);cls=mod.Scheduler
    reports=[run(cls,limited) for limited in (False,True)]
    output=Path('artifacts/retry-speed')/('before.json' if args.baseline else 'after.json');output.write_text(json.dumps(reports,indent=2),encoding='utf-8');print(json.dumps(reports))
