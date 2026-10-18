import json
import wave
from pathlib import Path
import pytest
from PySide6.QtGui import QImage,QColor
from transcomic.capcut.media import MediaGroup,scan_group,freeze,numeric_id,Cancelled,native_path
from transcomic.capcut.state import GroupManager
from transcomic.storage import Store


def media_group(root,count=3,name='Nhóm tiếng Việt'):
    images=root/'ảnh gốc';audio=root/'audio gốc';images.mkdir(parents=True);audio.mkdir()
    for n in range(1,count+1):
        image=QImage(80+n%4,60,QImage.Format_RGB32);image.fill(QColor('#4b7699'));assert image.save(str(images/f'{n:03}.png'))
        with wave.open(str(audio/f'{n:03}.wav'),'wb') as w:
            w.setparams((1,2,8000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*(800+n))
    return MediaGroup.create(name,images,audio)


@pytest.mark.parametrize('images,audios',[(100,100),(100,99),(99,100)])
def test_strict_100_files(tmp_path,images,audios):
    group=media_group(tmp_path,100)
    if images<100:(Path(group.image_dir)/'050.png').unlink()
    if audios<100:(Path(group.audio_dir)/'050.wav').unlink()
    scan=scan_group(group)
    assert scan.valid==(images==audios==100)
    assert scan.image_count==images and scan.audio_count==audios
    if not scan.valid:
        row=next(r for r in scan.rows if r.number==50);assert row.errors
        with pytest.raises(ValueError):freeze([scan])


def test_positional_mismatch_does_not_claim_valid_pairs(tmp_path):
    group=media_group(tmp_path,4)
    (Path(group.image_dir)/'003.png').unlink();(Path(group.audio_dir)/'004.wav').unlink()
    scan=scan_group(group)
    assert scan.valid and scan.matched==3  # Equal counts are structural only, never semantic proof.
    (Path(group.image_dir)/'001.png').rename(Path(group.image_dir)/'photo 001.png')
    image=QImage(10,10,QImage.Format_RGB32);image.fill(QColor('red'));image.save(str(Path(group.image_dir)/'1.png'))
    (Path(group.audio_dir)/'no-id.wav').write_bytes(b'invalid')
    scan=scan_group(group)
    assert not scan.valid and scan.matched==3
    assert scan.rows[-1].errors  # Corrupt audio is still reported, not dropped.
    assert numeric_id('chapter 1-2.mp3') is None


def test_natural_sort_and_file_errors(tmp_path):
    group=media_group(tmp_path,11);scan=scan_group(group)
    assert [r.number for r in scan.rows]==list(range(1,12))
    (Path(group.image_dir)/'005.png').write_bytes(b'bad image')
    (Path(group.audio_dir)/'006.wav').write_bytes(b'broken wave')
    (Path(group.image_dir)/'007.png').write_bytes(b'')
    assert scan_group(group).error_count==3
    assert not scan.rows[4].images[0].unchanged()


def test_removed_empty_directory_and_cancellation(tmp_path):
    group=MediaGroup.create('empty',tmp_path/'missing',tmp_path/'missing2')
    assert scan_group(group).error_count==2
    import threading
    cancel=threading.Event();cancel.set()
    with pytest.raises(Cancelled):scan_group(group,cancel)
    group=media_group(tmp_path/'valid',0);assert not scan_group(group).valid


def test_missing_same_position_both_sides_is_structural_only(tmp_path):
    group=media_group(tmp_path,4)
    for folder,ext in ((group.image_dir,'png'),(group.audio_dir,'wav')):(Path(folder)/f'003.{ext}').unlink()
    scan=scan_group(group);assert scan.valid and scan.matched==3


def test_persistence_order_duplicate_names_and_restart(tmp_path):
    store=Store(tmp_path/'state.db')
    groups=[media_group(tmp_path/f'group {i}',1,'Tên trùng') for i in range(10)]
    m=GroupManager(store)
    for group in groups:m.add(group)
    m.move(groups[-1].id,-1);m.remove(groups[0].id);m.add(groups[0]);expected=[g.id for g in m.groups]
    store.close();store=Store(tmp_path/'state.db')
    try:assert [g.id for g in GroupManager(store).groups]==expected
    finally:store.close()


def test_source_file_fingerprint_and_long_path(tmp_path):
    root=tmp_path
    while len(str(root))<280:root=root/'long directory'
    group=media_group(native_path(root),1);scan=scan_group(group);assert scan.valid
    assert scan.rows[0].images[0].unchanged()


def test_mp3_real_metadata_and_no_conversion(tmp_path):
    lameenc=pytest.importorskip('lameenc')
    from transcomic.capcut.media import audio_duration
    group=media_group(tmp_path,1);source=Path(group.audio_dir)/'001.wav';source.unlink()
    encoder=lameenc.Encoder();encoder.set_bit_rate(128);encoder.set_in_sample_rate(44100);encoder.set_channels(1);encoder.set_quality(2)
    path=source.with_suffix('.mp3');path.write_bytes(encoder.encode(b'\0\0'*44100)+encoder.flush())
    duration=audio_duration(path);assert 900000<duration<1200000
    assert scan_group(group).rows[0].duration_us==duration
