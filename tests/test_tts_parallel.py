import json
import threading
import time
from pathlib import Path
from tests.test_tts import prepare,FakeEngine,wave
from transcomic.tts.scheduler import Scheduler
from transcomic.tts.parallel import SharedLane
from transcomic.tts.process_engine import EngineFailure,Stopped


def setup(store,run,monkeypatch):
    import transcomic.tts.scheduler as module
    monkeypatch.setattr(module,'backend_plan',lambda _:['CUDAExecutionProvider']);monkeypatch.setattr('transcomic.tts.concurrency.resource_gate',lambda n:(True,''))
    config=json.loads(store.run(run)['config']);config.update(device='Auto',workers=2);store.execute('UPDATE runs SET config=? WHERE id=?',(json.dumps(config),run))


def test_parallel_out_of_order_atomic_claim_and_correct_names(tmp_path,monkeypatch):
    barrier=threading.Barrier(2);order=[]
    class Lane(SharedLane):
        def synthesize(self,text,*args):
            if text in ('One','Two'):barrier.wait(5)
            time.sleep(.06 if text=='One' else .001);order.append(text);yield wave()
    class Pool:
        def __init__(self,*args):self.backend='CUDAExecutionProvider';self.lanes=[Lane(self,i) for i in range(2)]
        def probe(self):pass
        def close(self):pass
    store,run,output,root=prepare(tmp_path,'One\nTwo\nThree\nFour');setup(store,run,monkeypatch);scheduler=Scheduler(store,None,engine_factory=FakeEngine);scheduler.parallel_factory=Pool;scheduler.start(run);scheduler.thread.join(10)
    assert order.index('Two')<order.index('One') and len(order)==len(set(order))==4
    assert store.run(run)['state']=='completed' and store.progress(run)=={'success':4}
    assert [i['filename'] for i in store.items(run)]==['0001.wav','0002.wav','0003.wav','0004.wav'];store.close()


def test_parallel_oom_reduces_one_and_keeps_leases_safe(tmp_path,monkeypatch):
    entered=threading.Barrier(2)
    class Lane(SharedLane):
        def synthesize(self,*args):
            entered.wait(5)
            if self.index==0:raise EngineFailure('CUDA out of memory')
            self.pool.cancelled.wait(5);raise Stopped();yield
    class Pool:
        def __init__(self,*args):self.backend='CUDAExecutionProvider';self.cancelled=threading.Event();self.lanes=[Lane(self,i) for i in range(2)]
        def probe(self):pass
        def close(self):pass
        def cancel(self):self.cancelled.set()
    store,run,output,root=prepare(tmp_path,'One\nTwo\nThree');setup(store,run,monkeypatch);scheduler=Scheduler(store,None,engine_factory=FakeEngine);scheduler.parallel_factory=Pool;scheduler.start(run);scheduler.thread.join(10)
    assert not scheduler.busy and store.run(run)['state']=='completed' and store.progress(run)=={'success':3}
    assert all(not i['attempt'] or i['state']=='success' for i in store.items(run));store.close()


def test_runtime_manager_cpu_fallback_does_not_install_dependencies(monkeypatch):
    from transcomic.tts.runtime_manager import RuntimeManager
    from types import SimpleNamespace
    monkeypatch.setattr('transcomic.tts.runtime_manager.providers',lambda:['CUDAExecutionProvider','CPUExecutionProvider'])
    monkeypatch.setattr('transcomic.tts.runtime_manager.diagnostics',lambda:dict(compatible=True))
    class Engine:
        def __init__(self,m,v,b):self.backend=b;self.runtime_info={'backend':b}
        def probe(self,*args):
            if self.backend=='CUDAExecutionProvider':raise EngineFailure('Missing cublasLt64_12.dll')
            return 1
        def close(self):pass
    manager=SimpleNamespace(ready=lambda _:True,size=lambda _:0)
    result=RuntimeManager(manager,Engine).prepare();assert result['backend']=='CPUExecutionProvider' and 'cublasLt64_12.dll' in result['gpu_traceback']
