"""MAU only. Integer timeline mapping, direct original paths, atomic projects.

Adapted from the user's MAU reference, without its Legacy/copy/headroom
branches. The bundled structure is extracted from the supplied real RAR.
"""
from bisect import bisect_right
from copy import deepcopy
import hashlib
from importlib.resources import files
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import time
import uuid
import zipfile

from .media import freeze,checkpoint,native_path,Cancelled


def uid():return str(uuid.uuid4()).upper()


def reference(path):
    text=str(Path(path).absolute()).replace('\\','/')
    if text.startswith('//?/UNC/'):return '//'+text[8:]
    return text[4:] if text.startswith('//?/') else text


def load_template():
    package=files('transcomic.capcut')
    raw=package.joinpath('mau-structure.zip').read_bytes()
    origin=json.loads(package.joinpath('mau-origin.json').read_text(encoding='utf8'))
    if hashlib.sha256(raw).hexdigest()!=origin['structure_sha256']:raise ValueError('Template MAU không khớp bản đã kiểm chứng')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        structure={p:z.read(p) for p in z.namelist()}
    content=json.loads(structure['draft_content.json']);meta=json.loads(structure['draft_meta_info.json'])
    video=[t for t in content['tracks'] if t['type']=='video'];audio=[t for t in content['tracks'] if t['type']=='audio']
    if len(video)!=2 or len(audio)!=1 or any(not t['segments'] for t in video+audio):raise ValueError('Cấu trúc MAU không được hỗ trợ')
    if any(not s.get('common_keyframes') for t in video for s in t['segments']):raise ValueError('Template MAU thiếu keyframe')
    return content,meta,structure


def remap(value,ids):
    if isinstance(value,dict):return {ids.get(k,k):remap(v,ids) for k,v in value.items()}
    if isinstance(value,list):return [remap(v,ids) for v in value]
    return ids.get(value,value) if isinstance(value,str) else value


def clone_segment(segment,material,lookup,new_materials):
    refs=[lookup[r] for r in segment.get('extra_material_refs',[]) if r in lookup]
    if len(refs)!=len(segment.get('extra_material_refs',[])):raise ValueError('Template tham chiếu material thiếu')
    original=[segment,material]+[m for _,m in refs]
    ids={}
    def collect(obj):
        if isinstance(obj,dict):
            val=obj.get('id')
            if isinstance(val,str) and re.fullmatch(r'[0-9a-fA-F-]{36}',val):ids.setdefault(val,uid())
            for v in obj.values():collect(v)
        elif isinstance(obj,list):
            for v in obj:collect(v)
    collect(original)
    seg,mat,*copies=remap(deepcopy(original),ids)
    for (kind,_),copy in zip(refs,copies):new_materials[kind].append(copy)
    return seg,mat,copies


