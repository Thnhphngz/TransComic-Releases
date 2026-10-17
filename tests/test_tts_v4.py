"""V4 terminal cancellation and recovery: isolated synthetic audio only."""
import json
import time
from pathlib import Path
import pytest
from tests.test_tts import prepare,FakeEngine,wave
from transcomic.tts.scheduler import Scheduler
from transcomic.tts.storage import TtsStore


class Slow(FakeEngine):
    def synthesize(self,*args):time.sleep(.04);yield wave()


def wait(predicate):
    end=time.monotonic()+5
    while not predicate() and time.monotonic()<end:time.sleep(.005)
    assert predicate()


def test_pause_resume_twenty_preserves_files_and_sequence(tmp_path):
    store,run,output,root=prepare(tmp_path,'\n'.join('Line '+str(i) for i in range(20)));scheduler=Scheduler(store,None,engine_factory=Slow)
    scheduler.start(run);wait(lambda:store.progress(run).get('success',0)>=2);scheduler.pause();scheduler.thread.join(5)
    saved={i['id']:i['sha256'] for i in store.items(run) if i['state']=='success'};assert store.run(run)['state']=='paused' and 2<=len(saved)<20
    scheduler.start(run);scheduler.thread.join(5);assert store.progress(run)=={'success':20}
    assert all(store.segment(id)['sha256']==sha for id,sha in saved.items());assert len(list(root.rglob('*.wav')))==20;store.close()


def test_cancel_twenty_terminal_restart_no_resume_or_late_commit(tmp_path):
    store,run,output,root=prepare(tmp_path,'\n'.join('Line '+str(i) for i in range(20)));scheduler=Scheduler(store,None,engine_factory=Slow)
    scheduler.start(run);wait(lambda:store.progress(run).get('success',0)>=2);scheduler.stop();scheduler.thread.join(5)
    assert store.run(run)['state']=='cancelled';saved={i['id']:i['sha256'] for i in store.items(run) if i['state']=='success'};assert 2<=len(saved)<20
    files={str(p):p.read_bytes() for p in root.rglob('*.wav')};time.sleep(.1);assert files=={str(p):p.read_bytes() for p in root.rglob('*.wav')}
    path=store.path;store.close();store=TtsStore(path);assert store.run(run)['state']=='cancelled' and store.claim(run) is None
    with pytest.raises(ValueError):Scheduler(store,None,engine_factory=Slow).start(run)
    with pytest.raises(ValueError):store.status(run,'running')
    assert len(list(root.rglob('*.wav')))==len(saved);store.close()


def test_cancel_paused_checkpoint_and_legacy_stopped_are_distinct(tmp_path):
    store,run,output,root=prepare(tmp_path);store.status(run,'paused');store.cancel_run(run)
    with pytest.raises(ValueError):output.retry(run,[store.items(run)[0]['id']])
    store.close()
    other=tmp_path/'legacy';other.mkdir();store,run,output,root=prepare(other);store.status(run,'stopped');path=store.path;store.close();store=TtsStore(path)
    assert store.run(run)['state']=='stopped';scheduler=Scheduler(store,None,engine_factory=FakeEngine);scheduler.start(run);scheduler.thread.join(5);assert store.run(run)['state']=='completed';store.close()


def test_shutdown_interrupt_is_recoverable_and_not_user_cancel(tmp_path):
    store,run,output,root=prepare(tmp_path,'One\nTwo\nThree');scheduler=Scheduler(store,None,engine_factory=Slow);scheduler.start(run);wait(lambda:bool(scheduler.active));scheduler.stop(permanent=False);scheduler.thread.join(5)
    assert store.run(run)['state']=='interrupted';scheduler.start(run);scheduler.thread.join(5);assert store.progress(run)=={'success':3};store.close()


def test_cancel_fences_existing_lease_before_filesystem_commit(tmp_path):
    from transcomic.tts.audio import encode
    store,run,output,root=prepare(tmp_path);item=store.claim(run);doc=store.doc(item['document_id']);temp=Path(doc['folder'])/'owned-test.part';info=encode(temp,[wave()]);store.cancel_run(run)
    assert not output.commit(item,temp,info,'CPUExecutionProvider') and not list(root.rglob('*.wav'));assert store.progress(run)=={'cancelled':2};store.close()
