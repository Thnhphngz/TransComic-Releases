"""Offline Qt comparison of the original exit polling rule and bounded cancellation."""
import asyncio,json,os,sys,time
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
import httpx
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler
from transcomic.ui.main import MainWindow


def wait(predicate):
    deadline=time.monotonic()+12
    while not predicate():
        QApplication.instance().processEvents();QTest.qWait(5);time.sleep(.005)
        assert time.monotonic()<deadline


app=QApplication([]);app.setQuitOnLastWindowClosed(False)
results=[]
with TemporaryDirectory() as temp:
    for legacy in (True,False):
        store=Store(Path(temp)/f'{legacy}.db')
        doc,_=store.import_document(Path(temp)/'a.txt',decode_txt('\n'.join(f'Source {i}' for i in range(120)).encode()))
        w=MainWindow(store);w.show();app.processEvents()
        calls=[]
        async def slow(request):
            calls.append(time.monotonic());await asyncio.sleep(3)
            lines=json.loads(json.loads(request.content)['messages'][1]['content'])['lines']
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'The translation is complete.'} for r in lines]})}}]})
        job=store.create_job(doc,'deepseek-v4.1-flash','vi','en',30)
        w.scheduler=Scheduler(store,KiraProvider('mock-only',transport=httpx.MockTransport(slow)),w.bridge.changed.emit)
        if legacy:
            # Original finish_safe_exit rule, read before the changes: poll forever
            # until worker exits, then close. No deadline and no HTTP cancellation.
            def original_poll():
                if any(t.is_alive() for t in getattr(w,'background_threads',[])):return
                if w.scheduler and w.scheduler._thread and w.scheduler._thread.is_alive():return
                w._exit_authorized=True;w.exit_timer.stop();w.close()
            w.exit_timer.timeout.disconnect();w.exit_timer.timeout.connect(original_poll)
        w.scheduler.start(job);wait(lambda:len(calls)==30)
        w.shutdown_grace_seconds=.2;w.confirm_exit=lambda running:'safe'
        ticks=[];timer=QTimer(w);timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start()
        started=time.monotonic();w.stop_translation();w.close();wait(lambda:w._closed)
        timer.stop()
        results.append({'policy':'original_unbounded_poll' if legacy else 'bounded_cancel',
                        'seconds':time.monotonic()-started,'heartbeats':len(ticks),'calls':len(calls),
                        'grace_seconds':None if legacy else .2,'mock_response_delay_seconds':3})
        assert len(calls)==30
out=Path('artifacts/performance/shutdown-comparison.json');out.write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))