def build_content(pairs,name,cancel=None):
    content,meta,structure=load_template()
    original_id=content['id'];timeline_id=uid();project_id=uid()
    id_map={original_id:timeline_id,meta['draft_id']:project_id}
    video=[t for t in content['tracks'] if t['type']=='video'];audio=[t for t in content['tracks'] if t['type']=='audio']
    materials=content['materials'];lookup={m['id']:(kind,m) for kind,values in materials.items() for m in values if isinstance(m,dict) and 'id' in m}
    patterns=[]
    for track_index,track in enumerate(video):
        for segment in track['segments']:
            patterns.append((segment['target_timerange']['start'],track_index,segment))
    patterns.sort(key=lambda p:(p[0],p[1]))
    starts=sorted({p[0] for p in patterns});points=starts+[content['duration']]
    if len(starts)!=len(patterns) or starts[0]!=0:raise ValueError('Các slot MAU không đúng template đã kiểm chứng')
    slot_starts=[];total=0
    for pair in pairs:slot_starts.append(total);total+=pair.duration_us
    slot_ends=slot_starts[1:]+[total]
    def map_time(value,pattern_index,output_index):
        if value>=points[-1]:point=len(starts)
        else:point=max(0,bisect_right(points,value)-1)
        output=output_index+point-pattern_index
        if output<0:return 0
        if output>=len(pairs):return total
        if point>=len(starts):return slot_starts[output]
        delta=value-points[point];length=points[point+1]-points[point]
        return slot_starts[output]+(delta*(slot_ends[output]-slot_starts[output])+length//2)//length
    new_materials={k:[] for k in materials};new_video=[[],[]];new_audio=[];manifest=[]
    for i,pair in enumerate(pairs):
        checkpoint(cancel)
        number=i%len(patterns);old_start,track_index,pattern=patterns[number]
        old_duration=pattern['target_timerange']['duration']
        segment,material,extras=clone_segment(pattern,lookup[pattern['material_id']][1],lookup,new_materials)
        image=pair.images[0];sound=pair.audios[0]
        start=map_time(old_start,number,i);end=map_time(old_start+old_duration,number,i);duration=end-start
        if duration<=0:raise ValueError('Slot MAU có thời lượng không hợp lệ')
        material.update(path=reference(image.path),material_name=Path(image.path).name,width=image.width,height=image.height,unique_id=uuid.uuid4().hex)
        material['duration']=max(material.get('duration',0),duration)
        segment.update(target_timerange=dict(start=start,duration=duration),source_timerange=dict(start=0,duration=duration))
        for prop in segment.get('common_keyframes',[]):
            for point in prop.get('keyframe_list',[]):
                point['time_offset']=max(0,min(duration,map_time(old_start+point['time_offset'],number,i)-start))
        # Keep MAU's animation/resource IDs and value curves; scale only time.
        for extra in extras:
            for animation in extra.get('animations',[]):
                animation['start']=min(duration,round(animation.get('start',0)*duration/old_duration))
                animation['duration']=min(duration-animation['start'],max(1,round(animation.get('duration',0)*duration/old_duration)))
        new_materials['videos'].append(material);new_video[track_index].append(segment)
        audio_pattern=audio[0]['segments'][0]
        aseg,amat,_=clone_segment(audio_pattern,lookup[audio_pattern['material_id']][1],lookup,new_materials)
        amat.update(path=reference(sound.path),name=Path(sound.path).name,material_name=Path(sound.path).name,duration=pair.duration_us)
        aseg.update(source_timerange=dict(start=0,duration=pair.duration_us),target_timerange=dict(start=slot_starts[i],duration=pair.duration_us))
        new_materials['audios'].append(amat);new_audio.append(aseg)
        manifest.append(dict(pair_id=pair.id,group_id=pair.group_id,order=i+1,image=reference(image.path),audio=reference(sound.path),
            start_us=slot_starts[i],duration_us=pair.duration_us,video_segment=segment['id'],audio_segment=aseg['id'],video_track=track_index))
    for track,segments in zip(video,new_video):track['segments']=segments;track['id']=uid()
    audio[0]['segments']=new_audio;audio[0]['id']=uid()
    content.update(materials=new_materials,duration=total,name=name,id=timeline_id,path='',create_time=int(time.time()*1e6),update_time=int(time.time()*1e6))
    content=remap(content,id_map)
    return content,meta,structure,id_map,manifest


def validate_content(content,manifest):
    """Export gate: exact audio order, no gap/trim, unique local IDs/references."""
    tracks=content['tracks'];video=[t for t in tracks if t['type']=='video'];audio=[t for t in tracks if t['type']=='audio']
    if len(video)!=2 or len(audio)!=1 or len(audio[0]['segments'])!=len(manifest):raise ValueError('Sai số track/segment MAU')
    materials={m['id']:m for values in content['materials'].values() for m in values}
    all_ids=[]
    def ids(obj):
        if isinstance(obj,dict):
            val=obj.get('id')
            if isinstance(val,str) and re.fullmatch(r'[0-9a-fA-F-]{36}',val):all_ids.append(val)
            for v in obj.values():ids(v)
        elif isinstance(obj,list):
            for v in obj:ids(v)
    ids(content)
    if len(set(all_ids))!=len(all_ids):raise ValueError('Trùng ID project')
    cursor=0;video_ids={s['id']:s for t in video for s in t['segments']}
    if len(video_ids)!=len(manifest):raise ValueError('Thiếu hoặc dư ảnh trên timeline')
    for segment,row in zip(audio[0]['segments'],manifest):
        if row['start_us']!=cursor or row['duration_us']<=0:raise ValueError('Thứ tự mapping không hợp lệ')
        expected=dict(start=cursor,duration=row['duration_us'])
        if segment['target_timerange']!=expected or segment['source_timerange']!=dict(start=0,duration=row['duration_us']):raise ValueError('Audio gap, overlap hoặc cắt nguồn')
        mat=materials[segment['material_id']]
        if mat['path']!=row['audio'] or mat['duration']!=row['duration_us']:raise ValueError('Sai audio material')
        v=video_ids[row['video_segment']]
        if v['target_timerange']['start']!=cursor or materials[v['material_id']]['path']!=row['image']:raise ValueError('Sai thứ tự ảnh')
        cursor+=row['duration_us']
    if cursor!=content['duration']:raise ValueError('Sai tổng duration')
    for track in tracks:
        for segment in track['segments']:
            if segment['material_id'] not in materials or any(r not in materials for r in segment.get('extra_material_refs',[])):raise ValueError('Tham chiếu material không tồn tại')
            tr=segment['target_timerange']
            if tr['start']<0 or tr['duration']<=0 or tr['start']+tr['duration']>cursor:raise ValueError('Segment vượt timeline')
            for prop in segment.get('common_keyframes',[]):
                if any(not 0<=k['time_offset']<=tr['duration'] for k in prop.get('keyframe_list',[])):raise ValueError('Keyframe vượt segment')


def safe_name(name):
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name).strip(' .')[:80] or 'TransComic'
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',name,re.I):name='Project_'+name
    return name


