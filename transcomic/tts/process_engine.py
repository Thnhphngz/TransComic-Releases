"""One killable inference process per backend; audio commits stay in parent.

Stop can interrupt ONNX's synchronous inference without killing a Qt/Python
thread. The child owns no SQLite/output file and cannot commit late audio.
"""
import multiprocessing as mp
from queue import Empty,Full
import threading
import traceback
import time


class Stopped(Exception):pass
class EngineFailure(RuntimeError):pass
class SegmentFailure(ValueError):pass


def engine_child(root,variant,backend,device_id,commands,results):
    def parent_watch():
        import os
        parent=mp.parent_process()
        while parent and parent.is_alive():time.sleep(.5)
        os._exit(2)  # Parent alone owns output; no child audio/DB handles.
    threading.Thread(target=parent_watch,daemon=True).start()
    try:
        from .models import ModelManager
        from .engine import KokoroEngine
        engine=KokoroEngine(ModelManager(root),variant,backend,device_id)
        import sys
        import onnxruntime
        results.put(('loaded',dict(executable=sys.executable,prefix=sys.prefix,runtime=onnxruntime.__version__,providers=onnxruntime.get_available_providers())))
        while True:
            command=commands.get()
            if command is None:return
            kind,args=command
            try:
                if kind=='probe':
                    duration=engine.probe(*args)
                    results.put(('probe',dict(duration=duration,gpu_verified=engine.gpu_verified,gpu_nodes=getattr(engine,'gpu_node_count',0),session_providers=engine.model.sess.get_providers())))
                else:
                    for block in engine.synthesize(*args):results.put(('audio',block))
                    results.put(('done',None))
            except Exception as exc:
                results.put(('segment_error' if isinstance(exc,ValueError) else 'error',(str(exc),traceback.format_exc())))
    except BaseException as exc:
        results.put(('error',(str(exc),traceback.format_exc())))


class ProcessEngine:
    def __init__(self,manager,variant,backend,device_id=-1):
        self.backend=backend;self.cancelled=threading.Event();self.loaded=False
        ctx=mp.get_context('spawn');self.commands=ctx.Queue(maxsize=1);self.results=ctx.Queue(maxsize=2)
        self.process=ctx.Process(target=engine_child,args=(str(manager.root.parent),variant,backend,device_id,self.commands,self.results),daemon=True)
        self.process.start()

    def receive(self):
        deadline=time.monotonic()+120
        while True:
            if self.cancelled.is_set():raise Stopped('Đã dừng bộ máy TTS')
            if time.monotonic()>deadline:self.cancel();raise EngineFailure('Kokoro không phản hồi trong thời hạn. Kiểm tra runtime hoặc chọn đoạn ngắn hơn.')
            try:
                kind,value=self.results.get(timeout=.1)
                if kind in ('error','segment_error'):
                    exc=SegmentFailure(value[0]) if kind=='segment_error' else EngineFailure(value[0]);exc.technical_traceback=value[1];raise exc
                return kind,value
            except Empty:
                if self.cancelled.is_set():raise Stopped('Đã dừng bộ máy TTS')
                if not self.process.is_alive():raise EngineFailure('Tiến trình Kokoro đã dừng bất thường. Xem log runtime.')

    def probe(self,*args):
        if not self.loaded:
            kind,self.runtime_info=self.receive()
            if kind!='loaded':raise EngineFailure('Kokoro không khởi tạo được')
            self.loaded=True
        self.commands.put(('probe',args))
        kind,value=self.receive()
        if kind!='probe':raise EngineFailure('Phản hồi probe không hợp lệ')
        if isinstance(value,dict):self.runtime_info.update(value);return value['duration']
        return value

    def synthesize(self,*args):
        self.commands.put(('synthesize',args))
        while True:
            kind,value=self.receive()
            if kind=='done':return
            if kind!='audio':raise EngineFailure('Phản hồi audio không hợp lệ')
            yield value

    def cancel(self):
        self.cancelled.set()
        if self.process.is_alive():self.process.terminate()

    def close(self):
        if self.process.is_alive():
            try:self.commands.put_nowait(None)
            except Full:self.process.terminate()
        self.process.join(timeout=.5)
        if self.process.is_alive():self.process.terminate();self.process.join(timeout=.5)
        for queue in (self.commands,self.results):queue.cancel_join_thread();queue.close()
