"""Classify and fingerprint project files before any automatic commit."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from transcomic.release_adapters import safe_path
from transcomic.update.metadata import UpdateError

ROOT_FILES={'.gitignore','README.md','TransComic.spec','run_transcomic.py',
            'release_transcomic.bat','pyproject.toml','requirements-release.lock','requirements-tts-cuda.lock','conftest.py'}
TTS_CATALOG_FILES={'transcomic/tts/setup-catalog.json','transcomic/tts/calibration.json'}
SECRET=re.compile(rb'gh[oopsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{25,}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')

def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE)

def allowed(name):
    p=Path(name)
    return (name in ROOT_FILES or name in TTS_CATALOG_FILES or name=='installer/TransComic.iss' or name=='installer/TransComic.ico'
        or (p.parts[0] in ('transcomic','scripts','tests') and p.suffix in ('.py','.svg'))
        or (p.parts[0]=='docs' and p.suffix=='.md')) and '..' not in p.parts

def releaseable(name):
    # Generated/historical reports and prose alone do not change the application.
    return allowed(name) and not name.startswith('docs/') and name!='README.md'

def normalized(name,raw):
    raw=raw.replace(b'\r\n',b'\n')
    if name=='transcomic/version.py':
        raw=re.sub(rb'(?m)^VERSION\s*=\s*[\'\"][^\'\"]+[\'\"]',b'VERSION = "GENERATED"',raw)
    return raw

def file_map(root,ref=None):
    if ref:
        names=git(root,'ls-tree','-r','--name-only','-z',ref).decode('utf8').split('\0')
        return {n:hashlib.sha256(normalized(n,git(root,'show',ref+':'+n))).hexdigest()
                for n in names if n and releaseable(n)}
    names=set(git(root,'ls-files','-z').decode('utf8').split('\0'))
    names.update(git(root,'ls-files','--others','--exclude-standard','-z').decode('utf8').split('\0'))
    result={}
    for n in sorted(names):
        if n and releaseable(n):
            p=safe_path(root/n,root)
            if p.is_file():result[n]=hashlib.sha256(normalized(n,p.read_bytes())).hexdigest()
    return result

def fingerprint(mapping):
    return hashlib.sha256(json.dumps(mapping,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def inspect(root):
    root=safe_path(root)
    branch=git(root,'branch','--show-current').decode().strip()
    if not branch:raise UpdateError('DETACHED_HEAD_REQUIRES_REVIEW')
    if git(root,'ls-files','-u'):raise UpdateError('MERGE_CONFLICT_REQUIRES_REVIEW')
    for marker in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply'):
        if Path(git(root,'rev-parse','--git-path',marker).decode().strip()).is_absolute():
            p=Path(git(root,'rev-parse','--git-path',marker).decode().strip())
        else:p=root/git(root,'rev-parse','--git-path',marker).decode().strip()
        if p.exists():raise UpdateError('GIT_OPERATION_IN_PROGRESS')
    # --no-renames exposes both sides; NUL delimiters preserve spaces and Unicode.
    changes=set()
    for args in (('diff','--name-only','--no-renames','-z'),('diff','--cached','--name-only','--no-renames','-z'),
                 ('ls-files','--others','--exclude-standard','-z')):
        changes.update(n for n in git(root,*args).decode('utf8').split('\0') if n)
    for name in changes:
        if not allowed(name):raise UpdateError('UNCLASSIFIED_CHANGE: '+name)
    names=set(git(root,'ls-files','-z').decode('utf8').split('\0'))|changes
    hashes={}
    for name in sorted(n for n in names if n and allowed(n)):
        p=safe_path(root/name,root)
        if not p.exists():continue
        raw=p.read_bytes()
        if len(raw)>5*1024*1024:raise UpdateError('OVERSIZED_PROJECT_FILE: '+name)
        if SECRET.search(raw):raise UpdateError('SOURCE_SECRET_DETECTED: '+name)
        if name=='installer/TransComic.ico' and not raw.startswith(b'\x00\x00\x01\x00'):
            raise UpdateError('INVALID_ICON_BINARY')
        if name!='installer/TransComic.ico':
            if b'\0' in raw:raise UpdateError('BINARY_SOURCE_REQUIRES_REVIEW: '+name)
            try:raw.decode('utf8')
            except UnicodeError:raise UpdateError('NON_UTF8_SOURCE_REQUIRES_REVIEW: '+name) from None
        hashes[name]=hashlib.sha256(raw).hexdigest()
    return {'head':git(root,'rev-parse','HEAD').decode().strip(),'branch':branch,
            'changes':sorted(changes),'source_hashes':hashes,'fingerprint':fingerprint(file_map(root))}

def commit(root,review,message):
    if inspect(root)!=review:raise UpdateError('SOURCE_CHANGED_AFTER_REVIEW')
    if review['changes']:
        subprocess.run(['git','-C',str(root),'add','--',*review['changes']],check=True)
        staged=set(git(root,'diff','--cached','--name-only','--no-renames','-z').decode('utf8').split('\0'))-{''}
        if staged!=set(review['changes']):raise UpdateError('STAGED_INVENTORY_CHANGED')
        subprocess.run(['git','-C',str(root),'commit','-m',message],check=True)
    if git(root,'status','--porcelain').strip():raise UpdateError('SOURCE_NOT_CLEAN_AFTER_COMMIT')
    return git(root,'rev-parse','HEAD').decode().strip()
