"""Small deterministic rejection/recovery comparison; no live HTTP."""
import asyncio
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import httpx
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler


def case(root,retries):
    store=Store(root/'state.db'); store.set_setting('auto_retries',str(retries))
    doc,_=store.import_document(root/'synthetic.txt',decode_txt('\n'.join('Source '+str(n) for n in range(150)).encode()),'VI','Tiếng Anh')
    job=store.create_job(doc,'mock-model','VI','Tiếng Anh',50); counts={}; active=peak=peak_recovery=0
    async def handler(req):
        nonlocal active,peak,peak_recovery
        rows=json.loads(json.loads(req.content)['messages'][1]['content'])['lines']; key=rows[0]['id']
        counts[key]=counts.get(key,0)+1; active+=1; peak=max(peak,active)
        if counts[key]>1: peak_recovery=max(peak_recovery,active)
        await asyncio.sleep(.01); active-=1
        if counts[key]==1: return httpx.Response(429,headers={'Retry-After':'.08'},json={})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'Translation.'} for r in rows]})}}], 'usage':{'prompt_tokens':10,'completion_tokens':12,'total_tokens':22}})
    scheduler=Scheduler(store,KiraProvider('mock-secret',transport=httpx.MockTransport(handler)))
    started=time.monotonic(); scheduler.start(job); scheduler.join(20); elapsed=time.monotonic()-started
    assert not scheduler._thread.is_alive()
    done=sum(r['state']=='done' for r in store.lines(doc))
    result={'auto_retries':retries,'configured_concurrency':50,'effective_after_429':scheduler.effective_concurrency,
        'requests':scheduler.request_count,'retry_requests':scheduler.retry_count,'success_requests':scheduler.success_requests,
        'http_429':scheduler.rate_limits,'successful_lines':done,'elapsed_seconds':round(elapsed,4),
        'successful_lines_per_minute':round(done*60/elapsed,2),'shared_cooldown_window_seconds':round(scheduler.cooldown_seconds,4),
        'peak_initial':peak,'peak_recovery':peak_recovery,'mock_usage_only':scheduler.usage or None,'real_api_requests':0}
    assert peak<=50 and peak_recovery<=1
    assert done==(150 if retries else 0)
    store.close(); return result


if __name__=='__main__':
    with TemporaryDirectory() as temporary:
        root=Path(temporary); report=[]
        for retries in [0,3]: report.append(case(root/str(retries),retries))
    out=Path('artifacts/final/retry-mock-comparison.json'); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report))
