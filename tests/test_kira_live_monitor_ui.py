import asyncio
import json
import os
from pathlib import Path
import threading
import time

import httpx
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest

from transcomic.documents import decode_txt
from transcomic.kira_pool import KiraPoolProvider
from transcomic.translation import Scheduler
from test_kira_multikey import success
from test_kira_multikey_ui import gui


def wait_gui(app,condition,timeout=10):
    deadline=time.monotonic()+timeout
    while not condition() and time.monotonic()<deadline:
        app.processEvents();QTest.qWait(10)
    assert condition()


def make_run(app,store,window,*,keys=2,files=3,count=15,cap=2,outcome=None):
    store.add_kira_keys(' '.join(f'sk-monitor-GUI-fixture-{i:03d}' for i in range(keys)))
    store.set_setting('concurrency',str(cap))
    docs=[]
    for i in range(files):
        raw='\n'.join(f'Nguồn kiểm thử giao diện {j}' for j in range(count)).encode()
        doc=store.import_document(store.path.parent/f'{i}'/'same-name.txt',decode_txt(raw),'vi','en')[0]
        docs.append(doc);window.open_document(doc)
    window.open_document(docs[0]);window.refresh_kira_keys();app.processEvents()
    run,jobs=store.create_run(docs,['en'],provider='kira',model='mock',source_lang='vi',concurrency=cap,config={'kira_multi_key':True})
    gate=threading.Event();calls=[];failed=[]
    async def handler(req):
        calls.append(req)
        while not gate.is_set():await asyncio.sleep(.002)
        if outcome and not failed:
            failed.append(True);return outcome(req)
        return success(req)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),account_limit=keys*cap,rpm=100000,tpm=1000000000)
    scheduler=Scheduler(store,pool,window.bridge.changed.emit);window.scheduler=scheduler
    window.current_job_ids={r['id'] for j in jobs for b in store.batches(j) for r in b['payload']}
    scheduler.start_many(jobs,run)
    return docs,run,jobs,pool,scheduler,gate,calls


@pytest.mark.parametrize('dark',[False,True])
@pytest.mark.parametrize('keys',[1,10])
def test_idle_popup_bounds_theme_esc_manage_and_no_translation(gui,dark,keys):
    app,store,w=gui
    if w.dark!=dark:w.toggle_theme()
    store.add_kira_keys(' '.join(f'sk-idle-monitor-fixture-{i:03d}' for i in range(keys)))
    w.refresh_kira_keys()
    before=store.db.total_changes
    for width,height in ((1500,900),(950,650)):
        w.resize(width,height);app.processEvents()
        QTest.mouseClick(w.kira_manage_button,Qt.LeftButton)
        d=w.kira_monitor_dialog;app.processEvents()
        assert w.pages.currentIndex()==0 and d.isVisible()
        assert len(d.cards)==keys and 'Chưa có lượt' in d.note.text()
        assert d.height()<=w.height()*.8+1
        assert d.width()<=w.width() and d.geometry().intersected(w.screen().availableGeometry())==d.geometry()
        assert d.close_button.isVisible() and d.watch.isActive()
        QTest.keyClick(d,Qt.Key_Escape);assert not d.isVisible() and not d.watch.isActive()
    assert store.db.total_changes==before
    QTest.mouseClick(w.kira_manage_button,Qt.LeftButton)
    QTest.mouseClick(d.manage,Qt.LeftButton)
    assert w.pages.currentIndex()==2 and not d.isVisible() and not d.watch.isActive()


