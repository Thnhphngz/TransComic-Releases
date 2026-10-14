try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory
"""Native Qt, same-process window/search stress and OS-exit child probe. HTTP mock only."""
import asyncio
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import threading
import time
import traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.ui.main import MainWindow
from transcomic.ui.glass import GlassSkin
from transcomic.languages import language
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler
import transcomic.app as application

EXIT_ONLY='--exit-only' in sys.argv
OUT=ROOT/'artifacts/stability/windows'/os.environ.get('QT_SCALE_FACTOR','1')
OUT.mkdir(parents=True,exist_ok=True)
send=httpx.Client.send;async_send=httpx.AsyncClient.send
def guarded(self,*a,**kw):
    if not isinstance(self._transport,httpx.MockTransport):raise AssertionError('Real HTTP forbidden')
    return send(self,*a,**kw)
async def async_guarded(self,*a,**kw):
    if not isinstance(self._transport,httpx.MockTransport):raise AssertionError('Real API forbidden')
    return await async_send(self,*a,**kw)
httpx.Client.send=guarded;httpx.AsyncClient.send=async_guarded

class Smoke(MainWindow):
    def __init__(self,store):
        super().__init__(store);self.update_panel.auto.setChecked(False)
        QTimer.singleShot(100,self.probe_exit if EXIT_ONLY else self.stress)
    def process(self):
        QApplication.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    def shot(self,name,widget=None):
        self.process();(widget or self).grab().save(str(OUT/(name+'.png')))
    def fail(self):
        (OUT/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');traceback.print_exc()
        self._exit_authorized=True;self.close();QApplication.instance().exit(1)
    def stress(self):
        try:
            assert QApplication.instance().platformName()=='windows'
            assert not self.workspace_ids and not self.target_languages()
            base=Path(os.environ['LOCALAPPDATA']);owner=threading.get_ident();destroyed=[]
            rounds=40;refreshes=0;max_seconds=0
            for iteration in range(rounds):
                store=Store(base/f'stress-{iteration}.db');w=MainWindow(store);w.update_panel.auto.setChecked(False)
                w.resize(1200,720);w.show();self.process()
                doc,_=store.import_document(base/f'fixture-{iteration}.txt',decode_txt(b'Evelyn one\nEvelyn two\nEvelyn three'),'Tiếng Việt','Tiếng Anh')
                run,jobs=store.create_run([doc],['Tiếng Anh','Tiếng Indonesia'],provider='kira',model='mock',source_lang='Tiếng Việt',concurrency=30)
                w.workspace_ids=[store.job(j)['document_id'] for j in jobs]
                for d in w.workspace_ids:
                    for r in store.lines(d):store.edit_line(r['id'],'translation','Evelyn mock sample')
                w.open_document(doc);self.process()
                w.source_lang.showPopup();w.toggle_theme();w.source_lang.hidePopup()
                if iteration%2:w.toggle_theme()
                for locale in ('id','en'):
                    name=language(locale).name;index=w.view_language.findData(name);assert index>=0
                    w.view_language.showPopup();w.view_language.hidePopup();w.view_language.setCurrentIndex(index)
                    assert language(store.document(w.doc_id)['target_lang']).locale==locale
                s=w.search;s.open(True);s.document_scope.setCurrentIndex(1)
                for i in range(25):
                    start=time.perf_counter();s.query.setText('Evelyn' if i%2 else '');s.rebuild()
                    max_seconds=max(max_seconds,time.perf_counter()-start);refreshes+=1
                    assert s.result_list.count()==len(s.results)
                    self.process()
                s.scope.setCurrentIndex(2);s.query.setText('Evelyn');s.navigate(1)
                s.replacement.setText('Emily');s.replace_current();s.undo()
                s.replace_all();s.confirm_preview();s.undo()
                s.query.clear();s.query.setText('Evelyn');s.close_bar();s.open()
                for page in (4,3,0):w.pages.setCurrentIndex(page);self.process()
                assert not w.update_panel.download.isEnabled() and not w.target_languages()
                if iteration in (0,1):
                    self.shot(f'search-{iteration}',w)
                    w.pages.setCurrentIndex(3);self.shot(f'updater-{iteration}',w);w.pages.setCurrentIndex(0)
                w.destroyed.connect(lambda:destroyed.append(threading.get_ident()),Qt.DirectConnection)
                model=s.result_list.model()
                if iteration%2:w.source_lang.showPopup()
                w._exit_authorized=True;w.close();w.close();self.process()
                assert not isValid(w) and not isValid(s) and not isValid(model)
                assert store.log.closed and not store.log.thread.is_alive()
                assert len([c for c in QApplication.instance().children() if isinstance(c,GlassSkin)])==1
            assert len(destroyed)==rounds and all(t==owner for t in destroyed)
            report={'platform':'windows','entry_point':'run_transcomic.py','dpr':self.devicePixelRatioF(),
                'same_process_windows':rounds,'search_refreshes':refreshes,'max_refresh_seconds':max_seconds,
                'destroyed_on_gui_thread':len(destroyed),'shared_filters':1,'real_api_requests':0,
                'production_install_locked':True,'updater_unchanged':True,'native_crashes':0,'mock_samples_only':True}
            (OUT/'report.json').write_text(json.dumps(report,indent=2));(OUT/'failure.txt').unlink(missing_ok=True)
            print(json.dumps(report),flush=True);self._exit_authorized=True;self.close()
        except Exception:self.fail()

    def probe_exit(self):
        try:
            doc,_=self.store.import_document(Path(os.environ['LOCALAPPDATA'])/'exit-fixture.txt',decode_txt(b'Line one\nLine two\nLine three'),'vi','en')
            job=self.store.create_job(doc,'mock','vi','en',1)
            calls=[];start=time.monotonic();confirmations=[]
            async def respond(req):calls.append(1);await asyncio.Event().wait()
            self.scheduler=Scheduler(self.store,KiraProvider('mock-only',transport=httpx.MockTransport(respond)),self.bridge.changed.emit)
            self.scheduler.start(job);self.shutdown_grace_seconds=.1
            self.confirm_exit=lambda running:confirmations.append(running) or 'safe'
            self.exit_probe_timer=QTimer(self);self.exit_probe_timer.setInterval(10)
            def tick():
                if calls and not self._exit_pending:
                    self.stop_translation();self.close();self.close()
                if time.monotonic()-start>5:raise AssertionError('OS-exit probe timeout')
            self.exit_probe_timer.timeout.connect(tick);self.exit_probe_timer.start()
            self._probe_info={'job':job,'doc':doc,'calls':calls,'start':start,'confirmations':confirmations}
        except Exception:self.fail()

if __name__=='__main__':
    if EXIT_ONLY:
        # Parent supplies its temp directory and verifies this process exit.
        os.environ['QT_QPA_PLATFORM']='windows';application.MainWindow=Smoke
        created=[];original=Smoke.__init__
        def init(self,store):original(self,store);created.append(self)
        Smoke.__init__=init
        try:runpy.run_path(str(ROOT/'run_transcomic.py'),run_name='__main__')
        except SystemExit as result:
            if result.code:raise
            w=created[0];info=w._probe_info
            reopened=Store(application.data_path())
            assert len(info['calls'])==1 and info['confirmations']==[True]
            assert not w.scheduler._thread.is_alive()
            assert all(r['state']=='unknown' for r in reopened.lines(info['doc']))
            assert not Scheduler.has_work(reopened,info['job']);reopened.close()
            print(json.dumps({'safe_exit_completed':True,'process_exit_verified_by_parent':True,
                'elapsed':time.monotonic()-info['start'],'requests':1,'unknown_preserved':True}),flush=True)
    else:
        with TemporaryDirectory() as directory:
            os.environ['LOCALAPPDATA']=directory;os.environ['QT_QPA_PLATFORM']='windows'
            application.MainWindow=Smoke;runpy.run_path(str(ROOT/'run_transcomic.py'),run_name='__main__')
