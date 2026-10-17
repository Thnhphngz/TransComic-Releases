"""Explicit isolated frozen acceptance harness. Never opens a normal profile."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def main():
    from .release_adapters import safe_path
    root=safe_path(Path(os.environ.get('LOCALAPPDATA','')))
    if not getattr(sys,'frozen',False) or not root.name.startswith('TransComic-distribution-'):
        return 2
    marker=root/'isolated-distribution.json'
    if not marker.is_file():return 2
    options=json.loads(marker.read_text(encoding='utf8'))
    if options.get('mode')!='isolated-distribution-smoke' or options.get('backend') not in ('cpu','cuda'):
        return 2
    import httpx
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QMessageBox
    from .storage import Store
    from .ui.main import MainWindow
    from .tts.managed_runtime import nvidia_device
    original=httpx.Client.send;network=[];allow_network=[True]
    def guarded(client,request,*args,**kwargs):
        if not allow_network[0]:raise AssertionError('Verified cache must not download again')
        if request.url.scheme!='https' or request.url.host not in ('www.python.org','files.pythonhosted.org','huggingface.co'):
            raise AssertionError('Only official TTS artifact HTTP is allowed')
        network.append({'host':request.url.host,'method':request.method})
        return original(client,request,*args,**kwargs)
    httpx.Client.send=guarded
    import transcomic.tts.setup as setup
    # Explicit CPU-path selection on a GPU-equipped developer machine; real CPU
    # interpreter/inference is used. This is not evidence of a CPU-only machine.
    hardware=nvidia_device()
    if options['backend']=='cpu':setup.nvidia_device=lambda:None
    app=QApplication(sys.argv);app.setQuitOnLastWindowClosed(False)
    window=None;page=None
    report={'frozen':True,'clean_windows':False,'backend_requested':options['backend'],
            'hardware':hardware,'cpu_path_forced':options['backend']=='cpu',
            'preseeded_cache':bool(options.get('preseeded_cache')),'http':network,
            'executable':sys.executable,'sys_path':sys.path,'events':[]}
    def wait(condition,seconds=1800):
        deadline=time.monotonic()+seconds
        while not condition() and time.monotonic()<deadline:
            app.processEvents();time.sleep(.02)
        app.processEvents();assert condition(),'Frozen acceptance timeout'
    def create():
        w=MainWindow(Store(root/'TransComic/transcomic.sqlite3'))
        w.confirm_exit=lambda running:'safe' if running else 'exit'
        w.update_panel.auto.setChecked(False);w.resize(1380,850);w.show()
        w.pages.setCurrentIndex(7);p=w.tts_page;wait(lambda:not p.is_busy())
        return w,p
    try:
        assert not any('.venv' in p or 'Sourch Code' in p for p in sys.path)
        from .tts.runtime import diagnostics
        bootstrap=diagnostics();assert not bootstrap['compatible']
        assert {'onnxruntime','kokoro_onnx','phonemizer','espeakng_loader'}<=set(bootstrap['missing'])
        report['bootstrap']=bootstrap
        window,page=create();page.open_settings();app.processEvents()
        page.settings_dialog.grab().save(str(root/'not-installed.png'))
        def progress(a,b,label):
            if not report['events'] or report['events'][-1]!=label:report['events'].append(label)
        page.download_progress.connect(progress)
        def unexpected(*args,**kwargs):raise AssertionError('No technical setup question expected')
        QMessageBox.question=unexpected
        QTest.mouseClick(page.setup_button,Qt.LeftButton)
        wait(lambda:not page.is_busy())
        if not page.runtime_ready:
            technical=page.directory/'Logs/technical.log'
            report['setup_failure']=dict(notice=page.notice.text(),status=page.asset_status.text(),
                technical_log=technical.read_text(encoding='utf8')[-12000:] if technical.is_file() else '')
        assert page.runtime_ready,json.dumps(report.get('setup_failure',page.runtime_details.toPlainText()),ensure_ascii=True)
        expected='CUDAExecutionProvider' if options['backend']=='cuda' else 'CPUExecutionProvider'
        assert page.runtime_info['backend']==expected
        report['setup']=page.runtime_info
        report['runtime_integrity']=page.packs.active()['protocol']==2
        page.settings_dialog.grab().save(str(root/'ready.png'));page.settings_dialog.hide()
        fixture=root/'fixture.txt'
        fixture.write_text('\n'.join(['A peaceful morning brings a new beginning beside the quiet river.']*4),encoding='utf8')
        fixture_hash=hashlib.sha256(fixture.read_bytes()).hexdigest()
        outputs={};report['jobs']=[]
        for fmt in ('WAV','MP3'):
            page.new_run();page.format.setCurrentText(fmt)
            page.parallel_width.setCurrentIndex(page.parallel_width.findData(0 if fmt=='WAV' else 2))
            page.import_paths([fixture]);wait(lambda:not page.is_busy())
            page.start();wait(lambda:not page.is_busy())
            assert page.store.progress(page.run_id)=={'success':4},page.store.progress(page.run_id)
            items=page.store.items(page.run_id)
            timeline=list(page.scheduler.parallel_timeline);active=set();peak=0
            for kind,thread,when in sorted(timeline,key=lambda r:r[2]):
                if kind=='start':active.add(thread)
                else:active.discard(thread)
                peak=max(peak,len(active))
            report['jobs'].append({'format':fmt,'success':4,'overlap_peak':peak,'timeline_events':len(timeline),'selection':'Auto' if fmt=='WAV' else '2'})
            for item in items:
                p=Path(item['folder'])/item['filename'];outputs[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
            doc=page.store.docs(page.run_id)[0];page.open_sentences(doc['id'])
            page.play_segment(items[0]['id']);wait(lambda:page.player.player.position()>40,40)
            report[fmt.lower()+'_playback']=True;page.player.close_button.click();page.audio_dialog.hide()
        if options['backend']=='cuda':assert max(j['overlap_peak'] for j in report['jobs'])==2
        assert fixture_hash==hashlib.sha256(fixture.read_bytes()).hexdigest()
        count=len(page.store.history_runs());window.grab().save(str(root/'completed.png'))
        window.close();wait(lambda:window._closed,45)
        window,page=create();assert page.runtime_ready;assert len(page.store.history_runs())==count
        allow_network[0]=False
        page.install_models();wait(lambda:not page.is_busy());assert page.runtime_ready
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in outputs.items())
        report.update(passed=True,restart_ready=True,history_preserved=count,
                      second_setup_no_http=True,audio_hashes_preserved=len(outputs),
                      source_unchanged=True,platform=app.platformName())
        window.grab().save(str(root/'restart.png'))
    except BaseException:
        report['error']=traceback.format_exc()
        return 1
    finally:
        (root/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=True),encoding='utf8')
        if page:
            page.request_stop()
            try:wait(lambda:not page.is_busy(),45)
            except AssertionError:pass
        if window and not window._closed:
            window._exit_authorized=True;window.close()
    return 0
