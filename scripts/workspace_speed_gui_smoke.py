"""Windows entry-point smoke: exact three authorized sources, HTTP mock only."""
import asyncio
import hashlib
import json
import os
import runpy
import time
from pathlib import Path
try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory
import httpx
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from transcomic.ui.main import MainWindow
from transcomic.ui.window_state import show_initial
from transcomic.providers import KiraProvider
from transcomic.storage import Store
from transcomic.security import protect_key
import transcomic.app as application
import transcomic.ui.stage2 as stage2

OUT=Path('artifacts/retry-speed/gui')
SOURCES=[Path(r'D:\word 50 cach\3-4.docx'),Path(r'D:\word 50 cach\5-6.docx'),Path(r'D:\Sourch Code\TransComic\7-8.docx')]


def wait(predicate,timeout=60):
    deadline=time.monotonic()+timeout
    while not predicate():
        QApplication.instance().processEvents();QTest.qWait(10)
        assert time.monotonic()<deadline,'GUI timeout'


def exercise(w):
    app=QApplication.instance();app.setQuitOnLastWindowClosed(False);store=w.store
    assert app.platformName()=='windows'
    hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES]
    w.import_paths(SOURCES);wait(lambda:not w.import_busy);assert len(w.workspace_ids)==3
    store.save_key(protect_key('mock-only'));w.concurrency.setValue(30)
    calls={};active=peak=0
    async def handle(req):
        nonlocal active,peak
        rows=json.loads(json.loads(req.content)['messages'][1]['content'])['lines'];key=rows[0]['id'];calls[key]=calls.get(key,0)+1
        active+=1;peak=max(peak,active);await asyncio.sleep(.03);active-=1
        if calls[key]==1 and len(calls)<=30:return httpx.Response(429,headers={'Retry-After':'.15'},json={})
        if calls[key]==1 and len(calls)%9==0:return httpx.Response(200,json={})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'Evelyn '+r['text']} for r in rows]})}}]})
    previous=stage2.KiraProvider;stage2.KiraProvider=lambda key,model,**kw:KiraProvider(key,model,transport=httpx.MockTransport(handle),**kw)
    reopened=None
    try:
        w.start_translation();wait(lambda:w.scheduler.rate_limits>0);w.refresh();w.grab().save(str(OUT/'cooldown.png'))
        wait(lambda:not w.scheduler._thread.is_alive());w.refresh()
        assert w.scheduler.effective_concurrency>1
        assert all(r['state']=='done' for d in w.workspace_ids for r in store.lines(d))
        s=w.search;s.open(True);s.document_scope.setCurrentIndex(1);s.scope.setCurrentIndex(2);s.query.setText('Evelyn');assert len(s.results)>=375
        s.document_scope.setCurrentIndex(2)
        for i in range(2):s.file_checks.item(i).setCheckState(Qt.Checked)
        selected_count=len(s.results);assert selected_count>0
        assert len({store.document(s.result_metadata[r]['document_id'])['source_instance'] for r in s.results})==2
        s.replacement.setText('Emily');s.replace_all();QTest.qWait(60);w.grab().save(str(OUT/'preview.png'));s.confirm_preview()
        assert len(s.undo_stack)==1;s.undo();assert not s.undo_stack
        s.navigate(-1);s.navigate(1);s.close_bar()
        if w.sidebar.width()>100:w.toggle_sidebar()
        w.document_splitter.setSizes([230,1000]);w.document_splitter.splitterMoved.emit(230,1);QTest.qWait(300)
        sizes=w.document_splitter.sizes();w.font_spin.setValue(18);w.toggle_theme();w.grab().save(str(OUT/'before-close.png'))
        path=store.path;history=len(store.documents());events=store.log.snapshot();retries=w.scheduler.retry_count;effective=w.scheduler.effective_concurrency
        w._exit_authorized=True;w.close()
        reopened=MainWindow(Store(path));show_initial(reopened);QTest.qWait(60);app.processEvents()
        assert reopened.sidebar.width()==72 and abs(reopened.document_splitter.sizes()[0]-sizes[0])<5
        assert reopened.dark and reopened.font_spin.value()==18 and not reopened.workspace_ids and reopened.doc_id is None and reopened.scheduler is None
        assert len(reopened.store.documents())==history
        reopened.grab().save(str(OUT/'restored-empty.png'))
        assert hashes==[hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES]
        report={'platform':app.platformName(),'actual_sources':[str(p) for p in SOURCES],'lines':375,'mock_requests':sum(calls.values()),'peak':peak,'effective_final':effective,'retry_requests':retries,'selected_search_matches':selected_count,'multi_file_preview_undo':True,'sidebar_restored':True,'panel_width_restored':True,'theme_font_restored':True,'workspace_reopened_empty':True,'history_preserved':True,'source_unchanged':True,'real_api_requests':0}
        (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');(OUT/'events.json').write_text(json.dumps(events,indent=2),encoding='utf-8');print(json.dumps(report))
    finally:
        stage2.KiraProvider=previous
        if not w._closed:
            if w.scheduler and w.scheduler._thread.is_alive():w.scheduler.stop();w.scheduler.join(10)
            w._exit_authorized=True;w.close()
        if reopened:reopened._exit_authorized=True;reopened.close()
        app.quit()


class Smoke(MainWindow):
    def __init__(self,store):
        super().__init__(store)
        def run():
            try:exercise(self)
            except Exception:
                import traceback
                (OUT/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
                traceback.print_exc();QApplication.instance().exit(1)
        QTimer.singleShot(200,run)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory() as temporary:
        previous=os.environ.get('LOCALAPPDATA');os.environ['LOCALAPPDATA']=temporary;application.MainWindow=Smoke
        try:runpy.run_path('run_transcomic.py',run_name='__main__')
        finally:
            if previous is None:os.environ.pop('LOCALAPPDATA',None)
            else:os.environ['LOCALAPPDATA']=previous
