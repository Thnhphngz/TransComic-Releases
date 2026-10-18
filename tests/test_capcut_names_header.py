from pathlib import Path
import json,threading
import pytest
from PySide6.QtCore import Qt,QPoint,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit,QApplication,QMenu
from transcomic.capcut.planning import project_plan,name_errors
from transcomic.capcut.media import scan_group,Cancelled
from transcomic.capcut.exporter import export_projects
from transcomic.capcut.state import GroupManager
from test_capcut_ui import page,wait
from test_capcut_single_page import populate,settle


def prepare(page,tmp_path):
    app,w,p=page;groups=populate(p,tmp_path,10);p.mode.setCurrentIndex(2);p.part_count.setValue(4);p.project_name.setText('vote');settle(app)
    return app,w,p,groups


def edit(app,p,row,text,key=Qt.Key_Return):
    view=p.split_preview;index=p.split_model.index(row,0);view.scrollTo(index);settle(app)
    QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(index).center())
    QTest.mouseDClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(index).center());settle(app)
    editors=[e for e in view.findChildren(QLineEdit) if e.isVisible()]
    assert editors
    editors[0].setText(text);QTest.keyClick(editors[0],key);settle(app)


def test_enter_escape_custom_defaults_count_order_and_reset_menu(page,tmp_path):
    app,w,p,groups=prepare(page,tmp_path)
    assert [part.name for part in p.split_model.parts]==[f'vote_part{i}' for i in range(1,5)]
    assert p.split_model.flags(p.split_model.index(0,0))&Qt.ItemIsEditable
    assert not p.split_model.flags(p.split_model.index(0,1))&Qt.ItemIsEditable
    assert not p.split_model.flags(p.split_model.index(0,2))&Qt.ItemIsEditable
    edit(app,p,0,'vote_1-6');edit(app,p,1,'Truyện phần 2')
    edit(app,p,2,'Canceled',Qt.Key_Escape)
    assert p.split_model.parts[2].name=='vote_part3' and '3' not in p.manager.custom_names
    p.project_name.setText('comic');assert [part.name for part in p.split_model.parts]==['vote_1-6','Truyện phần 2','comic_part3','comic_part4']
    edit(app,p,3,'Final');p.part_count.setValue(3)
    assert p.split_model.parts[0].name=='vote_1-6' and p.manager.custom_names['4']=='Final'
    p.part_count.setValue(4);assert p.split_model.parts[3].name=='Final'
    p.move_group(groups[3].id,-1)
    assert p.split_model.parts[0].name=='vote_1-6' and p.split_model.parts[0].groups[2].id==groups[3].id
    index=p.split_model.index(0,0);position=p.split_preview.visualRect(index).center();seen=[]
    def choose_default():
        menu=app.activePopupWidget();assert isinstance(menu,QMenu);action=menu.actions()[0];seen.append(action.text())
        QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(action).center())
    QTimer.singleShot(0,choose_default);p.part_name_menu(position);settle(app)
    assert seen==['Dùng tên mặc định'] and p.split_model.parts[0].name=='comic_part1' and '1' not in p.manager.custom_names
    assert 'Truyện phần 2' in p.split_model.index(1,0).data(Qt.ToolTipRole)


@pytest.mark.parametrize('name',['','   ','a/b','a\\b','a:b','a?b','a*b','a"b','a<b','a>b','a|b','a\x00b','a\x1fb','CON','con.txt','PRN','AUX','NUL','COM1','LPT9','COM¹','.hidden','trailing.',' trailing','trailing ','x'*81])
def test_invalid_names_warning_blocks_export_without_silent_change(page,tmp_path,name):
    app,w,p,groups=prepare(page,tmp_path)
    assert p.split_model.setData(p.split_model.index(0,0),name)
    assert p.split_model.parts[0].name==name and p.manager.custom_names['1']==name
    assert p.split_model.errors and not p.export_button.isEnabled() and 'Part 1:' in p.split_notice.text()
    p.output.setText(str(tmp_path/'blocked'))
    with pytest.raises(ValueError):p.start_export()
    assert not p.busy and not (tmp_path/'blocked').exists()
    p.reset_part_name(0);assert not p.split_model.errors and p.export_button.isEnabled()


