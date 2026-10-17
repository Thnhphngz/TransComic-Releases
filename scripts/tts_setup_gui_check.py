"""Real one-click CPU provisioning in an isolated source GUI, not a clean VM.

The GUI's bootstrap audio/Qt libraries are present; ORT availability is injected
as missing, forcing a real downloaded embedded CPU interpreter and runtime.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--scale',default='1');p.add_argument('--dark',action='store_true');p.add_argument('--resume-fixture',action='store_true');args=p.parse_args()
    from scripts.test_runtime import outside
    root=outside(Path(args.root).absolute())
    if args.resume_fixture:
        prior=json.loads((root/'evidence/report.json').read_text())
        assert prior.get('source_gui_with_missing_ort_injection') and prior.get('error'),'Only resume this helper\'s failed isolated fixture'
        (root/'evidence/report.json').rename(root/'evidence/prior-failed-report.json')
    else:root.mkdir(parents=True,exist_ok=False)
    evidence=root/'evidence';evidence.mkdir(exist_ok=args.resume_fixture)
    import ctypes
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4));os.environ['QT_SCALE_FACTOR']=str(float(args.scale)/(ctypes.windll.user32.GetDpiForSystem()/96))
    from PySide6.QtWidgets import QApplication,QMessageBox
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt,QTimer
    from transcomic.storage import Store
    from transcomic.ui.main import MainWindow
    import transcomic.tts.setup as setup
    import transcomic.tts.runtime_manager as runtime
    def bootstrap():return dict(compatible=False,missing=['onnxruntime'],runtimes=[],providers=[],error=None)
    setup.diagnostics=bootstrap;setup.nvidia_device=lambda:None;runtime.diagnostics=bootstrap;runtime.providers=lambda:[]
    app=QApplication([]);window=None;page=None;events=[];report={'clean_windows':False,'source_gui_with_missing_ort_injection':True,'resumed_fixture':args.resume_fixture,'events':events};ticks=[0]
    timer=QTimer();timer.setInterval(50);timer.timeout.connect(lambda:ticks.__setitem__(0,ticks[0]+1));timer.start()
    def wait(condition,seconds=1200):
        end=time.monotonic()+seconds
        # qWait holds the GIL on this PySide build and starves the setup thread
        # during thousands of file operations. The native app's exec() releases
        # it; this explicit sleep lets the source GUI harness do the same.
        while not condition() and time.monotonic()<end:app.processEvents();time.sleep(.02)
        app.processEvents();assert condition(),'one-click timeout'
    def create():
        store=Store(root/'translation.sqlite3');store.set_setting('dark','1' if args.dark else '0');window=MainWindow(store);window.confirm_exit=lambda running:'safe' if running else 'exit';window.resize(1380,820);window.show();window.pages.setCurrentIndex(7);page=window.tts_page;wait(lambda:not page.is_busy());return window,page
    try:
        window,page=create();page.open_settings();app.processEvents();assert not page.runtime_ready;page.settings_dialog.grab().save(str(evidence/'not-installed.png'))
        captured=[False]
        def progress(a,b,label):
            if not events or events[-1]!=label:events.append(label)
            if not captured[0] and b>1:page.settings_dialog.grab().save(str(evidence/'progress.png'));captured[0]=True
        page.download_progress.connect(progress)
        def no_question(*a,**k):raise AssertionError('One-click must not prompt for technical setup')
        QMessageBox.question=no_question
        before=ticks[0];QTest.mouseClick(page.setup_button,Qt.LeftButton);assert not page.runtime_ready;wait(lambda:not page.is_busy());assert page.runtime_ready and page.runtime_info['backend']=='CPUExecutionProvider'
        assert ticks[0]-before>10;page.settings_dialog.grab().save(str(evidence/'ready.png'));report['setup']=page.runtime_info;report['gui_ticks_during_setup']=ticks[0]-before;page.settings_dialog.hide()
        fixture=root/'fixture.txt';fixture.write_text('A peaceful morning.\nA new beginning.',encoding='utf8')
        for fmt in ('WAV','MP3'):
            page.new_run();page.format.setCurrentText(fmt);page.import_paths([fixture]);wait(lambda:not page.is_busy());page.start();wait(lambda:not page.is_busy());assert page.store.progress(page.run_id)=={'success':2};assert page.store.run(page.run_id)['state']=='completed'
            doc=page.store.docs(page.run_id)[0];page.open_sentences(doc['id']);page.play_segment(page.store.items(page.run_id)[0]['id']);wait(lambda:page.player.player.position()>30,30);page.player.close_button.click();page.audio_dialog.hide();report[fmt.lower()]=True
        report['history_before_restart']=len(page.store.history_runs());window.close();wait(lambda:window._closed)
        window,page=create();assert page.runtime_ready;report['restart_ready']=True;report['history_after_restart']=len(page.store.history_runs());assert report['history_after_restart']==report['history_before_restart']
        # Explicit setup again must use pinned cache: no network allowed.
        import httpx
        original=httpx.Client.send
        def forbidden(*a,**k):raise AssertionError('Restart/setup must reuse verified cache')
        httpx.Client.send=forbidden
        try:page.install_models();wait(lambda:not page.is_busy());assert page.runtime_ready
        finally:httpx.Client.send=original
        report['second_setup_no_http']=True;window.grab().save(str(evidence/'restart.png'));report['dpr']=window.devicePixelRatioF()
    except BaseException:
        import traceback
        report['error']=traceback.format_exc();raise
    finally:
        (evidence/'report.json').write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8')
        if page:page.request_stop();wait(lambda:not page.is_busy(),30)
        if window and not window._closed:window.close();wait(lambda:window._closed)
    print(json.dumps(report,ensure_ascii=True));return 0

if __name__=='__main__':raise SystemExit(main())
