"""Bounded stdio protocol for a verified self-contained acceleration worker."""
import json
from queue import Queue,Empty
import subprocess
import threading
import time
import os
from .process_engine import EngineFailure,SegmentFailure,Stopped


class PackEngine:
    def __init__(self,models,config,runtime):
        self.backend='CUDAExecutionProvider';self.cancelled=threading.Event();self.events=Queue(maxsize=2);self.runtime_info={}
        self.process=subprocess.Popen([str(runtime['python']),'-I','-B',str(runtime['worker'])],cwd=runtime['folder'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.reader=threading.Thread(target=self.read,daemon=True);self.reader.start();self.send(dict(kind='load',models=str(models.root.parent),config=config,parent_pid=os.getpid()))
    def read(self):
        try:
            while True:
                line=self.process.stdout.readline(65536)
                if not line:raise EngineFailure('GPU pack worker exited')
                if len(line)>=65536:raise EngineFailure('GPU pack protocol header too large')
                message=json.loads(line)
                if message['kind']=='audio':
                    size=message['bytes']
                    if not 0<size<=32*1024**2 or size%4:raise EngineFailure('Invalid GPU pack audio frame')
                    import numpy as np
                    block=self.process.stdout.read(size)
                    if len(block)!=size:raise EngineFailure('Truncated GPU pack audio')
                    message['value']=np.frombuffer(block,dtype='<f4').copy()
                if not self.publish(message):return
        except Exception as exc:self.publish(dict(kind='error',message=str(exc)))
    def publish(self,message):
        from queue import Full
        while not self.cancelled.is_set():
            try:self.events.put(message,timeout=.1);return True
            except Full:pass
        return False
    def send(self,message):self.process.stdin.write((json.dumps(message,ensure_ascii=False)+'\n').encode('utf8'));self.process.stdin.flush()
    def receive(self):
        end=time.monotonic()+120
        while time.monotonic()<end:
            if self.cancelled.is_set():raise Stopped('GPU pack stopped')
            try:
                message=self.events.get(timeout=.1)
                if message['kind']=='error':
                    error=EngineFailure(message['message']);error.technical_traceback=message.get('traceback','');raise error
                return message
            except Empty:pass
        raise EngineFailure('GPU pack worker timed out')
    def probe(self,voice,speed,language):
        loaded=self.receive()
        if loaded.get('protocol')!=1:raise EngineFailure('GPU pack protocol incompatible')
        self.runtime_info=loaded;self.send(dict(kind='probe',voice=voice,speed=speed,language=language));probe=self.receive()
        if probe['kind']!='probe' or not probe.get('gpu_verified'):raise EngineFailure('GPU pack did not prove CUDA inference')
        self.runtime_info.update(probe);return probe['duration']
    def synthesize(self,text,voice,speed,language):
        self.send(dict(kind='synthesize',text=text,voice=voice,speed=speed,language=language))
        while True:
            message=self.receive()
            if message['kind']=='done':return
            if message['kind']!='audio':raise EngineFailure('Unexpected GPU pack response')
            yield message['value']
    def cancel(self):
        self.cancelled.set()
        if self.process.poll() is None:self.process.terminate()
    def close(self):
        self.cancel()
        try:self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=1)
        self.reader.join(.5)
        for stream in (self.process.stdin,self.process.stdout):stream.close()
