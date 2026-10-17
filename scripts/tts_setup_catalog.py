"""Build-time only: pin official Windows artifacts; never invoked by the GUI."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import httpx
from packaging.tags import Tag,cpython_tags,compatible_tags
from packaging.utils import parse_wheel_filename

BASE={'kokoro-onnx':'0.6.1','numpy':'2.5.1','soundfile':'0.14.0','lameenc':'1.9.0','phonemizer':'3.4.0','espeakng-loader':'0.2.4','misaki':'0.7.4','fugashi':'1.5.2','unidic-lite':'1.0.8','jaconv':'0.5.0','jieba':'0.42.1','pypinyin':'0.55.0','cn2an':'0.5.24','ordered-set':'4.1.0','regex':'2026.9.29','attrs':'26.1.0','joblib':'1.6.0','dlinfo':'2.0.0','typing-extensions':'4.16.0','cffi':'2.1.1','pycparser':'3.11','flatbuffers':'25.12.19','packaging':'26.3','protobuf':'7.36.2','sympy':'1.14.0','mpmath':'1.3.0','proces':'0.1.7','setuptools':'84.0.0'}
CUDA={'onnxruntime-gpu':'1.24.4','nvidia-cublas-cu12':'12.9.2.10','nvidia-cuda-runtime-cu12':'12.9.79','nvidia-cuda-nvrtc-cu12':'12.9.86','nvidia-cudnn-cu12':'9.27.0.42','nvidia-cufft-cu12':'11.4.1.4','nvidia-curand-cu12':'10.3.10.19','nvidia-nvjitlink-cu12':'12.9.86'}
BASE['cloudpickle']='3.1.2'
LICENSE_FALLBACK={'kokoro-onnx':'MIT (upstream LICENSE)','espeakng-loader':'REVIEW_REQUIRED: wrapper metadata missing; bundled eSpeak NG GPL-3.0 corresponding source required','nvidia-cudnn-cu12':'LicenseRef-NVIDIA-cuDNN; upstream EULA applies'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    tags=list(cpython_tags((3,13),platforms=['win_amd64']))+list(compatible_tags((3,13),interpreter='cp313',platforms=['win_amd64']))
    with httpx.Client(timeout=90,follow_redirects=True,trust_env=False) as client:
        records=[]
        for name,version in {**BASE,**CUDA,'onnxruntime':'1.24.4'}.items():
            response=client.get(f'https://pypi.org/pypi/{name}/{version}/json');response.raise_for_status();data=response.json();candidates=[]
            for item in data['urls']:
                if item['yanked']:continue
                if item['filename'].endswith('.whl'):
                    wheel_tags=parse_wheel_filename(item['filename'])[3];ranks=[tags.index(t) for t in wheel_tags if t in tags]
                    if ranks:candidates.append((min(ranks),item,'wheel'))
                elif name in ('jieba','unidic-lite') and item['filename'].endswith('.tar.gz'):candidates.append((10000,item,'sdist'))
            if not candidates:raise RuntimeError('No reviewed Windows artifact: '+name)
            _,item,kind=min(candidates,key=lambda x:x[0]);info=data['info']
            records.append(dict(name=name,version=version,url=item['url'],size=item['size'],sha256=item['digests']['sha256'],kind=kind,package=name.replace('-','_') if kind=='sdist' else None,license=info.get('license_expression') or info.get('license') or '; '.join(c for c in info.get('classifiers',[]) if c.startswith('License ::')) or LICENSE_FALLBACK.get(name,'REVIEW_REQUIRED'),metadata_url=f'https://pypi.org/pypi/{name}/{version}/json',group='cuda' if name in CUDA else 'cpu' if name=='onnxruntime' else 'base'))
        version='3.13.14';url=f'https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip'
        page=client.get('https://www.python.org/downloads/release/python-31314/');page.raise_for_status()
        row=next(row for row in page.text.split('</tr>') if url in row)
        code=re.search(r'<code[^>]*>(.*?)</code>',row,re.S);sha=re.sub('<[^>]+>','',code[1]).strip() if code else ''
        if not re.fullmatch('[0-9a-f]{64}',sha):raise RuntimeError('Official Python SHA256 missing')
        response=client.get(url);response.raise_for_status();payload=response.content
        assert hashlib.sha256(payload).hexdigest()==sha
        python=dict(name='python-embedded',version=version,url=url,size=len(payload),sha256=sha,kind='python',license='PSF-2.0',group='base')
        lock=dict(schema=1,platform='win_amd64',python=python,artifacts=records,policy='Official upstream direct downloads; pinned hashes; no pip or setup.py at runtime')
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(lock,indent=2),encoding='utf8')
        print(json.dumps({'artifacts':len(records),'cpu_bytes':sum(r['size'] for r in records if r['group']!='cuda')+python['size'],'cuda_bytes':sum(r['size'] for r in records if r['group']!='cpu')+python['size'],'python':python}))

if __name__=='__main__':main()
