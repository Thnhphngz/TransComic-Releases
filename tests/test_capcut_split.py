from dataclasses import replace
from pathlib import Path
import hashlib,json,threading
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QColor
from transcomic.capcut.planning import partition_groups,project_plan
from transcomic.capcut.media import scan_group,Cancelled,MediaGroup
from transcomic.capcut.exporter import export_projects,validate_content
from test_capcut_media import media_group


CASES=[(10,2,[5,5]),(10,3,[4,3,3]),(10,4,[3,3,2,2]),(20,3,[7,7,6]),(100,4,[25]*4),(103,4,[26,26,26,25]),(200,3,[67,67,66]),(200,4,[50]*4),(200,5,[40]*5),(10,10,[1]*10)]


@pytest.mark.parametrize('total,count,sizes',CASES)
def test_consecutive_balanced_partition(total,count,sizes):
    groups=tuple(MediaGroup(str(i),f'Group {i}','images','voice') for i in range(total))
    parts=project_plan(groups,'split','1 - 20 vote',count)
    assert [len(p.groups) for p in parts]==sizes
    assert tuple(g for p in parts for g in p.groups)==groups
    assert [p.name for p in parts]==[f'1 - 20 vote_part{i}' for i in range(1,count+1)]
    assert parts[0].start==1 and parts[-1].end==total
    assert all(a.end+1==b.start for a,b in zip(parts,parts[1:]))
    assert len({g.id for p in parts for g in p.groups})==total


@pytest.mark.parametrize('count',[0,-1,1,11,2.5,True,'3'])
def test_reject_invalid_partition(count):
    with pytest.raises(ValueError):partition_groups(range(10),count)


def test_long_safe_names_preserve_distinct_suffixes():
    parts=project_plan(range(10),'split','x'*100+':invalid',4)
    assert len({p.name for p in parts})==4 and all(len(p.name)<=80 for p in parts)
    assert [p.name[-6:] for p in parts]==[f'_part{i}' for i in range(1,5)]


@pytest.mark.parametrize('total,count,sizes',CASES)
def test_real_multi_part_exports_order_cover_sources_and_timeline(tmp_path,total,count,sizes):
    groups=[]
    for i in range(total):
        group=media_group(tmp_path/f'g{i}',5 if i==0 else 1,f'Group {i}')
        image=QImage(80,60,QImage.Format_RGB32);image.fill(QColor.fromHsv(i*37%360,200,210));image.save(str(Path(group.image_dir)/'001.png'))
        groups.append(group)
    groups=tuple(reversed(groups));scans=tuple(scan_group(g) for g in groups)
    before={p:hashlib.sha256(p.read_bytes()).hexdigest() for g in groups for folder in (g.image_dir,g.audio_dir) for p in Path(folder).iterdir()}
    progress=[];outputs=export_projects(scans,tmp_path/'out',mode='split',name='1 - 20 vote',part_count=count,progress=lambda n,msg:progress.append(n))
    assert len(outputs)==count and progress[-1]==100 and progress==sorted(progress)
    observed=[];expected=partition_groups(scans,count)
    for i,(output,part) in enumerate(zip(outputs,expected),1):
        assert output.name==f'1 - 20 vote_part{i}'
        content=json.loads((output/'draft_content.json').read_text(encoding='utf8'))
        rows=json.loads((output/'transcomic_mapping.json').read_text(encoding='utf8'))['pairs'];validate_content(content,rows)
        observed.extend(r['pair_id'] for r in rows)
        assert [r['pair_id'] for r in rows]==[p.id for scan in part for p in scan.rows]
        assert rows[0]['start_us']==0 and content['duration']==sum(p.duration_us for s in part for p in s.rows)
        assert len({r['group_id'] for r in rows})==sizes[i-1]
        meta=json.loads((output/'draft_meta_info.json').read_text(encoding='utf8'));assert meta['draft_cover']=='draft_cover.jpg'
        root=output/'draft_cover.jpg';timeline=output/'Timelines'/content['id']/'draft_cover.jpg'
        assert root.read_bytes()==timeline.read_bytes() and root.read_bytes()[:2]==b'\xff\xd8'
        cover=QImage(str(root));original=QImage(part[0].rows[0].images[0].path)
        assert (cover.width(),cover.height())==(640,360)
        actual=cover.pixelColor(320,180);color=original.pixelColor(40,30)
        assert max(abs(a-b) for a,b in zip(actual.getRgb()[:3],color.getRgb()[:3]))<=5
        assert not list(output.rglob('*.wav')) and not list(output.rglob('*.mp3')) and not list(output.rglob('*.png'))
    assert observed==[p.id for s in scans for p in s.rows] and len(set(observed))==len(observed)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in before.items())


def test_collision_cancel_and_failure_keep_completed_parts(tmp_path,monkeypatch):
    import transcomic.capcut.exporter as module
    scans=[scan_group(media_group(tmp_path/f'g{i}',1)) for i in range(6)]
    out=tmp_path/'out';existing=out/'vote_part1';existing.mkdir(parents=True);(existing/'keep').write_text('keep')
    outputs=export_projects(scans,out,mode='split',name='vote',part_count=3)
    assert outputs[0].name=='vote_part1_2' and (existing/'keep').read_text()=='keep'
    cancel=threading.Event()
    def progress(n,msg):
        if 'Ghi cấu trúc' in msg and 'vote_part2' in msg:cancel.set()
    with pytest.raises(Cancelled,match='1 project'):export_projects(scans,tmp_path/'cancel',mode='split',name='vote',part_count=3,cancel=cancel,progress=progress)
    assert sorted(p.name for p in (tmp_path/'cancel').iterdir())==['vote_part1']
    original=module.write_project
    def fail(groups,output,name,*args,**kwargs):
        if name.endswith('_part2'):raise OSError('simulated disk failure')
        return original(groups,output,name,*args,**kwargs)
    monkeypatch.setattr(module,'write_project',fail)
    with pytest.raises(ValueError,match='giữ nguyên 1 project'):export_projects(scans,tmp_path/'fail',mode='split',name='vote',part_count=3)
    assert sorted(p.name for p in (tmp_path/'fail').iterdir())==['vote_part1']


def test_all_sources_validated_before_part_one_and_failed_cover_is_atomic(tmp_path,monkeypatch):
    import transcomic.capcut.cover as cover
    scans=[scan_group(media_group(tmp_path/f'g{i}',1)) for i in range(4)]
    path=Path(scans[-1].rows[0].audios[0].path);data=path.read_bytes();path.write_bytes(b'changed')
    with pytest.raises(ValueError):export_projects(scans,tmp_path/'invalid',mode='split',part_count=2)
    assert not (tmp_path/'invalid').exists();path.write_bytes(data)
    scans=[scan_group(s.group) for s in scans]
    def fail(*args):raise OSError('cover write failed')
    monkeypatch.setattr(cover,'write_cover',fail)
    with pytest.raises(ValueError,match='cover write failed'):export_projects(scans,tmp_path/'bad-cover',mode='split',part_count=2)
    assert not list((tmp_path/'bad-cover').iterdir())
