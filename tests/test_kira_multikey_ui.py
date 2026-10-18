import json
import os
from pathlib import Path
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.documents import decode_txt
from transcomic.kira_pool import KiraPoolProvider
from transcomic.providers import BatchResult
from transcomic.translation import Scheduler


@pytest.fixture
def gui(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    s=Store(tmp_path/'isolated.db');w=MainWindow(s);w.resize(1400,850);w.show();app.processEvents()
    yield app,s,w
    if not w._closed:w._exit_authorized=True;w.close();app.processEvents()


@pytest.mark.parametrize('dark',[False,True])
def test_selected_model_status_does_not_display_old_quota(gui,dark):
    app,s,w=gui
    if w.dark!=dark:w.toggle_theme()
    s.add_kira_keys('synthetic-model-display')
    key=s.kira_keys()[0]['id']
    s.kira_key_status(key,'QUOTA_EXHAUSTED',model='old-paid-model')
    pool=KiraPoolProvider(s,'explicit-free-model')
    w.scheduler=Scheduler(s,pool)
    w.refresh_kira_keys()
    assert 'Sẵn sàng' in w.kira_keys_list.item(0).text()
    assert s.kira_keys()[0]['status']=='QUOTA_EXHAUSTED'
    lease=pool.reserve(1,1)
    pool.release(lease[0],BatchResult({},'permission',diagnostics={'failure_kind':'permission'}))
    w.refresh_kira_keys()
    assert 'Không có quyền dùng model' in w.kira_keys_list.item(0).text()


def test_idle_monitor_does_not_infer_shared_account(gui):
    from transcomic.ui.kira_monitor import idle_snapshot
    app,s,w=gui
    s.add_kira_keys('synthetic-idle-a synthetic-idle-b synthetic-idle-c')
    s.set_setting('concurrency','30')
    snap=idle_snapshot(w)
    assert snap['keys']==3 and snap['maximum']==90
    ids=[k['id'] for k in s.kira_keys()]
    for key in ids:s.set_kira_account_scope(key,ids[0])
    assert idle_snapshot(w)['maximum']==30


@pytest.mark.parametrize('dark',[False,True])
def test_keys_ui_refresh_stable_toggle_delete_and_no_network(gui,monkeypatch,dark):
    app,s,w=gui
    if w.dark!=dark:w.toggle_theme()
    w.pages.setCurrentIndex(2)
    w.api_key_input.setText(' '.join(f'sk-GUI-synthetic-{i:03d}' for i in range(35)))
    w.save_api_key();assert len(s.kira_keys())==35 and not w.api_key_input.text()
    app.processEvents();QTest.qWait(100)
    assert w.kira_keys_list.count()==35 and w.kira_keys_list.verticalScrollBar().maximum()>0
    w.kira_keys_list.setCurrentRow(20);key=w.selected_kira_key()
    for _ in range(4):w.refresh_kira_keys();w.refresh_stage2()
    assert len(s.kira_keys())==35 and w.selected_kira_key()==key
    item=w.kira_keys_list.currentItem();item.setCheckState(Qt.Unchecked)
    assert not next(k for k in s.kira_keys() if k['id']==key)['enabled']
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.No)
    w.delete_kira_key();assert len(s.kira_keys())==35
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    w.delete_kira_key();assert len(s.kira_keys())==34
    assert all('sk-GUI-' not in w.kira_keys_list.item(i).text() for i in range(w.kira_keys_list.count()))
    assert not any(e['event']=='gui_error' for e in s.log.snapshot())


