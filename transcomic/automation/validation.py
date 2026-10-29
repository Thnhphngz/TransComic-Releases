"""Read-only filesystem validation and stable positional mapping."""
from dataclasses import asdict
from pathlib import Path
import shutil
import tempfile
from .repository import file_hash,fingerprint
from ..tts.documents import segments
from ..capcut.media import IMAGES,natural_key,probe


def speakable(text):return bool(segments(text,'none'))


def read_source(path):
    from ..documents import import_txt,ImportedText,TextLine
    from ..docx_document import import_docx
    path=Path(path)
    if path.suffix.lower()=='.docx':
        obj=import_docx(path)
        return ImportedText(tuple(TextLine(u.text,'') for u in obj.units),'docx',obj.raw),[u.locator for u in obj.units]
    return import_txt(path),None


def image_manifest(folder,mode,*,cancelled=None):
    root=Path(folder)
    if not folder or not root.is_dir():raise ValueError('Chưa chọn thư mục ảnh hợp lệ.')
    paths=sorted((p for p in root.iterdir() if p.is_file() and p.suffix.lower() in IMAGES),key=lambda p:natural_key(p.name))
    values=[]
    for path in paths:
        check_current(cancelled)
        media=probe(path,True)
        if media.error:raise ValueError(path.name+': '+media.error)
        row=asdict(media);row['sha256']=file_hash(path);values.append(row)
    if mode=='created':
        if any(v['created_ns'] is None for v in values):raise ValueError('Không có Date created đáng tin cậy; chọn theo tên.')
        values.sort(key=lambda v:(v['created_ns'],natural_key(Path(v['path']).name)))
    elif mode!='name':raise ValueError('Cách sắp ảnh không hợp lệ.')
    return values


def plan_parts(groups,config):
    from ..capcut.planning import ProjectPart,project_plan,name_errors
    if not groups:return ()
    mode=config['capcut_mode'];name=config['project_name'];custom=config.get('part_names',{})
    if mode=='split':return project_plan(groups,mode,name,config['part_count'],custom)
    if mode=='merged':parts=(ProjectPart(custom.get('1',name),1,len(groups),tuple(groups)),)
    elif mode=='separate':
        from ..capcut.exporter import safe_name
        used=set();reserved={v.casefold() for k,v in custom.items() if k in {g['id'] for g in groups}};values=[]
        for i,g in enumerate(groups,1):
            base=safe_name(Path(g['path']).stem);name=custom.get(g['id'],base);n=2
            if g['id'] not in custom:
                while name.casefold() in used|reserved:name=base+f'_v{n}';n+=1
            used.add(name.casefold());values.append(ProjectPart(name,i,i,(g,)))
        parts=tuple(values)
    else:raise ValueError('Chế độ CapCut không hợp lệ.')
    errors=name_errors(parts)
    if errors:raise ValueError(' · '.join(errors.values()))
    return parts


def defaults(store):
    import json
    try:tts=json.loads(store.setting('tts_config','{}'))
    except ValueError:tts={}
    try:cap=json.loads(store.setting('capcut_workspace_v1','{}'))
    except ValueError:cap={}
    cfg=dict(source_lang='vi',target_lang='en',provider='kira',model=store.setting('model',''),workers=30,
             deepseek_batch_size=3,kira_recovery_version=4,
             voice='af_jessica',speed=tts.get('speed',1.0),variant=tts.get('variant','standard'),tts_language='en-us',
             device=tts.get('device','Auto'),format='wav',capcut_mode='separate',part_count=2,project_name='TransComic',part_names={},output=cap.get('output',''))
    try:cfg.update(json.loads(store.setting('automation_last_config','{}')))
    except ValueError:pass
    cfg.update(kira_recovery_version=4,kira_completion_policy=1,kira_dispatch_policy=1,translation_completion_policy=1)
    history=getattr(getattr(store,'automation',None),'tts_store',None)
    if history:
        for run in history.history_runs():
            try:
                saved=json.loads(run['config']);speed=float(saved['speed'])
                if .5<=speed<=2:cfg['speed']=speed;break
            except (ValueError,TypeError,KeyError):continue
    from ..tts.catalog import voice_names
    cfg['voice']='af_jessica' if 'af_jessica' in voice_names(cfg.get('tts_language','en-us')) else ''
    return cfg


DEPENDENCIES={
    'translation':('source_lang','target_lang','provider','model','workers','deepseek_batch_size'),
    'kokoro':('target_lang','tts_language','voice','speed','variant','device','format'),
    'capcut':('capcut_mode','part_count','project_name','part_names','output'),
}


