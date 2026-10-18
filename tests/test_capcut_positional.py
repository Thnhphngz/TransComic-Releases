from dataclasses import replace
from pathlib import Path
import json
import os
import pytest
from transcomic.capcut.media import scan_group,freeze,native_path
from transcomic.capcut.state import GroupManager
from transcomic.storage import Store
from test_capcut_media import media_group


def test_184_unrelated_names_multinumber_nested_voice_and_parent_audio(tmp_path):
    group=media_group(tmp_path,184)
    # Audio subfolder is intentionally below the image folder; no recursion.
    nested=Path(group.image_dir)/'1-2_EN_184tts';Path(group.audio_dir).rename(nested)
    group=replace(group,audio_dir=str(nested))
    for n,path in enumerate(sorted(Path(group.image_dir).glob('*.png')),1):path.rename(path.with_name(f'chapter01_{n:06}_hash123.png'))
    for n,path in enumerate(sorted(nested.glob('*.wav')),1):path.rename(path.with_name(f'1-2_EN_{n}.wav'))
    (Path(group.image_dir)/'extra.wav').write_bytes(b'ignored parent audio')
    (nested/'deeper').mkdir();(nested/'deeper'/'000.wav').write_bytes(b'ignored recursive audio')
    scan=scan_group(group)
    assert scan.valid and scan.image_count==scan.audio_count==scan.matched==184
    assert [Path(r.audios[0].path).name for r in scan.rows[:3]]==['1-2_EN_1.wav','1-2_EN_2.wav','1-2_EN_3.wav']
    assert all(len(r.images)==len(r.audios)==1 for r in scan.rows)


def test_name_sort_no_numeric_requirement_and_created_order(tmp_path,monkeypatch):
    group=media_group(tmp_path,3)
    for old,new in [('001.png','image_c.png'),('002.png','image_a.png'),('003.png','image_b.png')]:
        (Path(group.image_dir)/old).rename(Path(group.image_dir)/new)
    for old,new in [('001.wav','1-2_10.wav'),('002.wav','1-2_2.wav'),('003.wav','1-2_1.wav')]:
        (Path(group.audio_dir)/old).rename(Path(group.audio_dir)/new)
    scan=scan_group(group)
    assert [Path(r.images[0].path).name for r in scan.rows]==['image_a.png','image_b.png','image_c.png']
    assert [Path(r.audios[0].path).name for r in scan.rows]==['1-2_1.wav','1-2_2.wav','1-2_10.wav']
    import transcomic.capcut.media as media
    original=media.probe
    def probe(path,image):
        f=original(path,image)
        return replace(f,created_ns={'image_c.png':1,'image_a.png':2,'image_b.png':2}[Path(path).name]) if image else f
    monkeypatch.setattr(media,'probe',probe)
    created=scan_group(replace(group,image_sort='created'))
    assert [Path(r.images[0].path).name for r in created.rows]==['image_c.png','image_a.png','image_b.png']
    assert [r.audios[0].path for r in created.rows]==[r.audios[0].path for r in scan.rows]


@pytest.mark.parametrize('side',['image','audio'])
def test_missing_middle_marks_every_pair_unverified(tmp_path,side):
    group=media_group(tmp_path,4)
    (Path(group.image_dir if side=='image' else group.audio_dir)/('002.png' if side=='image' else '002.wav')).unlink()
    scan=scan_group(group)
    assert len(scan.rows)==4 and scan.matched==0 and all(row.errors for row in scan.rows)
    with pytest.raises(ValueError):freeze([scan])


def test_unknown_birth_time_blocks_created_mode(tmp_path,monkeypatch):
    import transcomic.capcut.media as media
    group=media_group(tmp_path,1);monkeypatch.setattr(media,'creation_time_ns',lambda stat:None)
    assert scan_group(group).valid
    created=scan_group(replace(group,image_sort='created'))
    assert not created.valid and 'Date created' in created.errors[0]


def test_duplicate_listing_is_detected_without_duplicate_export(tmp_path,monkeypatch):
    group=media_group(tmp_path,1);original=Path.iterdir
    def entries(path):
        rows=list(original(path))
        return iter(rows+rows) if str(path)==group.image_dir else iter(rows)
    monkeypatch.setattr(Path,'iterdir',entries)
    scan=scan_group(group)
    assert not scan.valid and len(scan.rows)==1
    assert any('trùng' in error for error in scan.errors)


def test_creation_time_never_uses_modified(monkeypatch):
    from types import SimpleNamespace
    from transcomic.capcut.media import creation_time_ns
    assert creation_time_ns(SimpleNamespace(st_birthtime_ns=100,st_mtime_ns=999))==100
    assert creation_time_ns(SimpleNamespace(st_birthtime_ns=0,st_mtime_ns=999)) is None


def test_legacy_settings_default_and_order_preserved(tmp_path):
    store=Store(tmp_path/'state.db');group=media_group(tmp_path/'media',2)
    store.set_setting('capcut_workspace_v1',json.dumps({'groups':[dict(id=group.id,name=group.name,image_dir=group.image_dir,audio_dir=group.audio_dir)]}))
    manager=GroupManager(store);assert manager.groups[0].image_sort=='name'
    manager.replace(replace(manager.groups[0],image_sort='created'));store.close();store=Store(tmp_path/'state.db')
    try:
        restored=GroupManager(store).groups[0];assert restored.id==group.id and restored.image_sort=='created'
        assert restored.image_dir==group.image_dir
    finally:store.close()


def test_export_184_mixed_sorts_keeps_snapshot_order(tmp_path):
    from transcomic.capcut.exporter import export_projects,validate_content
    groups=[media_group(tmp_path/f'g{i}',n) for i,n in enumerate((184,3))]
    scans=[scan_group(groups[0]),scan_group(replace(groups[1],image_sort='created'))]
    expected=[p.id for s in scans for p in s.rows]
    for mode in ('separate','merged'):
        outputs=export_projects(scans,tmp_path/mode,mode=mode)
        order=[]
        for output in outputs:
            c=json.loads((output/'draft_content.json').read_text(encoding='utf8'));m=json.loads((output/'transcomic_mapping.json').read_text(encoding='utf8'))['pairs']
            validate_content(c,m);order.extend(r['pair_id'] for r in m)
            assert not list(output.rglob('*.wav')) and not list(output.rglob('*.png'))
        assert order==expected
