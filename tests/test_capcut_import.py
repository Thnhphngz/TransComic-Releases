from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QFileDialog
from transcomic.ui.capcut_import import MultiGroupDialog
from transcomic.capcut.media import MediaGroup
from test_capcut_ui import page,wait
from test_capcut_media import media_group


@pytest.mark.parametrize('count',[1,2,10,20])
def test_multiple_manual_pairs_single_dialog(page,tmp_path,count):
    app,w,p=page;d=MultiGroupDialog(p)
    for _ in range(count-1):d.add_entry()
    for i,e in enumerate(d.entries):
        e.name.setText(f'Chương {i}');e.image.setText(str(tmp_path/f'g{i}'));e.audio.setText(str(tmp_path/f'g{i}'/'voice'));e.sort.setCurrentIndex(i%2)
    d.accept();assert d.result()==QDialog.Accepted and len(d.result_groups)==count
    assert all(g.image_sort==('created' if i%2 else 'name') for i,g in enumerate(d.result_groups))
    assert not p.manager.groups
    p.manager.add_many(d.result_groups);assert len(p.manager.groups)==count


def test_incomplete_cancel_delete_and_duplicate_warning(page,tmp_path,monkeypatch):
    app,w,p=page;d=MultiGroupDialog(p);d.add_entry();d.entries[0].image.setText(str(tmp_path));d.entries[0].audio.setText(str(tmp_path/'voice'))
    d.accept();assert not d.result_groups and 'Cặp 2' in d.error.text()
    d.remove_entry(d.entries[1]);d.reject();assert not p.manager.groups
    d=MultiGroupDialog(p);e=d.entries[0];e.image.setText(str(tmp_path));e.audio.setText(str(tmp_path/'voice'))
    duplicate=d.add_entry();duplicate.image.setText(e.image.text());duplicate.audio.setText(e.audio.text())
    calls=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *args:(calls.append(1) or QMessageBox.No))
    d.accept();assert calls and not d.result_groups
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.Yes)
    d.accept();assert len(d.result_groups)==2


def test_image_choice_never_autoselects_audio(page,tmp_path,monkeypatch):
    app,w,p=page;d=MultiGroupDialog(p);entry=d.entries[0];chosen=tmp_path/'Ảnh 1-2';voice=chosen/'1-2_EN_184tts';calls=[]
    def choose(parent,title,start):
        calls.append(start);return str(chosen if len(calls)==1 else voice)
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',choose)
    entry.browse(entry.image);assert entry.name.text()=='Ảnh 1-2' and not entry.audio.text()
    entry.browse(entry.audio);assert calls[1]==str(chosen) and entry.audio.text()==str(voice)


def test_compact_expand_sort_refresh_and_latest_export(page,tmp_path):
    from PySide6.QtWidgets import QComboBox
    import json
    app,w,p=page;group=media_group(tmp_path/'a',3);p.manager.add(group);p.render_groups();p.scan_all();wait(app,p)
    p.show_group(group.id);assert p.inspector.currentWidget() is p.inspector_body
    sort=p.group_sort;d=p.details
    sort.setCurrentIndex(1);assert p.is_busy() and d.model.rowCount()==0
    wait(app,p);assert p.scans[group.id].group.image_sort=='created'
    assert d.proxy.columnCount()==7 and d.model.index(0,4).data()!='Không xác định'
    p.output.setText(str(tmp_path/'export'));p.start_export();wait(app,p)
    output=next((tmp_path/'export').glob('*/transcomic_mapping.json'))
    mapping=json.loads(output.read_text(encoding='utf8'))['pairs']
    assert [r['pair_id'] for r in mapping]==[r.id for r in p.scans[group.id].rows]


def test_add_button_dialog_applies_all_entries_once(page,tmp_path,monkeypatch):
    app,w,p=page;groups=[media_group(tmp_path/f'g{i}',1) for i in range(2)]
    def execute(dialog):
        dialog.add_entry()
        for entry,group in zip(dialog.entries,groups):entry.image.setText(group.image_dir);entry.audio.setText(group.audio_dir);entry.name.setText(group.name)
        dialog.accept();return dialog.result()
    monkeypatch.setattr(MultiGroupDialog,'exec',execute)
    p.add_button.click();wait(app,p)
    assert len(p.manager.groups)==2 and len(p.scans)==2 and all(s.valid for s in p.scans.values())


def test_compact_controls_do_not_overlap_low_window(page,tmp_path):
    from transcomic.ui.glass import GlassButton
    app,w,p=page
    for i in range(20):p.manager.add(media_group(tmp_path/f'g{i}',1))
    p.render_groups();w.resize(950,620);app.processEvents()
    p.show_group(p.manager.groups[0].id);app.processEvents()
    controls=[p.group_edit,p.group_up,p.group_down,p.group_remove]
    panel=p.inspector_body
    from PySide6.QtCore import QPoint,QRect
    rects=[QRect(b.mapTo(panel,QPoint()),b.size()) for b in controls]
    assert all(panel.rect().contains(r) for r in rects)
    assert all(not a.intersects(b) for i,a in enumerate(rects) for b in rects[i+1:])
    p.settings_toggle.setChecked(False);app.processEvents()
    assert p.output.isVisible() and p.export_button.isVisible()