def assert_sources(pairs,cancel=None):
    for pair in pairs:
        checkpoint(cancel)
        for media in pair.images+pair.audios:
            if not media.unchanged():raise ValueError('Media đã thay đổi hoặc bị xóa: '+media.path)


def write_project(scans,output,name,cancel=None,progress=None,*,ownership=None,strict_target=False):
    pairs=freeze(scans);assert_sources(pairs,cancel)
    output=native_path(output,force=True).resolve()
    for scan in scans:
        for source in (scan.group.image_dir,scan.group.audio_dir):
            if output.is_relative_to(native_path(source,force=True).resolve()):raise ValueError('Thư mục đầu ra không được nằm trong thư mục media gốc')
    output.mkdir(parents=True,exist_ok=True)
    name=safe_name(name);target=output/name;counter=2
    if strict_target and target.exists():raise FileExistsError('Project đích đã tồn tại; không thay đổi kế hoạch đã chốt.')
    while target.exists():target=output/f'{name}_{counter}';counter+=1
    content,meta,structure,id_map,manifest=build_content(pairs,target.name,cancel)
    validate_content(content,manifest)
    timeline=content['id'];project=id_map[meta['draft_id']];now=int(time.time()*1e6)
    meta.update(draft_id=project,draft_name=target.name,draft_fold_path=reference(target),draft_root_path=reference(output),tm_duration=content['duration'],
        tm_draft_create=now,tm_draft_modified=now,tm_draft_removed=0,draft_cover='draft_cover.jpg',cloud_draft_cover=False,draft_materials=[],draft_materials_copied_info=[],draft_segment_extra_info=[],
        draft_timeline_materials_size_=sum(f.size for p in pairs for f in p.images+p.audios))
    items=[]
    for pair in pairs:
        for f,kind in ((pair.images[0],'photo'),(pair.audios[0],'music')):
            items.append(dict(id=uid(),create_time=now//1_000_000,duration=pair.duration_us,extra_info=Path(f.path).name,file_Path=reference(f.path),
                height=f.height,width=f.width,import_time=now//1_000_000,import_time_ms=now,item_source=1,md5='',metetype=kind,type=0,
                roughcut_time_range=dict(duration=-1,start=-1),sub_time_range=dict(duration=-1,start=-1)))
    meta['draft_materials']=[dict(type=0,value=items)]
    stage=output/('.transcomic-capcut-'+uuid.uuid4().hex);stage.mkdir()
    try:
        from .resources import materialize
        effect_files=materialize(stage,target,content,cancel)
        def write(relative,data):
            checkpoint(cancel);relative=PurePosixPath(relative)
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Đường dẫn cấu trúc không an toàn')
            path=stage.joinpath(*relative.parts);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(data)
        for index,(relative,data) in enumerate(structure.items()):
            checkpoint(cancel)
            for old,new in id_map.items():relative=relative.replace(old,new)
            if relative=='draft_meta_info.json':obj=meta
            elif Path(relative).name=='draft_content.json':obj=content
            elif relative=='draft_virtual_store.json':obj={'draft_materials':[],'draft_virtual_store':[{'type':0,'value':[{'creation_time':0,'display_name':'','filter_type':0,'id':'','import_time':0,'import_time_us':0,'sort_sub_type':1,'sort_type':2}]},{'type':1,'value':[{'child_id':m['id'],'parent_id':''} for m in items]}]}
            elif relative=='key_value.json':obj={}
            elif relative.endswith('attachment_id_mapping.json'):
                obj={'id_mapping':{'mapping':[{'short_id':str(1000+i),'uuid':s['id']} for i,s in enumerate(s for t in content['tracks'] for s in t['segments'])],'next_index':1000+sum(len(t['segments']) for t in content['tracks']),'version':'1.0.0'}}
            elif relative=='draft_settings':
                write(relative,f'[General]\ndraft_create_time={now//1000000}\ndraft_last_edit_time={now//1000000}\nreal_edit_seconds=0\nreal_edit_keys=0\ncloud_last_modify_platform=windows\n'.encode());continue
            else:
                try:obj=remap(json.loads(data),id_map)
                except ValueError:
                    if not data:write(relative,data);continue
                    raise ValueError('Metadata MAU không đọc được: '+relative)
            write(relative,json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode('utf8'))
            if progress:progress(10+int(index*75/len(structure)),'Ghi cấu trúc MAU: '+target.name)
        # All content variants point to this same generated timeline, never old media.
        for base in ('',f'Timelines/{timeline}/'):
            for filename in ('template.tmp','template-2.tmp'):
                write(base+filename,json.dumps(content,ensure_ascii=False,separators=(',',':')).encode('utf8'))
        write('transcomic_mapping.json',json.dumps({'template':'MAU','audio_gap_sec':0.0,'pairs':manifest,'animation_resources':effect_files},ensure_ascii=False,indent=2).encode('utf8'))
        if ownership is not None:
            write('transcomic-automation.json',json.dumps(ownership,ensure_ascii=False,sort_keys=True).encode('utf8'))
        from .cover import write_cover
        write_cover(stage,timeline,pairs[0].images[0].path,cancel)
        validate_content(json.loads((stage/'draft_content.json').read_text(encoding='utf8')),manifest)
        assert_sources(pairs,cancel);checkpoint(cancel)
        # On Windows directory rename fails if the destination already exists.
        # Never replace/rmtree an existing project, including a racing creator.
        if target.exists():raise FileExistsError('Project đích vừa được tạo; hãy xuất lại')
        stage.rename(target)
        return target
    finally:
        # Only our unique, direct child staging directory may be removed.
        resolved=stage.resolve()
        if stage.exists() and resolved==stage and resolved.parent==output and resolved.name.startswith('.transcomic-capcut-') and not stage.is_symlink() and not getattr(stage,'is_junction',lambda:False)():shutil.rmtree(stage)


