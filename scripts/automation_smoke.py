"""Opt-in isolated source smoke. Mock translation; no downloads or GPU tests."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--cpu-cache',type=Path);parser.add_argument('--native-tray',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('QT_OPENGL','software');os.environ.setdefault('QT_QUICK_BACKEND','software')
    if args.native_tray:os.environ['QT_QPA_PLATFORM']='windows'
    else:os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication,QSystemTrayIcon
    from PySide6.QtGui import QImage,QColor
    from transcomic.storage import Store
    from transcomic.ui.main import MainWindow
    from transcomic.automation.validation import defaults
    from transcomic.automation.adapters import Translation,Kokoro
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.tts.models import ModelManager
    from transcomic.tts.setup import RuntimeRegistry
    from transcomic.tts.audio import validate
    import httpx
    app=QApplication([])
    root=Path('D:/TransComic-TestRuntime')/('automation-smoke-'+uuid.uuid4().hex);root.mkdir(parents=True)
    store=Store(root/'App/transcomic.sqlite3');store.set_setting('update_auto_check','0');store.set_setting('dark','1')
    window=MainWindow(store);window.resize(1440,900);window.show();window.pages.setCurrentIndex(9);app.processEvents()
    repo=window.automation_repo;services=window.automation_services;services.preflight=lambda cfg:None
    entered=threading.Event();release=threading.Event();calls=[]
    async def handler(request):
        entered.set();calls.append(str(request.url))
        while not release.is_set():await asyncio.sleep(.01)
        payload=json.loads(json.loads(request.content)['messages'][1]['content'])
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'The synthetic story continues to the next chapter'} for r in payload['lines']]})},'finish_reason':'stop'}]})
    services.translation=Translation(repo,lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000),network_probe=lambda provider:True)
    if args.cpu_cache:
        cache=args.cpu_cache.resolve();assert 'TransComic-TestRuntime' in cache.parts
        marker=json.loads((cache/'isolated-distribution.json').read_text(encoding='utf8'));assert marker['backend']=='cpu'
        manager=ModelManager(cache/'TransComic/TTS/Models');assert manager.ready('standard')
        packs=RuntimeRegistry(cache/'TransComic/TTS/Runtimes');runtime=packs.active();assert runtime['backend']=='CPUExecutionProvider'
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
    source=root/'Chapter 1.txt';source.write_text('Một câu tổng hợp để kiểm tra.',encoding='utf8');images=root/'Images';images.mkdir()
    image=QImage(60,80,QImage.Format_RGB32);image.fill(QColor('#cf8844'));assert image.save(str(images/'0001.png'))
    output=root/'Projects';output.mkdir();cfg=defaults(store);cfg.update(model='mock',device='CPU',output=str(output))
    id=repo.create('Source smoke',cfg);gid=repo.add(id,[source])[0];repo.pair_images(gid,images);store.add_kira_keys('automation-source-smoke-fixture')
    page=window.automation_page;page.load_worksets(id);controller=window.automation_controller
    def wait(predicate,seconds=90):
        until=time.monotonic()+seconds
        while not predicate() and time.monotonic()<until:app.processEvents();time.sleep(.01)
        app.processEvents();assert predicate()
    try:
        proof=controller.validate(id);assert proof['passed'];controller.start(id);wait(entered.is_set)
        tray_available=QSystemTrayIcon.isSystemTrayAvailable();hidden=False
        if args.native_tray:
            assert tray_available,'Windows System Tray is unavailable; native smoke cannot claim PASS'
            window.confirm_exit=lambda running:'background';window.close();app.processEvents()
            hidden=not window.isVisible();assert hidden and controller.busy and not controller.stop_event.is_set()
        release.set();wait(lambda:not controller.busy)
        assert repo.workset(id)['state']=='completed',repo.events(id)
        meta=repo.group(gid)['data'];doc=services.tts_store.docs(meta['tts_run'])[0];wave=Path(doc['folder'])/'0001.wav';audio=validate(wave)
        project=Path(meta['project']);assert (project/'draft_content.json').is_file() and (project/'draft_cover.jpg').is_file()
        if hidden:window.restore_from_tray();app.processEvents();assert window.isVisible()
        report=dict(passed=True,source=True,fixture=str(root),real_translation_requests=0,mock_http_requests=len(calls),gpu_stress=False,model_downloads=0,
                    kokoro='verified_cached_CPU' if args.cpu_cache else 'synthetic_PCM_fake',audio=audio,capcut_project=str(project),
                    native_tray_requested=args.native_tray,native_tray_available=tray_available,hidden_while_http_inflight=hidden,worker_completed_while_hidden=hidden,
                    restored_visible=window.isVisible(),dpr=window.devicePixelRatioF(),state=repo.workset(id)['state'])
        (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        assert window.grab().save(str(args.output/'automation.png'));print(json.dumps(report))
    finally:
        release.set()
        if controller.busy:controller.stop();wait(lambda:not controller.busy)
        window._exit_authorized=True;window.close();app.processEvents()


if __name__=='__main__':main()
