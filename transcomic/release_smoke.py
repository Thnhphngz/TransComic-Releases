"""Helpers used only by the explicitly isolated --local-build-smoke mode."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import threading


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def rows(db,table):
    return [[v.hex() if isinstance(v,bytes) else v for v in tuple(row)]
            for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')]


def verify_baseline(window,root):
    """Assert exact legacy records, ciphertext and external files survive startup."""
    expected_path=root/'baseline-expected.json'
    if not expected_path.exists():return {'status':'NOT_VERIFIED','reason':'no baseline fixture supplied'}
    expected=json.loads(expected_path.read_text(encoding='utf8'))
    for table,value in expected['tables'].items():assert rows(window.store.db,table)==value,table
    for table,value in expected['tts_tables'].items():assert rows(window.automation_services.tts_store.db,table)==value,table
    assert all(window.store.setting(k)==v for k,v in expected['settings'].items())
    assert rows(window.automation_services.tts_store.db,'runs')[:len(expected['tts_history'])]==expected['tts_history']
    assert all(digest(root/name)==value for name,value in expected['files'].items())
    assert window.store.kira_keys(decrypt=True)[0]['secret']=='release-synthetic-key'
    assert not window.automation_controller.busy and not window.automation_repo.active()
    return {'status':'PASS','baseline_version':expected['version'],'actual_frozen_baseline_fixture':True,
            'legacy_records_and_ciphertext_unchanged':True,'external_files_unchanged':True,'autostart':False}


def run_automation(window,root,wait):
    from PySide6.QtWidgets import QApplication,QSystemTrayIcon
    from PySide6.QtGui import QImage,QColor
    import httpx
    from .automation.adapters import Translation,Kokoro
    from .automation.validation import defaults
    from .kira_pool import KiraPoolProvider
    from .tts.audio import validate
    repo=window.automation_repo;services=window.automation_services;controller=window.automation_controller
    services.preflight=lambda cfg:None
    entered=threading.Event();release=threading.Event();calls=[]
    async def handler(request):
        entered.set();payload=json.loads(json.loads(request.content)['messages'][1]['content']);calls.append([r['id'] for r in payload['lines']])
        while not release.is_set():await asyncio.sleep(.01)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'The synthetic story continues to the next chapter'} for r in payload['lines']]})},'finish_reason':'stop'}]})
    services.translation=Translation(repo,lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000),network_probe=lambda provider:True)
    cpu=os.environ.get('TRANSCOMIC_SMOKE_CPU_CACHE')
    if cpu:
        from .tts.models import ModelManager
        from .tts.setup import RuntimeRegistry
        cache=Path(cpu).resolve()
        assert cache.name.startswith('TransComic-distribution-cpu-')
        assert json.loads((cache/'isolated-distribution.json').read_text(encoding='utf8'))['backend']=='cpu'
        manager=ModelManager(cache/'TransComic/TTS/Models');packs=RuntimeRegistry(cache/'TransComic/TTS/Runtimes')
        assert manager.ready('standard') and packs.active()['backend']=='CPUExecutionProvider'
        services.kokoro=Kokoro(repo,services.tts_store,manager,packs)
    else:
        class TinyEngine:
            backend='CPUExecutionProvider'
            def __init__(self,*args):pass
            def probe(self,*args):pass
            def synthesize(self,*args):
                import numpy as np
                yield np.sin(np.arange(2400,dtype=np.float32)*.12)*.1
            def close(self):pass
        services.kokoro=Kokoro(repo,services.tts_store,None,engine_factory=TinyEngine)
    services.kokoro.before_finalize=window.automation_page.release_audio
    fixtures=root/'Automation-fixtures';fixtures.mkdir()
    source=fixtures/'Chapter 1.txt';source.write_text('A synthetic source sentence',encoding='utf8')
    images=fixtures/'Images';images.mkdir()
    image=QImage(60,80,QImage.Format_RGB32);image.fill(QColor('#cf8844'));assert image.save(str(images/'0001.png'))
    originals={str(p.relative_to(root)):digest(p) for p in (source,images/'0001.png')}
    output=fixtures/'Projects';output.mkdir();cfg=defaults(window.store);cfg.update(model='mock',device='CPU',output=str(output))
    id=repo.create('Frozen release smoke',cfg);gid=repo.add(id,[source])[0];repo.pair_images(gid,images)
    if not window.store.kira_keys():window.store.add_kira_keys('release-synthetic-key')
    window.automation_page.load_worksets(id);window.pages.setCurrentIndex(9)
    try:
        assert controller.validate(id)['passed'];controller.start(id);wait(entered.is_set,20)
        assert QSystemTrayIcon.isSystemTrayAvailable(),'Native Windows Tray unavailable'
        window.confirm_exit=lambda running:'background';window.close();QApplication.processEvents()
        assert not window.isVisible() and controller.busy and not controller.stop_event.is_set()
        release.set();wait(lambda:not controller.busy,100)
        assert repo.workset(id)['state']=='completed',repo.events(id)
        window.restore_from_tray();QApplication.processEvents();assert window.isVisible()
        meta=repo.group(gid)['data'];doc=services.tts_store.docs(meta['tts_run'])[0]
        wave=Path(doc['folder'])/'0001.wav';audio=validate(wave);project=Path(meta['project'])
        assert (project/'draft_content.json').is_file() and (project/'draft_cover.jpg').is_file()
        line=window.store.lines(repo.group(gid)['document_id'])[0]
        assert meta['slots']==[line['id']] and line['translation']=='The synthetic story continues to the next chapter'
        assert len(calls)==1 and calls[0]==[line['id']]
        assert all(digest(root/p)==h for p,h in originals.items())
        # Seed an interrupted trial checkpoint; the next EXE launch must recover,
        # preserve manifests and remain idle. Never reuse completed source group.
        trial=repo.create('Interrupted trial fixture',cfg);trial_gid=repo.add(trial,[source])[0]
        repo.update_group(trial_gid,images=[{'fixture':1}],slots=[line['id']],state='translated')
        checkpoint={'fixture':'durable-trial-checkpoint','manual_order':True}
        repo.execute("UPDATE automation_worksets SET state='running',started=1,owner_pid=2147483647,owner_started=1,checkpoint=? WHERE id=?",(json.dumps(checkpoint),trial))
        preserved={str(p.relative_to(root)):digest(p) for p in fixtures.rglob('*') if p.is_file()}
        proof={'completed_id':id,'group_id':gid,'completed_checkpoint':repo.workset(id)['checkpoint'],
               'trial_id':trial,'trial_group_id':trial_gid,'trial_checkpoint':checkpoint,'trial_data':repo.group(trial_gid)['data'],
               'files':preserved,'attempts':rows(window.store.db,'request_attempts')}
        (root/'reopen-expected.json').write_text(json.dumps(proof),encoding='utf8')
        window.grab().save(str(root/'automation-completed.png'))
        return {'passed':True,'mock_http_requests':len(calls),'real_translation_requests':0,
                'kokoro':'cached_CPU' if cpu else 'synthetic_PCM','audio':audio,'mau_project':str(project),
                'stable_line_mapping':True,'checkpoint':True,'native_tray_hide_background_restore':True,
                'source_unchanged':True,'gpu_stress':False}
    finally:
        release.set()
        if controller.busy:controller.stop();wait(lambda:not controller.busy,20)


def verify_reopen(window,root):
    expected=json.loads((root/'reopen-expected.json').read_text(encoding='utf8'));repo=window.automation_repo
    assert not window.automation_controller.busy and repo.active() is None
    assert repo.workset(expected['completed_id'])['state']=='completed'
    assert repo.workset(expected['completed_id'])['checkpoint']==expected['completed_checkpoint']
    assert repo.workset(expected['trial_id'])['state']=='interrupted'
    assert repo.workset(expected['trial_id'])['checkpoint']==expected['trial_checkpoint']
    assert repo.group(expected['trial_group_id'])['data']==expected['trial_data']
    assert rows(window.store.db,'request_attempts')==expected['attempts']
    assert all(digest(root/name)==value for name,value in expected['files'].items())
    proof={'passed':True,'frozen':bool(getattr(__import__('sys'),'frozen',False)),
           'completed_and_interrupted_trial_checkpoints_preserved':True,'source_wav_projects_reports_unchanged':True,
           'autostart':False,'new_translation_attempts':0}
    (root/'reopen-report.json').write_text(json.dumps(proof,indent=2),encoding='utf8')
