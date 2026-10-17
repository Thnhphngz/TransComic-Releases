"""Explicit source-development repair. Never installs into system Python."""
from pathlib import Path
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[1]


def main():
    target=ROOT/'.venv'
    if target.is_symlink():raise RuntimeError('Project environment must not be a symlink')
    marker=target/'.transcomic-ready'
    if marker.exists():marker.unlink()  # Only our readiness marker; never user data.
    if not (target/'pyvenv.cfg').exists():venv.EnvBuilder(with_pip=True).create(target)
    python=target/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    # Never replace a user-verified CUDA runtime with the CPU dependency lock.
    gpu=subprocess.run([str(python),'-c',"import importlib.metadata as m; m.version('onnxruntime-gpu')"],capture_output=True).returncode==0
    if gpu:
        subprocess.run([str(python),'-c',"import onnxruntime,kokoro_onnx,soundfile,lameenc,PySide6; onnxruntime.preload_dlls(directory=''); print(onnxruntime.get_available_providers())"],check=True)
        marker.write_text('TransComic existing CUDA runtime preserved\n',encoding='utf8');print('READY: existing GPU packages preserved');return
    subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(ROOT/'requirements-release.lock')],check=True)
    subprocess.run([str(python),'-m','pip','check'],check=True)
    subprocess.run([str(python),'-c',"import onnxruntime,kokoro_onnx,soundfile,lameenc,PySide6; print(onnxruntime.get_available_providers())"],check=True)
    marker.write_text('TransComic source runtime verified\n',encoding='utf8')
    print('READY: restart run_transcomic.py',flush=True)


if __name__=='__main__':main()
