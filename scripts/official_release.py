"""Conditional v1.0.0 entry; reuse the existing scoped publisher and journal."""
import hashlib,json,shutil
from pathlib import Path
from transcomic.version import VERSION,APP_ID
from transcomic.release_journal import ReleaseJournal,ReleaseState
from transcomic.update.internal import candidate,verify_checksums
from transcomic.update.metadata import canonical,asset_url,release_url,UpdateError
from scripts.release_environment import file_version,pe_architecture
from scripts.first_internal_release import (ROOT,REPO,OFFICIAL_SCOPE,FIRST_SCOPE,FirstReleaseCommands,
    FirstReleasePublisher,FirstReleaseOperations,FirstReleaseCoordinator,require_current_tests,source_identity,
    sha,load,safe_path)

OUT=OFFICIAL_SCOPE.out
RELEASE=ROOT/'releases/1.0.0'
GATE_NAMES=('SOURCE_REVIEW_PASS','BUILD_1_0_0_PASS','TXT_DOCX_PASS','BULK_TRANSLATION_PASS',
    'KIRA_GEMINI_VALIDATION_PASS','GUI_SMOKE_PASS','REGRESSION_PASS','SAFE_EXIT_PASS',
    'APPID_VERSION_COMPATIBILITY_PASS','BASELINE_0_1_1_UPDATE_COMPATIBILITY_PASS',
    'MANIFEST_SHA256_PASS','SECRETS_PRIVACY_SCAN_PASS','RELEASE_PIPELINE_PREFLIGHT_PASS')

def local_gates(require_clean=True):
    if VERSION!='1.0.0' or APP_ID!='TransComic.Desktop':raise UpdateError('OFFICIAL_VERSION_IDENTITY_REQUIRED')
    source=source_identity() if require_clean else None
    report=load(OUT/'build/build-report.json')
    if report['version']!='1.0.0' or report['source_version']!='1.0.0' or report['version_overlay']:
        raise UpdateError('OFFICIAL_BUILD_VERSION_MISMATCH')
    if source is not None and report['head']!=source.commit:raise UpdateError('BUILD_SOURCE_COMMIT_CHANGED')
    for name,digest in report['hashes'].items():
        if sha(safe_path(ROOT/name,ROOT))!=digest or sha(OUT/'build/source'/name)!=digest:
            raise UpdateError('OFFICIAL_BUILD_SOURCE_DRIFT: '+name)
    for item in report['artifacts']:
        original=safe_path(item['path'],ROOT);flat=RELEASE/original.name
        if sha(original)!=item['sha256'] or sha(flat)!=item['sha256'] or file_version(flat)!='1.0.0.0':
            raise UpdateError('OFFICIAL_ARTIFACT_CHANGED')
        if flat.name in ('TransComic.exe','TransComic-UpdateHelper.exe') and pe_architecture(flat)!='x64':
            raise UpdateError('X64_APP_HELPER_REQUIRED')
    iss=(OUT/'build/source/installer/TransComic.iss').read_text(encoding='utf8')
    for required in ('AppId={{CB58C770-47B7-42DC-A2CA-409DDF456487}',
        'DefaultDirName={localappdata}\\Programs\\{#MyAppName}','PrivilegesRequired=lowest',
        'AppMutex=TransComic.Desktop.Running','ArchitecturesInstallIn64BitMode=x64compatible'):
        if required not in iss:raise UpdateError('INSTALLER_IDENTITY_DRIFT')
    if '[UninstallDelete]' in iss:raise UpdateError('USER_DATA_DELETE_POLICY_REJECTED')
    allowed=set(OFFICIAL_SCOPE.names)|{'TransComic.exe','TransComic-UpdateHelper.exe','release-notes.md','build-manifest.json'}
    if {p.name for p in RELEASE.iterdir()}!=allowed:raise UpdateError('OFFICIAL_RELEASE_FOLDER_INVENTORY_MISMATCH')
    assets=[__import__('transcomic.release_adapters',fromlist=['Asset']).Asset.inspect(n,RELEASE/n,RELEASE) for n in OFFICIAL_SCOPE.names]
    envelope=load(RELEASE/'transcomic-update.json')
    fixture={'tag_name':'v1.0.0','draft':False,'prerelease':False,'html_url':release_url('v1.0.0'),
        'published_at':'OFFLINE_COMPATIBILITY_ONLY','body':'Offline schema verification',
        'assets':[{'name':a.name,'size':a.size,'state':'uploaded','browser_download_url':asset_url('v1.0.0',a.name)} for a in assets]}
    item=candidate(fixture,envelope)
    verify_checksums((RELEASE/'SHA256SUMS.txt').read_bytes(),item,(RELEASE/'transcomic-update.json').read_bytes())
    if (item.sha256,item.size)!=(assets[0].sha256,assets[0].size):raise UpdateError('MANIFEST_BINDING_FAILED')
    return assets,report

