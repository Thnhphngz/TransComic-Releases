import json
from pathlib import Path
import threading
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QPlainTextEdit,QLabel
import httpx
import pytest
from qt_wait import wait_until
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.update.internal import InternalUpdateService
from transcomic.update.service import CheckResult
from test_internal_queue_clear import fixture,service


def window(tmp_path):
    app=QApplication.instance() or QApplication([]);w=MainWindow(Store(tmp_path/'gui.sqlite3'));w.show()
    return app,w


def wait(condition):
    assert wait_until(condition, 3000)


@pytest.mark.parametrize('kind',['manual','auto','same','offline','no-release','invalid','cached'])
def test_popup_only_manual_verified_internal(tmp_path,kind):
    app,w=window(tmp_path);release,envelope,contents=fixture('0.1.0' if kind=='same' else '0.2.0')
    if kind=='invalid':release['draft']=True
    respond=(lambda req:httpx.Response(404)) if kind=='no-release' else (lambda req:(_ for _ in ()).throw(httpx.ConnectError('fixture'))) if kind=='offline' else None
    panel=w.update_panel;panel.service=service(tmp_path,release,contents,respond)
    if kind=='cached':
        assert panel.service.check(True).candidate
        cache=panel.service._cache();cache['retry_after']=panel.service.clock()+3600;panel.service._save(cache)
    panel.check_now(kind!='auto');wait(lambda:not panel.busy)
    if kind in ('manual','cached'):
        assert panel.update_dialog is not None
        assert panel.update_dialog.windowTitle()=='Đã có phiên bản TransComic mới!'
        if kind=='cached':assert any('cache' in label.text() for label in panel.update_dialog.findChildren(QLabel))
        panel.update_dialog.reject();wait(lambda:panel.update_dialog is None);assert panel.downloaded_path is None and panel.item is not None
    else:assert panel.update_dialog is None
    w._exit_authorized=True;w.close();QTest.qWait(30)


@pytest.mark.parametrize('action',['later','escape','x','download'])
def test_popup_actions_and_duplicate_checks(tmp_path,action):
    app,w=window(tmp_path);release,envelope,contents=fixture();panel=w.update_panel;panel.service=service(tmp_path,release,contents)
    panel.check_now(True);panel.check_now(True);wait(lambda:panel.update_dialog is not None)
    dialog=panel.update_dialog;panel.check_now(True);assert panel.update_dialog is dialog
    if action=='later':dialog.later.click()
    elif action=='escape':QTest.keyClick(dialog,Qt.Key_Escape)
    elif action=='x':dialog.close()
    else:dialog.download.click()
    wait(lambda:panel.update_dialog is None and not panel.busy)
    if action=='download':
        assert panel.downloaded_path and panel.downloaded_path.suffix=='.testdata'
        assert 'không chạy bộ cài' in panel.status.text()
    else:
        assert panel.downloaded_path is None
        panel.check_now(True);wait(lambda:panel.update_dialog is not None);panel.update_dialog.reject()
    w._exit_authorized=True;w.close();QTest.qWait(30)


def test_popup_notes_plain_text_and_other_modal_not_stolen(tmp_path):
    app,w=window(tmp_path);release,envelope,contents=fixture();release['body']='<script>alert(1)</script><b>notes</b>'
    panel=w.update_panel;panel.service=service(tmp_path,release,contents)
    other=QDialog(w);other.open();panel.check_now(True);wait(lambda:not panel.busy)
    assert panel.update_dialog is None;other.reject()
    panel.check_now(True);wait(lambda:panel.update_dialog is not None)
    assert panel.update_dialog.findChild(QPlainTextEdit).toPlainText()==release['body']
    panel.update_dialog.reject();w._exit_authorized=True;w.close();QTest.qWait(30)


def test_http_304_cache_popup_does_not_claim_no_network(tmp_path):
    app,w=window(tmp_path);release,envelope,contents=fixture();panel=w.update_panel
    panel.service=service(tmp_path,release,contents);panel.check_now(False);wait(lambda:not panel.busy)
    calls=[]
    panel.service.client=httpx.Client(transport=httpx.MockTransport(lambda req:calls.append(req) or httpx.Response(304)))
    panel.check_now(True);wait(lambda:panel.update_dialog is not None)
    labels=[label.text() for label in panel.update_dialog.findChildren(QLabel)]
    assert len(calls)==1 and any('cache' in text for text in labels)
    assert not any('chưa có lượt kiểm tra mạng' in text for text in labels)
    panel.update_dialog.reject();w._exit_authorized=True;w.close();QTest.qWait(30)


def test_srt_placeholder_navigation_preserves_editor(tmp_path):
    from transcomic.documents import decode_txt
    app,w=window(tmp_path);doc=w.store.import_document(tmp_path/'book.txt',decode_txt(b'hello'),'Tiếng Việt','Tiếng Anh')[0]
    w.workspace_ids=[doc];w.open_document(doc);w.table.setCurrentIndex(w.model.index(0,0))
    before=w.store.lines(doc);targets=w.target_languages();selection=w.table.currentIndex()
    for dark in (False,True):
        if w.dark!=dark:w.toggle_theme()
        for compact in (False,True):
            if (w.sidebar.width()<100)!=compact:w.toggle_sidebar()
            w.navigation_group.button(6).click();app.processEvents()
            assert w.pages.currentIndex()==6 and w.navigation_group.button(6).isChecked()
            assert w.navigation_group.button(6).toolTip()=='Dịch file SRT'
            assert any(label.text()=='Chức năng đang được cập nhật' for label in w.pages.widget(6).findChildren(QLabel))
            assert not w.pages.widget(6).findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton)
            w.navigation_group.button(0).click();assert w.store.lines(doc)==before and w.target_languages()==targets and w.table.currentIndex()==selection
    w._exit_authorized=True;w.close();QTest.qWait(30)


def test_build_allowlist_and_permission_separation():
    from scripts.build_local import input_files,ROOT
    paths=[p.relative_to(ROOT).as_posix() for p in input_files(ROOT)]
    assert 'transcomic/ui/assets/nav-subtitles.svg' in paths
    assert not any(p.startswith(('tests/','artifacts/','.pytest_','.git/')) or p.endswith(('.db','.docx','.tc-keybackup','.pem')) for p in paths)
    from transcomic.release_adapters import ProductionCommands
    from transcomic.update.metadata import UpdateError
    with pytest.raises(UpdateError):ProductionCommands()(['gh','release','create'],ROOT)
    from transcomic.update.install import InstallMachine
    with pytest.raises(UpdateError):InstallMachine().install()
