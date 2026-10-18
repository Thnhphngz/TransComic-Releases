"""Normalize known MAU fields and preserve its referenced effect files exactly."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import zipfile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def archive(entries):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as packed:
        for name,raw in sorted(entries.items()):
            info=zipfile.ZipInfo(name,(2000,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            packed.writestr(info,raw)
    return stream.getvalue()


def prepare(package,output):
    package=Path(package);output=Path(output)
    if output.exists():raise ValueError('Use a new output directory')
    original=(package/'mau-structure.zip').read_bytes()
    origin=json.loads((package/'mau-origin.json').read_text(encoding='utf8'))
    if digest(original)!=origin['structure_sha256']:raise ValueError('Original MAU hash mismatch')
    with zipfile.ZipFile(io.BytesIO(original)) as packed:
        entries={name:packed.read(name) for name in packed.namelist()}
    effects={};counts={'media':0,'animation':0,'project':0,'identity':0}
    for name,raw in list(entries.items()):
        if Path(name).name=='draft_content.json':
            obj=json.loads(raw)
            for kind in ('videos','audios'):
                for material in obj['materials'][kind]:
                    if material.get('path'):counts['media']+=1
                    material['path']=''
                    for field in ('name','material_name'):
                        if field in material:material[field]=''
            for material in obj['materials']['material_animations']:
                for animation in material['animations']:
                    path=Path(animation['path']).resolve()
                    if not path.is_relative_to(Path(os.environ['LOCALAPPDATA']).resolve()):
                        raise ValueError('Effect must be in the local application cache')
                    if not re.fullmatch('[a-f0-9]{32}',path.name) or not path.is_dir():
                        raise ValueError('Referenced effect directory missing')
                    for file in path.rglob('*'):
                        if not file.is_file():continue
                        if file.is_symlink() or getattr(file.lstat(),'st_file_attributes',0)&0x400:
                            raise ValueError('Effect links are forbidden')
                        if file.suffix not in ('.json','.prefab','.material','.lua','.xshader','.frag','.vert'):
                            raise ValueError('Unexpected effect file type')
                        relative=path.name+'/'+file.relative_to(path).as_posix();data=file.read_bytes()
                        if relative in effects and effects[relative]!=data:raise ValueError('Effect changed during snapshot')
                        effects[relative]=data
                    animation['path']='transcomic-animation://'+path.name;counts['animation']+=1
            for field in ('platform','last_modified_platform'):
                if obj.get(field,{}).get('device_id'):counts['identity']+=1
                if field in obj:obj[field]['device_id']=''
            obj['name']='MAU';obj['path']=''
        elif name=='draft_meta_info.json':
            obj=json.loads(raw)
            counts['media']+=sum(bool(v.get('file_Path')) for m in obj['draft_materials'] for v in m.get('value',[]))
            obj['draft_materials']=[]
            for field in ('draft_fold_path','draft_root_path'):
                if obj.get(field):counts['project']+=1
                obj[field]=''
            if obj.get('tm_draft_cloud_user_id'):counts['identity']+=1
            obj['tm_draft_cloud_user_id']=0;obj['draft_name']='MAU'
        else:continue
        entries[name]=json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode('utf8')
    structure=archive(entries);resources=archive(effects)
    if any(re.search(rb'(?<![A-Za-z0-9])[A-Za-z]:[/\\]',raw) for raw in entries.values()):
        raise ValueError('Unclassified absolute path remains')
    origin.update(structure_sha256=digest(structure),files={n:digest(b) for n,b in entries.items()},
        normalization={'original_structure_sha256':digest(original),'fields':counts},
        animation_resources={'archive':'mau-animations.zip','sha256':digest(resources),
                             'files':{n:digest(b) for n,b in effects.items()}})
    output.mkdir(parents=True)
    (output/'mau-structure.zip').write_bytes(structure)
    (output/'mau-animations.zip').write_bytes(resources)
    (output/'mau-origin.json').write_text(json.dumps(origin,indent=2),encoding='utf8')
    return {'normalized_fields':counts,'effect_files':len(effects),'effect_bytes':sum(map(len,effects.values())),
            'structure_sha256':digest(structure),'animation_sha256':digest(resources)}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(prepare(args.package,args.output),indent=2))
