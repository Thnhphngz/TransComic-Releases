"""Run the real Windows entry point with isolated storage and HTTP mocks only."""
import asyncio
import json
import os
import runpy
import sys
import time
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from transcomic.ui.main import MainWindow
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler
from transcomic.documents import decode_txt
from transcomic.bulk import import_many
import transcomic.app as application

OUT=Path('artifacts/performance/gui')/os.environ.get('QT_SCALE_FACTOR','1')


def wait(predicate,seconds=10):
    deadline=time.monotonic()+seconds
    while not predicate():
        QApplication.instance().processEvents();QTest.qWait(5);time.sleep(.003)
        assert time.monotonic()<deadline,'native GUI timeout'


class Smoke(MainWindow):
    def __init__(self,store):
        super().__init__(store);QTimer.singleShot(200,self.exercise)

    def exercise(self):
        try:
            app=QApplication.instance();app.setQuitOnLastWindowClosed(False)
            assert app.platformName()=='windows'
            doc=import_many(self.store,[Path('15-16.docx')],'vi','en')['document_ids'][0]
            self.open_document(doc)
            geometry=[]
            for dark in (False,True):
                if self.dark!=dark:self.toggle_theme()
                self.showNormal();self.resize(1400,850);QTest.qWait(240);app.processEvents()
                self.sky_switch.setFocus();self.grab().save(str(OUT/f'glass-{dark}.png'))
                self.stop_button.setEnabled(True);QTest.mousePress(self.stop_button,Qt.LeftButton)
                self.stop_button.grab().save(str(OUT/f'pressed-{dark}.png'));QTest.mouseRelease(self.stop_button,Qt.LeftButton)
                self.stop_button.setEnabled(False);self.stop_button.grab().save(str(OUT/f'disabled-{dark}.png'))
                index=self.model_name.currentIndex();self.model_name.showPopup();QTest.qWait(50)
                self.model_name.view().window().grab().save(str(OUT/f'dropdown-{dark}.png'));self.model_name.hidePopup()
                assert self.model_name.currentIndex()==index
                self.resize(900,580);QTest.qWait(80);app.processEvents()
                assert self.table.viewport().height()>80
                geometry.append({'dark':dark,'table_height_900':self.table.viewport().height()})
                self.grab().save(str(OUT/f'small-{dark}.png'))
            if self.sidebar.width()>100:self.toggle_sidebar()
            self.showMaximized();QTest.qWait(80);self.grab().save(str(OUT/'maximized-collapsed.png'))
            calls=[]
            async def stalled(request):
                calls.append(time.monotonic());await asyncio.Event().wait()
            job=self.store.create_job(doc,'deepseek-v4.1-flash','vi','en',30)
            self.scheduler=Scheduler(self.store,KiraProvider('mock-only',transport=httpx.MockTransport(stalled)),self.bridge.changed.emit)
            self.scheduler.start(job);wait(lambda:len(calls)==30)
            self.shutdown_grace_seconds=.2
            self.confirm_exit=lambda running:'safe'
            ticks=[];timer=QTimer(self);timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start()
            start=time.monotonic();self.stop_translation();self.close();wait(lambda:self._closed,5)
            elapsed=time.monotonic()-start
            assert elapsed<1.5 and len(calls)==30 and len(ticks)>5
            report={'platform':app.platformName(),'scale':os.environ.get('QT_SCALE_FACTOR','1'),'geometry':geometry,
                    'device_pixel_ratio':self.devicePixelRatioF(),
                    'shutdown_seconds':elapsed,'heartbeat_count':len(ticks),'active_at_stop':30,'real_api_requests':0,'entry_point':'run_transcomic.py'}
            (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
            app.quit()
        except Exception:
            (OUT/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');traceback.print_exc();QApplication.instance().exit(1)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory() as root:
        os.environ['LOCALAPPDATA']=root
        application.MainWindow=Smoke
        runpy.run_path('run_transcomic.py',run_name='__main__')
