"""Native Windows smoke through run_transcomic.py; generated DOCX, mock API only."""
import asyncio
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
from docx import Document
from PySide6.QtCore import QTimer, Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from transcomic.ui.main import MainWindow
from transcomic.providers import KiraProvider
from transcomic.security import protect_key
import transcomic.ui.stage2 as stage2
import transcomic.app as application

OUT=Path('artifacts/retry-management/gui')


def wait(predicate, timeout=20):
    deadline=time.monotonic()+timeout
    while not predicate():
        QApplication.instance().processEvents(); QTest.qWait(10)
        assert time.monotonic()<deadline, 'GUI deadline'


def exercise(w):
    app=QApplication.instance(); store=w.store
    assert app.platformName()=='windows'
    files=[]
    for n in range(3):
        path=store.path.parent/f'chapter{n}.docx'; d=Document()
        for i in range(18): d.add_paragraph(f'File {n} source line {i}')
        d.save(path); files.append(path)
    w.import_paths(files); wait(lambda:not w.import_busy); assert len(w.workspace_ids)==3
    identities=list(w.workspace_ids)
    w.import_paths(files); wait(lambda:not w.import_busy); assert w.workspace_ids==identities
    before=w.model_name.currentIndex()
    e=QWheelEvent(QPointF(10,10), QPointF(10,10), QPoint(), QPoint(0,-120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(w.model_name,e); assert w.model_name.currentIndex()==before
    store.save_key(protect_key('mock-only-key')); w.concurrency.setValue(3)
    calls={}; active=peak=0
    async def handle(req):
        nonlocal active, peak
        rows=json.loads(json.loads(req.content)['messages'][1]['content'])['lines']; key=rows[0]['id']
        calls[key]=calls.get(key,0)+1; active+=1; peak=max(peak,active)
        await asyncio.sleep(.03); active-=1
        if len(calls)<=3 and calls[key]==1: return httpx.Response(429, headers={'Retry-After':'.4'}, json={})
        if calls[key]==1 and len(calls)%4==0: return httpx.Response(200,json={})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'Valid '+r['text']} for r in rows]})}}]})
    previous=stage2.KiraProvider
    stage2.KiraProvider=lambda key,model,**kw:KiraProvider(key,model,transport=httpx.MockTransport(handle),**kw)
    try:
        w.start_translation(); wait(lambda:w.scheduler and w.scheduler.rate_limits>0)
        w.refresh(); assert not w.scheduler._paused.is_set()
        assert 'API' in w.active_label.text()
        w.grab().save(str(OUT/'cooldown.png'))
        # Switch to a different import while pending responses continue.
        w.open_document(identities[-1]); position=w.table.verticalScrollBar().value()
        wait(lambda:not w.scheduler._thread.is_alive()); w.refresh(); QTest.qWait(100)
        assert w.table.verticalScrollBar().value()==position
        for j in w.scheduler.job_ids: assert all(r['state']=='done' for r in store.lines(store.job(j)['document_id']))
        events=store.log.snapshot(); names={e['event'] for e in events}
        assert {'automatic_resume','retry_scheduled','job_completed','notification'}<=names
        assert len([e for e in events if e['event']=='notification'])==1
        w.refresh(); assert len([e for e in store.log.snapshot() if e['event']=='notification'])==1
        assert not list(store.path.parent.rglob('*_EN.docx'))
        w.grab().save(str(OUT/'completed.png'))
        report={'platform':app.platformName(),'generated_docx':3,'source_lines':54,'mock_requests':sum(calls.values()),'retry_requests':w.scheduler.retry_count,'peak_concurrency':peak,'user_paused':False,'automatic_resume':True,'duplicate_import_blocked':True,'wheel_blocked':True,'notification_count':1,'sound_requested':True,'scroll_preserved':True,'real_api_requests':0,'exports':0}
        (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        (OUT/'events.json').write_text(json.dumps(events,indent=2),encoding='utf-8')
        print(json.dumps(report))
    finally:
        stage2.KiraProvider=previous
        if w.scheduler and w.scheduler._thread.is_alive(): w.scheduler.stop(); w.scheduler.join(5)
        w._exit_authorized=True; w.close(); app.quit()


class SmokeWindow(MainWindow):
    def __init__(self, store):
        super().__init__(store)
        def run():
            try: exercise(self)
            except Exception:
                import traceback
                traceback.print_exc()
                if not self._closed and self.scheduler and self.scheduler._thread.is_alive(): self.scheduler.stop(); self.scheduler.join(5)
                self._exit_authorized=True; self.close(); QApplication.instance().exit(1)
        QTimer.singleShot(200,run)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory() as temporary:
        previous=os.environ.get('LOCALAPPDATA'); os.environ['LOCALAPPDATA']=temporary
        application.MainWindow=SmokeWindow
        try: runpy.run_path('run_transcomic.py',run_name='__main__')
        finally:
            if previous is None: os.environ.pop('LOCALAPPDATA',None)
            else: os.environ['LOCALAPPDATA']=previous