def prepared_identity(groups):
    return fingerprint([(g['id'],g['document_id'],{k:g['data'].get(k) for k in ('source_sha256','image_folder','image_sort','images','slots')}) for g in groups])


def config_identity(config,section,services=None):
    environment=services.validation_identity(section,config) if services and hasattr(services,'validation_identity') else None
    return fingerprint(dict(config={k:config[k] for k in DEPENDENCIES[section]},environment=environment))


def file_stamp(path):
    s=Path(path).stat();return (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino)


def input_stamp(group,path,rows):
    """Cheap change detection for UI config edits; dispatch still does full hashes."""
    meta=group['data'];folder=Path(meta['image_folder'])
    if not meta['image_folder'] or not folder.is_dir():raise ValueError('Chưa chọn thư mục ảnh hợp lệ.')
    images=sorted((str(p.resolve()),file_stamp(p)) for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGES)
    return fingerprint(dict(source=(str(path),file_stamp(path)),images=images,sort=meta['image_sort'],folder=str(folder.resolve()),
                            lines=[(r['id'],r['source_revision']) for r in rows],sha=meta['source_sha256']))


def project_name_error(config):
    from ..capcut.planning import ProjectPart,name_errors
    return name_errors((ProjectPart(config.get('project_name',''),1,1,()),)).get(1,'')


def check_config(section,config):
    from ..languages import validate_pair,language
    from ..tts.catalog import voice_names,LANGUAGES
    if section=='translation':
        if config.get('kira_recovery_version',2) not in (2,3,4):raise ValueError('Phiên bản recovery không hợp lệ.')
        validate_pair(config['source_lang'],config['target_lang'])
        if type(config['workers']) is not int or not 1<=config['workers']<=30:raise ValueError('Số worker phải từ 1–30.')
        if config['provider'] not in ('kira','gemini','deepseek') or not isinstance(config['model'],str) or not config['model'].strip():raise ValueError('Chọn provider/model hợp lệ.')
        if config['provider']=='deepseek':
            from ..deepseek_models import validate_model
            validate_model(config['model'])
            from ..deepseek_batch import job_size
            job_size('deepseek',config)
    elif section=='kokoro':
        _,target=validate_pair(config['source_lang'],config['target_lang'])
        tts_lang=config['tts_language']
        compatible={'en':('en-us','en-gb'),'en-CA':('en-us','en-gb'),'fr-CA':('fr-fr',),'hi':('hi',),'ja':('ja',),'zh-CN':('cmn',)}
        if tts_lang not in compatible.get(target.locale,()):raise ValueError('Kokoro không hỗ trợ ngôn ngữ đích/voice này.')
        if tts_lang not in LANGUAGES or config['voice'] not in voice_names(tts_lang):raise ValueError('Chọn voice Kokoro hợp lệ; không tự đổi Jessica.')
        if not .5<=float(config['speed'])<=2 or config['variant'] not in ('standard','light'):raise ValueError('Cấu hình Kokoro không hợp lệ.')
        if config['format']!='wav':raise ValueError('Automation yêu cầu WAV để giữ mapping/duration.')
    else:
        if error:=project_name_error(config):raise ValueError(error)
        output=Path(config['output'])
        if not config['output'] or not output.is_dir():raise ValueError('Chọn thư mục xuất CapCut hiện có.')
        if shutil.disk_usage(output).free<32*1024*1024:raise ValueError('Không đủ dung lượng thư mục CapCut.')
        # A unique temporary probe verifies Windows/ACL write access, never an existing output.
        with tempfile.TemporaryFile(dir=output,prefix='.transcomic-preflight-') as probe_file:probe_file.write(b'1');probe_file.flush()


class ValidationSuperseded(Exception):
    """An obsolete UI validation must not publish a checkpoint."""


def check_current(cancelled):
    if cancelled and cancelled():raise ValidationSuperseded()


