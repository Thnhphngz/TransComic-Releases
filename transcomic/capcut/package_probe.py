"""Small isolated packaging probe, using original synthetic media paths."""
import hashlib
import os
from pathlib import Path
import sys
import wave
from PySide6.QtGui import QImage,QColor
from .media import MediaGroup,scan_group
from .exporter import export_projects,load_template,validate_content,reference
from .resources import effects


def run(root):
    import json
    import mutagen
    from mutagen.mp3 import MP3
    import lameenc
    root=Path(root).resolve();media=root/'capcut-fixture';images=media/'images';audio=media/'audio'
    images.mkdir(parents=True);audio.mkdir()
    for n in range(1,9):
        image=QImage(96,64,QImage.Format_RGB32);image.fill(QColor(40+n*10,80,120))
        assert image.save(str(images/f'{n:04}.png'))
        if n<8:
            with wave.open(str(audio/f'{n:04}.wav'),'wb') as stream:
                stream.setparams((1,2,8000,0,'NONE','not compressed'));stream.writeframes(b'\0\0'*(800+n))
        else:
            encoder=lameenc.Encoder();encoder.set_in_sample_rate(22050);encoder.set_channels(1);encoder.set_bit_rate(64)
            data=encoder.encode(b'\0\0'*2205)+encoder.flush();path=audio/f'{n:04}.mp3';path.write_bytes(data)
            assert MP3(path).info.length>0
    sources={p:hashlib.sha256(p.read_bytes()).hexdigest() for folder in (images,audio) for p in folder.iterdir()}
    scan=scan_group(MediaGroup.create('Packaging fixture',images,audio));assert scan.valid
    source_content,_,_=load_template();reference_ids={a['resource_id'] for m in source_content['materials']['material_animations'] for a in m['animations']}
    # Disallow Python reads from any directory outside the fixture/package while
    # exporting. In particular, no original media or effect cache can be opened.
    package=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    allowed=(root,package)
    active=[True];opened=[]
    def audit(event,args):
        if active[0] and event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(reference(os.fsdecode(args[0]))).resolve()
            if not any(path.is_relative_to(base) for base in allowed):raise AssertionError('Export attempted a read outside fixture/package')
            opened.append(path)
    sys.addaudithook(audit)
    try:project=export_projects([scan],root/'capcut-output')[0]
    finally:active[0]=False
    content=json.loads((project/'draft_content.json').read_text(encoding='utf8'))
    mapping=json.loads((project/'transcomic_mapping.json').read_text(encoding='utf8'));validate_content(content,mapping['pairs'])
    assert [p['image'] for p in mapping['pairs']]==[reference(p.images[0].path) for p in scan.rows]
    assert [p['audio'] for p in mapping['pairs']]==[reference(p.audios[0].path) for p in scan.rows]
    assert content['duration']==sum(p.duration_us for p in scan.rows)
    tracks=content['tracks'];assert sum(t['type']=='video' for t in tracks)==2
    assert all(s['common_keyframes'] for t in tracks if t['type']=='video' for s in t['segments'])
    animations=[a for m in content['materials']['material_animations'] for a in m['animations']]
    assert {a['resource_id'] for a in animations}==reference_ids
    packed=effects()
    for a in animations:
        folder=Path(a['path']);assert folder.is_relative_to(Path(reference(project))) and folder.is_dir()
        expected={n.split('/',1)[1]:raw for n,raw in packed.items() if n.startswith(folder.name+'/')}
        assert expected and {p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}==expected
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in sources.items())
    assert not list(project.rglob('*.png')) and not list(project.rglob('*.wav')) and not list(project.rglob('*.mp3'))
    cover=QImage(str(project/'draft_cover.jpg'));assert cover.width()==640 and cover.height()==360
    assert abs(cover.pixelColor(320,180).red()-50)<15
    return dict(passed=True,pairs=8,video_tracks=2,audio_gap_us=0,duration_us=content['duration'],
                source_unchanged=True,input_media_copied=False,cover=True,
                portable_effect_files=len(mapping['animation_resources']),animation_ids_preserved=True,
                outside_package_reads=0,fixture_outside_source=True,mutagen=mutagen.version_string)
