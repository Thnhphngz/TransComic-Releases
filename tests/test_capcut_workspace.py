"""Selection identity, scan fencing and unchanged application navigation."""
import threading
import pytest
from PySide6.QtCore import Qt
from transcomic.capcut.media import MediaGroup,scan_group
from test_capcut_ui import page,wait
from test_capcut_single_page import populate,settle,click_group


@pytest.mark.parametrize('count',[0,1,10,20,100])
def test_empty_pending_group_list_and_filter_does_not_change_export_order(page,count):
    app,w,p=page
    groups=[MediaGroup(f'id-{i}',f'Group {i:03}',f'D:/fixture/image/{i}',f'D:/fixture/voice/{i}') for i in range(count)]
    if groups:p.manager.add_many(groups)
    p.render_groups();settle(app)
    assert p.group_model.rowCount()==count and p.selected_group_id is None
    assert p.details.proxy.rowCount()==0 and p.totals.state==('pending' if count else 'empty')
    assert p.list_empty.isVisible()==(count==0) and p.inspector.currentWidget() is p.inspector_empty
    order=[g.id for g in p.manager.groups]
    if count:
        p.show_group(groups[-1].id);assert p.selected_group_id==groups[-1].id
        assert p.details.model.rowCount()==0 and p.group_summary.property('scanState')=='pending'
        p.group_search.setText('not found');assert p.group_proxy.rowCount()==0 and p.selected_group_id is None
        assert p.details.model.rowCount()==0
        p.group_search.clear();assert p.group_proxy.rowCount()==count
    assert [g.id for g in p.manager.groups]==order


def test_switch_group_while_scan_busy_and_late_preview_cannot_restore_old_group(page,tmp_path,monkeypatch):
    import transcomic.ui.capcut_page as module
    app,w,p=page;a,b=populate(p,tmp_path);p.show_group(a.id);d=p.details
    d.table.setCurrentIndex(d.proxy.index(0,0));old_file=d.preview_file
    entered=threading.Event();release=threading.Event();calls=[]
    def delayed(group,cancel):calls.append(group.id);entered.set();release.wait(5);return scan_group(group,cancel)
    monkeypatch.setattr(module,'scan_group',delayed);p.scan_all();assert entered.wait(1)
    generation=p.generation
    try:
        click_group(app,p,b.id)
        assert p.selected_group_id==b.id and d.model.rowCount()==0 and p.groups.isEnabled()
        assert not p.group_sort.isEnabled() and not p.group_edit.isEnabled()
        d.preview_ready((old_file.path,old_file.size,old_file.mtime_ns))
        assert d.preview_file is None and d.selected_pair is None
        release.set();wait(app,p)
        assert calls==[a.id,b.id] and p.generation==generation
        assert p.selected_group_id==b.id and d.scan.group.id==b.id and d.proxy.rowCount()==3
        assert d.selected_pair is None and p.player is None
    finally:release.set();wait(app,p)


def test_sidebar_icons_navigation_geometry_and_no_top_navigation(page,tmp_path):
    app,w,p=page;groups=populate(p,tmp_path);p.show_group(groups[0].id)
    titles=[b.text() for b in w.nav_buttons];icons=[b.icon().pixmap(24,24).toImage() for b in w.nav_buttons]
    assert len(titles)==7 and all(not b.icon().isNull() for b in w.nav_buttons)
    width=w.sidebar.width()
    for index in (0,8,0,8):w.pages.setCurrentIndex(index);settle(app)
    assert w.sidebar.width()==width and [b.text() for b in w.nav_buttons]==titles
    assert [b.icon().pixmap(24,24).toImage() for b in w.nav_buttons]==icons
    assert p.selected_group_id==groups[0].id
    w.toggle_sidebar();settle(app);assert w.sidebar.width()<width
    w.toggle_sidebar();settle(app);assert w.sidebar.width()==width
    assert not hasattr(p,'expand_button') and not hasattr(p,'collapse_button')


def test_group_search_reuses_cached_summaries_and_same_media_model(page,tmp_path,monkeypatch):
    app,w,p=page;groups=populate(p,tmp_path);p.show_group(groups[0].id);d=p.details
    scan=d.scan;rows=d.model.rows;cached=p.group_model.items
    def unexpected():raise AssertionError('Typing group search must not rebuild all summaries')
    monkeypatch.setattr(p.group_model,'load',unexpected)
    for text in ('N','Nh','Nhóm',''):
        p.group_search.setText(text);settle(app)
        assert p.group_model.items is cached and d.scan is scan and d.model.rows is rows
        assert p.selected_group_id==groups[0].id
