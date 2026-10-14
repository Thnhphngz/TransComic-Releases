"""Canonical packaging and offline gates shared by automatic/build-only modes."""
import hashlib
import json
import re
from datetime import datetime,timezone
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader
from scripts.release_environment import file_version,pe_architecture
from scripts.release_source import SECRET
from transcomic.release_adapters import Asset,safe_path
from transcomic.update.internal import manifest,candidate,verify_checksums
from transcomic.update.metadata import canonical,asset_url,release_url,UpdateError

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def save_exact(path,raw):
    path=safe_path(path)
    if path.exists():
        if path.read_bytes()!=raw:raise UpdateError('EXISTING_OUTPUT_CONFLICT: '+path.name)
    else:
        with path.open('xb') as stream:stream.write(raw)

def names(version):return ('TransComic-Setup-'+version+'-windows-x64.exe','transcomic-update.json','SHA256SUMS.txt')

def verify_identity(iss):
    for token in ('AppId={{CB58C770-47B7-42DC-A2CA-409DDF456487}',
        'DefaultDirName={localappdata}\\Programs\\{#MyAppName}', 'PrivilegesRequired=lowest',
        'AppMutex=TransComic.Desktop.Running','ArchitecturesInstallIn64BitMode=x64compatible'):
        if token not in iss:raise UpdateError('INSTALLER_IDENTITY_DRIFT')
    if '[UninstallDelete]' in iss:raise UpdateError('USER_DATA_DELETE_POLICY_REJECTED')

def verify_archives(products):
    result=[]
    for path in products:
        reader=CArchiveReader(str(path));entries=[n.replace('\\','/') for n in reader.toc]
        modules=list(reader.open_embedded_archive('PYZ.pyz').toc)
        public=('docx/templates/default.docx','certifi/cacert.pem')
        bad=[n for n in entries if n not in public and (n.startswith(('tests/','artifacts/','.git/','.pytest_','releases/'))
            or n.endswith(('.sqlite3','.db','.docx','.tc-keybackup','.pem','.log','.key','.pfx')) or 'TestArchive' in n or 'SecureBackup' in n)]
        if bad or any(n=='tests' or n.startswith('tests.') for n in modules):raise UpdateError('PRIVATE_DATA_IN_ARCHIVE')
        if not {'transcomic.update.windows_helper','transcomic.update.windows_channel'}.issubset(modules):raise UpdateError('HELPER_MODULES_ABSENT')
        if path.name=='TransComic.exe' and not all(any(n.endswith(t) for n in entries) for t in ('qwindows.dll','qsvg.dll','qsvgicon.dll','nav-subtitles.svg')):
            raise UpdateError('GUI_RESOURCES_ABSENT')
        result.append({'file':path.name,'entries':len(entries),'modules':len(modules),'privacy_findings':[]})
    return result

def assemble(root,work,version,record):
    report=load(work/'build/build-report.json')
    if report['version']!=version or report['head']!=record['source_commit'] or report['version_overlay'] or report['git_status'].strip():
        raise UpdateError('BUILD_PROVENANCE_MISMATCH')
    folder=safe_path(root/'releases'/version,root);folder.mkdir(parents=True,exist_ok=True)
    for item in report['artifacts']:
        original=safe_path(item['path'],root)
        if sha(original)!=item['sha256']:raise UpdateError('BUILD_ARTIFACT_CHANGED')
        save_exact(folder/original.name,original.read_bytes())
    installer=folder/names(version)[0]
    # Fixed reservation time makes interrupted package assembly reproducible.
    metadata=manifest(version,installer.name,installer.stat().st_size,sha(installer),record['created_at'])
    save_exact(folder/'transcomic-update.json',canonical(metadata))
    save_exact(folder/'SHA256SUMS.txt',''.join(sha(folder/n)+'  '+n+'\n' for n in names(version)[:2]).encode('ascii'))
    notes=(f'# TransComic {version}\n\nBản Windows x64 — kênh Internal (HTTPS + SHA256, không phải chữ ký publisher).\n\n'
        'TXT/DOCX, dịch hàng loạt, Kira/Gemini, lịch sử, hàng đợi và Liquid Glass V3 được kiểm thử offline trước build.\n'
        'SRT giữ nguyên mục sidebar và thông báo “Chức năng đang được cập nhật”.\n\n'
        'Hậu kiểm release dùng staging riêng ngoài source/program; journal phân biệt trạng thái đã publish và đã xác minh, hỗ trợ khôi phục release public bằng GET.\n\n'
        f'Source commit: `{record["source_commit"]}`.\n\n'
        f'Người đang dùng bản installed {record["previous_published_version"]}: Kiểm tra cập nhật trong ứng dụng → tải → xác nhận cài sau SafeExit. '
        'Không gỡ bản cũ hoặc chạy Installer tay để thay thế kiểm thử updater. Người dùng mới có thể dùng Installer per-user mặc định. '
        'EXE chạy trực tiếp không được quảng cáo là portable tự cập nhật; helper không mở thủ công.\n\n'
        f'Compatibility từ package {record["previous_published_version"]} được kiểm tra; native update cho phiên bản mới cần người dùng nghiệm thu.\n')
    save_exact(folder/'release-notes.md',notes.encode('utf8'))
    public={'version':version,'source_commit':record['source_commit'],'source_tree_state':'clean_local_commit',
        'source_hashes':report['hashes'],'version_overlay':False,'created_at':record['created_at'],
        'artifacts':[{'name':Path(a['path']).name,'size':a['bytes'],'sha256':a['sha256']} for a in report['artifacts']],
        'tool_versions':{n:{k:v for k,v in values.items() if k in ('version','bits','system','machine')} for n,values in report['tools'].items()},
        'distribution_policy':'internal','native_install_verified':False}
    save_exact(folder/'build-manifest.json',json.dumps(public,indent=2).encode('utf8'))
    return verify(root,work,version,record)

