from pathlib import Path
import json
import pytest
from PySide6.QtCore import Qt,QPoint
from transcomic.capcut.media import MediaGroup
from transcomic.capcut.state import GroupManager
from test_capcut_ui import page,wait
from test_capcut_single_page import populate,settle


@pytest.mark.parametrize('dark',[False,True])
def test_live_plan_name_order_count_clamp_and_persistence(page,tmp_path,dark):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    groups=populate(p,tmp_path,10);assert p.mode.count()==3 and p.split_controls.isHidden()
    p.mode.setCurrentIndex(2);p.part_count.setValue(4);p.project_name.setText('1 - 20 vote');settle(app)
    assert p.split_controls.isVisible() and p.project_name.isEnabled()
    assert [len(part.groups) for part in p.split_model.parts]==[3,3,2,2]
    assert [p.split_model.index(i,0).data() for i in range(4)]==[f'1 - 20 vote_part{i}' for i in range(1,5)]
    assert p.split_model.index(1,1).data()=='4–6'
    p.move_group(groups[3].id,-1);settle(app)
    assert p.split_model.index(0,0).data(Qt.UserRole)==tuple(g.id for g in p.manager.groups[:3])
    assert groups[3].name in p.split_model.index(0,0).data(Qt.ToolTipRole)
    p.part_count.setValue(10);p.remove_group(groups[-1].id);settle(app)
    assert p.part_count.maximum()==9 and p.part_count.value()==9 and p.split_model.rowCount()==9
    assert GroupManager(p.store).part_count==9
    p.mode.setCurrentIndex(0);assert p.split_controls.isHidden() and not p.project_name.isEnabled()
    p.mode.setCurrentIndex(1);assert p.split_controls.isHidden() and p.project_name.isEnabled()


def test_split_needs_two_groups_and_revalidates_after_clear(page,tmp_path,monkeypatch):
    app,w,p=page;groups=populate(p,tmp_path,1);p.mode.setCurrentIndex(2)
    assert p.part_count.minimum()==2 and not p.part_count.isEnabled() and not p.export_button.isEnabled()
    p.output.setText(str(tmp_path/'invalid'))
    with pytest.raises(ValueError):p.start_export()
    assert not p.busy and not (tmp_path/'invalid').exists()
    p.part_count.setValue(0);assert p.part_count.value()==2
    p.part_count.setValue(-5);assert p.part_count.value()==2
    monkeypatch.setattr(p,'confirm_clear_all',lambda:True);p.clear_all()
    assert not p.split_model.rowCount() and not p.export_button.isEnabled()
    populate(p,tmp_path/'new',2);p.render_groups();assert p.part_count.isEnabled() and p.export_button.isEnabled()
    p.part_count.setValue(99);assert p.part_count.value()==2 and p.split_model.rowCount()==2


@pytest.mark.parametrize('dark',[False,True])
def test_split_export_ui_snapshot_and_preview_geometry(page,tmp_path,dark):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    populate(p,tmp_path,10);p.mode.setCurrentIndex(2);p.part_count.setValue(4);p.project_name.setText('vote');p.output.setText(str(tmp_path/'projects'))
    for size in ((1400,1000),(950,620)):
        w.resize(*size);settle(app)
        assert p.settings_frame.geometry().bottom()<p.height() and p.export_button.isVisible()
        assert p.split_preview.height()<=136 and p.groups.viewport().height()>=90
        assert p.part_count.mapTo(p,QPoint()).x()+p.part_count.width()<=p.width()
    expected=[tuple(g.id for g in part.groups) for part in p.split_model.parts]
    p.export_button.click();assert p.busy and not p.clear_button.isEnabled() and not p.part_count.isEnabled()
    wait(app,p)
    for i,ids in enumerate(expected,1):
        output=tmp_path/'projects'/f'vote_part{i}';mapping=json.loads((output/'transcomic_mapping.json').read_text(encoding='utf8'))['pairs']
        assert tuple(dict.fromkeys(r['group_id'] for r in mapping))==ids
        assert (output/'draft_cover.jpg').is_file() and mapping[0]['start_us']==0
    assert p.bar.value()==100 and p.part_count.isEnabled()


def test_preview_200_groups_uses_virtual_model_and_bounded_height(page):
    app,w,p=page
    groups=[MediaGroup(f'id-{i}',f'Group {i}',f'D:/synthetic/images/{i}',f'D:/synthetic/voice/{i}') for i in range(200)]
    p.manager.add_many(groups);p.render_groups();p.mode.setCurrentIndex(2);p.part_count.setValue(3);settle(app)
    assert [len(part.groups) for part in p.split_model.parts]==[67,67,66]
    p.part_count.setValue(200);assert p.split_model.rowCount()==200 and p.split_preview.height()<=136
    p.split_preview.scrollToBottom();settle(app)
    assert p.split_preview.verticalScrollBar().maximum()>0
