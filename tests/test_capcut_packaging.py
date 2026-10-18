"""Portable effects, real external media and precise action identity."""
import json
import re
from pathlib import Path
import zipfile
from PySide6.QtWidgets import QApplication
from transcomic.capcut.package_probe import run
from transcomic.capcut.resources import effects
from test_capcut_ui import page
from test_capcut_single_page import populate
from test_capcut_row_actions import playback,click


def test_portable_project_does_not_read_developer_media_or_cache(tmp_path):
    app=QApplication.instance() or QApplication([])
    proof=run(tmp_path)
    assert proof['passed'] and proof['portable_effect_files']==32
    assert proof['outside_package_reads']==0 and proof['mutagen']=='1.48.1'


def test_distributable_template_has_no_private_paths_or_identity():
    package=Path(__file__).resolve().parents[1]/'transcomic/capcut'
    with zipfile.ZipFile(package/'mau-structure.zip') as packed:
        for name in packed.namelist():
            raw=packed.read(name)
            assert not re.search(rb'(?<![A-Za-z0-9])[A-Za-z]:[/\\]',raw)
            if Path(name).name=='draft_content.json':
                data=json.loads(raw)
                assert data['platform']['device_id']==data['last_modified_platform']['device_id']==''
    assert len(effects())==32


def test_action_uses_clicked_pair_even_when_current_is_another_row(page,tmp_path,playback):
    app,w,p=page;group=populate(p,tmp_path,1)[0];p.show_group(group.id);d=p.details
    first,second=p.scans[group.id].rows[:2]
    d.table.setCurrentIndex(d.proxy.index(1,0))
    click(app,d,0,0)
    assert d.playing_pair_id==first.id and playback[-1][0][0]==first.audios[0].path
    d.table.setCurrentIndex(d.proxy.index(1,0))
    click(app,d,0,1)
    assert d.preview_file.path==first.images[0].path
    assert second.id!=first.id
