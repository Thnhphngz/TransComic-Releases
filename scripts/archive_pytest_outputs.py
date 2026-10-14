"""Recoverable pytest archive: copy/hash/manifest, then move; never delete."""
import argparse
import ctypes
from ctypes import wintypes as W
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from transcomic.maintenance import active_work,require_idle,tree
from transcomic.release_adapters import safe_path
from scripts.native_reparse import read as read_reparse,restore_junction

def stamp():return datetime.now(timezone.utc).isoformat()
def sha(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):result.update(data)
    return result.hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.new-'+uuid4().hex)
    with temporary.open('x',encoding='utf8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
def git(args):return subprocess.check_output(['git','-C',str(ROOT),*args]).decode('utf8')
def idle():
    # Include native helper/installer and GUI/build harnesses missed by older cache cleanup.
    script="Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(TransComic(-UpdateHelper)?|TransComic-Setup.*|ISCC|unins\\d+)\\.exe$' -or ($_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -match 'pytest|PyInstaller|live_|release_transcomic|update_helper|run_transcomic|gui_smoke|exe_smoke|windows_stress|build_local|archive_pytest_outputs') } | Select-Object ProcessId | ConvertTo-Json -Compress"
    result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=20)
    if result.returncode:raise ValueError('Process inspection failed')
    data=json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(data,dict):data=[data]
    processes=set(active_work())|{row['ProcessId'] for row in data if row['ProcessId']!=os.getpid()}
    require_idle(ROOT,list(processes))
