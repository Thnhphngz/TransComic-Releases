import json
from pathlib import Path
import pytest
from tests.test_tts import prepare,FakeEngine,wave
from transcomic.tts.scheduler import Scheduler
from transcomic.tts.output import Outputs
from transcomic.tts.runtime import friendly


def test_local_segment_failure_continues_other_segments(tmp_path):
    class BadText(FakeEngine):
        def synthesize(self,text,*args):
            if text=='Bad':raise ValueError('Segment rejected')
            yield wave()
    store,run,output,root=prepare(tmp_path,'One\nBad\nThree');scheduler=Scheduler(store,None,engine_factory=BadText);scheduler.start(run);scheduler.thread.join(10)
    assert store.progress(run)=={'success':2,'error':1} and store.run(run)['state']=='partial'
    folder=Path(store.docs(run)[0]['folder']);assert (folder/'0001.wav').exists() and (folder/'0003.wav').exists() and not (folder/'0002.wav').exists()
    store.close()


def test_auto_mid_inference_fallback_retires_gpu_once(tmp_path,monkeypatch):
    from transcomic.tts.process_engine import EngineFailure
    import transcomic.tts.scheduler as module
    class BrokenGpu(FakeEngine):
        closed=[]
        def close(self):self.closed.append(self.backend)
        def synthesize(self,*args):
            if self.backend=='mock-GPU':raise EngineFailure('GPU failed')
            yield wave()
    store,run,output,root=prepare(tmp_path,'One\nTwo');config=json.loads(store.run(run)['config']);config['device']='Auto';store.execute('UPDATE runs SET config=? WHERE id=?',(json.dumps(config),run))
    monkeypatch.setattr(module,'backend_plan',lambda _:['mock-GPU']);scheduler=Scheduler(store,None,engine_factory=BrokenGpu);scheduler.start(run);scheduler.thread.join(10)
    assert store.run(run)['state']=='completed' and all(i['backend']=='CPUExecutionProvider' for i in store.items(run))
    assert BrokenGpu.closed.count('mock-GPU')==1;store.close()


def test_friendly_missing_dependency_and_durable_technical_log(tmp_path):
    from transcomic.tts.runtime import logger
    error=ModuleNotFoundError("No module named 'onnxruntime'")
    assert 'Kokoro' in friendly(error) and 'ModuleNotFoundError' not in friendly(error)
    log=logger(tmp_path/'logs')
    try:raise error
    except ModuleNotFoundError:log.exception('Fixture runtime error')
    assert 'Traceback' in (tmp_path/'logs'/'technical.log').read_text(encoding='utf8')


def test_source_launcher_selects_only_marked_project_env(tmp_path,monkeypatch):
    import transcomic.dev_runtime as module
    python=module.project_python(tmp_path);python.parent.mkdir(parents=True);python.write_bytes(b'fixture')
    calls=[];monkeypatch.setattr(module.subprocess,'call',lambda args:calls.append(args) or 7)
    assert module.launch(tmp_path,['--fixture']) is None
    (python.parents[1]/'.transcomic-ready').write_text('ready');assert module.launch(tmp_path,['--fixture'])==7
    assert calls[0]==[str(python),str(tmp_path/'run_transcomic.py'),'--fixture']
    monkeypatch.setattr(module.sys,'frozen',True,raising=False);assert module.launch(tmp_path,[]) is None


def test_gpu_only_mid_inference_failure_never_switches_cpu(tmp_path,monkeypatch):
    from transcomic.tts.process_engine import EngineFailure
    import transcomic.tts.scheduler as module
    class Broken(FakeEngine):
        def synthesize(self,*args):raise EngineFailure('GPU failed');yield
    store,run,output,root=prepare(tmp_path,'One\nTwo');config=json.loads(store.run(run)['config']);config['device']='GPU';store.execute('UPDATE runs SET config=? WHERE id=?',(json.dumps(config),run))
    monkeypatch.setattr(module,'backend_plan',lambda _:['mock-GPU']);scheduler=Scheduler(store,None,engine_factory=Broken);scheduler.start(run);scheduler.thread.join(10)
    assert store.run(run)['state']=='paused' and store.progress(run)=={'error':1,'pending':1} and not list(root.rglob('*.wav'));store.close()


def test_partial_output_allocation_can_resume_without_reassigning_owned_folder(tmp_path,monkeypatch):
    from transcomic.tts.storage import TtsStore
    store=TtsStore(tmp_path/'tts.sqlite3');run=store.draft()
    for name in ('One','Two'):store.add_document(run,dict(name=name,text='Hello',line_count=1,path=None))
    config=dict(language='en-us',voice='af_heart',speed=1,format='wav',device='CPU',variant='standard',split='lines')
    output=Outputs(store);plans=output.plan(run,'custom',str(tmp_path),'wav');original=Path.mkdir
    def interrupted(path,*a,**k):
        if path==Path(plans[1]['folder']):raise PermissionError('Fixture disk interruption')
        return original(path,*a,**k)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'mkdir',interrupted)
        with pytest.raises(PermissionError):output.confirm(run,config,plans)
    owned=store.docs(run)[0]['folder'];ids=[i['id'] for i in store.items(run)]
    output.confirm(run,config,output.plan(run,'custom',str(tmp_path),'wav'))
    assert store.docs(run)[0]['folder']==owned and [i['id'] for i in store.items(run)]==ids
    scheduler=Scheduler(store,None,engine_factory=FakeEngine);scheduler.start(run);scheduler.thread.join(10)
    assert store.run(run)['state']=='completed' and store.progress(run)=={'success':2};store.close()


def test_stop_racing_process_exit_returns_pending_not_error(tmp_path):
    import threading
    from transcomic.tts.process_engine import EngineFailure
    entered=threading.Event();cancelled=threading.Event()
    class ExitRace(FakeEngine):
        def cancel(self):cancelled.set()
        def synthesize(self,*args):
            entered.set();assert cancelled.wait(5);raise EngineFailure('Process exited');yield
    store,run,output,root=prepare(tmp_path,'One\nTwo');scheduler=Scheduler(store,None,engine_factory=ExitRace);scheduler.start(run)
    assert entered.wait(5);scheduler.stop();scheduler.thread.join(5)
    assert not scheduler.busy and store.run(run)['state']=='cancelled' and store.progress(run)=={'cancelled':2}
    assert all(not i['error'] for i in store.items(run));store.close()


def test_receive_cancellation_between_timeout_and_liveness_check():
    import threading
    from queue import Empty
    from transcomic.tts.process_engine import ProcessEngine,Stopped
    engine=object.__new__(ProcessEngine);engine.cancelled=threading.Event()
    class CancelOnTimeout:
        def get(self,timeout):engine.cancelled.set();raise Empty
    engine.results=CancelOnTimeout()
    with pytest.raises(Stopped):engine.receive()
