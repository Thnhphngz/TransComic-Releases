"""Isolated real GUI crash/reopen probe; only enabled by an explicit CLI flag."""
import argparse
import json
import os
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tts-crash-smoke',action='store_true');parser.add_argument('--root',required=True);parser.add_argument('--models',required=True);parser.add_argument('--phase',choices=['crash','resume'],required=True);args=parser.parse_args()
    from scripts.test_runtime import outside
    root=outside(Path(args.root).absolute());assert (root/'isolated-crash-fixture').is_file()
    import httpx
    httpx.Client.send=lambda *a,**k:(_ for _ in ()).throw(AssertionError('No HTTP in local GUI crash fixture'))
    from PySide6.QtWidgets import QApplication,QMessageBox
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from ..storage import Store
    from ..ui.main import MainWindow
    from .models import ModelManager
    app=QApplication([])
    def wait(condition,seconds=60):
        end=time.monotonic()+seconds
        while not condition() and time.monotonic()<end:app.processEvents();QTest.qWait(10);time.sleep(.003)
        app.processEvents();assert condition(),'Crash GUI timeout'
    window=MainWindow(Store(root/'translation.sqlite3'));window.confirm_exit=lambda running:'safe' if running else 'exit';window.show();window.pages.setCurrentIndex(7);app.processEvents();page=window.tts_page;wait(lambda:not page.is_busy());page.manager=ModelManager(args.models);page.scheduler.manager=page.manager;page.check_runtime();wait(lambda:not page.is_busy());assert page.runtime_ready
    if args.phase=='crash':
        fixture=root/'Crash.txt';fixture.write_text('\n'.join(['Hello there.']*2+['A long sentence for checking crash recovery. '*10]*10),encoding='utf8');page.voice.setCurrentText('af_heart');page.parallel_width.setCurrentIndex(page.parallel_width.findData(2));page.import_paths([fixture]);wait(lambda:not page.is_busy());QTest.mouseClick(page.start_button,Qt.LeftButton)
        wait(lambda:page.store.progress(page.run_id).get('success',0)>=2)
        info=dict(pid=os.getpid(),run=page.run_id,document=page.store.docs(page.run_id)[0]['id'],worker_pids=[e.process.pid for e in page.scheduler.engines],active=len(page.scheduler.active),hashes={i['id']:i['sha256'] for i in page.store.items(page.run_id) if i['state']=='success'})
        (root/'ready.json').write_text(json.dumps(info),encoding='utf8')
        while True:app.processEvents();time.sleep(.01)  # Parent kills this exact fixture PID.
    else:
        info=json.loads((root/'ready.json').read_text());run=info['run'];assert page.store.run(run)['state']=='interrupted'
        for item in page.store.items(run):
            if item['state']!='success':page.store.edit(item['id'],'A calm day.')
        def accept():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget,QMessageBox) and widget.isVisible():widget.button(QMessageBox.Yes).click()
        QTimer.singleShot(80,accept);page.history_document=info['document'];page.resume_history();wait(lambda:not page.is_busy());assert page.store.progress(run)=={'success':12}
        assert all(page.store.segment(id)['sha256']==sha for id,sha in info['hashes'].items())
        result=dict(state=page.store.run(run)['state'],audio=12,preserved=len(info['hashes']),backend=sorted({i['backend'] for i in page.store.items(run)}),actual_gui=True)
        (root/'resume-report.json').write_text(json.dumps(result),encoding='utf8');window.close();wait(lambda:window._closed)
    return 0