def verify(root,work,version,record):
    folder=safe_path(root/'releases'/version,root);report=load(work/'build/build-report.json')
    expected=set(names(version))|{'TransComic.exe','TransComic-UpdateHelper.exe','release-notes.md','build-manifest.json'}
    if {p.name for p in folder.iterdir()}!=expected:raise UpdateError('RELEASE_FOLDER_INVENTORY_MISMATCH')
    public=load(folder/'build-manifest.json')
    if (report['head'],report['version'],report['source_version'])!=(record['source_commit'],version,version) or report['version_overlay']:
        raise UpdateError('BUILD_PROVENANCE_MISMATCH')
    if public['source_commit']!=record['source_commit'] or public['source_hashes']!=report['hashes']:raise UpdateError('PUBLIC_PROVENANCE_CHANGED')
    expected_artifacts=[{'name':Path(a['path']).name,'size':a['bytes'],'sha256':a['sha256']} for a in report['artifacts']]
    if public['version']!=version or public['artifacts']!=expected_artifacts:raise UpdateError('PUBLIC_ARTIFACT_PROVENANCE_CHANGED')
    for n,h in report['hashes'].items():
        if sha(safe_path(root/n,root))!=h or sha(work/'build/source'/n)!=h:raise UpdateError('BUILD_SOURCE_DRIFT: '+n)
        if SECRET.search((root/n).read_bytes()):raise UpdateError('SOURCE_SECRET_DETECTED')
    for a in report['artifacts']:
        p=folder/Path(a['path']).name
        if sha(p)!=a['sha256'] or p.stat().st_size!=a['bytes'] or file_version(p)!=version+'.0':raise UpdateError('PE_HASH_VERSION_MISMATCH')
        if p.name in ('TransComic.exe','TransComic-UpdateHelper.exe') and pe_architecture(p)!='x64':raise UpdateError('X64_REQUIRED')
    verify_identity((work/'build/source/installer/TransComic.iss').read_text(encoding='utf8'))
    archives=verify_archives([folder/'TransComic.exe',folder/'TransComic-UpdateHelper.exe'])
    for p in folder.iterdir():
        if p.suffix in ('.json','.txt','.md') and SECRET.search(p.read_bytes()):raise UpdateError('SECRET_IN_PACKAGE_METADATA')
    assets=[Asset.inspect(n,folder/n,root) for n in names(version)]
    fixture={'tag_name':'v'+version,'draft':False,'prerelease':False,'html_url':release_url('v'+version),
        'published_at':'OFFLINE_VALIDATION_ONLY','body':'Protocol verification',
        'assets':[{'name':a.name,'size':a.size,'state':'uploaded','browser_download_url':asset_url('v'+version,a.name)} for a in assets]}
    item=candidate(fixture,load(folder/'transcomic-update.json'))
    verify_checksums((folder/'SHA256SUMS.txt').read_bytes(),item,(folder/'transcomic-update.json').read_bytes())
    if (item.sha256,item.size)!=(assets[0].sha256,assets[0].size):raise UpdateError('MANIFEST_BINDING_MISMATCH')
    (work/'package-verification.json').write_text(json.dumps({'passed':True,'version':version,'archives':archives,
        'artifacts':{p.name:sha(p) for p in folder.iterdir()},'native_installer_executions':0},indent=2),encoding='utf8')
    return assets