@pytest.mark.parametrize('dark',[False,True])
def test_capture_kira_api_and_editor_no_toolbar_regression(gui,tmp_path,dark):
    app,s,w=gui
    if w.dark!=dark:w.toggle_theme()
    s.add_kira_keys('sk-synthetic-AAA sk-synthetic-BBB sk-synthetic-CCC')
    key=s.kira_keys()[1]['id'];s.kira_key_status(key,'QUOTA_EXHAUSTED')
    path=tmp_path/'Minh họa Multi-Key.txt';raw='\n'.join(f'Nguồn minh họa {i}' for i in range(150)).encode()
    path.write_bytes(raw);doc=s.import_document(path,decode_txt(raw),'vi','en')[0];w.open_document(doc)
    s.edit_line(s.lines(doc)[1]['id'],'translation','An example.')
    w.refresh();w.refresh_kira_keys();QTest.qWait(250)
    assert w.concurrency.maximum()==30 and 'MỖI key' in w.concurrency.toolTip()
    for width in (1400,950):
        w.resize(width,850);app.processEvents();QTest.qWait(80)
        buttons=w.file_action_buttons[1:]
        positions=[b.mapTo(w.editor_page,QPoint()) for b in buttons]
        assert len({p.y() for p in positions})==1
        assert all(a.x()<b.x() for a,b in zip(positions,positions[1:]))
        assert w.line_check.mapTo(w.editor_page,QPoint()).y()==w.period_warning.mapTo(w.editor_page,QPoint()).y()
    assert w.kira_manage_button.isVisible()
    QTest.mouseClick(w.kira_manage_button,Qt.LeftButton)
    assert w.pages.currentIndex()==0 and w.kira_monitor_dialog.isVisible()
    QTest.keyClick(w.kira_monitor_dialog,Qt.Key_Escape)
    w.provider_selector.setCurrentIndex(1);app.processEvents();assert w.kira_manage_button.isHidden()
    assert 'Gemini' in w.concurrency.toolTip()
    w.provider_selector.setCurrentIndex(0);assert not w.kira_manage_button.isHidden()
    available=w.screen().availableGeometry();w.resize(min(1500,available.width()-20),min(900,available.height()-50))
    destination=os.environ.get('TRANSCOMIC_KIRA_EVIDENCE')
    if destination:
        out=Path(destination);out.mkdir(parents=True,exist_ok=True)
        w.pages.setCurrentIndex(0);QTest.qWait(150);assert w.grab().save(str(out/f'editor-{dark}.png'))
        w.pages.setCurrentIndex(2);QTest.qWait(150);assert w.grab().save(str(out/f'api-{dark}.png'))
        (out/'dpi.json').write_text(json.dumps({'dpr':w.devicePixelRatioF(),'platform':app.platformName()}))


@pytest.mark.parametrize('dark',[False,True])
def test_account_group_picker_and_visible_per_key_counters(gui,monkeypatch,dark):
    app,s,w=gui
    if w.dark!=dark:w.toggle_theme()
    s.add_kira_keys('sk-ui-counter-one sk-ui-counter-two')
    ids=[k['id'] for k in s.kira_keys()]
    w.refresh_kira_keys()
    for i,key in enumerate(ids):
        w.kira_keys_list.setCurrentRow(i)
        monkeypatch.setattr(QInputDialog,'getItem',lambda parent,title,prompt,labels,*args,n=i: (labels[n+1],True))
        w.group_kira_account()
        assert s.kira_account_scope(key)==key
    w.kira_keys_list.setCurrentRow(1)
    monkeypatch.setattr(QInputDialog,'getItem',lambda parent,title,prompt,labels,*args:(labels[0],False))
    w.group_kira_account();assert s.kira_account_scope(ids[1])==ids[1]
    pool=KiraPoolProvider(s,'mock')
    key,_=pool.reserve(30,1);pool.sent(key)
    pool.completed(key,BatchResult({}),3,3,.1);pool.release(key)
    pool.pending_batches=0
    w.scheduler=Scheduler(s,pool)
    w.refresh_kira_keys()
    assert 'gửi 1' in w.kira_metrics.text() and 'thành công 1' in w.kira_metrics.text()
    assert '1 batch/3 dòng đã lưu' in w.kira_metrics.text()
    assert 'gửi 0' in w.kira_metrics.text() and 'hết batch chưa gửi' in w.kira_metrics.text()
    assert '2 nhóm' in w.kira_metrics.text() and 'tổng trần 60' in w.kira_metrics.text()
    assert all(secret not in w.kira_metrics.toolTip() for secret in ('sk-ui-counter-one','sk-ui-counter-two'))
    w.pages.setCurrentIndex(2);app.processEvents()
    destination=os.environ.get('TRANSCOMIC_KIRA_EVIDENCE')
    if destination:
        out=Path(destination);out.mkdir(parents=True,exist_ok=True)
        w.pages.widget(2).ensureWidgetVisible(w.kira_metrics)
        app.processEvents()
        assert w.grab().save(str(out/f'account-stats-{dark}.png'))
    w.scheduler=None
