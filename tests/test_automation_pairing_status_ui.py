"""Folder-drop status cannot move the target row under the pointer."""
import json
import os
from pathlib import Path
import threading

import pytest
from docx import Document
from PySide6.QtCore import Qt,QPoint,QPointF,QMimeData,QUrl
from PySide6.QtGui import QImage,QColor,QDragEnterEvent,QDropEvent
from test_automation_ui import gui,wait


@pytest.mark.parametrize('dark',[False,True])
def test_word_folder_drop_status_stays_beside_validation_without_moving_rows(gui,tmp_path,monkeypatch,dark):
    import transcomic.automation.validation as validation
    app,w,p,wid=gui
    if w.dark!=dark:w.toggle_theme()
    if w.sidebar.width()<100:w.toggle_sidebar()
    w.resize(1672,941);app.processEvents()
    paths=[]
    for i in range(40):
        doc=Document();doc.add_paragraph(f'Synthetic chapter number {i}')
        path=tmp_path/f'{i+1:02}.docx';doc.save(path);paths.append(path)
    gids=p.repo.add(wid,paths);folder=tmp_path/'images';folder.mkdir()
    image=QImage(20,30,QImage.Format_RGB32);image.fill(QColor(30,60,80));assert image.save(str(folder/'0001.png'))
    for gid in gids[:6]:p.repo.pair_images(gid,folder)
    p.refresh();p.validate_clicked();wait(app,lambda:p.proof is not None,15)
    assert '34 nhóm' in p.validation_badge.text()
    target=gids[32];p.table.setCurrentIndex(p.model.index(32,1));p.table.scrollTo(p.model.index(32,1));app.processEvents()
    geometries=[];evidence=os.environ.get('AUTOMATION_PAIRING_UI_EVIDENCE')
    def capture(phase):
        result=dict(table=p.table_shell.geometry().getRect(),viewport=p.table.viewport().geometry().getRect(),
                    scroll=p.table.verticalScrollBar().value(),selection=p.selected(),
                    target=p.table.visualRect(p.model.index(32,1)).getRect(),
                    notice=p.notice.geometry().getRect(),badge=p.validation_badge.geometry().getRect())
        if evidence:
            out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
            assert w.grab().save(str(out/f'pairing-{dark}-{phase}.png'))
            (out/f'pairing-{dark}-{phase}.json').write_text(json.dumps(dict(dpr=w.devicePixelRatioF(),platform=app.platformName(),**result),indent=2),encoding='utf8')
        return result
    before=capture('before');entered=threading.Event();release=threading.Event();original=validation.image_manifest
    name=p.model.index(32,1)
    assert name.data(Qt.ForegroundRole) is None
    def held(*a,**kw):entered.set();assert release.wait(8);return original(*a,**kw)
    monkeypatch.setattr(validation,'image_manifest',held)
    point=p.table.visualRect(p.model.index(32,2)).center()
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(folder))])
    enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    try:
        app.sendEvent(p.table.viewport(),enter);app.sendEvent(p.table.viewport(),drop)
        assert enter.isAccepted() and drop.isAccepted()
        from transcomic.ui.automation_widgets import status_color
        assert name.data(Qt.ForegroundRole)==QColor(status_color('completed',dark))
        assert 'Đã nhận thư mục ảnh' in name.data(Qt.ToolTipRole)
        assert not p.repo.group(target)['data'].get('image_folder') # Still being inspected, not marked valid.
        assert p.model.index(31,1).data(Qt.ForegroundRole) is None
        wait(app,entered.is_set)
        during=capture('checking')
        assert before['table']==during['table'] and before['target']==during['target'],(before,during)
        assert before['scroll']==during['scroll'] and p.selected()==target
        assert p.notice.parentWidget() is p.validation_badge.parentWidget()
        assert p.notice.isVisible() and p.notice.text()=='Đang kiểm tra thư mục ảnh…'
        assert p.notice.geometry().center().y()==p.validation_badge.geometry().center().y()
        assert p.notice.geometry().right()<p.validation_badge.geometry().left()
        assert p.notice.toolTip()==p.notice.text() and not p.start.isEnabled()
    finally:release.set()
    wait(app,lambda:not p.pair_pending and p.proof is not None and not p.validation_busy,15)
    assert p.repo.group(target)['data']['image_folder']==str(folder.resolve())
    assert name.data(Qt.ForegroundRole)==QColor(status_color('completed',dark))
    assert '33 nhóm' in p.validation_badge.text() and not p.notice.isVisible()
    assert capture('complete')['table']==before['table']
    # Progress and long errors share the same inline slot, at every layout size.
    for size in ((1672,941),(1050,760),(900,580)):
        w.resize(*size);app.processEvents();p.adapt_layout();app.processEvents()
        baseline=(p.table_shell.geometry(),p.search.geometry(),p.toolbar.geometry(),p.table.verticalScrollBar().value())
        for text in ('Đang kiểm tra thư mục ảnh…','','Thông báo lỗi dài cần giữ đầy đủ trong tooltip. '*15,''):
            p.notice.setText(text);app.processEvents();p.adapt_layout();app.processEvents()
            assert baseline==(p.table_shell.geometry(),p.search.geometry(),p.toolbar.geometry(),p.table.verticalScrollBar().value())
            assert p.notice.toolTip()==text
            if text:
                assert p.notice.geometry().center().y()==p.validation_badge.geometry().center().y()
                assert not p.notice.geometry().intersects(p.validation_badge.geometry())
            geometries.append(dict(size=size,text=bool(text),table=p.table_shell.geometry().getRect()))
    assert p.selected()==target and not w.store.jobs() and not p.controller.busy
    if evidence:
        (Path(evidence)/f'pairing-{dark}-resize.json').write_text(json.dumps(geometries,indent=2),encoding='utf8')


