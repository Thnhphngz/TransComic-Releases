"""Read-only RC evidence. Never build, install, sign, publish or load user data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def records(root=ROOT):
    from transcomic.tts.catalog import ASSETS,REVISION,REPOSITORY
    lock=json.loads((root/'transcomic/tts/setup-catalog.json').read_text(encoding='utf8'))
    rows=[dict(r,category='runtime') for r in [lock['python'],*lock['artifacts']]]
    rows += [dict(name=n,asset_name=n,category='model',version=REVISION,size=r['size'],sha256=r['sha256'],license='Apache-2.0',kind='raw',group='model',url=f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{n}') for n,r in ASSETS.items()]
    return lock,rows


def validate(rows):
    from packaging.tags import cpython_tags,compatible_tags
    from packaging.utils import parse_wheel_filename
    supported=set(cpython_tags((3,13),platforms=['win_amd64']))|set(compatible_tags((3,13),interpreter='cp313',platforms=['win_amd64']))
    seen=set()
    for r in rows:
        key=(r['category'],r['name'])
        if key in seen:raise ValueError('Duplicate artifact')
        seen.add(key)
        url=urlsplit(r['url'])
        if url.scheme!='https' or url.hostname not in ('files.pythonhosted.org','www.python.org','huggingface.co') or url.username or url.password or url.query:raise ValueError('Untrusted or credential-bearing URL')
        if not re.fullmatch('[0-9a-f]{64}',r['sha256']) or type(r['size']) is not int or r['size']<=0 or not r.get('version') or not r.get('license'):raise ValueError('Unpinned artifact')
        if r['kind']=='wheel' and not (parse_wheel_filename(Path(url.path).name)[3]&supported):raise ValueError('Incompatible Windows x64 / CP313 artifact')
        if r['kind']=='sdist' and r['name'] not in ('jieba','unidic-lite'):raise ValueError('Unreviewed source package')
        if r.get('metadata_url') is not None and r['metadata_url']!=f"https://pypi.org/pypi/{r['name']}/{r['version']}/json":raise ValueError('Untrusted registry metadata URL')
    profiles={r['name']:r.get('group') for r in rows}
    if profiles.get('onnxruntime')!='cpu' or profiles.get('onnxruntime-gpu')!='cuda':raise ValueError('ORT profiles must remain exclusive')


def cache_check(record,runtime_caches,model_caches):
    from transcomic.tts.catalog import REVISION
    candidates=[p/record['sha256'] for p in runtime_caches] if record['category']=='runtime' else [p/REVISION/record['asset_name'] for p in model_caches]
    for path in candidates:
        if not path.is_file():continue
        if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('Reparse cache asset rejected')
        if path.stat().st_size==record['size'] and sha(path)==record['sha256']:return dict(status='VERIFIED',path=str(path))
    return dict(status='NOT_CACHED',downloaded=False)


def remote_check(record,client):
    import httpx
    result=dict(reachable=False,source_metadata_match=None,downloaded_payload=False)
    try:
        response=client.head(record['url'],follow_redirects=True);response.raise_for_status()
        if any(r.url.scheme!='https' for r in [*response.history,response]):raise ValueError('Non-HTTPS redirect')
        length=response.headers.get('content-length')
        result.update(reachable=True,http_status=response.status_code,final_host=response.url.host,content_length=int(length) if length and length.isdigit() else None)
        if record.get('metadata_url'):
            data=client.get(record['metadata_url']);data.raise_for_status()
            result['source_metadata_match']=any(r['url']==record['url'] and r['size']==record['size'] and r['digests']['sha256']==record['sha256'] and not r.get('yanked') for r in data.json()['urls'])
    except (httpx.HTTPError,ValueError,KeyError) as exc:result['error']=type(exc).__name__+': '+str(exc).split('?')[0][:240]
    return result


def gate(checks):
    """Evidence not reviewed/passed cannot silently authorize the one build."""
    return 'PASS' if checks and all(v=='PASS' for v in checks.values()) else 'BLOCKED — DO NOT RELEASE'


def package_inventory():
    result=[]
    for line in (ROOT/'requirements-release.lock').read_text().splitlines():
        if not line or line.startswith('#'):continue
        name,version=line.split('==',1)
        try:
            d=metadata.distribution(name);m=d.metadata
            license_files=[p for p in d.files or [] if p.name.upper().startswith(('LICENSE','COPYING','NOTICE')) and '.dist-info' in str(p)]
            result.append(dict(name=name,target=version,installed=d.version,license=m.get('License-Expression') or m.get('License') or [v for v in m.get_all('Classifier',[]) if v.startswith('License ::')],notices=[dict(name=str(p),sha256=sha(Path(d.locate_file(p)))) for p in license_files if Path(d.locate_file(p)).is_file()]))
        except metadata.PackageNotFoundError:result.append(dict(name=name,target=version,installed=None,status='MISSING_IN_DEVELOPMENT_PROFILE'))
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--network',action='store_true');p.add_argument('--runtime-cache',action='append',default=[]);p.add_argument('--model-cache',action='append',default=[]);args=p.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True);lock,rows=records();validate(rows)
    for row in rows:row['cache']=cache_check(row,[Path(p) for p in args.runtime_cache],[Path(p) for p in args.model_cache])
    if args.network:
        import httpx
        with httpx.Client(timeout=30,trust_env=False,limits=httpx.Limits(max_connections=4)) as client:
            with ThreadPoolExecutor(max_workers=4) as pool:
                for row,result in zip(rows,pool.map(lambda r:remote_check(r,client),rows)):row['remote']=result
            (out/'remote-rows.json').write_text(json.dumps(rows,ensure_ascii=True,indent=2),encoding='utf8')
            # Model size/LFS SHA comes from the pinned repository revision.
            from transcomic.tts.catalog import REVISION,REPOSITORY
            response=client.get(f'https://huggingface.co/api/models/{REPOSITORY}/revision/{REVISION}',params=dict(blobs='true'));response.raise_for_status();tree={r['rfilename']:r for r in response.json()['siblings']}
            for row in rows:
                if row['category']=='model':
                    item=tree.get(row['asset_name'],{});row['remote']['source_metadata_match']=item.get('size')==row['size'] and item.get('lfs',{}).get('sha256')==row['sha256']
            python=lock['python'];response=client.get('https://www.python.org/downloads/release/python-31314/');response.raise_for_status()
            section=next((s for s in response.text.split('</tr>') if python['url'] in s),'');text=re.sub('<[^>]+>','',section)
            rows[0]['remote']['source_metadata_match']=python['sha256'] in text
    report=dict(count=len(rows),runtime_count=sum(r['category']=='runtime' for r in rows),model_count=sum(r['category']=='model' for r in rows),target=lock['platform'],catalog_sha256=sha(ROOT/'transcomic/tts/setup-catalog.json'),cached_verified=sum(r['cache']['status']=='VERIFIED' for r in rows),remote_checked=args.network,remote_reachable=sum(r.get('remote',{}).get('reachable',False) for r in rows),remote_metadata_matches=sum(r.get('remote',{}).get('source_metadata_match') is True for r in rows),artifacts=rows)
    (out/'artifacts.json').write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8');(out/'package-licenses.json').write_text(json.dumps(package_inventory(),ensure_ascii=True,indent=2),encoding='utf8')
    print(json.dumps({k:report[k] for k in ('count','runtime_count','model_count','target','cached_verified','remote_reachable','remote_metadata_matches')}));return 0 if (not args.network or report['remote_reachable']==len(rows)==report['remote_metadata_matches']) else 2


if __name__=='__main__':raise SystemExit(main())
