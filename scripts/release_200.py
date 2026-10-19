"""User-authorized v2.0.0 release through the existing six-asset publisher.

Build is separate. Prepare/bind are local. Publication revalidates the exact
committed build, frozen smoke, migrations and actual baseline updater proof.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.first_internal_release import (automatic_scope,FirstReleaseCommands,FirstReleasePublisher,
    FirstReleaseOperations,source_identity,require_current_tests,PACKAGING_200_GATES,draft_validation_identity,inspect_scoped_asset)
from scripts.release_package import sha,load,verify_identity
from scripts.release_environment import file_version,pe_architecture
from scripts.distribution_kit import verify_kit
from scripts.release_source import inspect,SECRET
from transcomic.release_adapters import Asset,execute
from transcomic.release_provenance import build_identity
from transcomic.release_journal import ReleaseJournal
from transcomic.release_pipeline import ReleaseCoordinator
from transcomic.update.internal import manifest,candidate,verify_checksums
from transcomic.update.metadata import canonical,release_url,asset_url,UpdateError

VERSION='2.0.0'
KIT=ROOT/'artifacts/release-1.2.0/packaging-followup/ThirdParty'
OUT=ROOT/'artifacts/release-2.0.0'
BUILD=OUT/'build'
FOLDER=ROOT/'releases'/VERSION
SCOPE=automatic_scope(VERSION)
EXTRAS=(f'TransComic-{VERSION}-ThirdParty-Sources.zip','build-manifest.json','ThirdParty-SHA256SUMS.txt')
NAMES=(*SCOPE.names,*EXTRAS)


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf8')


def copy_exact(source,target):
    if target.exists():
        if sha(source)!=sha(target):raise UpdateError('EXISTING_RELEASE_FILE_CONFLICT: '+target.name)
    else:shutil.copyfile(source,target)


def verify_build():
    report=load(BUILD/'build-report.json')
    if report['version']!=VERSION or report['source_version']!=VERSION or report['version_overlay']:
        raise UpdateError('BUILD_VERSION_MISMATCH')
    if report['git_status'] or report['head']!=source_identity().commit:raise UpdateError('BUILD_COMMIT_MISMATCH')
    for name,digest in report['hashes'].items():
        if sha(ROOT/name)!=digest or sha(BUILD/'source'/name)!=digest:raise UpdateError('BUILD_INPUT_DRIFT: '+name)
    for artifact in report['artifacts']:
        p=Path(artifact['path'])
        if sha(p)!=artifact['sha256'] or p.stat().st_size!=artifact['bytes'] or file_version(p)!=VERSION+'.0':
            raise UpdateError('ARTIFACT_HASH_VERSION_MISMATCH')
    verify_identity((BUILD/'source/installer/TransComic.iss').read_text(encoding='utf8'))
    for scale,dpr in (('100',1.0),('150',1.5)):
        smoke=load(OUT/f'frozen-final-{scale}/report.json')
        if not (smoke['passed'] and smoke['frozen'] and smoke['version']==VERSION and abs(smoke['dpr']-dpr)<.01
                and smoke['safe_exit_verified'] and smoke['capcut']['passed'] and smoke['capcut']['outside_package_reads']==0
                and smoke['automation']['passed'] and smoke['automation']['native_tray_hide_background_restore']
                and smoke['migration']['status']=='PASS' and smoke['migration']['baseline_version']=='1.2.0'
                and smoke['reopen']['passed'] and smoke['reopen']['frozen'] and smoke['reopen']['autostart'] is False
                and smoke['real_http_requests']==smoke['installer_processes']==0):
            raise UpdateError('PACKAGED_SMOKE_INCOMPLETE')
    tts=load(OUT/'frozen-final-100/report.json')['tts']
    if tts['cached_cpu_load']!='PASS' or not tts['audio_wav'] or not tts['audio_mp3']:raise UpdateError('KOKORO_LOAD_NOT_VERIFIED')
    if load(OUT/'frozen-final-100/report.json')['automation']['kokoro']!='cached_CPU':raise UpdateError('AUTOMATION_CPU_NOT_VERIFIED')
    verify_kit(KIT,ROOT);inspect(ROOT)
    return report


def prepare():
    report=verify_build();FOLDER.mkdir(parents=True,exist_ok=True)
    for artifact in report['artifacts']:
        source=Path(artifact['path']);name=SCOPE.names[0] if source.name.endswith('devtest-windows-x64.exe') else source.name
        copy_exact(source,FOLDER/name)
    third=FOLDER/EXTRAS[0]
    if not third.exists():
        with zipfile.ZipFile(third,'x',zipfile.ZIP_DEFLATED,compresslevel=1) as packed:
            for p in sorted(KIT.rglob('*')):
                if p.is_file():packed.write(p,'ThirdParty/'+p.relative_to(KIT).as_posix())
    record=load(KIT/'manifest.json')
    with zipfile.ZipFile(third) as packed:
        if set(packed.namelist())!={'ThirdParty/'+n for n in record['files']}|{'ThirdParty/manifest.json'}:
            raise UpdateError('SOURCE_ZIP_INVENTORY_MISMATCH')
        for name,entry in record['files'].items():
            if hashlib.sha256(packed.read('ThirdParty/'+name)).hexdigest()!=entry['sha256']:raise UpdateError('SOURCE_ZIP_HASH_MISMATCH')
    stamp=load(OUT/'preparation.json')['created_at'] if (OUT/'preparation.json').exists() else datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    installer=FOLDER/SCOPE.names[0]
    raw=canonical(manifest(VERSION,installer.name,installer.stat().st_size,sha(installer),stamp))
    (FOLDER/'transcomic-update.json').write_bytes(raw)
    (FOLDER/'SHA256SUMS.txt').write_text(sha(installer)+'  '+installer.name+'\n'+sha(FOLDER/'transcomic-update.json')+'  transcomic-update.json\n',encoding='ascii')
    save(OUT/'preparation.json',dict(version=VERSION,created_at=stamp,installer_sha256=sha(installer),source_archive_sha256=sha(third)))
    print(json.dumps({'prepared':True,'installer':installer.name,'bytes':installer.stat().st_size,'sha256':sha(installer)}))


def verify_local(require_clean=True):
    report=verify_build()
    baseline=load(OUT/'baseline/baseline-offline.json')
    if not (baseline['passed'] and baseline['baseline_version']=='1.2.0' and baseline['candidate_version']==VERSION
            and baseline['installer_sha256']==sha(FOLDER/SCOPE.names[0])
            and baseline['native_installer_executions']==0):raise UpdateError('BASELINE_UPDATER_NOT_VERIFIED')
    if require_clean:source_identity();require_current_tests(SCOPE)
    for artifact in report['artifacts']:
        name=SCOPE.names[0] if artifact['path'].endswith('devtest-windows-x64.exe') else Path(artifact['path']).name
        if sha(FOLDER/name)!=artifact['sha256']:raise UpdateError('PUBLIC_BINARY_CHANGED')
    if not load(OUT/'baseline/baseline-offline.json')['passed']:raise UpdateError('BASELINE_UPDATER_NOT_VERIFIED')
    envelope=load(FOLDER/'transcomic-update.json')
    assets=[inspect_scoped_asset(SCOPE,n,FOLDER/n,ROOT) for n in NAMES]
    release={'tag_name':'v'+VERSION,'draft':False,'prerelease':False,'html_url':release_url('v'+VERSION),
             'published_at':'OFFLINE_VALIDATION_ONLY','assets':[{'name':a.name,'size':a.size,'state':'uploaded','browser_download_url':'https://github.com/Thnhphngz/TransComic-Releases/releases/download/v'+VERSION+'/'+a.name} for a in assets]}
    item=candidate(release,envelope);verify_checksums((FOLDER/'SHA256SUMS.txt').read_bytes(),item,(FOLDER/'transcomic-update.json').read_bytes())
    for path in (FOLDER/'build-manifest.json',FOLDER/'transcomic-update.json',FOLDER/'release-notes.md'):
        if SECRET.search(path.read_bytes()):raise UpdateError('PUBLIC_METADATA_SECRET')
    public=load(FOLDER/'build-manifest.json')
    if public['version']!=VERSION or public['source_hashes']!=report['hashes']:raise UpdateError('PUBLIC_BUILD_PROVENANCE_MISMATCH')
    if require_clean and public['source_commit']!=source_identity().commit:raise UpdateError('PUBLIC_COMMIT_MISMATCH')
    extra_sums=''.join(sha(FOLDER/n)+'  '+n+'\n' for n in EXTRAS[:2])
    if (FOLDER/'ThirdParty-SHA256SUMS.txt').read_text(encoding='ascii')!=extra_sums:raise UpdateError('SOURCE_CHECKSUMS_MISMATCH')
    return assets


def bind():
    source=source_identity();report=verify_build();SCOPE.out.mkdir(parents=True,exist_ok=True)
    if (SCOPE.out/'gates.json').exists():
        verify_local();return
    identity=build_identity(source,VERSION,{'Python':report['tools']['python']['version'],'PyInstaller':report['tools']['PyInstaller']['version']},sha(FOLDER/SCOPE.names[0]))
    notes=(ROOT/'docs/release-notes-2.0.0.md').read_text(encoding='utf8').rstrip()+'\n\nSource commit: `'+source.commit+'`.\n\n<!-- transcomic-build-id: '+identity['build_id']+' -->\n'
    (FOLDER/'release-notes.md').write_text(notes,encoding='utf8');(SCOPE.out/'release-notes.md').write_text(notes,encoding='utf8')
    public={'version':VERSION,'source_commit':source.commit,'build_parent_commit':report['head'],
            'source_tree_state':'clean_committed_canonical_build','source_hashes':report['hashes'],
            'version_overlay':False,'created_at':load(OUT/'preparation.json')['created_at'],
            'artifacts':[{'name':SCOPE.names[0] if a['path'].endswith('devtest-windows-x64.exe') else Path(a['path']).name,'size':a['bytes'],'sha256':a['sha256']} for a in report['artifacts']],
            'verification':{'frozen_dpr':[1.0,1.5],'kokoro_cached_cpu_wav_mp3':True,'portable_mau_external_media':True,
                            'automation_frozen_mock_CPU_MAU_tray':True,'v120_database_migration':True,
                            'trial_checkpoint_reopen_no_autostart':True,'full_regression_rerun':False,
                            'native_installer_executed':False,'second_machine_update':'AWAITING_USER'}}
    save(FOLDER/'build-manifest.json',public)
    (FOLDER/'ThirdParty-SHA256SUMS.txt').write_text(''.join(sha(FOLDER/n)+'  '+n+'\n' for n in EXTRAS[:2]),encoding='ascii')
    tests={}
    for label in ('focused',):
        name=label+'.xml';copy_exact(OUT/name,SCOPE.out/name);tests[name]=sha(SCOPE.out/name)
    review=inspect(ROOT)
    proof={'source_commit':source.commit,'source_dirty':False,'source_hashes':review['source_hashes'],'test_evidence':tests,
           'baseline_compatibility':True,'privacy_findings':[],'publication_notes_sha256':sha(SCOPE.out/'release-notes.md'),
           'version':VERSION,'gate_profile':'automation_smoke_200',
           'release_gates':gate_results(report),'build_id':identity['build_id']}
    save(SCOPE.out/'gates.json',proof);verify_local()
    save(OUT/'bound-identity.json',identity)
    print(json.dumps({'bound':True,'source_commit':source.commit,'build_id':identity['build_id']}))


def gate_results(report):
    """Evaluate the twelve requested gates from byte-bound local evidence."""
    smoke=load(OUT/'frozen-final-100/report.json');baseline=load(OUT/'baseline/baseline-offline.json')
    gates=dict(VERSION_SYNC=report['version']==report['source_version']==VERSION and not report['version_overlay'],
        SOURCE_PRESERVED=all(sha(ROOT/n)==h for n,h in report['hashes'].items()),
        INSTALLER_BUILD=all(sha(Path(a['path']))==a['sha256'] for a in report['artifacts']),
        FROZEN_STARTUP=smoke['passed'] and smoke['frozen'] and smoke['safe_exit_verified'],
        AUTOMATION_RESOURCES=smoke['automation']['passed'] and smoke['automation']['checkpoint'],
        KOKORO_DEPENDENCIES=smoke['tts']['cached_cpu_load']=='PASS' and smoke['automation']['kokoro']=='cached_CPU',
        MAU_EXPORT=smoke['capcut']['passed'] and smoke['capcut']['outside_package_reads']==0,
        SQLITE_120_MIGRATION=smoke['migration']['status']=='PASS' and smoke['reopen']['passed'],
        BASELINE_UPDATER=baseline['passed'] and baseline['baseline_version']=='1.2.0' and baseline['candidate_version']==VERSION,
        DATA_SECURITY=smoke['migration']['external_files_unchanged'] and smoke['reopen']['source_wav_projects_reports_unchanged']
            and smoke['real_http_requests']==smoke['installer_processes']==0,
        PUBLIC_PRIVACY=not any(SECRET.search((FOLDER/n).read_bytes()) for n in ('build-manifest.json','transcomic-update.json','release-notes.md')),
        INSTALLER_SHA256=sha(FOLDER/SCOPE.names[0])==baseline['installer_sha256'])
    if set(gates)!=set(PACKAGING_200_GATES) or not all(gates.values()):raise UpdateError('RELEASE_200_GATES_FAILED')
    return gates


class SixAssetPublisher(FirstReleasePublisher):
    """The v1.1.0 six-asset protocol, restricted to this v2.0.0 scope."""
    def __init__(self,commands):
        if commands.scope is not SCOPE:raise UpdateError('ONLY_REVIEWED_200_SCOPE')
        super().__init__(commands);self.downloaded={}
    def upload(self,version,release,assets):
        self._identity(version,release,True)
        if {a.name for a in assets}!=set(NAMES):raise UpdateError('SIX_ASSET_INVENTORY_REQUIRED')
        existing={a['name']:a for a in release['assets']}
        if len(existing)!=len(release['assets']) or not set(existing)<=set(NAMES):raise UpdateError('UNEXPECTED_REMOTE_ASSET')
        for asset in assets:
            if inspect_scoped_asset(SCOPE,asset.name,asset.path,ROOT)!=asset:raise UpdateError('LOCAL_ASSET_DRIFT')
            if asset.name in existing:
                remote=existing[asset.name]
                if (remote['size'],remote.get('digest'))!=(asset.size,'sha256:'+asset.sha256):raise UpdateError('EXISTING_ASSET_CONFLICT')
                continue
            endpoint=f'https://uploads.github.com/repos/{self.repository}/releases/{release["id"]}/assets?name={asset.name}'
            execute(self.commands,[str(self.gh),'api',endpoint,'--method','POST','-H','Content-Type: application/octet-stream','--input',str(asset.path)],ROOT,300)
    def verify(self,version,release,assets,published=False):
        self.commands.bind_release(release);self.check_tag(version,self.commands.distribution)
        self._identity(version,release,not published)
        if published and not release.get('published_at'):raise UpdateError('PUBLIC_TIMESTAMP_MISSING')
        expected={a.name:a for a in assets};remote={a['name']:a for a in release['assets']}
        if len(assets)!=6 or len(release['assets'])!=6 or set(expected)!=set(NAMES) or set(remote)!=set(NAMES):raise UpdateError('SIX_ASSET_INVENTORY_REQUIRED')
        protocol=dict(release,assets=[r for r in release['assets'] if r['name'] in SCOPE.names])
        shape=draft_validation_identity(protocol,SCOPE)
        shape=dict(shape,draft=False,published_at=shape.get('published_at') or 'PREPUBLICATION_VERIFICATION')
        item=candidate(shape,load(FOLDER/'transcomic-update.json'))
        verify_checksums((FOLDER/'SHA256SUMS.txt').read_bytes(),item,(FOLDER/'transcomic-update.json').read_bytes())
        for name,asset in expected.items():
            r=remote[name]
            if published and r.get('browser_download_url')!=asset_url(SCOPE.tag,name):raise UpdateError('PUBLIC_ASSET_URL_MISMATCH')
            if inspect_scoped_asset(SCOPE,name,asset.path,ROOT)!=asset or r.get('state')!='uploaded' or r['size']!=asset.size or r.get('digest')!='sha256:'+asset.sha256:
                raise UpdateError('REMOTE_ASSET_HASH_SIZE_MISMATCH')
            key=(r['id'],asset.size,asset.sha256)
            if key not in self.downloaded:
                raw=execute(self.commands,[str(self.gh),'api',f'repos/{self.repository}/releases/assets/{r["id"]}','-H','Accept: application/octet-stream'],ROOT,300,asset.size)
                if len(raw)!=asset.size or hashlib.sha256(raw).hexdigest()!=asset.sha256:raise UpdateError('REMOTE_DOWNLOADED_HASH_MISMATCH')
                self.downloaded[key]=True
        save(OUT/'verified-remote-assets.json',{'published':published,'assets':[{'name':a.name,'size':a.size,'sha256':a.sha256,'id':remote[a.name]['id']} for a in assets]})
        return True


def publish():
    assets=verify_local();source=source_identity();identity=load(OUT/'bound-identity.json')
    gh=shutil.which('gh');notes=(SCOPE.out/'release-notes.md').read_text(encoding='utf8')
    commands=FirstReleaseCommands(gh,source.commit,source.commit,identity['build_id'],notes,assets,scope=SCOPE)
    publisher=SixAssetPublisher(commands)
    operations=FirstReleaseOperations(source,publisher,assets,identity['build_id'],local_checker=verify_local)
    try:
        result=ReleaseCoordinator(ReleaseJournal(SCOPE.out/'publication-journal.json'))._execute(operations,
            current='1.2.0',choice=VERSION,build_id=identity['build_id'],distribution_commit=source.commit)
        save(OUT/'publication-result.json',result);print(json.dumps({'state':result['state'],'version':result['version'],'source_commit':source.commit}))
    finally:save(OUT/'publication-command-events.json',commands.events)


if __name__=='__main__':
    parser=argparse.ArgumentParser(allow_abbrev=False);group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--bind',action='store_true');group.add_argument('--publish',action='store_true')
    args=parser.parse_args()
    if args.prepare:prepare()
    elif args.bind:bind()
    else:publish()
