"""Read-only packaging/readiness audit. Never builds, installs or publishes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
    from transcomic.version import VERSION,RELEASE_REPOSITORY
    from transcomic.tts.managed_runtime import catalog,WORKER_FILES,nvidia_device
    from scripts.tts_packaging import audit
    from transcomic.tts.catalog import ASSETS,REVISION,REPOSITORY
    root=Path(__file__).resolve().parents[1];lock=catalog();audit_result=audit()
    artifacts=[lock['python'],*lock['artifacts']]
    for name,info in ASSETS.items():artifacts.append(dict(name=name,version=REVISION,size=info['size'],sha256=info['sha256'],url=f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}',license='Apache-2.0',group='model',kind='raw'))
    report=dict(version=VERSION,repository=RELEASE_REPOSITORY,status='PARTIAL',build='BLOCKED: explicit BUILD_LOCAL authorization required by existing spec/Inno gates',clean_windows='PARTIAL: no frozen clean-machine test in this audit',license='PARTIAL: eSpeak binary/source provenance, GPL/LGPL distribution obligations and final NVIDIA/Qt notices require release review',base_build_profile='CPU ORT only; CUDA isolated in app-managed embedded runtime',development_runtime=audit_result,hardware=nvidia_device(),architecture=platform.machine(),catalog_sha256=hashlib.sha256((root/'transcomic/tts/setup-catalog.json').read_bytes()).hexdigest(),worker_sources={n:hashlib.sha256((root/'transcomic/tts'/n).read_bytes()).hexdigest() for n in WORKER_FILES},artifacts=artifacts)
    for a in artifacts:
        if not a['url'].startswith('https://') or len(a['sha256'])!=64 or a['size']<=0:raise ValueError('Unpinned release artifact')
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8');print(json.dumps({k:report[k] for k in ('version','status','build','clean_windows','base_build_profile')}))

if __name__=='__main__':main()