def test_duplicate_casefold_auto_collision_and_unicode_valid(page,tmp_path):
    app,w,p,groups=prepare(page,tmp_path)
    p.split_model.setData(p.split_model.index(0,0),'Tên riêng');p.split_model.setData(p.split_model.index(1,0),'TÊN RIÊNG')
    assert set(p.split_model.errors)=={1,2} and not p.export_button.isEnabled()
    assert p.totals.state=='review' and 'Sẵn sàng' not in p.totals.text()
    p.split_model.setData(p.split_model.index(1,0),'Khác');assert not p.split_model.errors
    assert p.totals.state=='ready'
    p.split_model.setData(p.split_model.index(0,0),'comic_part3');p.project_name.setText('comic')
    assert set(p.split_model.errors)=={1,3} and not p.export_button.isEnabled()
    p.reset_part_name(0);assert not p.split_model.errors


def test_restart_custom_names_and_legacy_settings(page,tmp_path):
    from transcomic.storage import Store
    from transcomic.ui.main import MainWindow
    app,w,p,groups=prepare(page,tmp_path);p.output.setText(str(tmp_path/'out'));p.save_options()
    p.split_model.setData(p.split_model.index(1,0),'Truyện phần 2');path=p.store.path
    before=[g.id for g in p.manager.groups];w._exit_authorized=True;w.close();settle(app)
    restored=MainWindow(Store(path));restored.show();restored.pages.setCurrentIndex(8);settle(app);q=restored.capcut_page
    try:
        wait(app,q);assert q.split_model.parts[1].name=='Truyện phần 2'
        assert [g.id for g in q.manager.groups]==before and q.manager.part_count==4 and q.manager.name=='vote'
        assert q.manager.output==str(tmp_path/'out') and q.manager.mode=='split'
        data=json.loads(q.store.setting('capcut_workspace_v1'));data.pop('custom_names');q.store.set_setting('capcut_workspace_v1',json.dumps(data))
        assert GroupManager(q.store).custom_names=={}
    finally:restored._exit_authorized=True;restored.close();settle(app)


def test_export_uses_edited_snapshot_and_does_not_silently_overwrite(page,tmp_path,monkeypatch):
    import transcomic.capcut.exporter as module
    app,w,p,groups=prepare(page,tmp_path)
    names=['vote_1-6','vote_7-12','Truyện 13-16','vote_17-20']
    for i,name in enumerate(names):edit(app,p,i,name)
    p.output.setText(str(tmp_path/'out'));entered=threading.Event();release=threading.Event();original=module.export_projects
    def delayed(*args,**kwargs):entered.set();release.wait(5);return original(*args,**kwargs)
    monkeypatch.setattr(module,'export_projects',delayed);p.start_export();assert entered.wait(1)
    try:
        assert not p.split_preview.isEnabled() and not p.split_model.flags(p.split_model.index(0,0))&Qt.ItemIsEditable
        assert not p.split_model.setData(p.split_model.index(0,0),'should not apply')
        p.manager.custom_names['1']='changed after snapshot'
        release.set();wait(app,p)
    finally:release.set();wait(app,p)
    for name in names:
        target=tmp_path/'out'/name
        assert target.is_dir() and json.loads((target/'draft_meta_info.json').read_text(encoding='utf8'))['draft_name']==name
        assert (target/'draft_cover.jpg').exists()
    assert not (tmp_path/'out'/'changed after snapshot').exists()
    # The same planner/engine keeps the old project and uses collision suffixes.
    scans=tuple(p.scans[g.id] for g in p.manager.groups)
    outputs=original(scans,tmp_path/'out',mode='split',name='vote',part_count=4,custom_names={str(i+1):n for i,n in enumerate(names)})
    assert [o.name for o in outputs]==[n+'_2' for n in names]
    cancel=threading.Event()
    def progress(n,msg):
        if 'vote_7-12' in msg:cancel.set()
    with pytest.raises(Cancelled):original(scans,tmp_path/'cancel',mode='split',part_count=4,custom_names={str(i+1):n for i,n in enumerate(names)},cancel=cancel,progress=progress)
    assert [o.name for o in (tmp_path/'cancel').iterdir()]==[names[0]]