def preflight():
    assets,report=local_gates();proof=require_current_tests(OFFICIAL_SCOPE)
    if proof.get('version')!='1.0.0':raise UpdateError('FIXED_OFFICIAL_VERSION_REQUIRED')
    for provider in ('kira','gemini'):
        live=load(OUT/(provider+'-live.json'))
        if not live['success'] or live['posts']!=1 or live['synthetic_lines']!=3:
            raise UpdateError('LIVE_PROVIDER_VALIDATION_BLOCKED')
    if sha(OUT/'release-notes.md')!=sha(RELEASE/'release-notes.md'):
        raise UpdateError('RELEASE_NOTES_CHANGED')
    return assets,report,proof

def verify_previous(record):
    if record['version']!='0.1.1' or record['state']!=ReleaseState.PUBLISHED:
        raise UpdateError('PREVIOUS_PUBLISHED_RELEASE_REQUIRED')
    assets=[__import__('transcomic.release_adapters',fromlist=['Asset']).Asset.inspect(n,d['path'],ROOT)
            for n,d in record['asset_inventory'].items()]
    for asset in assets:
        expected=record['asset_inventory'][asset.name]
        if (asset.sha256,asset.size)!=(expected['sha256'],expected['size']):raise UpdateError('PREVIOUS_LOCAL_ASSET_CHANGED')
    notes=(FIRST_SCOPE.out/'release-notes.md').read_text(encoding='utf8').rstrip()+'\n\n<!-- transcomic-build-id: '+record['build_id']+' -->\n'
    commands=FirstReleaseCommands(shutil.which('gh'),source_identity().commit,record['distribution_commit'],
        record['build_id'],notes,assets,read_only=True)
    publisher=FirstReleasePublisher(commands);remote=publisher.read('0.1.1')
    if remote is None:raise UpdateError('PREVIOUS_REMOTE_RELEASE_MISSING')
    publisher.verify('0.1.1',remote,assets,published=True)
    (OUT/'previous-release-verified.json').write_text(json.dumps(remote,indent=2),encoding='utf8')
    return {'tag':'v0.1.1','build_id':record['build_id'],'assets_verified':True,'published':True,'draft':False}

def main():
    assets,report,proof=preflight();source=source_identity()
    build_id=hashlib.sha256(canonical({'source_commit':source.commit,'assets':{a.name:a.sha256 for a in assets}})).hexdigest()
    notes=(OUT/'release-notes.md').read_text(encoding='utf8').rstrip()+'\n\n<!-- transcomic-build-id: '+build_id+' -->\n'
    commands=FirstReleaseCommands(shutil.which('gh'),source.commit,proof['distribution_commit'],build_id,
        notes,assets,scope=OFFICIAL_SCOPE)
    publisher=FirstReleasePublisher(commands)
    operations=FirstReleaseOperations(source,publisher,assets,build_id,local_checker=local_gates,previous_verifier=verify_previous)
    try:
        journal=ReleaseJournal(safe_path(ROOT/'.release-state/journal.json',ROOT))
        record=FirstReleaseCoordinator(journal).run(operations)
        (OUT/'published-journal.json').write_text(json.dumps(record,indent=2),encoding='utf8')
    finally:
        (OUT/'command-events.json').write_text(json.dumps(commands.events,indent=2),encoding='utf8')
    print('v1.0.0 publication reconciled; independent baseline/anonymous verification required.')
    return 0
