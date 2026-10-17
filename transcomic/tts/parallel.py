"""Concurrent ONNX calls sharing one model/session in one killable process."""
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor
from queue import Empty,Full
import threading
import time
import traceback
from .process_engine import Stopped,EngineFailure,SegmentFailure


def pool_child(root,config,backend,width,commands,outputs,control):
    import os
    def watch():
        parent=mp.parent_process()
        while parent and parent.is_alive():time.sleep(.5)
        os._exit(2)
    threading.Thread(target=watch,daemon=True).start()
    try:
        from .engine import KokoroEngine
        from .models import ModelManager
        import onnxruntime as rt
        import sys
        engine=KokoroEngine(ModelManager(root),config['variant'],backend,config.get('device_id',-1))
        engine.probe(config['voice'],config['speed'],config['language'])
        control.put(('ready',dict(executable=sys.executable,runtime=rt.__version__,providers=rt.get_available_providers(),gpu_verified=engine.gpu_verified,gpu_nodes=getattr(engine,'gpu_node_count',0),backend=backend,workers=width)))
        engine.inference_observer=lambda kind,thread:control.put(('inference',(kind,thread,time.perf_counter())))
        def work(lane,args):
            try:
                for block in engine.synthesize(*args):outputs[lane].put(('audio',block))
                outputs[lane].put(('done',None))
            except Exception as exc:outputs[lane].put(('segment_error' if isinstance(exc,ValueError) else 'error',(str(exc),traceback.format_exc())))
        with ThreadPoolExecutor(width,thread_name_prefix='kokoro-infer') as workers:
            while True:
                command=commands.get()
                if command is None:return
                lane,args=command;workers.submit(work,lane,args)
    except BaseException as exc:control.put(('error',(str(exc),traceback.format_exc())))


class SharedLane:
    def __init__(self,pool,index):self.pool=pool;self.index=index;self.backend=pool.backend;self.slot_id=f'{pool.backend}:{index}'
    def synthesize(self,*args):
        self.pool.commands.put((self.index,args))
        deadline=time.monotonic()+120
        while True:
            if self.pool.cancelled.is_set():raise Stopped('Đã dừng các worker TTS')
            if time.monotonic()>deadline:raise EngineFailure('Kokoro song song không phản hồi trong thời hạn')
            try:kind,value=self.pool.outputs[self.index].get(timeout=.1)
            except Empty:
                if self.pool.cancelled.is_set():raise Stopped('Đã dừng các worker TTS')
                if not self.pool.process.is_alive():raise EngineFailure('Tiến trình Kokoro song song đã thoát')
                continue
            if kind=='done':return
            if kind in ('error','segment_error'):
                error=SegmentFailure(value[0]) if kind=='segment_error' else EngineFailure(value[0]);error.technical_traceback=value[1];raise error
            deadline=time.monotonic()+120;yield value


class SharedProcessEngine:
    def __init__(self,manager,config,backend,width):
        self.backend=backend;self.cancelled=threading.Event();self.timeline=[];self.telemetry_stop=threading.Event();self.runtime_info={}
        context=mp.get_context('spawn');self.commands=context.Queue(maxsize=width);self.outputs=[context.Queue(maxsize=2) for _ in range(width)];self.control=context.Queue(maxsize=128)
        self.lanes=[SharedLane(self,n) for n in range(width)]
        self.process=context.Process(target=pool_child,args=(str(manager.root.parent),config,backend,width,self.commands,self.outputs,self.control),daemon=True);self.process.start()
    def probe(self):
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            if self.cancelled.is_set():raise Stopped('Đã dừng')
            try:kind,value=self.control.get(timeout=.1)
            except Empty:
                if not self.process.is_alive():raise EngineFailure('Không khởi tạo được process Kokoro')
                continue
            if kind=='error':error=EngineFailure(value[0]);error.technical_traceback=value[1];raise error
            self.runtime_info=value;self.collector=threading.Thread(target=self.collect,daemon=True);self.collector.start();return
        raise EngineFailure('Quá thời gian khởi tạo Kokoro song song')
    def collect(self):
        while not self.telemetry_stop.is_set():
            try:
                kind,value=self.control.get(timeout=.1)
                if kind=='inference' and len(self.timeline)<20000:self.timeline.append(value)
            except (Empty,EOFError,OSError,ValueError):pass
    def cancel(self):
        self.cancelled.set()
        if self.process.is_alive():self.process.terminate()
    def close(self):
        if self.process.is_alive():
            try:self.commands.put_nowait(None)
            except Full:self.process.terminate()
        self.process.join(.5)
        if self.process.is_alive():self.process.terminate();self.process.join(.5)
        self.telemetry_stop.set()
        if hasattr(self,'collector'):self.collector.join(.3)
        for queue in [self.commands,self.control,*self.outputs]:queue.cancel_join_thread();queue.close()