@pytest.mark.parametrize('dark',[False,True])
def test_header_hierarchy_states_geometry_and_actual_group_font(page,tmp_path,dark,monkeypatch):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    assert p.totals.parentWidget() is p.page_header and p.totals.state=='empty'
    assert len(p.findChildren(type(p.totals)))==1
    groups=populate(p,tmp_path,10);w.resize(1400,1000);settle(app)
    assert p.totals.state=='ready' and p.totals.font().weight()>=700 and 'Sẵn sàng' in p.totals.text()
    title=p.title.mapTo(p,QPoint());totals=p.totals.mapTo(p,QPoint())
    assert not p.page_header.stacked and abs(title.y()+p.title.height()/2-totals.y()-p.totals.height()/2)<3
    assert totals.x()>title.x()+p.title.width() and p.page_header.geometry().bottom()<p.add_button.y()
    p.show_group(groups[0].id);c=p.group_heading
    assert c.font().pixelSize()==15 and c.font().weight()==600
    assert p.group_image_path.font().pixelSize()==13
    group=groups[0];p.manager.replace(__import__('dataclasses').replace(group,name='Long name '*50));p.render_groups();settle(app)
    assert c.text()!=c.full and c.toolTip()==c.full
    p.scans[group.id]=__import__('dataclasses').replace(p.scans[group.id],errors=('invalid media',));p.render_groups();assert p.totals.state=='review'
    w.resize(950,620);settle(app)
    assert p.page_header.stacked and p.totals.mapTo(p,QPoint()).y()>p.title.mapTo(p,QPoint()).y()
    assert p.page_header.geometry().bottom()<p.add_button.y() and p.page_header.width()<=p.width()
    entered=threading.Event();release=threading.Event()
    import transcomic.ui.capcut_page as module
    def failed_scan(group,cancel):entered.set();release.wait(5);raise OSError('simulated scan failure')
    monkeypatch.setattr(module,'scan_group',failed_scan);p.scan_all();assert entered.wait(1)
    try:
        assert p.totals.state=='scanning' and 'Sẵn sàng' not in p.totals.text()
        release.set();wait(app,p);assert p.totals.state=='review' and 'Quét thất bại' in p.totals.text()
        assert '1 mục lỗi' in p.totals.text()
        assert 'simulated scan failure' in p.totals.toolTip()
    finally:release.set();wait(app,p)


def test_backend_custom_validation_and_partition_unchanged():
    groups=tuple(range(10));parts=project_plan(groups,'split','vote',4,{'2':'Truyện phần 2'})
    assert [len(p.groups) for p in parts]==[3,3,2,2] and parts[1].name=='Truyện phần 2'
    assert tuple(g for part in parts for g in part.groups)==groups
    with pytest.raises(ValueError):project_plan(groups,'split','vote',4,{'1':'A','2':'a'})
    with pytest.raises(ValueError):project_plan(groups,'split','vote',4,{'1':'CON.txt'})


def test_single_group_header_and_stale_edit_index(page,tmp_path):
    app,w,p=page;group=populate(p,tmp_path,1)[0]
    assert p.totals.state=='ready'
    p.mode.setCurrentIndex(2);assert p.totals.state=='pending' and not p.export_button.isEnabled()
    populate(p,tmp_path/'extra',2);p.scans[group.id]=scan_group(group);p.render_groups();p.part_count.setValue(3)
    stale=p.split_model.index(2,0);p.part_count.setValue(2)
    assert not p.split_model.setData(stale,'wrong part') and p.totals.state=='ready'


@pytest.mark.parametrize('cancel',[False,True])
def test_export_commits_visible_editor_but_never_revives_escaped_edit(page,tmp_path,cancel):
    app,w,p=page;populate(p,tmp_path,2);p.mode.setCurrentIndex(2);p.project_name.setText('vote');settle(app)
    p.split_preview.edit(p.split_model.index(0,0));settle(app)
    editor=next(e for e in p.split_preview.findChildren(QLineEdit) if e.isVisible());editor.setText('From active editor')
    if cancel:QTest.keyClick(editor,Qt.Key_Escape)
    p.output.setText(str(tmp_path/'output'));p.start_export();wait(app,p)
    expected='vote_part1' if cancel else 'From active editor'
    meta=json.loads((tmp_path/'output'/expected/'draft_meta_info.json').read_text(encoding='utf8'))
    assert meta['draft_name']==expected and len(list((tmp_path/'output').iterdir()))==2
    assert p.manager.custom_names.get('1')==(None if cancel else expected)
