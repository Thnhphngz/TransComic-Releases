"""Read-only Windows/source/distribution inspection with no credential output."""
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from scripts.release_config import discover, static_configuration
from transcomic.release_provenance import SourceIdentity
from transcomic.version import RELEASE_REPOSITORY


def pe_architecture(path):
    try:
        with Path(path).open('rb') as stream:
            if stream.read(2)!=b'MZ':return 'NOT_PE'
            stream.seek(60);offset=struct.unpack('<I',stream.read(4))[0];stream.seek(offset)
            if stream.read(4)!=b'PE\0\0':return 'INVALID_PE'
            return {0x8664:'x64',0x14c:'x86',0xaa64:'arm64'}.get(struct.unpack('<H',stream.read(2))[0],'UNKNOWN_MACHINE')
    except (OSError,struct.error,TypeError):return 'NOT_DETECTED'


def file_version(path):
    if sys.platform!='win32' or not path:return None
    try:
        import ctypes
        from ctypes import wintypes as w
        dll=ctypes.WinDLL('version',use_last_error=True)
        dll.GetFileVersionInfoSizeW.argtypes=[w.LPCWSTR,ctypes.POINTER(w.DWORD)]
        dll.GetFileVersionInfoW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID]
        dll.VerQueryValueW.argtypes=[w.LPVOID,w.LPCWSTR,ctypes.POINTER(w.LPVOID),ctypes.POINTER(w.UINT)]
        unused=w.DWORD();size=dll.GetFileVersionInfoSizeW(str(path),ctypes.byref(unused))
        if not size:return None
        buffer=ctypes.create_string_buffer(size)
        if not dll.GetFileVersionInfoW(str(path),0,size,buffer):return None
        pointer=w.LPVOID();length=w.UINT()
        if not dll.VerQueryValueW(buffer,'\\',ctypes.byref(pointer),ctypes.byref(length)):return None
        values=ctypes.cast(pointer,ctypes.POINTER(w.DWORD))
        ms,ls=values[2],values[3]
        return f'{ms>>16}.{ms&65535}.{ls>>16}.{ls&65535}'
    except (OSError,ValueError,IndexError):return None


class ReadOnlyInspector:
    def __init__(self,root,git=None,gh=None,run=subprocess.run):self.root=Path(root).resolve();self.git=git;self.gh=gh;self.run=run
    def call(self,kind,args):
        if kind=='git':
            allowed=[['--version'],['rev-parse','--show-toplevel'],['rev-parse','HEAD'],['branch','--show-current'],
                     ['status','--porcelain','--untracked-files=all'],['remote','get-url','origin']]
            if args not in allowed or not self.git: return False,b''
            argv=[self.git,'-C',str(self.root),*args]
        elif kind=='gh':
            prefix='repos/'+RELEASE_REPOSITORY
            allowed=[['--version'],['auth','status'],['api',prefix],['api',prefix+'/branches'],['api',prefix+'/git/matching-refs/tags']]
            if args not in allowed or not self.gh:return False,b''
            argv=[self.gh,*args]
        else:return False,b''
        try:
            result=self.run(argv,cwd=self.root,capture_output=True,shell=False,timeout=30)
            raw=result.stdout if isinstance(result.stdout,bytes) else result.stdout.encode()
            return result.returncode==0,b'' if args==['auth','status'] else raw[:1024*1024]
        except (OSError,subprocess.TimeoutExpired):return False,b''

    def source(self):
        ok,root=self.call('git',['rev-parse','--show-toplevel'])
        if not ok:return {'status':'SOURCE_PROVENANCE_NOT_READY','git_root':None,'head':None,'branch':None,'dirty':None,'untracked_build_files':[],'source_remote_present':False,'source_private':None,'git_marker_found':any((p/'.git').exists() for p in (self.root,*self.root.parents))}
        commit_ok,head=self.call('git',['rev-parse','HEAD']);branch_ok,branch=self.call('git',['branch','--show-current'])
        status_ok,status=self.call('git',['status','--porcelain','--untracked-files=all']);remote_ok,remote=self.call('git',['remote','get-url','origin'])
        head=head.decode(errors='replace').strip();files=[]
        for line in status.decode(errors='replace').splitlines():
            if line.startswith('?? '):
                name=line[3:].strip('"')
                if name.startswith(('transcomic/','scripts/','installer/')) or name in ('TransComic.spec','run_transcomic.py','pyproject.toml','requirements-release.lock'):files.append(name)
        ready=commit_ok and status_ok and re.fullmatch('[0-9a-f]{40}',head) is not None and not status.strip()
        # Raw source remote URL is deliberately not returned/publicized. Privacy stays unknown until separately verified.
        return {'status':'VERIFIED_CLEAN_LOCAL_COMMIT' if ready else 'SOURCE_PROVENANCE_NOT_READY',
                'git_root':root.decode(errors='replace').strip(),'head':head if re.fullmatch('[0-9a-f]{40}',head) else None,
                'branch':branch.decode(errors='replace').strip() if branch_ok else None,'dirty':bool(status.strip()) if status_ok else None,
                'untracked_build_files':files,'source_remote_present':bool(remote_ok and remote.strip()),'source_private':None}

    def distribution(self):
        ok,raw=self.call('gh',['api','repos/'+RELEASE_REPOSITORY]);branches_ok,branches=self.call('gh',['api','repos/'+RELEASE_REPOSITORY+'/branches'])
        try:
            repo=json.loads(raw);refs=json.loads(branches)
            if not ok or not branches_ok or repo.get('full_name')!=RELEASE_REPOSITORY or not isinstance(refs,list):raise ValueError()
            return {'status':'DISTRIBUTION_REPO_NEEDS_INITIAL_COMMIT' if not refs else 'HAS_BRANCH_COMMIT',
                    'repository':RELEASE_REPOSITORY,'public':repo.get('private') is False,
                    'declared_default_branch':repo.get('default_branch'),'branch_count':len(refs),
                    'default_branch_has_commit':any(r.get('name')==repo.get('default_branch') and re.fullmatch('[0-9a-f]{40}',r.get('commit',{}).get('sha','')) for r in refs)}
        except (ValueError,TypeError):return {'status':'DISTRIBUTION_STATE_UNVERIFIED','repository':RELEASE_REPOSITORY}


