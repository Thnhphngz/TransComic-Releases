"""Verified portable MAU effect resources; never read a developer cache."""
import hashlib
from importlib.resources import files
import io
import json
from pathlib import PurePosixPath
import re
import zipfile
from .media import checkpoint


RESOURCE_FILES=('mau-structure.zip','mau-origin.json','mau-animations.zip')


def effects():
    package=files('transcomic.capcut')
    manifest=json.loads(package.joinpath('mau-origin.json').read_text(encoding='utf8'))['animation_resources']
    raw=package.joinpath(manifest['archive']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:raise ValueError('MAU animation archive hash mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if set(archive.namelist())!=set(manifest['files']):raise ValueError('MAU animation inventory mismatch')
        result={}
        for name,expected in manifest['files'].items():
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                raise ValueError('Unsafe animation resource path')
            data=archive.read(name)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('MAU effect file hash mismatch')
            result[name]=data
    return result


def materialize(stage,target,content,cancel=None):
    resources=effects();used=set()
    for material in content['materials']['material_animations']:
        for animation in material.get('animations',[]):
            marker=animation.get('path','')
            match=re.fullmatch(r'transcomic-animation://([a-f0-9]{32})',marker)
            if not match:raise ValueError('MAU effect must use a verified portable reference')
            key=match[1]
            if not any(n.startswith(key+'/') for n in resources):raise ValueError('MAU effect missing')
            used.add(key)
            from .exporter import reference
            animation['path']=reference(target/'transcomic_resources/animations'/key)
    output={}
    for name,data in resources.items():
        if name.split('/')[0] not in used:continue
        checkpoint(cancel)
        relative='transcomic_resources/animations/'+name
        destination=stage.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        output[relative]=hashlib.sha256(data).hexdigest()
    return output
