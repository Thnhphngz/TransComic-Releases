"""Opt-in real GUI smoke through run_transcomic.py, strictly isolated data.

No production DB, translation requests, installer or release operations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tts-source-smoke',action='store_true');parser.add_argument('--root',required=True);parser.add_argument('--models',required=True);parser.add_argument('--scale',default='1');parser.add_argument('--dark',action='store_true');parser.add_argument('--device',default='Auto');parser.add_argument('--workers',type=int,default=0);parser.add_argument('--gpu-fail-test',action='store_true');parser.add_argument('--extended',action='store_true');args=parser.parse_args()
    from scripts.test_runtime import outside
    root=outside(Path(args.root).absolute())
    if root.exists():raise ValueError('Smoke directory must be new')
    root.mkdir(parents=True);out=root/'evidence';out.mkdir();fixtures=root/'fixtures';fixtures.mkdir();custom=root/'custom';custom.mkdir()
    import ctypes
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4));native=ctypes.windll.user32.GetDpiForSystem()/96
    os.environ['QT_SCALE_FACTOR']=str(float(args.scale)/native)
    import httpx
    def forbidden(*a,**k):raise AssertionError('No HTTP in real local TTS smoke')
    httpx.Client.send=forbidden;httpx.AsyncClient.send=forbidden
    from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from ..storage import Store
    from ..ui.main import MainWindow
    from .models import ModelManager
    if args.gpu_fail_test:
        from . import process_engine
        original=process_engine.ProcessEngine
        def injected(manager,variant,backend,device_id=-1):
            if backend=='CUDAExecutionProvider':raise process_engine.EngineFailure('Injected missing cublasLt64_12.dll')
            return original(manager,variant,backend,device_id)
        process_engine.ProcessEngine=injected
    app=QApplication(sys.argv)
    def wait(condition,seconds=100):
        end=time.monotonic()+seconds
        while not condition() and time.monotonic()<end:app.processEvents();QTest.qWait(10);time.sleep(.003)
        app.processEvents()
        assert condition(),'GUI timeout'
    store=Store(root/'translation.sqlite3');store.set_setting('dark','1' if args.dark else '0');window=MainWindow(store);window.confirm_exit=lambda running:'safe' if running else 'exit';window.resize(1380,820);window.show();window.pages.setCurrentIndex(7);app.processEvents();page=window.tts_page
    report=dict(executable=sys.executable,prefix=sys.prefix,scale=args.scale,dpr=window.devicePixelRatioF(),dark=args.dark,cases={})
    try:
        print('GUI opened',flush=True);wait(lambda:not page.is_busy());page.manager=ModelManager(args.models);page.scheduler.manager=page.manager
        if args.gpu_fail_test:page.scheduler.factory=injected
        page.check_runtime();print('checking runtime',flush=True);wait(lambda:not page.is_busy());assert page.runtime_ready,page.notice.text();print('runtime ready',flush=True)
        report['diagnostics']=page.runtime_info;page.voice.setCurrentText('af_heart')
        page.parallel_width.setCurrentIndex(page.parallel_width.findData(args.workers))
        if args.gpu_fail_test:page.parallel_width.setCurrentIndex(page.parallel_width.findData(1))
        text=fixtures/'Ten lines.txt';text.write_text('\n'.join(['Hello there.']*10),encoding='utf8');page.import_paths([text]);wait(lambda:not page.is_busy());assert page.document_model.rowCount()==1
        QFileDialog.getExistingDirectory=lambda *a:(_ for _ in ()).throw(AssertionError('Beside must not show picker'))
        started=time.perf_counter();assert page.start_button.isEnabled();QTest.mouseClick(page.start_button,Qt.LeftButton);wait(lambda:not page.is_busy());assert page.store.run(page.run_id)['state']=='completed',page.notice.text();wall=time.perf_counter()-started
        doc=page.store.docs(page.run_id)[0];folder=Path(doc['folder']);assert folder.name=='Ten lines_10tts' and len(list(folder.glob('*.wav')))==10
        audio_seconds=sum(i['duration'] for i in page.store.items(page.run_id));report['cases']['beside_wav']=dict(count=10,folder=str(folder),backend=page.store.items(page.run_id)[0]['backend'],wall_seconds=wall,audio_seconds=audio_seconds,audio_per_wall=audio_seconds/wall)
        print('10 WAV complete',flush=True)
        page.load_history();id=page.audio_model.items[0]['id'];page.play_segment(id);wait(lambda:not page.is_busy());wait(lambda:page.player.player.position()>80,15)
        report['cases']['wav_playback']=dict(position=page.player.player.position(),duration=page.player.player.duration());page.play_segment(id);assert page.player.player.source().isEmpty()
        page.open_details(doc['id']);assert page.model.rowCount()==10;page.tabs.setCurrentIndex(0)
        for name in ('files','input','details','history'):
            if name=='input':page.tabs.setCurrentIndex(1)
            elif name=='details':page.open_details(doc['id'])
            else:page.tabs.setCurrentIndex(0)
            app.processEvents();window.grab().save(str(out/(name+'.png')))
        page.tabs.setCurrentIndex(0);page.new_run();second=fixtures/'Custom.txt';second.write_text('A new beginning.',encoding='utf8');page.import_paths([second]);wait(lambda:not page.is_busy());page.mode.setCurrentIndex(page.mode.findData('custom'))
        QFileDialog.getExistingDirectory=lambda *a:'';page.start();assert page.store.run(page.run_id)['state']=='draft' and not page.store.docs(page.run_id)[0]['folder'];report['cases']['cancel_picker']=True
        QFileDialog.getExistingDirectory=lambda *a:str(custom);page.format.setCurrentText('MP3');QTest.mouseClick(page.start_button,Qt.LeftButton);wait(lambda:not page.is_busy());assert page.store.run(page.run_id)['state']=='completed'
        page.load_history();page.history_document=page.store.docs(page.run_id)[0]['id'];page.refresh_history();page.play_segment(page.audio_model.items[0]['id']);wait(lambda:not page.is_busy());wait(lambda:page.player.player.position()>80,15)
        report['cases']['custom_mp3_playback']=dict(position=page.player.player.position(),duration=page.player.player.duration());page.player.stop()
        print('MP3 playback complete',flush=True)
        page.new_run();page.tabs.setCurrentIndex(1);page.input_text.setPlainText('\n'.join(['Good day.']*10));page.input_name.setText('Direct input');page.format.setCurrentText('WAV');page.update_input_counts();QTest.mouseClick(page.start_button,Qt.LeftButton);wait(lambda:not page.is_busy());assert page.store.run(page.run_id)['state']=='completed';report['cases']['input_wav_count']=10;print('10 pasted audio complete',flush=True)
        page.tabs.setCurrentIndex(0);page.new_run();long=fixtures/'Stop fixture.txt';long.write_text('\n'.join(['A calm day.']+['A long sentence for checking cancellation. '*12]*9),encoding='utf8');page.import_paths([long]);wait(lambda:not page.is_busy());QTest.mouseClick(page.start_button,Qt.LeftButton)
        # Recoverable interruption is now distinct from V4 user cancellation.
        # The V4 native harness separately tests the terminal Stop button.
        wait(lambda:page.store.progress(page.run_id).get('success',0)>=1);before=page.store.progress(page.run_id).get('success',0);active_before=len(page.scheduler.active);pids=[e.process.pid for e in page.scheduler.engines if hasattr(e,'process')];assert pids;start=time.monotonic();page.scheduler.stop(permanent=False);wait(lambda:not page.is_busy(),8)
        elapsed=time.monotonic()-start;assert page.store.run(page.run_id)['state']=='interrupted';count=page.store.progress(page.run_id).get('success',0);assert count<=before+max(1,active_before)
        app.processEvents();QTest.qWait(400);assert page.store.progress(page.run_id).get('success',0)==count
        import psutil
        alive=[pid for pid in pids if psutil.pid_exists(pid)];assert not alive
        report['cases']['recoverable_interrupt']=dict(seconds=elapsed,before=before,after=count,active_before=active_before,worker_pids=pids,children_alive=bool(alive))
        # Retain fixed numbering and successful hashes; shorten only ungenerated
        # fixture snapshots to make the resume check bounded on developer CPU.
        saved={i['id']:i['sha256'] for i in page.store.items(page.run_id) if i['state']=='success'}
        for item in page.store.items(page.run_id):
            if item['state']=='pending':page.store.edit(item['id'],'Good day.')
        page.start();wait(lambda:not page.is_busy());assert page.store.run(page.run_id)['state']=='completed'
        assert all(page.store.segment(id)['sha256']==sha for id,sha in saved.items());report['cases']['resume']=True
        if args.extended:
            from docx import Document
            page.tabs.setCurrentIndex(0);page.new_run();page.tabs.setCurrentIndex(1);page.split.setCurrentIndex(page.split.findData('none'));page.resplit();page.input_name.setText('One paragraph');page.input_text.setPlainText('A quiet day.\nA new beginning!');page.format.setCurrentText('MP3');page.start();wait(lambda:not page.is_busy())
            pasted=page.store.docs(page.run_id)[0];assert page.store.progress(page.run_id)=={'success':1};card=page.history_panel.cards[pasted['id']];app.processEvents();QTest.mouseClick(card.listen,Qt.LeftButton);wait(lambda:not page.is_busy());wait(lambda:page.player.player.position()>80,15);assert page.player.isVisible() and page.player.parentWidget()!=card;QTest.mouseClick(card.listen,Qt.LeftButton);assert page.player.isHidden() and page.player.player.source().isEmpty();report['cases']['none_mp3_shared_player']=True
            page.tabs.setCurrentIndex(0);page.new_run();word=Document()
            page.split.setCurrentIndex(page.split.findData('lines'));page.resplit();page.format.setCurrentText('WAV')
            for n in range(145):word.add_paragraph('A peaceful morning brings a fresh beginning.')
            word_path=fixtures/'Word fixture.docx';word.save(word_path)
            companion=fixtures/'Companion.txt';companion.write_text('Hello again.\nHave a good day.',encoding='utf8')
            page.import_paths([word_path,companion]);wait(lambda:not page.is_busy());assert page.document_model.rowCount()==2
            page.speed.setValue(1.25);page.start();wait(lambda:page.store.progress(page.run_id).get('success',0)>=1)
            before=page.store.progress(page.run_id).get('success',0);page.pause();wait(lambda:not page.is_busy());after=page.store.progress(page.run_id).get('success',0)
            assert page.store.run(page.run_id)['state']=='paused' and before<=after<=before+4
            persisted_run=page.run_id;persisted_document=page.store.docs(persisted_run)[0]['id'];saved={i['id']:i['sha256'] for i in page.store.items(persisted_run) if i['state']=='success'}
            window.close();wait(lambda:window._closed)
            # Close/reopen all GUI and database handles, then resume from History.
            store=Store(root/'translation.sqlite3');window=MainWindow(store);window.confirm_exit=lambda running:'safe' if running else 'exit';window.resize(1380,820);window.show();window.pages.setCurrentIndex(7);app.processEvents();page=window.tts_page
            wait(lambda:not page.is_busy());page.manager=ModelManager(args.models);page.scheduler.manager=page.manager;page.check_runtime();wait(lambda:not page.is_busy());assert page.runtime_ready
            page.history_document=persisted_document;page.refresh_history();page.speed.setValue(2);page.resume_history();wait(lambda:not page.is_busy())
            assert page.store.run(persisted_run)['state']=='completed' and json.loads(page.store.run(persisted_run)['config'])['speed']==1.25
            assert all(page.store.segment(id)['sha256']==sha for id,sha in saved.items());assert page.store.progress(persisted_run)=={'success':147}
            report['cases']['docx_txt_pause_reopen_resume']=dict(documents=2,docx_lines=145,audio=147,before=before,after_pause=after,preserved_audio=len(saved),snapshot_speed=1.25)
            document=page.store.docs(persisted_run)[0];page.open_sentences(document['id']);assert page.audio_dialog.model.rowCount()==145;page.audio_dialog.reject();report['cases']['bulk_history_sentences']=True
            from PySide6.QtCore import QTimer
            def accept():
                for widget in QApplication.topLevelWidgets():
                    if isinstance(widget,QMessageBox) and widget.isVisible():widget.button(QMessageBox.Yes).click()
            page.tabs.setCurrentIndex(0);page.new_run();a=fixtures/'Delete A.txt';b=fixtures/'Delete B.txt';a.write_text('One.',encoding='utf8');b.write_text('Two.',encoding='utf8');page.import_paths([a,b]);wait(lambda:not page.is_busy());page.document_model.setData(page.document_model.index(0,0),Qt.Checked,Qt.CheckStateRole);QTimer.singleShot(80,accept);page.remove_files();assert page.document_model.rowCount()==1
            QTimer.singleShot(80,accept);page.clear_all();assert page.document_model.rowCount()==0 and page.store.doc(document['id']) and Path(document['folder']).is_dir();report['cases']['checkbox_clear_keeps_history']=True
            def fixture_error():raise RuntimeError('Diagnostic fixture: missing dependency')
            page.guard(fixture_error);assert page.error_dialog.isVisible();page.error_dialog.copy();assert 'Traceback' in QApplication.clipboard().text();page.error_dialog.close();report['cases']['error_copy']=True
        page.tabs.setCurrentIndex(0);window.resize(900,580);app.processEvents();window.grab().save(str(out/'small.png'));assert window.width()==900 and window.height()==580
        report['cases']['small_window']=True;report['runtime_ready']=page.runtime_ready
    except BaseException:
        import traceback
        report['error']=traceback.format_exc();raise
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        page.request_stop();wait(lambda:not page.is_busy());window.close();wait(lambda:window._closed)
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0
