"""Last authorized Word fixture pass: real Windows GUI, isolated DB, mock HTTP."""
import asyncio
import hashlib
import json
import os
import runpy
import shutil
import time
from pathlib import Path
try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory
import httpx
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog, QFileDialog
from PySide6.QtTest import QTest
from transcomic.ui.main import MainWindow
from transcomic.providers import KiraProvider
from transcomic.docx_document import import_docx
from scripts.docx_fixture_budget import reserve, complete
import transcomic.app as application
import transcomic.ui.stage2 as controls

OUT=Path('artifacts/final/docx-native')


def wait_until(predicate,timeout=45):
    deadline=time.monotonic()+timeout
    while not predicate():
        QApplication.instance().processEvents(); QTest.qWait(10)
        assert time.monotonic()<deadline, 'Native GUI deadline'


def exercise(w):
    number=reserve('Windows native full DOCX import, EN/ID mock, retry workspace, three exports')
    assert number is not None, 'Authorized document test budget exhausted'
    app=QApplication.instance(); assert app.platformName()=='windows'
    original=Path('D:/word 50 cach/7-8.docx'); raw=original.read_bytes()
    folder=w.store.path.parent/'input'; folder.mkdir(); source=folder/'7-8.docx'; source.write_bytes(raw)
    calls=[]; counts={}; failed=None; limited=None; active=peak=0; heartbeat=[]; confirmations=[]
    timer=QTimer(w); timer.setInterval(20); timer.timeout.connect(lambda:heartbeat.append(time.monotonic())); timer.start()
    async def handler(req):
        nonlocal failed,limited,active,peak
        data=json.loads(json.loads(req.content)['messages'][1]['content']); rows=data['lines']
        key=rows[0]['id']; counts[key]=counts.get(key,0)+1; calls.append(key)
        active+=1; peak=max(peak,active); await asyncio.sleep(.02); active-=1
        if failed is None: failed=key
        if key==failed and counts[key]<=4:
            return httpx.Response(200,json={'choices':[{'message':{'content':'invalid JSON'}}]})
        if limited is None:
            limited=key
            return httpx.Response(429,headers={'Retry-After':'.08'},json={})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'Mr.P, '+r['text']+'.'} for r in reversed(rows)]})}}]})
    saved=controls.KiraProvider
    question=QMessageBox.question; getitem=QInputDialog.getItem; getdir=QFileDialog.getExistingDirectory
    controls.KiraProvider=lambda key,model,**kw:KiraProvider(key,model,transport=httpx.MockTransport(handler),**kw)
    QMessageBox.question=lambda *args:(confirmations.append(args[1]) or QMessageBox.Yes)
    w._key=lambda:'isolated-fake'
    try:
        w.import_paths([str(source)]); wait_until(lambda:not w.import_busy)
        assert len(w.workspace_ids)==1 and len(w.store.lines(w.doc_id))==125
        w.extra_targets=['Tiếng Indonesia']; w.sync_target_chips(); w.concurrency.setValue(50)
        w.start_translation(); wait_until(lambda:w.scheduler is not None and not w.scheduler._thread.is_alive())
        initial=w.scheduler; assert initial.rate_limits==1 and initial.retry_count==4
        errors=sum(r['state']=='error' for d in w.workspace_ids for r in w.store.lines(d)); assert errors==3
        assert len(w.workspace_ids)==2
        w.refresh(); w.grab().save(str(OUT/'errors-before-retry.png'))
        first=w.workspace_ids[0]; row=next(r for r in w.store.lines(first) if r['state']=='done')
        w.store.edit_line(row['id'],'translation','Manual.period. stays')
        w.filter_combo.setCurrentIndex(1)
        w.retry_workspace_button.click(); wait_until(lambda:w.scheduler is not initial and not w.scheduler._thread.is_alive())
        assert all(r['state'] in ('done','skip') for d in w.workspace_ids for r in w.store.lines(d))
        assert w.store.line(row['id'])['translation']=='Manual.period. stays'
        assert all('.' not in r['translation'] for d in w.workspace_ids for r in w.store.lines(d) if r['id']!=row['id'])
        results=[]
        for index,mode in enumerate(['direct','transcomic','custom']):
            QInputDialog.getItem=lambda *args,n=index:(args[3][n],True)
            custom=w.store.path.parent/'custom'; custom.mkdir(exist_ok=True)
            QFileDialog.getExistingDirectory=lambda *args:str(custom)
            w.export_many(); wait_until(lambda:not w.export_busy)
            for doc_id in w.workspace_ids:
                path=Path(w.store.setting('export_path_'+doc_id)); assert path.is_file()
                reimported=import_docx(path); original_units=import_docx(source)
                assert len(reimported.units)==125
                assert [u.locator for u in reimported.units]==[u.locator for u in original_units.units]
                destination=OUT/'outputs'/mode/path.name; destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,destination)
                results.append({'mode':mode,'path':str(destination),'units':len(reimported.units)})
        w.filter_combo.setCurrentIndex(0); w.refresh(); QTest.qWait(50)
        w.grab().save(str(OUT/'complete.png'))
        for index,name in [(4,'console'),(3,'settings')]:
            w.pages.setCurrentIndex(index); w.refresh(); QTest.qWait(50); w.grab().save(str(OUT/(name+'.png')))
        w.pages.setCurrentIndex(0)
        count=len(w.store.documents()); w.document_panel.remove_all.click(); app.processEvents()
        assert not w.workspace_ids and w.doc_id is None and len(w.store.documents())==count
        assert source.read_bytes()==raw and original.read_bytes()==raw
        w.grab().save(str(OUT/'empty-preserved-history.png'))
        complete(number)
        report={'pass_number':number,'platform':app.platformName(),'source_sha256':hashlib.sha256(raw).hexdigest(),
            'source_units':125,'target_workspaces':2,'mock_requests':len(calls),'peak':peak,'initial_retries':initial.retry_count,
            'initial_429':initial.rate_limits,'initial_errors':errors,'retry_workspace_success':True,
            'manual_preserved':True,'source_unchanged':True,'locator_structure_preserved':True,
            'real_api_requests':0,'exports':results,'confirmations':confirmations,'heartbeat_ticks':len(heartbeat)}
        (OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(report,ensure_ascii=True))
    finally:
        controls.KiraProvider=saved; QMessageBox.question=question; QInputDialog.getItem=getitem; QFileDialog.getExistingDirectory=getdir
        if w.scheduler: w.scheduler.stop(); w.scheduler.join(5)
        w._exit_authorized=True; w.close(); app.quit()


class SmokeWindow(MainWindow):
    def __init__(self,store):
        super().__init__(store)
        def run():
            try: exercise(self)
            except Exception:
                import traceback
                traceback.print_exc(); self._exit_authorized=True; self.close(); QApplication.instance().exit(1)
        QTimer.singleShot(200,run)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory() as temporary:
        os.environ['LOCALAPPDATA']=temporary; application.MainWindow=SmokeWindow
        runpy.run_path('run_transcomic.py',run_name='__main__')
