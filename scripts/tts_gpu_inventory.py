"""Read-only pinned DLL/metadata audit; never installs or builds an executable."""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    from scripts.tts_packaging import audit
    names=('onnxruntime-gpu','nvidia-cublas-cu12','nvidia-cuda-runtime-cu12','nvidia-cuda-nvrtc-cu12','nvidia-cudnn-cu12','nvidia-cufft-cu12','nvidia-curand-cu12','nvidia-nvjitlink-cu12')
    result=dict(runtime=audit(),packages={},dlls=[],license_gate='PARTIAL; inventory is not a redistribution approval',strategy='A: bundle exclusive GPU ORT plus pinned runtime DLLs, retaining CPU EP offline; no driver, pip, System32 writes on end-user PC',clean_windows='NOT VERIFIED')
    for name in names:
        distribution=metadata.distribution(name);files=list(distribution.files or [])
        result['packages'][name]=dict(version=distribution.version,license_files=[str(p) for p in files if any(token in str(p).lower() for token in ('license','copying','notice'))])
        for file in files:
            if Path(file).suffix.lower()!='.dll':continue
            path=distribution.locate_file(file);sha=hashlib.sha256()
            with path.open('rb') as source:
                for block in iter(lambda:source.read(1024**2),b''):sha.update(block)
            result['dlls'].append(dict(package=name,path=str(file),bytes=path.stat().st_size,sha256=sha.hexdigest()))
    result['dll_bytes']=sum(i['bytes'] for i in result['dlls']);output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(result['dll_bytes']);return 0


if __name__=='__main__':raise SystemExit(main())