def snapshot(folder,original=None):
    original=original or folder;files=[];directories=[];links=[]
    for path,info,reparse in tree(folder):
        relative=path.relative_to(folder).as_posix()
        if reparse:
            native=read_reparse(path)
            if native['tag']==0xA0000003:
                target=Path(os.path.normpath(native['substitute_name'].removeprefix('\\??\\')))
                expected=original/relative
                if relative!='test_directory_junction_loop_d0/chapters/loop' or target!=expected.parent:
                    raise ValueError('Unverified junction target: '+relative)
                parent_info=path.parent.lstat()
                if getattr(parent_info,'st_file_attributes',0)&0x400:raise ValueError('Junction parent reparse')
                links.append({'path':relative,'kind':'junction','target':str(target),'raw_reparse_hex':native['raw_hex']})
                continue
            if not path.is_symlink() or getattr(info,'st_reparse_tag',0)!=0xA000000C:raise ValueError('Unknown reparse: '+relative)
            target=os.readlink(path);normalized=Path(os.path.normpath(target.removeprefix('\\\\?\\')))
            expected=original/relative
            if not path.name.endswith('current') or not normalized.is_absolute() or normalized.parent!=expected.parent or not normalized.name.startswith(path.name[:-7]) or not re.search(r'\d+$',normalized.name):raise ValueError('Non-pytest or external alias: '+relative)
            # Never traverse the alias. Check target's counterpart in this tree instead.
            counterpart=folder/normalized.relative_to(original)
            target_info=counterpart.lstat()
            if not stat.S_ISDIR(target_info.st_mode) or getattr(target_info,'st_file_attributes',0)&0x400:raise ValueError('Alias target is not a plain fixture directory')
            links.append({'path':relative,'target':target})
        elif stat.S_ISDIR(info.st_mode):directories.append(relative)
        elif stat.S_ISREG(info.st_mode):files.append({'path':relative,'bytes':info.st_size,'sha256':sha(path)})
        else:raise ValueError('Unknown filesystem node: '+relative)
    files.sort(key=lambda r:r['path']);links.sort(key=lambda r:r['path']);directories.sort()
    contents={'files':files,'directories':directories,'links':links}
    contents['aggregate_sha256']=hashlib.sha256(json.dumps(contents,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return contents

def copy_no_follow(source,destination,contents):
    if destination.exists():raise ValueError('Copy destination exists')
    destination.mkdir(parents=True)
    for relative in sorted(contents['directories'],key=lambda p:(p.count('/'),p)):
        if relative!='.':(destination/relative).mkdir()
    for item in contents['files']:
        path=safe_path(source/item['path'],source)
        if path.lstat().st_file_attributes&0x400:raise ValueError('File became reparse')
        shutil.copy2(path,destination/item['path'],follow_symlinks=False)
    for link in contents['links']:
        target=destination/link['path']
        if link.get('kind')=='junction':restore_junction(target,link['raw_reparse_hex'])
        else:target.symlink_to(link['target'],target_is_directory=True)
def unlocked(folder,inventory):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,ctypes.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
    kernel.CreateFileW.restype=W.HANDLE;kernel.CloseHandle.argtypes=[W.HANDLE]
    for item in inventory['files']:
        handle=kernel.CreateFileW(str(folder/item['path']),0x80000000,0,None,3,0x80,None)
        if handle==ctypes.c_void_p(-1).value:raise ValueError('Locked/unreadable file: '+item['path'])
        kernel.CloseHandle(handle)
def source_state():
    tracked=git(['ls-files','-z']).split('\0')
    return {'head':git(['rev-parse','HEAD']).strip(),'branch':git(['branch','--show-current']).strip(),
            'status':git(['status','--porcelain']),
            'tracked_hashes':{name:sha(ROOT/name) for name in tracked if name and (ROOT/name).is_file()}}
def refs():
    command=['rg','-n','--hidden','-g','!__pycache__/**','\\.pytest_','transcomic','scripts','tests','docs','README.md','.gitignore','pyproject.toml']
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf8')
    if result.returncode not in (0,1):raise ValueError('Reference scan failed')
    return result.stdout.splitlines()
def inventory():
    idle();before=source_state();references=refs();records=[]
    for folder in sorted(ROOT.glob('.pytest_*')):
        record={'path':folder.name,'created_at':datetime.fromtimestamp(folder.lstat().st_ctime,timezone.utc).isoformat(),
                'references':[line for line in references if folder.name in line],'classification':'C','reason':'Unverified'}
        try:
            safe_path(folder,ROOT)
            if folder.is_symlink() or folder.lstat().st_file_attributes&0x400:raise ValueError('Root reparse')
            nodes=list(tree(folder))
            regular=[(p,s) for p,s,r in nodes if not r and stat.S_ISREG(s.st_mode)]
            record.update(file_count=len(regular),total_bytes=sum(s.st_size for p,s in regular),
                          link_count=sum(bool(r) for p,s,r in nodes),
                          reparses=[{'path':p.relative_to(folder).as_posix(),**read_reparse(p,exclusive=True),
                                     'object_id':s.st_ino,'parent_id':p.parent.lstat().st_ino,
                                     'tracked':any(n==p.relative_to(ROOT).as_posix() for n in before['tracked_hashes']),
                                     'process_gate':'idle','lock_gate':'regular files exclusive-open required'} for p,s,r in nodes if r])
            if any(name==folder.name or name.startswith(folder.name+'/') for name in before['tracked_hashes']):raise ValueError('Tracked data')
            # Documentation of --basetemp is historical, not a live path dependency.
            required=[line for line in record['references'] if not line.replace('\\','/').startswith(('docs/','README.md:','.gitignore:','scripts/archive_pytest_outputs.py:'))]
            if folder.name=='.pytest_cache':
                allowed={'.gitignore','CACHEDIR.TAG','README.md','v/cache/nodeids','v/cache/lastfailed','v/cache/stepwise'}
                if any(p.relative_to(folder).as_posix() not in allowed for p,s in regular):raise ValueError('Unrecognized cache data')
                required=[line for line in required if any('.pytest_cache/'+name in line.replace('\\','/') for name in allowed)]
            if required:raise ValueError('Source/test reference needs review')
            children=list(folder.iterdir())
            if folder.name!='.pytest_cache' and any(not p.name.startswith(('test_','pytest-','popen-')) and p.name not in ('.lock','garbage') for p in children):raise ValueError('Unknown root data/provenance')
            contents=snapshot(folder);unlocked(folder,contents)
            record.update(classification='B' if contents['files'] else 'A',reason='Historical pytest fixture outputs; no runtime dependency; verified internal current aliases preserved without traversal',
                          inventory=contents,file_count=len(contents['files']),link_count=len(contents['links']),total_bytes=sum(f['bytes'] for f in contents['files']),
                          ignored=subprocess.run(['git','check-ignore','-q',folder.name],cwd=ROOT).returncode==0)
        except Exception as error:record['reason']=str(error)
        records.append(record)
    return {'created_at':stamp(),'root':str(ROOT),'root_items_before':len(list(ROOT.iterdir())),
            'git_before':before,'reference_scan':references,'directories':records,'directory_count':len(records)}
def archive(plan,base,prefix='archive'):
    base=safe_path(base)
    if base.is_relative_to(ROOT) or base==Path('D:/TransComic-SecureBackup') or base.is_relative_to(Path('D:/TransComic-SecureBackup')):raise ValueError('Archive must be outside workspace and signing backup')
    idle()
    base.mkdir(parents=True,exist_ok=True)
    if prefix not in ('archive','final-pytest-cleanup'):raise ValueError('Unknown archive prefix')
    destination=base/(prefix+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8]);destination.mkdir()
    manifest={'created_at':stamp(),'root':str(ROOT),'archive':str(destination),'git_before':plan['git_before'],'entries':[],
              'restore':'Use originals/<name> only after verifying against entry inventory. Move to original workspace path only when absent and idle. Absolute pytest aliases retain original targets and become valid upon restoration. Verified copies are retained independently.'}
    write(destination/'manifest.json',manifest)
    for record in plan['directories']:
        if record['classification']=='C':continue
        source=safe_path(ROOT/record['path'],ROOT);backup=safe_path(destination/'verified'/record['path'],destination);retired=safe_path(destination/'originals'/record['path'],destination)
        entry={'relative_source':record['path'],'source':str(source),'verified_copy':str(backup),'archived_path':str(retired),'created_at':record['created_at'],'archive_time':stamp(),'reason':record['reason'],'state':'pending','inventory':record['inventory']}
        manifest['entries'].append(entry);write(destination/'manifest.json',manifest)
        try:
            idle()
            if git(['ls-files','--',record['path']]).strip():raise ValueError('Candidate now contains tracked data')
            if snapshot(source)!=record['inventory']:raise ValueError('Source changed since inventory')
            unlocked(source,record['inventory']);backup.parent.mkdir(parents=True,exist_ok=True)
            copy_no_follow(source,backup,record['inventory'])
            if snapshot(backup,source)!=record['inventory']:raise ValueError('Backup verification mismatch')
            entry['state']='copy_verified';write(destination/'manifest.json',manifest)
            if snapshot(source)!=record['inventory']:raise ValueError('Source changed during copy')
            idle();unlocked(source,record['inventory']);retired.parent.mkdir(parents=True,exist_ok=True)
            if git(['ls-files','--',record['path']]).strip():raise ValueError('Candidate gained tracked data before move')
            # Native same-volume rename; no deletion, no recursion through aliases.
            if source.drive.lower()!=retired.drive.lower():raise ValueError('Only same-volume source move supported')
            os.rename(source,retired)
            if snapshot(retired,source)!=record['inventory']:raise ValueError('Moved source verification mismatch')
            entry['state']='moved_verified';entry['receipt_time']=stamp()
        except Exception as error:entry['state']='error';entry['error']=str(error)
        write(destination/'manifest.json',manifest)
    after=source_state()
    if after!=plan['git_before']:raise ValueError('Git/source preservation mismatch; archive retained for recovery')
    manifest['git_after']=after;manifest['source_preserved']=True
    manifest['root_items_after']=len(list(ROOT.iterdir()));manifest['pytest_remaining']=[p.name for p in ROOT.glob('.pytest_*')]
    write(destination/'manifest.json',manifest)
    moved=[entry for entry in manifest['entries'] if entry['state']=='moved_verified']
    if moved:
        # Restore rehearsal to a new OUTSIDE-workspace path, preserving raw aliases.
        selected=min(moved,key=lambda e:sum(f['bytes'] for f in e['inventory']['files']))
        trial=destination/'restore-verification'/selected['relative_source'];trial.parent.mkdir()
        copy_no_follow(Path(selected['archived_path']),trial,selected['inventory'])
        assert snapshot(trial,Path(selected['source']))==selected['inventory']
        manifest['restore_test']={'path':str(trial),'from':selected['archived_path'],'hash_verified':True,'original_location_restored':False}
        write(destination/'manifest.json',manifest)
    return manifest
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--archive-root',type=Path,default=Path('D:/TransComic-TestArchive'))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/workspace-cleanup');parser.add_argument('--prefix',default='archive');args=parser.parse_args()
    output=safe_path(args.output,ROOT);output.mkdir(parents=True,exist_ok=True)
    plan=inventory();write(output/'inventory.json',plan)
    print(json.dumps({'folders':len(plan['directories']),'candidates':sum(r['classification']!='C' for r in plan['directories']),
                      'bytes':sum(r.get('total_bytes',0) for r in plan['directories']),'kept':[{k:r[k] for k in ('path','reason')} for r in plan['directories'] if r['classification']=='C']}))
    if args.apply:
        result=archive(plan,args.archive_root,args.prefix);write(output/'archive-receipt.json',result)
        print(json.dumps({'archive':result['archive'],'moved':sum(e['state']=='moved_verified' for e in result['entries']),'errors':[e['relative_source'] for e in result['entries'] if e['state']=='error']}))
if __name__=='__main__':main()
