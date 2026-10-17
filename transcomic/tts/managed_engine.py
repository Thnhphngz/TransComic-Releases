"""The existing scheduler uses these shared lanes without changing its leases."""
import json
import os
from queue import Queue,Empty,Full
import subprocess
import sys
from pathlib import Path
import threading
import time
from .parallel import SharedLane
from .process_engine import EngineFailure,Stopped

# CPython normalizes embedded _pth entries during startup. DLL loading can then
# fail after staging is promoted to the longer content-addressed directory,
# even though extraction/integrity checks already use extended Win32 paths.
# Qualify import paths before importing any native inference module. This does
# not change worker sources, the runtime identity, or previously verified cache.
WORKER_BOOTSTRAP=r'''
import os, sys, runpy
if os.name == 'nt':
    # ONNX/MeCab need MSVC C++ DLLs that the embedded Python ZIP does not
    # include. Use the CRT already shipped with the frozen GUI, privately in
    # this worker. Keep handles alive; never install a system runtime or edit
    # PATH. These directories contain replaceable application libraries.
    dll_handles = [os.add_dll_directory(value) for value in sys.argv[2:]]
    def extended(value):
        value = os.path.abspath(value)
        if value.startswith('\\\\?\\'):
            return value
        return '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    sys.path[:] = [extended(value) for value in sys.path]
    # Native eSpeak/MeCab data APIs use narrow paths and do not understand the
    # Win32 extended prefix. Relative package-data paths avoid both that prefix
    # and non-ASCII/long profile names; the worker's cwd stays the runtime root.
    def ordinary(value):
        if value.startswith('\\\\?\\UNC\\'):
            value = '\\\\' + value[8:]
        elif value.startswith('\\\\?\\'):
            value = value[4:]
        return value
    def native_data(value):
        return os.path.relpath(ordinary(value), ordinary(os.getcwd()))
    import espeakng_loader
    data = native_data(espeakng_loader.get_data_path())
    espeakng_loader.get_data_path = lambda: data
    from phonemizer.backend.espeak.api import EspeakAPI
    original_init = EspeakAPI.__init__
    def initialize(self, library, data_path):
        # EspeakWrapper resolves its input back to an absolute path. Normalize
        # at the C API boundary too: this Windows build has a 230-byte buffer.
        return original_init(self, library, native_data(str(data_path)) if data_path is not None else None)
    EspeakAPI.__init__ = initialize
    import unidic_lite
    unidic_lite.DICDIR = native_data(unidic_lite.DICDIR)
runpy.run_path(sys.argv[1], run_name='__main__')
'''


def worker_command(runtime):
    directories=[]
    if getattr(sys,'frozen',False):
        root=Path(getattr(sys,'_MEIPASS',Path(sys.executable).parent/'_internal'))
        directories=[str(p) for p in (root,root/'PySide6') if p.is_dir()]
    return [str(runtime['python']),'-I','-B','-c',WORKER_BOOTSTRAP,str(runtime['worker']),*directories]


class ManagedLane(SharedLane):
    def synthesize(self,*args):
        self.pool.send(dict(kind='synthesize',lane=self.index,args=args))
        while True:
            message=self.pool.receive(self.pool.outputs[self.index])
            if message['kind']=='done':return
            if message['kind']!='audio':raise EngineFailure('Unexpected managed audio frame')
            yield message['value']


class ManagedEngine:
    def __init__(self,models,config,runtime,width=1):
        self.backend=runtime['backend'];self.config=dict(language='en-us',voice='af_heart',speed=1,**{k:v for k,v in config.items() if k not in ('language','voice','speed')});self.config.update(config)
        self.cancelled=threading.Event();self.control=Queue(maxsize=8);self.outputs=[Queue(maxsize=2) for _ in range(width)];self.timeline=[];self.runtime_info={};self.write_lock=threading.Lock()
        self.lanes=[ManagedLane(self,n) for n in range(width)];self.loaded=False
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME')};env['PYTHONDONTWRITEBYTECODE']='1'
        self.process=subprocess.Popen(worker_command(runtime),cwd=runtime['folder'],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.reader=threading.Thread(target=self.read,daemon=True);self.reader.start();self.send(dict(kind='load',models=str(models.root.parent),config=self.config,backend=self.backend,width=width,parent_pid=os.getpid()))
    def send(self,message):
        if self.cancelled.is_set():raise Stopped('Đã dừng Kokoro')
        with self.write_lock:self.process.stdin.write((json.dumps(message,ensure_ascii=False)+'\n').encode());self.process.stdin.flush()
    def publish(self,queue,value):
        while not self.cancelled.is_set():
            try:queue.put(value,timeout=.1);return
            except Full:pass
    def read(self):
        try:
            while not self.cancelled.is_set():
                line=self.process.stdout.readline(65536)
                if not line or len(line)>=65536:raise EngineFailure('Managed runtime exited or invalid frame')
                message=json.loads(line)
                if message['kind']=='inference':
                    if len(self.timeline)<20000:self.timeline.append(message['value'])
                    continue
                if message['kind']=='audio':
                    import numpy as np
                    size=message['bytes']
                    if not 0<size<=32*1024**2 or size%4:raise EngineFailure('Invalid managed audio size')
                    payload=bytearray()
                    while len(payload)<size:
                        block=self.process.stdout.read(size-len(payload))
                        if not block:raise EngineFailure('Truncated managed audio')
                        payload.extend(block)
                    message['value']=np.frombuffer(payload,dtype='<f4').copy()
                if 'lane' in message:
                    if not 0<=message['lane']<len(self.outputs):raise EngineFailure('Invalid managed lane')
                    self.publish(self.outputs[message['lane']],message)
                else:self.publish(self.control,message)
        except Exception as exc:
            for queue in [self.control,*self.outputs]:self.publish(queue,dict(kind='error',message=str(exc)))
    def receive(self,queue):
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            if self.cancelled.is_set():raise Stopped('Đã dừng Kokoro')
            try:value=queue.get(timeout=.1)
            except Empty:
                if self.process.poll() is not None:raise EngineFailure('Managed runtime exited')
                continue
            if value['kind']=='error':
                error=EngineFailure(value['message']);error.technical_traceback=value.get('traceback','');raise error
            return value
        self.cancel();raise EngineFailure('Managed runtime timed out')
    def probe(self,voice=None,speed=None,language=None):
        if not self.loaded:
            value=self.receive(self.control)
            if value.get('protocol')!=2 or value['kind']!='loaded':raise EngineFailure('Managed protocol mismatch')
            self.runtime_info=value;self.loaded=True
        args=(voice or self.config['voice'],speed or self.config['speed'],language or self.config['language']);self.send(dict(kind='probe',args=args));value=self.receive(self.control)
        if value['kind']!='ready' or value.get('backend')!=self.backend or value.get('duration',0)<=0 or (self.backend=='CUDAExecutionProvider' and (not value.get('gpu_verified') or value.get('gpu_nodes',0)<=0)):raise EngineFailure('Runtime did not prove inference')
        self.runtime_info.update(value);return value['duration']
    def synthesize(self,*args):yield from self.lanes[0].synthesize(*args)
    def cancel(self):
        self.cancelled.set()
        if self.process.poll() is None:self.process.terminate()
    def close(self):
        self.cancel()
        try:self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
        self.reader.join(.5)
        for stream in (self.process.stdin,self.process.stdout):stream.close()
        self.lanes.clear()  # break lane→pool cycle so Windows process handles release
