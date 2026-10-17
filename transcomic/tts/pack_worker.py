"""Ship at worker/worker.py in the independently verified embedded Python pack.

The pack builder must include transcomic.tts engine/catalog/models sources and
their pinned dependencies; this script never installs anything or writes audio.
"""
import json
from pathlib import Path
import sys
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parent))


def main():
    engine=None
    def emit(message,block=None):
        sys.stdout.buffer.write((json.dumps(message)+'\n').encode('utf8'))
        if block is not None:sys.stdout.buffer.write(block)
        sys.stdout.buffer.flush()
    for line in sys.stdin.buffer:
        try:
            command=json.loads(line)
            if command['kind']=='load':
                import threading
                import os
                def watch(parent_pid=command['parent_pid']):
                    import time
                    if os.name=='nt':
                        import ctypes
                        from ctypes import wintypes
                        kernel=ctypes.WinDLL('kernel32');kernel.OpenProcess.restype=wintypes.HANDLE;kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
                        handle=kernel.OpenProcess(0x100000,False,parent_pid)
                        if handle:kernel.WaitForSingleObject(handle,0xffffffff)
                    else:
                        while os.getppid()==parent_pid:time.sleep(.5)
                    os._exit(2)
                threading.Thread(target=watch,daemon=True).start()
                from transcomic.tts.engine import KokoroEngine
                from transcomic.tts.models import ModelManager
                import onnxruntime as rt
                config=command['config'];engine=KokoroEngine(ModelManager(command['models']),config['variant'],'CUDAExecutionProvider')
                emit(dict(kind='loaded',protocol=1,executable=sys.executable,runtime=rt.__version__,providers=rt.get_available_providers()))
            elif command['kind']=='probe':
                duration=engine.probe(command['voice'],command['speed'],command['language']);emit(dict(kind='probe',duration=duration,gpu_verified=engine.gpu_verified))
            elif command['kind']=='synthesize':
                import numpy as np
                for samples in engine.synthesize(command['text'],command['voice'],command['speed'],command['language']):
                    payload=np.asarray(samples,dtype='<f4').tobytes();emit(dict(kind='audio',bytes=len(payload)),payload)
                emit(dict(kind='done'))
        except Exception as exc:emit(dict(kind='error',message=str(exc),traceback=traceback.format_exc()))


if __name__=='__main__':main()
