"""Windows entry-point smoke; only mock HTTP, exact user DOCX sources."""
import asyncio,json,os,runpy,time,hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import httpx
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from transcomic.ui.main import MainWindow
from transcomic.ui.window_state import show_initial
from transcomic.languages import language
from transcomic.providers import KiraProvider
from transcomic.security import protect_key
from transcomic.storage import Store
import transcomic.app as application
import transcomic.ui.stage2 as stage2

OUT=Path('artifacts/multilingual/gui')/os.environ.get('QT_SCALE_FACTOR','1')
SOURCES=[Path(r'D:\word 50 cach\3-4.docx'),Path(r'D:\word 50 cach\5-6.docx'),Path(r'D:\Sourch Code\TransComic\7-8.docx')]

def wait(predicate,timeout=90):
    end=time.monotonic()+timeout
    while not predicate():
        QApplication.instance().processEvents();QTest.qWait(5);time.sleep(.001)
        assert time.monotonic()<end,'GUI timeout'

def exercise(w):
    app=QApplication.instance();app.setQuitOnLastWindowClosed(False)
    assert app.platformName()=='windows'
    hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES]
    w.import_paths(SOURCES);wait(lambda:not w.import_busy);assert len(w.workspace_ids)==3
    for chip in w.target_chips.values():chip.setChecked(False)
    for code in ('ja','de','en'):w.target_chips[language(code).name].click()
    assert [language(n).locale for n in w.target_languages()]==['ja','de','en']
    w.target_chips[language('de').name].click();w.target_chips[language('de').name].click()
    assert [language(n).locale for n in w.target_languages()]==['ja','en','de']
    # Native screenshots compare actual rendered selected background across hover, both themes.
    chip=w.target_chips[language('ja').name];hover=[]
    for dark in (False,True):
        if w.dark!=dark:w.toggle_theme()
        w.resize(1400,850);app.processEvents();QTest.qWait(30)
        QTest.mouseMove(w.sidebar);QTest.qWait(20)
        before=chip.grab().toImage();color=before.pixelColor(12,before.height()//2).name()
        QTest.mouseMove(chip);QTest.qWait(20)
        after=chip.grab().toImage();assert color==after.pixelColor(12,after.height()//2).name()
        assert color in ('#9b552c','#d88a4e')
        hover.append({'dark':dark,'background':color});w.grab().save(str(OUT/f'hover-{dark}.png'))
    w.store.save_key(protect_key('mock-only'));w.concurrency.setValue(30)
    order=[];current_active=0;peak=0;ended=[];seen={}
    async def handle(req):
        nonlocal current_active,peak
        payload=json.loads(req.content);instruction=payload['messages'][0]['content']
        locale=next(code for code in ('ja','en','de') if 'Target locale: '+code+';' in instruction)
        rows=json.loads(payload['messages'][1]['content'])['lines'];key=rows[0]['id'];seen[key]=seen.get(key,0)+1
        assert not current_active or order[-1][0]==locale
        order.append((locale,time.monotonic()));current_active+=1;peak=max(peak,current_active)
        await asyncio.sleep(.01);current_active-=1;ended.append((locale,time.monotonic()))
        if locale=='ja' and seen[key]==1 and len(seen)%7==0:return httpx.Response(200,json={})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'Mock '+r['text']} for r in rows]})}}]})
    previous=stage2.KiraProvider;stage2.KiraProvider=lambda key,model,**kw:KiraProvider(key,model,transport=httpx.MockTransport(handle),**kw)
    try:
        w.start_translation();wait(lambda:not w.scheduler._thread.is_alive());w.refresh()
        assert list(dict.fromkeys(l for l,_ in order))==['ja','en','de']
        for a,b in [('ja','en'),('en','de')]:assert max(t for l,t in ended if l==a)<min(t for l,t in order if l==b)
        assert all(r['state']=='done' for d in w.workspace_ids for r in w.store.lines(d))
        w.pages.setCurrentIndex(4);w.grab().save(str(OUT/'console.png'));w.pages.setCurrentIndex(0)
        scroll=w.table.verticalScrollBar();scroll.setValue(min(250,scroll.maximum()));position=scroll.value();w.refresh();assert scroll.value()==position
        for width,height in ((1400,850),(900,580)):
            w.resize(width,height);QTest.qWait(50);app.processEvents()
            assert w.table.width()>400 and w.table.height()>80
            w.grab().save(str(OUT/f'layout-{width}.png'))
        path=w.store.path;events=w.store.log.snapshot();w._exit_authorized=True;w.close()
        reopened=MainWindow(Store(path));show_initial(reopened);QTest.qWait(50)
        assert not reopened.workspace_ids and reopened.scheduler is None
        assert [language(n).locale for n in reopened.target_languages()]==['ja','en','de']
        assert len(reopened.store.documents())==9
        reopened.grab().save(str(OUT/'reopened.png'));reopened._exit_authorized=True;reopened.close()
        assert hashes==[hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES]
        report={'platform':app.platformName(),'scale':os.environ.get('QT_SCALE_FACTOR','1'),'files':3,'language_order':['ja','en','de'],'lines':1125,'mock_requests':len(order),'peak':peak,'selected_hover':hover,'workspace_empty_on_restart':True,'history_preserved':True,'source_unchanged':True,'real_api_requests':0}
        (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');(OUT/'console.json').write_text(json.dumps(events,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
    finally:stage2.KiraProvider=previous

class Smoke(MainWindow):
    def __init__(self,store):
        super().__init__(store)
        def run():
            try:exercise(self);QApplication.instance().quit()
            except Exception:
                import traceback
                (OUT/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');traceback.print_exc();QApplication.instance().exit(1)
        QTimer.singleShot(200,run)

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory() as root:
        os.environ['LOCALAPPDATA']=root;application.MainWindow=Smoke
        runpy.run_path('run_transcomic.py',run_name='__main__')
