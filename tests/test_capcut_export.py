import hashlib
import json
from pathlib import Path
import threading
import pytest
from transcomic.capcut.media import scan_group,Cancelled
from transcomic.capcut.exporter import export_projects,load_template,validate_content,safe_name
from test_capcut_media import media_group


def read(project):
    content=json.loads((project/'draft_content.json').read_text(encoding='utf8'))
    manifest=json.loads((project/'transcomic_mapping.json').read_text(encoding='utf8'))['pairs']
    validate_content(content,manifest)
    return content,manifest


@pytest.mark.parametrize('mode,count',[('separate',3),('merged',1)])
def test_three_groups_both_modes_direct_paths_and_mau(tmp_path,mode,count):
    groups=[media_group(tmp_path/f'group {i}',i+2,'Tên trùng') for i in range(3)]
    scans=[scan_group(g) for g in groups]
    hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for g in groups for folder in (g.image_dir,g.audio_dir) for p in Path(folder).iterdir()}
    outputs=export_projects(scans,tmp_path/'output',mode=mode,name='Gộp tiếng Việt')
    assert len(outputs)==count
    template,_,_=load_template()
    expected=[p.id for s in scans for p in s.rows]
    observed=[]
    for output in outputs:
        content,manifest=read(output);observed.extend(row['pair_id'] for row in manifest)
        assert content['canvas_config']==template['canvas_config']
        assert len([t for t in content['tracks'] if t['type']=='video'])==2
        assert all(s['common_keyframes'] for t in content['tracks'] if t['type']=='video' for s in t['segments'])
        assert content['materials']['material_animations']
        covers={Path('draft_cover.jpg'),Path('Timelines')/content['id']/'draft_cover.jpg'}
        media={p.relative_to(output) for p in output.rglob('*') if p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.mp3','.wav','.mp4')}
        assert media==covers  # Derived thumbnails only; original media stays external.
        assert not list(output.rglob('local_media'))
        for row in manifest:
            assert Path(row['image']).is_absolute() and Path(row['image']).is_file()
            assert Path(row['audio']).is_absolute() and Path(row['audio']).is_file()
        for variant in [*output.rglob('draft_content.json'),*output.rglob('template.tmp'),*output.rglob('template-2.tmp')]:
            assert json.loads(variant.read_text(encoding='utf8'))==content
        index=json.loads((output/'Timelines/project.json').read_text(encoding='utf8'))
        assert index['main_timeline_id']==content['id']
        meta=json.loads((output/'draft_meta_info.json').read_text(encoding='utf8'))
        assert meta['draft_name']==output.name and meta['tm_duration']==content['duration']
    assert observed==expected
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in hashes.items())


def test_many_slots_cycle_and_group_boundary_order(tmp_path):
    scans=[scan_group(media_group(tmp_path/f'g{i}',n)) for i,n in enumerate((13,12,15))]
    projects=export_projects(scans,tmp_path/'out',mode='merged')
    c,m=read(projects[0]);assert len(m)==40
    assert [r['group_id'] for r in m]==[s.group.id for s in scans for p in s.rows]
    assert len(c['tracks'][0]['segments'])==len(c['tracks'][1]['segments'])==20
    assert all(a['start_us']+a['duration_us']==b['start_us'] for a,b in zip(m,m[1:]))


def test_missing_changed_media_blocks_before_any_project(tmp_path):
    group=media_group(tmp_path/'a',3);scan=scan_group(group)
    (Path(group.audio_dir)/'002.wav').unlink()
    with pytest.raises(ValueError,match='Media'):export_projects([scan],tmp_path/'out')
    assert not (tmp_path/'out').exists()
    with pytest.raises(ValueError):export_projects([scan_group(group)],tmp_path/'out')