def environment_report(root):
    root=Path(root).resolve();inventory=discover()
    inspector=ReadOnlyInspector(root,inventory['git']['path'],inventory['gh']['path'])
    for name in ('git','gh','ISCC','SignTool','python'):
        tool=inventory[name];tool['architecture']=pe_architecture(tool.get('path'))
        tool['file_version']=file_version(tool.get('path'))
        tool['blocks_b2_2']=tool.get('path') is None
    inventory['ISCC']['compatibility']='INNO6_REQUIRED' if not inventory['ISCC']['file_version'] else 'COMPATIBLE' if inventory['ISCC']['file_version'].startswith('6.') else 'INCOMPATIBLE_VERSION'
    # x86 ISCC can produce an x64 installer; don't incorrectly classify its compiler architecture as app architecture.
    inventory['ISCC']['architecture_policy']='x86 compiler allowed; target Windows x64'
    inventory['PowerShell']={'path':shutil.which('powershell'),'file_version':file_version(shutil.which('powershell'))}
    inventory['BAT']={'cmd_path':shutil.which('cmd'),'present':(root/'release_transcomic.bat').is_file()}
    for name in ('git','gh'):
        ok,raw=inspector.call(name,['--version'])
        match=re.search(rb'\d+\.\d+\.\d+(?:\.windows\.\d+)?',raw)
        inventory[name]['version']=match.group().decode() if ok and match else None
    if inventory['PowerShell']['path']:
        try:
            result=subprocess.run([inventory['PowerShell']['path'],'-NoProfile','-NonInteractive','-Command','$PSVersionTable.PSVersion.ToString()'],capture_output=True,shell=False,timeout=15)
            value=result.stdout.decode(errors='replace').strip()
            inventory['PowerShell']['version']=value if re.fullmatch(r'\d+(?:\.\d+){1,3}',value) else None
        except (OSError,subprocess.TimeoutExpired):inventory['PowerShell']['version']=None
    inventory['platform']['compatible_windows_x64']=inventory['platform']['system']=='Windows' and inventory['python']['architecture']=='x64'
    for name,item in inventory.items():
        if name in ('git','ISCC','SignTool'):
            item['required_action']='Locate custom installation or install with separate user authorization' if not item.get('path') else 'Verify version and configured absolute executable path'
        elif name=='python':item['required_action']='Create isolated venv and verify hash-locked wheels in B2.2' if not item['venv'] else 'Verify dependency lock'
        elif name in ('PyInstaller','PySide6','cryptography','pytest'):item['required_action']='Match dependency lock; no reinstall requested if compatible'
    auth,_=inspector.call('gh',['auth','status'])
    return {'tools':inventory,'static_configuration':static_configuration(root),'source':inspector.source(),
            'distribution':inspector.distribution(),'gh_authenticated':auth,'production_execution_locked':True}
