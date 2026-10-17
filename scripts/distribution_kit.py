"""Validate an explicit local corresponding-source kit, never publish it."""
import hashlib
import json
from pathlib import Path, PurePosixPath

REQUIRED={'qtbase','qtdeclarative','qtmultimedia','qtsvg','pyside','ffmpeg',
          'espeak','espeak-loader','phonemizer','lameenc','lame','libsndfile',
          'soundfile','sndfile-build','worker','notices','replacement','terms',
          'mpg123','sndfile-lame','zlib','ogg','vorbis','flac','opus','qtimageformats',
          'model-notice'}


def verify_kit(directory,source_root=None):
    from transcomic.release_adapters import safe_path
    root=safe_path(directory)
    record=json.loads((root/'manifest.json').read_text(encoding='utf8'))
    if record.get('schema')!=1 or not REQUIRED<=set(record.get('components',[])):
        raise ValueError('Incomplete corresponding-source kit')
    files=record.get('files',{})
    if not files:raise ValueError('Empty corresponding-source kit')
    for name,entry in files.items():
        rel=PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe kit member')
        p=root.joinpath(*rel.parts)
        for parent in [p,*p.parents]:
            if parent==root.parent:break
            if parent.is_symlink() or getattr(parent.lstat(),'st_file_attributes',0)&0x400:
                raise ValueError('Kit links are not permitted')
        with p.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        if p.stat().st_size!=entry['bytes'] or sha!=entry['sha256']:
            raise ValueError('Corresponding-source kit hash mismatch: '+name)
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual!=set(files)|{'manifest.json'}:raise ValueError('Unlisted kit member')
    if source_root is not None:
        source=Path(source_root)
        lock=hashlib.sha256((source/'requirements-release.lock').read_bytes()).hexdigest()
        if record.get('release_lock_sha256')!=lock:raise ValueError('Source media dependency lock is stale')
        from transcomic.tts.managed_runtime import WORKER_FILES
        for name in (*WORKER_FILES,'setup-catalog.json','calibration.json'):
            data=(source/'transcomic/tts'/name).read_bytes()
            if files.get('worker/'+name,{}).get('sha256')!=hashlib.sha256(data).hexdigest():
                raise ValueError('Worker corresponding source is stale: '+name)
        import ast
        tree=ast.parse((source/'transcomic/tts/managed_engine.py').read_text(encoding='utf8'))
        bootstrap=next(n.value.value for n in tree.body if isinstance(n,ast.Assign)
                       and any(isinstance(t,ast.Name) and t.id=='WORKER_BOOTSTRAP' for t in n.targets))
        if files.get('worker/windows_bootstrap.py',{}).get('sha256')!=hashlib.sha256(bootstrap.encode('utf8')).hexdigest():
            raise ValueError('Windows worker bootstrap corresponding source is stale')
    return {'files':len(files),'components':record['components'],
            'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()}
