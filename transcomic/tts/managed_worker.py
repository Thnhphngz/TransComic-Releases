"""Protocol 2 sidecar: one Kokoro session, bounded shared inference lanes."""
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parent))


def main():
    engine=None;pool=None;lock=threading.Lock()
    def emit(message,block=None):
        with lock:
            sys.stdout.buffer.write((json.dumps(message)+'\n').encode())
            if block is not None:sys.stdout.buffer.write(block)
            sys.stdout.buffer.flush()
    def watch(pid):
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32');kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE;kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        handle=kernel.OpenProcess(0x100000,False,pid)
        if handle:kernel.WaitForSingleObject(handle,0xffffffff)
        os._exit(2)
    def work(lane,args):
        try:
            import numpy as np
            for samples in engine.synthesize(*args):
                payload=np.asarray(samples,dtype='<f4').tobytes();emit(dict(kind='audio',lane=lane,bytes=len(payload)),payload)
            emit(dict(kind='done',lane=lane))
        except Exception as exc:emit(dict(kind='error',lane=lane,message=str(exc),traceback=traceback.format_exc()))
    for line in sys.stdin.buffer:
        try:
            command=json.loads(line)
            if command['kind']=='load':
                threading.Thread(target=watch,args=(command['parent_pid'],),daemon=True).start()
                from transcomic.tts.engine import KokoroEngine
                from transcomic.tts.models import ModelManager
                import onnxruntime as rt
                config=command['config'];backend=command['backend'];engine=KokoroEngine(ModelManager(command['models']),config['variant'],backend,config.get('device_id',-1))
                pool=ThreadPoolExecutor(max_workers=min(2,max(1,command['width'])))
                emit(dict(kind='loaded',protocol=2,backend=backend,runtime=rt.__version__,providers=rt.get_available_providers(),executable=sys.executable,prefix=sys.prefix))
            elif command['kind']=='probe':
                duration=engine.probe(*command['args']);emit(dict(kind='ready',duration=duration,gpu_verified=engine.gpu_verified,gpu_nodes=getattr(engine,'gpu_node_count',0),backend=engine.backend))
                engine.inference_observer=lambda kind,thread:emit(dict(kind='inference',value=(kind,thread,time.perf_counter())))
            elif command['kind']=='synthesize':pool.submit(work,command['lane'],command['args'])
        except Exception as exc:emit(dict(kind='error',message=str(exc),traceback=traceback.format_exc()))
    if pool:pool.shutdown()

if __name__=='__main__':main()