@pytest.mark.parametrize('dark',[False,True])
def test_rejected_folder_reverts_received_color_and_keeps_previous_mapping(gui,tmp_path,monkeypatch,dark):
    import transcomic.automation.validation as validation
    from transcomic.ui.automation_widgets import status_color
    from test_automation import add_group
    app,w,p,wid=gui
    if w.dark!=dark:w.toggle_theme()
    unpaired,_,_=add_group(p.repo,wid,tmp_path/'first',count=2)
    paired,_,folder=add_group(p.repo,wid,tmp_path/'second',count=2)
    p.repo.update_group(unpaired,image_folder='',images=[])
    empty=tmp_path/'empty';empty.mkdir();p.refresh()
    rows={row['id']:i for i,row in enumerate(p.model.rows)}
    index=p.model.index(rows[unpaired],1);old=p.model.index(rows[paired],1)
    green=QColor(status_color('completed',dark))
    assert index.data(Qt.ForegroundRole) is None and old.data(Qt.ForegroundRole)==green
    entered=threading.Event();release=threading.Event();original=validation.image_manifest
    def held(*a,**kw):entered.set();assert release.wait(5);return original(*a,**kw)
    monkeypatch.setattr(validation,'image_manifest',held)
    p.pair_folder(unpaired,empty)
    try:
        assert index.data(Qt.ForegroundRole)==green
        wait(app,entered.is_set);p.refresh() # A snapshot cannot erase pending feedback.
        assert index.data(Qt.ForegroundRole)==green
    finally:release.set()
    wait(app,lambda:not p.pair_pending)
    assert index.data(Qt.ForegroundRole) is None and old.data(Qt.ForegroundRole)==green
    assert not p.repo.group(unpaired)['data'].get('image_folder')
    p.pair_folder(paired,empty);wait(app,lambda:not p.pair_pending)
    assert old.data(Qt.ForegroundRole)==green
    assert p.repo.group(paired)['data']['image_folder']==str(folder.resolve())
    assert not w.store.jobs() and not p.controller.busy
