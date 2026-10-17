"""Resource gates and hardware-specific measured choices; default is one."""
import hashlib
import json
import subprocess
import sys
import functools
from pathlib import Path


@functools.lru_cache(maxsize=1)
def gpu_identity():
    try:return subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'],text=True,timeout=4,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).strip()
    except (OSError,subprocess.SubprocessError):return 'no-nvidia'


def fingerprint(config):
    import importlib.metadata as metadata
    try:
        import onnxruntime as rt
        runtime_version=rt.__version__;available=rt.get_available_providers();kokoro_version=metadata.version('kokoro-onnx')
    except ImportError:
        # Frozen GUI has no inference libraries. Use the successfully probed
        # sidecar's metadata for the same calibration key; before a probe use
        # a distinct key so unmeasured hardware conservatively selects one lane.
        from .managed_runtime import catalog
        runtime=config.get('_managed_engine') or {}
        runtime_version=runtime.get('runtime','managed-not-probed');available=runtime.get('providers',[])
        kokoro_version=next(r['version'] for r in catalog()['artifacts'] if r['name']=='kokoro-onnx')
    value=[gpu_identity(),runtime_version,available,kokoro_version,sys.version,config.get('variant'),config.get('revision'),config.get('language'),config.get('voice'),config.get('format')]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def resource_gate(workers):
    if workers<=1:return True,''
    import psutil
    needed={2:1.5,3:3,4:4}[min(4,workers)]*1024**3
    if psutil.virtual_memory().available<needed:return False,f'Chưa đủ RAM trống cho {workers} đoạn đồng thời'
    try:
        free=float(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True,timeout=3,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).splitlines()[0])*1024**2
        if free<({2:1.5,3:2.5,4:3.2}[min(4,workers)]*1024**3):return False,'VRAM trống không đủ'
    except (OSError,ValueError,subprocess.SubprocessError):return False,'Chưa đo được VRAM an toàn'
    return True,''


def selected(store,config):
    record=store.one('SELECT value FROM preferences WHERE name=?',('parallel:'+fingerprint(config),))
    width=1
    if record:width=json.loads(record['value']).get('workers',1)
    else:
        calibration=Path(__file__).with_name('calibration.json')
        if calibration.is_file():width=json.loads(calibration.read_text(encoding='utf8')).get(fingerprint(config),{}).get('workers',1)
    width=min(4,max(1,int(width)))
    return width if resource_gate(width)[0] else 1