def export_projects(scans,output,*,mode='separate',name='TransComic',part_count=2,custom_names=None,cancel=None,progress=None):
    scans=tuple(scans);pairs=freeze(scans);assert_sources(pairs,cancel)
    if mode not in ('separate','merged','split'):raise ValueError('Chế độ xuất không hợp lệ')
    if mode=='split':
        from .planning import project_plan
        targets=[(p.groups,p.name) for p in project_plan(scans,mode,name,part_count,dict(custom_names or {}))]
    else:targets=[(scans,name)] if mode=='merged' else [((s,),s.group.name) for s in scans]
    completed=[]
    for i,(groups,project_name) in enumerate(targets):
        try:
            checkpoint(cancel)
            result=write_project(groups,output,project_name,cancel,
                progress=(lambda n,msg:progress(int((i+n/100)*100/len(targets)),msg)) if progress else None)
        except Cancelled:
            raise Cancelled(f'Đã hủy an toàn; giữ nguyên {len(completed)} project đã hoàn tất') from None
        except Exception as exc:
            if mode=='split':raise ValueError(f'Part {i+1}/{len(targets)} thất bại; giữ nguyên {len(completed)} project đã hoàn tất: {exc}') from exc
            raise
        completed.append(result)
    if progress:progress(100,'Đã xuất '+str(len(completed))+' project')
    return tuple(completed)
