"""Explicit native V4 acceptance with real cached Kokoro, isolated fixtures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tts-v4-smoke',action='store_true');parser.add_argument('--root',required=True);parser.add_argument('--models',required=True);parser.add_argument('--scale',default='1');parser.add_argument('--dark',action='store_true');parser.add_argument('--gpu-fail-test',action='store_true');args=parser.parse_args()
    from scripts.test_runtime import outside
    root=outside(Path(args.root).absolute());root.mkdir(parents=True,exist_ok=False);out=root/'evidence';out.mkdir();fixtures=root/'files';fixtures.mkdir();custom=root/'audio';custom.mkdir()
    import ctypes
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4));os.environ['QT_SCALE_FACTOR']=str(float(args.scale)/(ctypes.windll.user32.GetDpiForSystem()/96))
    import httpx
    def forbidden(*a,**k):raise AssertionError('No HTTP or translation APIs in local TTS acceptance')
    httpx.Client.send=forbidden;httpx.AsyncClient.send=forbidden
    from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt,QTimer
    from ..storage import Store
    from ..ui.main import MainWindow
    from .models import ModelManager
    from . import process_engine
    if args.gpu_fail_test:
        original=process_engine.ProcessEngine
        def injected(manager,variant,backend,device_id=-1):
            if backend=='CUDAExecutionProvider':raise process_engine.EngineFailure('Injected CUDA initialization failure for CPU acceptance')
            return original(manager,variant,backend,device_id)
        process_engine.ProcessEngine=injected
    app=QApplication(sys.argv);window=None;page=None;report=dict(scale=args.scale,dark=args.dark,cpu_fallback_injected=args.gpu_fail_test,cases={})
    def wait(condition,seconds=180):
        end=time.monotonic()+seconds
        while not condition() and time.monotonic()<end:app.processEvents();QTest.qWait(10);time.sleep(.003)
        app.processEvents();assert condition(),'Acceptance timeout'
    def settle():app.processEvents();QTest.qWait(80);app.processEvents()
    def capture(name):settle();assert window.grab().save(str(out/(name+'.png')))
    def create():
        store=Store(root/'translation.sqlite3');store.set_setting('dark','1' if args.dark else '0');window=MainWindow(store);window.confirm_exit=lambda running:'safe' if running else 'exit';window.resize(1500,880);window.show();window.pages.setCurrentIndex(7);app.processEvents();page=window.tts_page
        wait(lambda:not page.is_busy());page.manager=ModelManager(args.models);page.scheduler.manager=page.manager
        if args.gpu_fail_test:page.scheduler.factory=injected
        page.check_runtime();wait(lambda:not page.is_busy());assert page.runtime_ready;page.voice.setCurrentText('af_heart');page.parallel_width.setCurrentIndex(page.parallel_width.findData(1 if args.gpu_fail_test else 2));return window,page
    def yes_no(value):
        def answer():
            for item in QApplication.topLevelWidgets():
                if isinstance(item,QMessageBox) and item.isVisible():
                    button=item.button(value)
                    if button is None:button=next(b for b in item.buttons() if b.text()==('Xóa lịch sử' if value==QMessageBox.Yes else 'Hủy'))
                    button.click()
        QTimer.singleShot(100,answer)
    def save_hashes(run):return {i['id']:i['sha256'] for i in page.store.items(run) if i['state']=='success'}
    try:
        window,page=create();report['runtime']=page.runtime_info;report['dpr']=window.devicePixelRatioF();print('Runtime ready',flush=True)
        from PySide6.QtMultimedia import QMediaDevices
        report['audio_outputs']=[dict(name=d.description(),default=d.isDefault()) for d in QMediaDevices.audioOutputs()]
        from docx import Document
        word=Document()
        for n in range(20):word.add_paragraph('A peaceful morning brings a new beginning, and the story continues with a quiet walk beside the river.')
        source=fixtures/'Twenty lines.docx';word.save(source);page.import_paths([source]);wait(lambda:not page.is_busy());QTest.mouseClick(page.start_button,Qt.LeftButton)
        wait(lambda:page.store.progress(page.run_id).get('success',0)>=2);page.pause();wait(lambda:not page.is_busy());run=page.run_id;assert page.store.run(run)['state']=='paused';saved=save_hashes(run);assert 2<=len(saved)<20
        first_timeline=list(page.scheduler.parallel_timeline)
        doc=page.store.docs(run)[0];settle();card=page.history_panel.cards[doc['id']];size=card.size();QTest.mouseClick(card.sentences,Qt.LeftButton);settle();dialog=page.audio_dialog;assert dialog.isVisible() and dialog.model.rowCount()==20 and card.size()==size
        dialog.grab().save(str(out/'sentences-popup.png'));page.play_segment(next(iter(saved)));wait(lambda:page.player.player.position()>80,20);capture('shared-player');assert page.player.parentWidget()!=card
        report['wav_output_device']=page.player.output.device().description();assert page.player.output.device()==QMediaDevices.defaultAudioOutput()
        dialog.reject();assert not dialog.isVisible() and not page.player.player.source().isEmpty();QTest.mouseClick(page.player.close_button,Qt.LeftButton);assert page.player.player.source().isEmpty() and page.store.run(run)['state']=='paused'
        page.start();wait(lambda:not page.is_busy());assert page.store.run(run)['state']=='completed' and page.store.progress(run)=={'success':20};assert all(page.store.segment(id)['sha256']==sha for id,sha in saved.items())
        active=set();peak=0
        for kind,thread,when in sorted([*first_timeline,*page.scheduler.parallel_timeline],key=lambda e:e[2]):
            if kind=='start':active.add(thread)
            else:active.discard(thread)
            peak=max(peak,len(active))
        if not args.gpu_fail_test and peak!=2:
            from .concurrency import resource_gate
            report['parallel_resource_limit']=dict(gate=resource_gate(2),note='GUI resource gate reduced to one; do not bypass RAM safety to manufacture concurrency proof.')
        report['cases']['twenty_pause_resume']=dict(audio=20,preserved=len(saved),concurrent_session_run_peak=peak);capture('bulk');print('20 DOCX complete',flush=True)
        page.new_run();source=fixtures/'Cancel twenty.txt';source.write_text('\n'.join(['A quiet morning.']+['A long story for safe cancellation. '*18]*19),encoding='utf8');page.import_paths([source]);wait(lambda:not page.is_busy());page.start();wait(lambda:page.store.progress(page.run_id).get('success',0)>=1 and bool(page.scheduler.active))
        cancelled=page.run_id;before=save_hashes(cancelled);busy=len(page.scheduler.active);pids=[e.process.pid for e in page.scheduler.engines if hasattr(e,'process')];started=time.monotonic();QTest.mouseClick(page.stop_button,Qt.LeftButton);wait(lambda:not page.is_busy(),10);elapsed=time.monotonic()-started;assert page.store.run(cancelled)['state']=='cancelled';assert all(page.store.segment(id)['sha256']==sha for id,sha in before.items());after=save_hashes(cancelled);QTest.qWait(300);assert after==save_hashes(cancelled)
        import psutil
        assert all(not psutil.pid_exists(pid) for pid in pids);report['cases']['cancel']=dict(seconds=elapsed,active=busy,preserved=len(before),worker_pids=pids,no_orphan=True);print('Cancel terminal',flush=True)
        window.close();wait(lambda:window._closed);window,page=create();assert page.store.run(cancelled)['state']=='cancelled';page.history_document=page.store.docs(cancelled)[0]['id']
        try:page.resume_history();raise AssertionError('Cancelled run resumed')
        except ValueError:pass
        assert all(page.store.segment(id)['sha256']==sha for id,sha in after.items());report['cases']['cancel_persists_restart']=True
        page.tabs.setCurrentIndex(1);page.input_name.setText('Direct take');page.input_text.setPlainText('A quiet day. A fresh beginning.\nWelcome to the story.');page.split_controls.toggle.setChecked(False);page.format.setCurrentText('MP3');QFileDialog.getExistingDirectory=lambda *a:str(custom);page.start();wait(lambda:not page.is_busy());old=page.run_id;old_doc=page.store.docs(old)[0];assert page.store.progress(old)=={'success':1};old_file=Path(old_doc['folder'])/'0001.mp3';old_bytes=old_file.read_bytes();capture('input-split-off')
        card=page.history_panel.cards[old_doc['id']];assert not card.sentences.isVisible();QTest.mouseClick(card.listen,Qt.LeftButton);wait(lambda:page.player.player.position()>80,20);capture('mp3-shared-player');page.player.toggle();page.player.volume.setValue(35);page.player.player.setPosition(200);QTest.mouseClick(page.player.close_button,Qt.LeftButton);assert page.player.isHidden() and page.player.player.source().isEmpty();assert page.store.run(old)['state']=='completed'
        page.input_name.setText('Direct take revised');page.input_text.setPlainText('A new story.\nGood morning!\nHave a wonderful day?');page.split_controls.toggle.setChecked(True);QTest.mouseClick(page.split_controls.sentence,Qt.LeftButton);page.format.setCurrentText('WAV');page.update_input_counts();assert page.split_controls.count.text()=='3 câu';capture('input-split-on');page.start();wait(lambda:not page.is_busy());assert page.run_id!=old and page.store.progress(page.run_id)=={'success':3} and old_file.read_bytes()==old_bytes
        doc=page.store.docs(page.run_id)[0];assert page.history_panel.cards[doc['id']].sentences.isVisible();page.open_sentences(doc['id']);settle();page.audio_dialog.grab().save(str(out/'revised-popup.png'));page.audio_dialog.reject();report['cases']['input_edit_new_job_mp3_wav']=True
        report['mp3_output_device']=page.player.output.device().description();assert page.player.output.device()==QMediaDevices.defaultAudioOutput()
        page.history_panel.search.setText('Direct');wait(lambda:len(page.history_panel.cards)==2);capture('history-search')
        paths=[Path(doc['folder'])/i['filename'] for doc in page.store.rows('SELECT * FROM documents') if doc['folder'] for i in page.store.rows("SELECT * FROM segments WHERE document_id=? AND state='success'",(doc['id'],))];hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        yes_no(QMessageBox.No);page.clear_history();assert page.store.doc(old_doc['id']);yes_no(QMessageBox.Yes);page.clear_history();assert not page.store.rows('SELECT id FROM documents');assert all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in hashes.items());report['cases']['clear_history_keeps_all_audio']=len(hashes)
        window.resize(1000,680);capture('small');report['cases']['header_history_full_height']=page.history_panel.height()==page.workspace.height();report['cases']['wav_mp3_playback']=True
    except BaseException:
        import traceback
        report['error']=traceback.format_exc();raise
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        if page:page.request_stop();wait(lambda:not page.is_busy())
        if window:window.close();wait(lambda:window._closed)
    # Windows redirected consoles may use cp1252. JSON on disk stays UTF-8;
    # ASCII escapes keep diagnostics printable without changing that console.
    print(json.dumps(report,ensure_ascii=True,indent=2));return 0