def test_cancel_and_naming_no_overwrite(tmp_path):
    scans=[scan_group(media_group(tmp_path/'a',3,'CON'))]
    out=tmp_path/'out';out.mkdir();existing=out/'Project_CON';existing.mkdir();(existing/'keep.txt').write_text('original')
    projects=export_projects(scans,out);assert projects[0].name=='Project_CON_2'
    cancel=threading.Event()
    def progress(n,message):cancel.set()
    with pytest.raises(Cancelled):export_projects(scans,out,cancel=cancel,progress=progress)
    assert not list(out.glob('.transcomic-capcut-*'))
    assert (existing/'keep.txt').read_text()=='original'
    assert safe_name('../..')=='_' and '/' not in safe_name('a/b:c')


def test_validation_rejects_audio_gap_and_wrong_path(tmp_path):
    scan=scan_group(media_group(tmp_path/'a',2));project=export_projects([scan],tmp_path/'out')[0]
    c,m=read(project);c['tracks'][2]['segments'][1]['target_timerange']['start']+=1
    with pytest.raises(ValueError):validate_content(c,m)
    c,m=read(project);c['materials']['audios'][0]['path']=m[1]['audio']
    with pytest.raises(ValueError):validate_content(c,m)


def test_384_pairs_long_project_and_every_group_boundary(tmp_path):
    scans=[scan_group(media_group(tmp_path/f'g{i}',n)) for i,n in enumerate((128,121,135))]
    project=export_projects(scans,tmp_path/'out',mode='merged')[0]
    c,m=read(project);assert len(m)==384
    assert [r['group_id'] for r in m]==[scan.group.id for scan in scans for _ in scan.rows]
    for index in (128,249):
        assert m[index]['start_us']==sum(row['duration_us'] for row in m[:index])
    assert c['duration']==sum(p.duration_us for scan in scans for p in scan.rows)


def test_media_changed_during_write_and_destination_race(tmp_path):
    group=media_group(tmp_path/'a',2,'Project');scans=[scan_group(group)]
    out=tmp_path/'out'
    def mutate(n,message):
        path=Path(group.audio_dir)/'001.wav'
        if path.exists():path.unlink()
    with pytest.raises(ValueError,match='Media'):export_projects(scans,out,progress=mutate)
    assert not list(out.iterdir())
    with pytest.raises(ValueError,match='media gốc'):
        export_projects([scan_group(media_group(tmp_path/'b',1))],Path(tmp_path/'b'/'ảnh gốc'))
    group=media_group(tmp_path/'c',2,'Race');scans=[scan_group(group)]
    def race(n,message):
        target=out/'Race';target.mkdir(exist_ok=True);(target/'keep.txt').write_text('keep')
    with pytest.raises(FileExistsError):export_projects(scans,out,progress=race)
    assert (out/'Race'/'keep.txt').read_text()=='keep' and not list(out.glob('.transcomic-capcut-*'))


def test_template_curves_and_animation_resources_preserved(tmp_path):
    scan=scan_group(media_group(tmp_path/'a',10));project=export_projects([scan],tmp_path/'out')[0]
    c,m=read(project);original,_,_=load_template()
    patterns=sorted((s['target_timerange']['start'],i,s) for i,t in enumerate(original['tracks'][:2]) for s in t['segments'])
    videos={s['id']:s for t in c['tracks'][:2] for s in t['segments']}
    for i,row in enumerate(m):
        before=patterns[i%8][2];after=videos[row['video_segment']]
        assert before['clip']==after['clip']
        assert [p['property_type'] for p in before['common_keyframes']]==[p['property_type'] for p in after['common_keyframes']]
        assert [[k['values'] for k in p['keyframe_list']] for p in before['common_keyframes']]==[[k['values'] for k in p['keyframe_list']] for p in after['common_keyframes']]
    expected={a['resource_id'] for mat in original['materials']['material_animations'] for a in mat['animations']}
    assert {a['resource_id'] for mat in c['materials']['material_animations'] for a in mat['animations']}==expected
