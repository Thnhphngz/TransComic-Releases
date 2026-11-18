"""Opt-in Windows Qt lifecycle/timing probe; synthetic profile, no network/TTS."""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-root',required=True)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--action',choices=('prepare','observe','crash'),required=True)
    parser.add_argument('--count',type=int,default=1)
    args=parser.parse_args();started=time.perf_counter()
    sys.path.insert(0,args.source_root)
    os.environ['QT_QPA_PLATFORM']='windows'
    import httpx
    def forbidden(*args,**kwargs):raise AssertionError('Native probe forbids HTTP')
    httpx.Client.send=forbidden;httpx.AsyncClient.send=forbidden
    from transcomic.storage import Store
    from transcomic.automation.repository import Repository
    from transcomic.automation.validation import defaults
    profile=Path(args.profile).resolve();profile.mkdir(parents=True,exist_ok=True)
    store=Store(profile/'translation.sqlite3')
    store.set_setting('update_auto_check','0');store.set_setting('dark','1')
    if args.action=='prepare':
        from docx import Document
        repo=Repository(store);inputs=profile/'inputs';inputs.mkdir(exist_ok=True)
        txt=inputs/'One.txt';txt.write_text('A small synthetic source line\nAnother synthetic line',encoding='utf8')
        word=inputs/'Two.docx';doc=Document();doc.add_paragraph('A synthetic DOCX paragraph');doc.save(word)
        third=inputs/'Three.txt';third.write_text('A third synthetic source',encoding='utf8')
        for i in range(args.count):
            wid=repo.create('Synthetic '+str(i+1),defaults(store));repo.add(wid,[txt,word,third])
        store.close();return
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtWidgets import QApplication
    from transcomic.ui.main import MainWindow
    from transcomic.ui.tts_page import TtsPage
    TtsPage.check_runtime=lambda self:None
    app=QApplication([]);window_start=time.perf_counter();w=MainWindow(store)
    w.resize(1280,820);w.show();app.processEvents();shown=time.perf_counter()
    w.pages.setCurrentIndex(9);app.processEvents();auto=time.perf_counter()
    p=w.automation_page
    result=dict(pid=os.getpid(),platform=app.platformName(),action=args.action,count=args.count,
        launch_to_visible_s=shown-started,window_create_to_visible_s=shown-window_start,
        launch_to_automation_s=auto-started,worksets=p.worksets.count(),rows=p.model.rowCount(),
        session=getattr(p.repo,'session_id',None),http_requests=0)
    result['dpr']=w.devicePixelRatioF()
    if args.action=='crash':
        import threading
        import transcomic.automation.validation as validation
        from PIL import Image
        wid=p.repo.create('Crash draft',defaults(store));p.load_worksets(wid)
        source=profile/'Crash.txt';source.write_text('Synthetic crash source',encoding='utf8')
        p.drop_paths([str(source)])
        deadline=time.monotonic()+5
        while p.import_busy and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
        gid=p.repo.group_summaries(wid)[0]['id'];folder=profile/'images';folder.mkdir(exist_ok=True)
        Image.new('RGB',(20,30),(30,80,100)).save(folder/'1.png')
        entered=threading.Event();original=validation.image_manifest
        def waiting(*args,**kwargs):
            entered.set()
            while True:
                validation.check_current(kwargs.get('cancelled'));time.sleep(.01)
        validation.image_manifest=waiting;p.pair_folder(gid,str(folder))
        while not entered.is_set():app.processEvents();time.sleep(.005)
        result['validation_active']=True
        (profile/'ready.json').write_text(json.dumps(result),encoding='utf8')
        while True:app.processEvents();time.sleep(.005)
    ticks=[];timer=QTimer();timer.setInterval(15);timer.timeout.connect(lambda:ticks.append(time.perf_counter()));timer.start()
    interactive_start=time.perf_counter()
    for page in (0,7,8,9):
        w.pages.setCurrentIndex(page);p.table.verticalScrollBar().setValue(p.table.verticalScrollBar().maximum())
        end=time.perf_counter()+.08
        while time.perf_counter()<end:app.processEvents();time.sleep(.004)
    result['tab_scroll_sequence_s']=time.perf_counter()-interactive_start;result['heartbeats']=len(ticks)
    stale=getattr(p.repo,'stale_cleanup',None)
    while stale and not stale.done.is_set() and time.perf_counter()-auto<15:app.processEvents();time.sleep(.005)
    result['cleanup_after_auto_s']=time.perf_counter()-auto
    result['cleanup_error']=getattr(stale,'error',None)
    result['cleanup_worker_s']=getattr(stale,'elapsed_seconds',None)
    result['stale_worksets_cleaned']=getattr(stale,'worksets',None)
    result['empty_lock_note_visible']=p.lock_note.isVisible()
    w.grab().save(str(profile/'automation.png'))
    w.confirm_exit=lambda running:'safe' if running else 'exit'
    close_start=time.perf_counter();w.close()
    while not w._closed and time.perf_counter()-close_start<10:app.processEvents();time.sleep(.005)
    result['close_to_window_closed_s']=time.perf_counter()-close_start
    result['closed']=w._closed;result['result_written_monotonic']=time.perf_counter()
    timer.stop()
    (profile/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    if not w._closed:raise RuntimeError('Test window failed to close')


if __name__=='__main__':main()
