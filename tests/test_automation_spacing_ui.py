"""Automation header geometry only: no engine, network, export or validation run."""
import json
import os
from pathlib import Path
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSplitter
from test_automation_ui import gui
from test_automation import add_group,FakeEngine
from transcomic.ui.theme import colors


def metrics(p):
    top=lambda w:w.mapTo(p.left_pane,QPoint()).y()
    return dict(table_top=p.table_shell.y(),table_height=p.table_shell.height(),
                header_height=p.title_label.parentWidget().height(),
                body_spacing=p.left_pane.layout().spacing(),header_spacing=p.header_grid.verticalSpacing(),
                toolbar_spacing=p.toolbar_grid.verticalSpacing(),top_margin=p.columns.contentsMargins().top(),
                rows={name:[top(w),w.height()] for name,w in (
                    ('title',p.title_label),('subtitle',p.subtitle),('worksets',p.worksets),('toolbar',p.toolbar),('search',p.search),('table',p.table_shell))})


@pytest.mark.parametrize('dark',[False,True])
def test_header_spacing_screenshots(gui,tmp_path,dark):
    app,w,p,id=gui;w.resize(1672,941)
    if w.dark!=dark:w.toggle_theme()
    if w.sidebar.width()<100:w.toggle_sidebar()
    target=os.environ.get('TRANSCOMIC_SPACING_SCREENSHOTS')
    if target:
        directory=Path(target);directory.mkdir(parents=True,exist_ok=True);theme='dark' if dark else 'light'
        p.refresh();app.processEvents();assert w.grab().save(str(directory/f'automation-empty-{theme}.png'))
    for n in range(6):add_group(p.repo,id,tmp_path/str(n),name=f'{n*2+1}-{n*2+2}',count=2)
    p.refresh();app.processEvents()
    assert not p.repo.store.jobs() and not FakeEngine.calls
    if target:
        directory=Path(target);directory.mkdir(parents=True,exist_ok=True);theme='dark' if dark else 'light'
        assert w.grab().save(str(directory/f'automation-{theme}.png'))
        (directory/f'geometry-{theme}.json').write_text(json.dumps(dict(dpr=w.devicePixelRatioF(),window=[w.width(),w.height()],**metrics(p)),indent=2),encoding='utf-8')


@pytest.mark.parametrize('dark',[False,True])
def test_one_rounded_boundary_clips_all_four_corners_without_rounding_internal_joins(gui,dark):
    app,w,p,id=gui;w.resize(1672,941)
    if w.dark!=dark:w.toggle_theme()
    app.processEvents();frame=p.table_shell;content=frame.content
    assert all(pane.parentWidget() is content for pane in p.table_panes)
    assert not content.mask().isEmpty() and content.mask().contains(content.rect().center())
    corners=(QPoint(0,0),QPoint(content.width()-1,0),QPoint(0,content.height()-1),QPoint(content.width()-1,content.height()-1))
    snapshot=w.grab().toImage();dpr=w.devicePixelRatioF()
    def pixel(point):
        position=content.mapTo(w,point);return snapshot.pixelColor(round(position.x()*dpr),round(position.y()*dpr))
    for point in corners:
        assert not content.mask().contains(point)
        assert pixel(point)==QColor(colors(w)['background'])
    # At the joins only the common header surface is visible, with no inner arcs.
    for x in (p.number_table.geometry().right(),p.action_table.x()):
        assert all(pixel(QPoint(x+delta,8))==QColor(colors(w)['field']) for delta in (-1,0,1))


@pytest.mark.parametrize('size',[(900,580),(1200,780),(1672,941)])
@pytest.mark.parametrize('expanded',[False,True])
@pytest.mark.parametrize('dark',[False,True])
def test_compact_header_keeps_controls_aligned_and_table_gets_remaining_height(gui,tmp_path,size,expanded,dark):
    app,w,p,id=gui;w.resize(*size)
    if w.dark!=dark:w.toggle_theme()
    if (w.sidebar.width()>100)!=expanded:w.toggle_sidebar()
    add_group(p.repo,id,tmp_path/'g');p.refresh();app.processEvents();p.adapt_layout();app.processEvents()
    assert not p.findChildren(QSplitter)
    assert p.left_pane.layout().spacing()==2 and p.columns.contentsMargins().top()==2
    assert p.header_grid.verticalSpacing()==0 and p.toolbar_grid.verticalSpacing()==0
    buttons=sorted(p.toolbar_buttons,key=lambda b:(b.y(),b.x()))
    assert buttons==[p.add,p.validate_button,p.start,p.stop]
    assert len({b.height() for b in buttons})==1 and buttons[0].height()==36
    for i,button in enumerate(buttons):
        assert p.toolbar.rect().contains(button.geometry())
        assert button.fontMetrics().horizontalAdvance(button.text())<=button.width()-12
        assert all(not button.geometry().intersects(other.geometry()) for other in buttons[i+1:])
    # Each toolbar row has aligned, equally sized buttons and a consistent gap.
    for row in {b.y() for b in buttons}:
        pair=[b for b in buttons if b.y()==row]
        assert max(b.width() for b in pair)-min(b.width() for b in pair)<=1
        assert all(b.x()-a.geometry().right()-1==6 for a,b in zip(pair,pair[1:]))
    assert p.table_shell.geometry().bottom()>=p.left_pane.height()-2
    assert p.table_shell.height()>=110 and not p.notice.isVisible()
    # No vertical stretch or spacer before the table.
    body=p.left_pane.layout()
    assert all(body.stretch(i)==0 and body.itemAt(i).spacerItem() is None for i in range(body.count()-1))
    sections=[p.title_label.parentWidget(),p.worksets,p.toolbar,p.search,p.table_shell]
    mapped=[(s.mapTo(p.left_pane,QPoint()).y(),s.height()) for s in sections]
    assert all(a+h<=b for (a,h),(b,_) in zip(mapped,mapped[1:]))
    assert not p.right_scroll.horizontalScrollBar().isVisible()
    assert p.action_table.viewport().rect().contains(p.action_table.visualRect(p.model.index(0,6)))
    assert not p.repo.store.jobs() and not FakeEngine.calls