def validate(repo,id,services=None,*,refresh=True,reuse_inputs=False,force_config=False,cancelled=None,groups=None,prepared=False,inputs_only=False):
    check_current(cancelled)
    work=repo.workset(id);config=work['config'];errors=[];result=[];sections={};checked=[]
    cached=work['checkpoint'].get('validation_sections',{}) if reuse_inputs and not force_config else {}
    for section in (() if inputs_only else DEPENDENCIES):
        check_current(cancelled)
        identity=config_identity(config,section,services);old=cached.get(section,{})
        if old.get('identity')==identity and not old.get('errors'):record=old
        else:
            faults=[];checked.append(section)
            try:
                check_config(section,config)
                if services:
                    if hasattr(services,'preflight_section'):services.preflight_section(section,config)
                    else:services.preflight(config)
            except (ValueError,OSError,KeyError,TypeError) as exc:faults.append(str(exc))
            record=dict(identity=identity,errors=faults)
        sections[section]=record;errors.extend(record['errors'])
    seen=set()
    groups=repo.groups(id) if groups is None else groups
    doc_ids=[g['document_id'] for g in groups]
    documents={r['id']:r for r in repo.rows('SELECT id,path FROM documents WHERE id IN ('+','.join('?'*len(doc_ids))+')',doc_ids)} if doc_ids else {}
    for group in groups:
        check_current(cancelled)
        faults=[];doc=documents[group['document_id']];path=Path(doc['path']);meta=group['data'];images=[]
        if prepared:
            images=meta.get('images',[]);slots=meta.get('slots',[]);faults=list(meta.get('validation',[]))
            result.append(dict(group,path=str(path),name=path.name,line_count=len(slots),image_count=len(images),valid=not faults,errors=faults,input_cached=True))
            continue
        rows=repo.store.lines(doc['id']);slots=[r for r in rows if speakable(r['source'])]
        stamp=None;used_cache=False
        try:
            if group['source_key'] in seen:raise ValueError('Nguồn bị trùng.')
            seen.add(group['source_key'])
            stamp=input_stamp(group,path,rows);cache=meta.get('input_validation',{})
            used_cache=bool(reuse_inputs and cache.get('version')==1 and cache.get('stamp')==stamp and meta.get('images') and meta.get('slots')==[r['id'] for r in slots])
            if used_cache:images=meta['images']
            else:
                read_source(path)
                if file_hash(path)!=meta['source_sha256']:raise ValueError('Nguồn đã thay đổi; cần đối chiếu từng dòng trước khi tiếp tục.')
                inspected=meta.get('image_inspection',{})
                if reuse_inputs and inspected.get('version')==1 and inspected.get('stamp')==stamp and meta.get('images'):images=meta['images']
                else:images=image_manifest(meta['image_folder'],meta['image_sort'])
            if len(images)!=len(slots) or not slots:raise ValueError(f'{len(slots)} dòng cần voice / {len(images)} ảnh — lệch {len(slots)-len(images)}')
            previous=meta.get('images',[])
            if previous and len(previous)==len(images):
                from ..capcut.media import numeric_id
                old_paths=[v['path'] for v in previous];new_paths=[v['path'] for v in images]
                if old_paths!=new_paths and not all(numeric_id(Path(a).name) is not None and numeric_id(Path(a).name)==numeric_id(Path(b).name) for a,b in zip(old_paths,new_paths)):
                    raise ValueError('Thứ tự/định danh ảnh thay đổi; chọn lại thư mục ảnh và xác nhận cách sắp xếp để giữ mapping chính xác.')
            if shutil.disk_usage(path.parent).free<max(16*1024*1024,len(slots)*2*1024*1024):raise ValueError('Không đủ dung lượng cho WAV ước lượng.')
            if not used_cache and input_stamp(group,path,rows)!=stamp:raise ValueError('Đầu vào thay đổi trong khi kiểm tra; kiểm tra lại trước khi bắt đầu.')
        except (OSError,ValueError,UnicodeError) as exc:faults.append(str(exc))
        row=dict(group,path=str(path),name=path.name,line_count=len(slots),image_count=len(images),valid=not faults,errors=faults,input_cached=used_cache)
        result.append(row)
        if refresh:
            updates=dict(image_count=len(images),validation=faults,error=' · '.join(faults))
            if not used_cache:updates.update(images=images if not faults else meta.get('images',[]),slots=[r['id'] for r in slots])
            updates['input_validation']=dict(version=1,stamp=stamp) if not faults else {}
            with repo.store.transaction():
                check_current(cancelled)
                repo.update_group(group['id'],**updates)
    check_current(cancelled)
    if not result:errors.append('Thêm ít nhất một tài liệu.')
    try:parts=() if inputs_only else plan_parts(result,config)
    except ValueError as exc:parts=();errors.append(str(exc))
    proof=dict(passed=not errors and all(g['valid'] for g in result),errors=errors,groups=result,
               parts=[dict(name=p.name,group_ids=[g['id'] for g in p.groups],start=p.start,end=p.end) for p in parts],config_fingerprint=fingerprint(config),sections=sections,checked_sections=checked)
    return proof
