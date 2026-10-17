"""Prepare local source/notices media from versioned upstream sources.

No executable is built, installed or published. The resulting manifest records
resolved source commits and hashes; build_local verifies every included file.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import sys
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    import httpx
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=out/'sources';sources.mkdir(exist_ok=True)
    rows=[]
    prior=json.loads((out/'source-provenance.json').read_text()) if (out/'source-provenance.json').is_file() else []
    with httpx.Client(timeout=180,follow_redirects=True,trust_env=False) as client:
        def fetch(name,url,sha=None):
            dest=sources/name
            if not dest.exists():
                part=dest.with_suffix(dest.suffix+'.part')
                with client.stream('GET',url) as response,part.open('wb') as stream:
                    response.raise_for_status()
                    for data in response.iter_bytes(1024**2):stream.write(data)
                part.rename(dest)
            with dest.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if sha and actual!=sha:raise ValueError('Upstream checksum mismatch '+name)
            return dict(file='sources/'+name,url=url,sha256=actual,bytes=dest.stat().st_size)
        def github(name,repo,ref):
            cached=next((r for r in prior if r.get('component')==name and r.get('ref')==ref),None)
            if cached:
                if cached.get('source_only'):
                    data=out/cached['file']
                    if hashlib.sha256(data.read_bytes()).hexdigest()!=cached['sha256']:raise ValueError('Source media changed')
                else:fetch(name+'.tar.gz',cached['url'],cached['sha256'])
                return cached
            response=client.get(f'https://api.github.com/repos/{repo}/commits/{ref}')
            if response.status_code==403:
                import subprocess
                refs=subprocess.check_output(['git','ls-remote','https://github.com/'+repo+'.git','refs/tags/'+ref,'refs/tags/'+ref+'^{}'],text=True).splitlines()
                if not refs:raise ValueError('Cannot resolve pinned source tag')
                commit=refs[-1].split()[0]
            else:response.raise_for_status();commit=response.json()['sha']
            return dict(fetch(name+'.tar.gz',f'https://codeload.github.com/{repo}/tar.gz/{commit}'),component=name,commit=commit,ref=ref)
        projects=[(n,'qt/'+n,'v6.11.1') for n in ('qtbase','qtdeclarative','qtmultimedia','qtsvg','qtimageformats','qtshadertools','qt5')]
        projects += [('pyside','qtproject/pyside-pyside-setup','v6.11.1'),
          ('ffmpeg','FFmpeg/FFmpeg','n7.1.3'),
          ('espeak','espeak-ng/espeak-ng','685480238072018edfc0e4f3d85e131c278c2ccf'),
          ('espeak-loader','thewh1teagle/espeakng-loader','9ec68e20d173ff4c795b970f54324fbeae9cea8d'),
          ('espeak-wrapper','thewh1teagle/espeakng-loader','0ddc87adf77e5850d7eeb542ac8a87d421b64daa'),
          ('lameenc','chrisstaite/lameenc','v1.9.0'),
          ('soundfile','bastibe/python-soundfile','0.14.0'),
          ('sndfile-build','bastibe/libsndfile-binaries','a3e6f9769d0c7e91d2d036cf0fdbe5b4bbf18b87'),
          ('libsndfile','libsndfile/libsndfile','1.2.2')]
        with ThreadPoolExecutor(max_workers=3) as pool:
            for row in pool.map(lambda p:github(*p),projects):rows.append(row);print(row['component'],row['bytes'],flush=True)
        # This build-script repository also stores unrelated prebuilt platform
        # libraries. Deliver its source/scripts, not those extra native objects.
        row=next(r for r in rows if r['component']=='sndfile-build')
        if not row.get('source_only'):
            original=out/row['file'];target=sources/'sndfile-build-source-only.tar.gz'
            with tarfile.open(original) as src,tarfile.open(target,'w:gz') as dst:
                for member in src:
                    if not member.isfile():continue
                    if any(s in member.name.lower() for s in ('.dll','.dylib','.so','.exe','.pyd')):continue
                    dst.addfile(member,src.extractfile(member))
            cache=out.parent/'upstream-source-downloads';cache.mkdir(exist_ok=True)
            saved=cache/(row['sha256']+'.tar.gz')
            if saved.exists():raise ValueError('Original source cache already exists; preserve both')
            original.rename(saved)
            row.update(source_only=True,upstream_sha256=row['sha256'],file=target.relative_to(out).as_posix(),
                       sha256=hashlib.sha256(target.read_bytes()).hexdigest(),bytes=target.stat().st_size)
        for package,version in [('phonemizer','3.4.0'),('certifi','2026.7.22')]:
            response=client.get(f'https://pypi.org/pypi/{package}/{version}/json');response.raise_for_status()
            source=next(r for r in response.json()['urls'] if r['packagetype']=='sdist')
            rows.append(dict(fetch(Path(source['url']).name,source['url'],source['digests']['sha256']),component=package))
        # Exact LAME source and patches specified by the pinned wrapper build.
        rows.append(dict(fetch('lame-4.0.tar.gz','https://downloads.sourceforge.net/project/lame/lame/4.0/lame-4.0.tar.gz',
          '3df5124d5ad3a98312ffd7ba6a9b36230e4f8a3e66d3ce0f425e336c32d216eb'),component='lame'))
        for name,url in [
          ('zlib','https://zlib.net/fossils/zlib-1.3.1.tar.gz'),
          ('ogg','https://downloads.xiph.org/releases/ogg/libogg-1.3.5.tar.gz'),
          ('vorbis','https://downloads.xiph.org/releases/vorbis/libvorbis-1.3.7.tar.gz'),
          ('flac','https://downloads.xiph.org/releases/flac/flac-1.4.3.tar.xz'),
          ('opus','https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz'),
          ('sndfile-lame','https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz'),
          ('mpg123','https://downloads.sourceforge.net/project/mpg123/mpg123/1.32.9/mpg123-1.32.9.tar.bz2')]:
            rows.append(dict(fetch(name+'-'+url.rsplit('/',1)[1],url),component=name))
        for name,url in [
          ('Microsoft-Python-conditions.txt','https://raw.githubusercontent.com/python/cpython/v3.13.14/PC/crtlicense.txt'),
          ('NVIDIA-CUDA-12.9.1.html','https://docs.nvidia.com/cuda/archive/12.9.1/eula/index.html'),
          ('NVIDIA-cuDNN-9.27.html','https://docs.nvidia.com/deeplearning/cudnn/backend/v9.27.0/reference/eula.html')]:
            rows.append(dict(fetch(name,url),component='terms'))
        rows.append(dict(fetch('Kokoro-model-card.md','https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/raw/1939ad2a8e416c0acfeecc08a694d14ef25f2231/README.md'),component='model-notice'))
    notices=out/'notices';notices.mkdir(exist_ok=True)
    for name in ('Microsoft-Python-conditions.txt','NVIDIA-CUDA-12.9.1.html','NVIDIA-cuDNN-9.27.html'):
        shutil.copyfile(sources/name,notices/name)
    for line in (ROOT/'requirements-release.lock').read_text().splitlines():
        if not line or line.startswith('#'):continue
        name=line.split('==')[0];dist=metadata.distribution(name)
        for file in dist.files or []:
            if file.name.upper().startswith(('LICENSE','LICENCE','COPYING','NOTICE','AUTHORS')):
                src=Path(dist.locate_file(file))
                if src.is_file():
                    target=notices/name/str(file);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
    # Make library/component notices readable without first unpacking sources.
    notice_index=[]
    for row in rows:
        archive=out/row['file']
        if not tarfile.is_tarfile(archive):continue
        with tarfile.open(archive) as packed:
            count=0
            for member in packed:
                name=Path(member.name).name;upper=name.upper()
                if not member.isfile() or member.size>2*1024**2:continue
                if not ('LICENSES/' in member.name or upper.startswith(('LICENSE','LICENCE','COPYING','COPYRIGHT','NOTICE','AUTHORS')) or name=='qt_attribution.json'):continue
                count+=1;target=notices/'upstream'/row['component']/(str(count)+'-'+name)
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(packed.extractfile(member).read())
                notice_index.append(dict(source=row['file'],member=member.name,notice=target.relative_to(out).as_posix()))
    (out/'upstream-notice-index.json').write_text(json.dumps(notice_index,indent=2),encoding='utf8')
    from transcomic.tts.managed_runtime import WORKER_FILES
    worker=out/'worker';worker.mkdir(exist_ok=True)
    for name in WORKER_FILES:shutil.copyfile(ROOT/'transcomic/tts'/name,worker/name)
    from transcomic.tts.managed_engine import WORKER_BOOTSTRAP
    (worker/'windows_bootstrap.py').write_bytes(WORKER_BOOTSTRAP.encode('utf8'))
    for name in ('setup-catalog.json','calibration.json'):shutil.copyfile(ROOT/'transcomic/tts'/name,worker/name)
    for name in ('tts-licenses.md','tts-third-party-notices.md','windows-distribution-rights.md'):
        shutil.copyfile(ROOT/'docs'/name,out/name)
    for name in ('native-build-details.json','libsndfile-source-evidence.json','espeak-data-comparison.json'):
        shutil.copyfile(out.parent/name,out/name)
    port=out/'vcpkg-mpg123';port.mkdir(exist_ok=True)
    for p in (out.parent/'vcpkg-1.32.9-1').iterdir():shutil.copyfile(p,port/p.name)
    # The vcpkg patchset hash in the shipped DLL is reproducibly identified.
    import re
    portfile=(port/'portfile.cmake').read_text()
    archive_hash=re.search(r'SHA512\s+([0-9a-f]{128})',portfile)[1]
    patchnames=re.findall(r'([\w.-]+\.(?:patch|diff))',re.search(r'PATCHES(.*?)\)',portfile,re.S)[1])
    patchset=hashlib.sha512((archive_hash+''.join(hashlib.sha512((port/n).read_bytes()).hexdigest() for n in patchnames)).encode()).hexdigest()[:10]
    if patchset!='66150af195':raise ValueError('mpg123 source does not match native patchset')
    mpg=next(r for r in rows if r.get('component')=='mpg123')
    if hashlib.sha512((out/mpg['file']).read_bytes()).hexdigest()!=archive_hash:raise ValueError('mpg123 upstream source hash mismatch')
    # Embedded Python's original license also covers its incorporated libraries.
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copyfile(python_license,notices/'Python-LICENSE.txt')
    (out/'source-provenance.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
    components=sorted({r['component'] for r in rows}|{'worker','notices','replacement'})
    files={}
    for p in sorted(out.rglob('*')):
        if not p.is_file() or p.name=='manifest.json':continue
        with p.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        files[p.relative_to(out).as_posix()]=dict(bytes=p.stat().st_size,sha256=sha)
    lock_sha=hashlib.sha256((ROOT/'requirements-release.lock').read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(dict(schema=1,components=components,files=files,release_lock_sha256=lock_sha),indent=2),encoding='utf8')
    from scripts.distribution_kit import verify_kit
    print(json.dumps(verify_kit(out,ROOT),indent=2))


if __name__=='__main__':main()
