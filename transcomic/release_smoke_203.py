"""Frozen-only synthetic admission acceptance, called inside isolated smoke."""
import asyncio
from collections import Counter
import json
from pathlib import Path
import threading


def verify_admission(window,root,wait):
    import httpx
    import numpy as np
    from PySide6.QtGui import QImage,QColor
    from PySide6.QtTest import QTest
    from .automation.adapters import Translation,Kokoro
    from .automation.validation import defaults
    from .deepseek import DeepSeekProvider,MODEL
    from .kira_pool import KiraPoolProvider
    repo=window.automation_repo;services=window.automation_services;controller=window.automation_controller
    prior=(services.translation,services.kokoro,services.preflight);results={}
    for provider in ('kira','deepseek'):
        # Keep fixture/report paths short even under pytest's unique run roots.
        area=Path(root)/('a203k' if provider=='kira' else 'a203d');area.mkdir();output=area/'projects';output.mkdir()
        cfg=defaults(window.store);cfg.update(provider=provider,model=MODEL if provider=='deepseek' else 'mock',workers=30,
            device='CPU',output=str(output),capcut_mode='merged',project_name='Synthetic admission',
            kira_recovery_version=4,kira_completion_policy=1,kira_dispatch_policy=1,translation_completion_policy=1,deepseek_batch_size=3)
        wid=repo.create('Frozen '+provider,cfg);docs=[]
        for i in range(12):
            file=area/f'{i:03}.txt';file.write_text('\n'.join(['Người lữ khách trở về ngôi nhà cũ']*3),encoding='utf8')
            group=repo.add(wid,[file])[0];images=area/f'{i:03}-images';images.mkdir()
            for n in range(3):
                image=QImage(20,30,QImage.Format_RGB32);image.fill(QColor(20+n,40,80));assert image.save(str(images/f'{n:04}.png'))
            repo.pair_images(group,images);docs.append(repo.group(group)['document_id'])
        owners={r['id']:i for i,doc in enumerate(docs) for r in window.store.lines(doc)}
        started=set();seen=Counter();release=threading.Event();nine=threading.Event();voice=threading.Event();calls=[]
        class TinyEngine:
            def __init__(self,*args):self.backend='CPUExecutionProvider'
            def probe(self,*args):pass
            def synthesize(self,text,*args):
                calls.append(text);voice.set();yield np.sin(np.arange(800,dtype=np.float32)*.12)*.1
            def close(self):pass
        async def handler(request):
            lines=json.loads(json.loads(request.content)['messages'][1]['content'])['lines'];index=owners[lines[0]['id']]
            started.add(index);seen.update(r['id'] for r in lines)
            while index!=2 and not release.is_set() and not (provider=='kira' and index<9 and nine.is_set()):await asyncio.sleep(.004)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'The synthetic story continues in the quiet village'} for r in lines]})}}]})
        def make(store,job):
            if provider=='deepseek':return DeepSeekProvider('synthetic',batch_size=3,transport=httpx.MockTransport(handler))
            return KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
        services.preflight=lambda _:None;services.translation=Translation(repo,make,network_probe=lambda _:True)
        services.kokoro=Kokoro(repo,services.tts_store,None,engine_factory=TinyEngine)
        assert controller.validate(wid)['passed'];controller.start(wid)
        try:
            wait(lambda:voice.is_set(),15)
            assert all(r['state']=='done' for r in window.store.lines(docs[2]))
            if provider=='deepseek':wait(lambda:10 in started,15)
            else:
                QTest.qWait(200);assert 10 not in started and started<=set(range(10))
                nine.set();wait(lambda:10 in started,15)
            assert not release.is_set() and any(r['state']!='done' for r in window.store.lines(docs[9]))
            assert len(services.translation.scheduler.admission.active)<=10
            release.set();wait(lambda:not controller.busy,35)
            assert repo.workset(wid)['state']=='completed',[(e['stage'],e['message']) for e in repo.events(wid)[:4]]
            assert len(seen)==36 and set(seen.values())=={1} and len(calls)==36
            results[provider]=dict(passed=True,files=12,rows=36,requests=12,tts_calls=36,active_file_limit=10,
                completion_opens_next='one file' if provider=='deepseek' else 'nine of ten',immediate_tts=True,duplicate_row_sends=0)
        finally:
            release.set()
            if controller.busy:controller.stop();wait(lambda:not controller.busy,20)
    services.translation,services.kokoro,services.preflight=prior
    return results