@pytest.mark.parametrize('dark',[False,True])
def test_live_file_attribution_navigation_completion_and_reopen(gui,dark):
    app,store,w=gui
    if w.dark!=dark:w.toggle_theme()
    docs,run,jobs,pool,scheduler,gate,calls=make_run(app,store,w,files=3,count=30)
    try:
        wait_gui(app,lambda:len(calls)==4)
        buttons=[b.mapTo(w.editor_page,QPoint()) for b in w.file_action_buttons[1:]]
        QTest.mouseClick(w.kira_manage_button,Qt.LeftButton);d=w.kira_monitor_dialog;app.processEvents()
        assert w.pages.currentIndex()==0 and d._run_id==run
        assert sum(c.model.rowCount() for c in d.cards.values())>=3
        assert sum(row['in_flight_lines'] for c in d.cards.values() for row in c.model.rows)==12
        assert 'gửi 4' in d.summary.text()
        assert all('sk-monitor' not in c.header.toolTip()+c.details.text() for c in d.cards.values())
        before={doc:[r['translation'] for r in store.lines(doc)] for doc in docs}
        card=next(c for c in d.cards.values() if any(r['document_id']!=w.doc_id for r in c.model.rows))
        QTest.mouseClick(card.header,Qt.LeftButton);app.processEvents()
        target=next(i for i,r in enumerate(card.model.rows) if r['document_id']!=w.doc_id)
        index=card.model.index(target,0);wanted=index.data(Qt.UserRole)[0]
        QTest.mouseClick(card.files.viewport(),Qt.LeftButton,pos=card.files.visualRect(index).center())
        assert w.doc_id==wanted and not d.isVisible() and not d.watch.isActive()
        assert before=={doc:[r['translation'] for r in store.lines(doc)] for doc in docs}
        assert len(calls)==4
        QTest.mouseClick(w.kira_manage_button,Qt.LeftButton)
        assert d.cards[card.key_id] is card and card.expanded
        w.workspace_ids.remove(wanted)
        d.choose_file((wanted,'en'));d.refresh_data()
        assert d.isVisible() and 'không còn' in d.note.text()
        w.workspace_ids.append(wanted)
        assert buttons==[b.mapTo(w.editor_page,QPoint()) for b in w.file_action_buttons[1:]]
        destination=os.environ.get('TRANSCOMIC_MONITOR_EVIDENCE')
        if destination:
            d._navigation_note='';d.refresh_data();app.processEvents()
            folder=Path(destination);folder.mkdir(parents=True,exist_ok=True)
            assert d.grab().save(str(folder/f'monitor-{"dark" if dark else "light"}.png'))
            assert w.grab().save(str(folder/f'editor-{"dark" if dark else "light"}.png'))
            (folder/'dpi.json').write_text(json.dumps({'dpr':w.devicePixelRatioF(),'platform':app.platformName()}),encoding='utf-8')
    finally:gate.set()
    wait_gui(app,lambda:not scheduler._thread.is_alive())
    assert d.watch.interval()==750
    wait_gui(app,lambda:'90 dòng đã lưu' in d.summary.text() and 'Đã hoàn thành' in d.summary.text())
    assert 'Đã hoàn thành' in d.summary.text() and '90 dòng đã lưu' in d.summary.text()
    assert sum(row['in_flight_lines'] for c in d.cards.values() for row in c.model.rows)==0
    QTest.mouseClick(d.close_button,Qt.LeftButton);assert not d.watch.isActive()
    w.scheduler=None
    QTest.mouseClick(w.kira_manage_button,Qt.LeftButton);app.processEvents()
    assert '90 dòng đã lưu' in d.summary.text() and 'Lượt gần nhất' in d.note.text()


def test_ten_cards_long_files_scroll_and_expansion_stay_stable(gui):
    app,store,w=gui
    docs,run,jobs,pool,scheduler,gate,calls=make_run(app,store,w,keys=10,files=30,count=3,cap=3)
    try:
        wait_gui(app,lambda:len(calls)==10)  # ten active files, one batch each
        QTest.mouseClick(w.kira_manage_button,Qt.LeftButton);d=w.kira_monitor_dialog;app.processEvents()
        for c in d.cards.values():c.toggle()
        app.processEvents();bar=d.scroll.verticalScrollBar();assert bar.maximum()>0
        bar.setValue(bar.maximum()//2);position=bar.value();order=list(d.cards)
        selections=[]
        for c in d.cards.values():
            if c.model.rows:c.files.setCurrentIndex(c.model.index(0,0));selections.append((c,c.files.currentIndex().data(Qt.UserRole)))
        queries=[];store.db.set_trace_callback(queries.append)
        for _ in range(15):d.refresh_data();app.processEvents()
        store.db.set_trace_callback(None)
        assert bar.value()==position and list(d.cards)==order and all(c.expanded for c in d.cards.values())
        assert all(c.files.currentIndex().data(Qt.UserRole)==key for c,key in selections)
        assert not any('SELECT a.state,a.diagnostics' in q for q in queries)
        for _ in range(5):
            d.close();assert not d.watch.isActive();QTest.mouseClick(w.kira_manage_button,Qt.LeftButton)
        assert len(calls)==10
    finally:gate.set()
    wait_gui(app,lambda:not scheduler._thread.is_alive());d.refresh_data()
    assert d.scroll.verticalScrollBar().value()==position
    assert all(c.expanded for c in d.cards.values())
    assert sum(c.model.rowCount() for c in d.cards.values())==30


def test_monitor_refresh_does_not_stall_150_http_slots(gui):
    app,store,w=gui
    docs,run,jobs,pool,scheduler,gate,calls=make_run(app,store,w,keys=5,files=10,count=60,cap=30)
    try:
        wait_gui(app,lambda:len(calls)==150,timeout=15)
        QTest.mouseClick(w.kira_manage_button,Qt.LeftButton);d=w.kira_monitor_dialog;app.processEvents()
        before=len(calls);durations=[]
        for _ in range(30):
            started=time.perf_counter();d.refresh_data();app.processEvents();durations.append(time.perf_counter()-started)
        assert len(calls)==before==150 and max(durations)<.5
        assert sum(s['in_flight_requests'] for s in pool.monitor_snapshot(30)['per_key'].values())==150
        out=Path('artifacts/kira-live-monitor');out.mkdir(parents=True,exist_ok=True)
        (out/'gui-performance.json').write_text(json.dumps(dict(mock_only=True,slots=150,
            max_refresh_seconds=max(durations),mean_refresh_seconds=sum(durations)/len(durations))),encoding='utf-8')
    finally:gate.set()
    wait_gui(app,lambda:not scheduler._thread.is_alive(),timeout=20)
    d.refresh_data();assert '600 dòng đã lưu' in d.summary.text()


def test_idle_key_status_changes_and_removal_keep_other_cards_stable(gui):
    app,store,w=gui
    store.add_kira_keys('sk-idle-state-A sk-idle-state-B');w.refresh_kira_keys()
    QTest.mouseClick(w.kira_manage_button,Qt.LeftButton);d=w.kira_monitor_dialog
    a,b=[k['id'] for k in store.kira_keys()];card_b=d.cards[b]
    for state,text in [('QUOTA_EXHAUSTED','Hết quota'),('INVALID','Key không hợp lệ'),
        ('COOLDOWN','Đang cooldown'),('UNKNOWN_ERROR','Lỗi chưa phân loại')]:
        store.kira_key_status(a,state,time.time()+60 if state=='COOLDOWN' else 0)
        d.refresh_data();assert text in d.cards[a].header.toolTip()
        assert d.cards[b] is card_b
    store.change_kira_key(a,enabled=False);d.refresh_data()
    assert 'Đã tắt' in d.cards[a].header.toolTip()
    store.change_kira_key(a,delete=True);d.refresh_data()
    assert list(d.cards)==[b] and d.cards[b] is card_b


def test_unknown_is_visible_separately_and_new_run_does_not_mix(gui):
    app,store,w=gui
    docs,run,jobs,pool,scheduler,gate,calls=make_run(app,store,w,files=1,count=6,outcome=lambda req:httpx.Response(504))
    try:
        wait_gui(app,lambda:len(calls)==2)
        QTest.mouseClick(w.kira_manage_button,Qt.LeftButton);d=w.kira_monitor_dialog
    finally:gate.set()
    wait_gui(app,lambda:not scheduler._thread.is_alive());d.refresh_data()
    assert 'unknown 1' in d.summary.text() and 'lỗi 0' in d.summary.text()
    assert sum(r['unknown_lines'] for c in d.cards.values() for r in c.model.rows)==3
    assert sum(r['failed_lines'] for c in d.cards.values() for r in c.model.rows)==0
    old_cards=list(d.cards.values())
    ids=[r['id'] for r in store.lines(docs[0]) if not r['translation']]
    job=store.create_job(docs[0],'mock','vi','en',2,ids,provider='kira')
    new=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(success))
    w.scheduler=Scheduler(store,new,w.bridge.changed.emit);w.scheduler.start(job)
    wait_gui(app,lambda:not w.scheduler._thread.is_alive());d.refresh_data()
    assert d._run_id==job and '3 dòng đã lưu' in d.summary.text()
    assert 'unknown 0' in d.summary.text()
    assert not any(c in old_cards for c in d.cards.values())


def test_monitor_open_and_file_navigation_preserve_native_editor_undo(gui):
    app,store,w=gui
    docs,run,jobs,pool,scheduler,gate,calls=make_run(app,store,w,files=2,count=3,cap=1)
    try:
        wait_gui(app,lambda:len(calls)==2)
        index=w.model.index(0,1);w.table.setCurrentIndex(index);w.table.edit(index);app.processEvents()
        editor=w.table.itemDelegate().active_editor;assert editor is not None
        QTest.keyClicks(editor,'Manual replacement');assert editor.document().isUndoAvailable()
        line_id=w.model.rows[0]['id'];assert store.line(line_id)['translation']=='Manual replacement'
        QTest.mouseClick(w.kira_manage_button,Qt.LeftButton);d=w.kira_monitor_dialog;app.processEvents()
        assert w.table.itemDelegate().active_editor is editor
        d.choose_file((docs[1],'en'));app.processEvents();assert w.doc_id==docs[1]
        QTest.mouseClick(w.kira_manage_button,Qt.LeftButton);d.choose_file((docs[0],'en'));app.processEvents()
        wait_gui(app,lambda:w.table.itemDelegate().active_editor is editor)
        restored=w.table.itemDelegate().active_editor
        assert restored is editor and restored.document().isUndoAvailable()
        QTest.keyClick(restored,Qt.Key_Z,Qt.ControlModifier)
        assert restored.toPlainText()==''
        QTest.keyClick(restored,Qt.Key_Y,Qt.ControlModifier)
        assert store.line(line_id)['translation']=='Manual replacement'
        assert len(calls)==2
    finally:gate.set()
    wait_gui(app,lambda:not scheduler._thread.is_alive())
