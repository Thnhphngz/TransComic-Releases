"""Independent local audio workers. No API scheduler, retries or network calls."""
import json
from pathlib import Path
import threading
import time
from .audio import encode
from .devices import backend_plan,CPU
from .engine import KokoroEngine
from .process_engine import ProcessEngine,Stopped,EngineFailure,SegmentFailure
from .runtime import logger,friendly
from .output import Outputs,safe_path
from .parallel import SharedProcessEngine,SharedLane


class Scheduler:
    def __init__(self,store,manager,notify=lambda *args:None,engine_factory=ProcessEngine,before_finalize=lambda:None):
        self.store=store;self.manager=manager;self.notify=notify;self.factory=engine_factory
        self.thread=None;self.cancel=threading.Event();self.stop_requested=False
        self.lock=threading.RLock();self.run_id=None;self.active={};self.message=''
        self.before_finalize=before_finalize
        self.engines=[];self.log=logger(store.path.parent/'Logs')
        self.parallel_factory=SharedProcessEngine;self.recover_parallel=False;self.pause_requested=False;self.parallel_timeline=[]
        self.packs=None;self.external_runtime=None;self.prepared_backend=None

    @property
    def busy(self):return bool(self.thread and self.thread.is_alive())

    def start(self,run,documents=None):
        with self.lock:
            if self.busy:raise RuntimeError('Đang chạy một lượt TTS')
            if self.store.run(run)['state'] in ('draft','cancelled','completed'):raise ValueError('Lượt chưa sẵn sàng hoặc đã kết thúc; tạo lượt mới')
            config=json.loads(self.store.run(run)['config'])
            from .catalog import LANGUAGES,voice_names
            if config.get('language') not in LANGUAGES or config.get('voice') not in voice_names(config['language']):raise ValueError('Chọn ngôn ngữ và giọng đọc hợp lệ')
            if not any(not item['skip'] and (documents is None or item['document_id'] in documents) for item in self.store.items(run)):raise ValueError('Không có đoạn TTS để chạy')
            self.permanent_stop=False
            self.cancel.clear();self.stop_requested=False;self.pause_requested=False;self.recover_parallel=False;self.parallel_timeline=[];self.run_id=run;self.documents=documents
            self.thread=threading.Thread(target=self._run,args=(run,),daemon=True,name='tts-coordinator')
            accepted=self.store.run(run)['history_accepted']
            self.store.execute('UPDATE runs SET history_accepted=1 WHERE id=?',(run,))
            try:self.thread.start()
            except BaseException:
                self.store.execute('UPDATE runs SET history_accepted=? WHERE id=?',(accepted,run));raise

    def pause(self):
        with self.lock:
            self.pause_requested=True;self.cancel.set()
            if self.run_id and self.busy:self.store.status(self.run_id,'pausing')

    def stop(self,permanent=True):
        with self.lock:
            record=self.store.run(self.run_id) if self.run_id else None
            permanent=permanent or bool(record and record['state']=='cancelled')
            self.permanent_stop=permanent
            self.stop_requested=True;self.cancel.set()
            if self.run_id and self.busy:
                if permanent:self.store.cancel_run(self.run_id)
                else:self.store.status(self.run_id,'stopping')
            elif record and permanent:self.store.cancel_run(self.run_id)
            for engine in list(self.engines):
                if hasattr(engine,'cancel'):engine.cancel()

    def load_engine(self,config,backend):
        with self.lock:
            if self.stop_requested:raise Stopped('Đã dừng')
            if self.external_runtime and backend==self.external_runtime.get('backend','CUDAExecutionProvider'):
                if self.external_runtime.get('protocol')==2:
                    from .managed_engine import ManagedEngine
                    engine=ManagedEngine(self.manager,config,self.external_runtime)
                else:
                    from .pack_engine import PackEngine
                    engine=PackEngine(self.manager,config,self.external_runtime)
            else:engine=self.factory(self.manager,config['variant'],backend,config.get('device_id',-1))
            self.engines.append(engine)
        engine.probe(config['voice'],config['speed'],config['language']);self.notify('backend',engine.backend);return engine

    def retire(self,engine):
        if hasattr(engine,'close'):engine.close()
        if hasattr(engine,'timeline'):self.parallel_timeline.extend(engine.timeline)
        with self.lock:
            if engine in self.engines:self.engines.remove(engine)

    def load_parallel(self,config,backend,width):
        with self.lock:
            if self.stop_requested:raise Stopped('Đã dừng')
            if self.external_runtime and self.external_runtime.get('protocol')==2:
                from .managed_engine import ManagedEngine
                pool=ManagedEngine(self.manager,config,self.external_runtime,width=min(2,width))
            else:pool=self.parallel_factory(self.manager,config,backend,width)
            self.engines.append(pool)
        pool.probe();self.notify('backend',backend);return pool.lanes

    def _run(self,run):
        output=Outputs(self.store);config=json.loads(self.store.run(run)['config']);engines=[];self.message=''
        try:
            output.reconcile(run)
            with self.store.transaction():
                if self.store.run(run)['state']=='cancelled':raise Stopped('Lượt đã hủy')
                self.store.execute("UPDATE runs SET state='running',error='',started=COALESCE(started,?) WHERE id=?",(time.time(),run))
            backends=[self.prepared_backend] if config['device']=='Auto' and self.prepared_backend else backend_plan(config['device'])
            self.external_runtime=None
            if self.packs and config['device']=='Auto' and (backends==[CPU] or self.prepared_backend):
                try:self.external_runtime=self.packs.active()
                except (OSError,ValueError):self.notify('notice','GPU pack không hợp lệ, tiếp tục với CPU')
                if self.external_runtime and self.prepared_backend and self.external_runtime.get('backend','CUDAExecutionProvider')!=self.prepared_backend:self.external_runtime=None
                if self.external_runtime:backends=[self.external_runtime.get('backend','CUDAExecutionProvider')]
                if self.prepared_backend==CPU and backends!=[CPU]:self.external_runtime=None;backends=[CPU]
            for backend in backends:
                try:
                    width=int(config.get('workers',1))
                    if self.external_runtime:width=min(2,width) if self.external_runtime.get('protocol')==2 else 1
                    if width>1 and backend!=CPU:
                        from .concurrency import resource_gate
                        allowed,reason=resource_gate(width)
                        if not allowed:width=1;self.notify('notice',reason+'; dùng 1 đoạn')
                    else:width=1
                    if width>1:
                        try:engines.extend(self.load_parallel(config,backend,width))
                        except Stopped:raise
                        except Exception:
                            for failed in list(self.engines):self.retire(failed)
                            self.notify('notice','Không đủ tài nguyên cho nhiều đoạn; giảm còn 1 đoạn.');engines.append(self.load_engine(config,backend))
                    else:engines.append(self.load_engine(config,backend))
                except Exception as exc:
                    self.log.exception('Backend initialization failed: %s %s',backend,getattr(exc,'technical_traceback',''))
                    for failed in list(self.engines):
                        if failed not in engines:self.retire(failed)
                    if config['device']=='Auto' and backend!=CPU and not self.stop_requested:
                        self.message='GPU không dùng được; lượt này chuyển CPU. '+friendly(exc);self.notify('notice',self.message)
                        engine=self.load_engine(config,CPU);engines.append(engine)
                    else:raise
            workers=[threading.Thread(target=self._worker,args=(run,config,engine),daemon=True,name='tts-'+engine.backend) for engine in engines]
            for worker in workers:worker.start()
            for worker in workers:worker.join()
            if self.recover_parallel and not self.stop_requested and not self.pause_requested:
                for failed in list(self.engines):self.retire(failed)
                self.active.clear();self.cancel.clear();self.recover_parallel=False
                self.notify('notice','Worker CUDA gặp lỗi; giảm còn 1 đoạn, giữ audio đã hoàn thành.')
                try:engine=self.load_engine(config,backends[0])
                except Exception:
                    for failed in list(self.engines):self.retire(failed)
                    if config['device']!='Auto':raise
                    engine=self.load_engine(config,CPU);self.notify('notice','Không thể khởi tạo GPU, đã chuyển sang CPU')
                self._worker(run,config,engine)
            if self.stop_requested and self.permanent_stop:self.store.cancel_run(run)
            elif self.cancel.is_set():self.store.status(run,'interrupted' if self.stop_requested else 'paused',self.message)
            else:
                self.before_finalize()
                output.finalize(run);counts=self.store.progress(run)
                self.store.status(run,'completed' if not any(counts.get(k,0) for k in ('pending','running','unknown','error')) else 'partial')
        except Stopped:
            if self.permanent_stop:self.store.cancel_run(run)
            else:self.store.status(run,'interrupted')
        except Exception as exc:
            self.log.exception('TTS run failed: %s',getattr(exc,'technical_traceback',''))
            self.message=friendly(exc)
            if self.stop_requested and self.permanent_stop:self.store.cancel_run(run)
            else:self.store.status(run,'paused',self.message)
            self.notify('notice',self.message)
            from .diagnostics import diagnostic
            self.notify('error',diagnostic(exc,'Khởi tạo / hoàn tất lượt',run,dict(backend=None)))
        finally:
            for engine in list(self.engines):self.retire(engine)
            self.active.clear();engines.clear();self.notify('finished',run)

    def _worker(self,run,config,engine):
        output=Outputs(self.store)
        while True:
            # Pause and claim share a lock: no new lease after pause returns.
            with self.lock:
                if self.cancel.is_set():return
                item=self.store.claim(run,self.documents)
                if not item:return
                slot=getattr(engine,'slot_id',id(engine));self.active[slot]=item['id']
            self.notify('segment',item['id']);temp=None
            try:
                doc=self.store.doc(item['document_id']);folder,_=output.manifest(doc)
                temp=safe_path(folder/(item['id']+'.'+item['attempt']+'.part'))
                info=encode(temp,engine.synthesize(item['text'],config['voice'],config['speed'],config['language']),config['format'],bitrate=config.get('bitrate',128))
                if self.stop_requested:raise Stopped('Đã dừng')
                output.commit(item,temp,info,engine.backend)
            except Stopped:
                with self.store.transaction():
                    if self.store.owns(item):self.store.execute("UPDATE segments SET state='pending',attempt=NULL,error='' WHERE id=?",(item['id'],))
                if temp and temp.exists():temp.unlink()  # only this attempt's owned partial
                return
            except Exception as exc:
                # Stop can race the receive timeout / process-exit observation.
                # Cancellation must return the owned lease to pending rather
                # than turning an intentional shutdown into a retry dialog.
                if self.stop_requested:
                    with self.store.transaction():
                        if self.store.owns(item):self.store.execute("UPDATE segments SET state='pending',attempt=NULL,error='' WHERE id=?",(item['id'],))
                    if temp and temp.exists():temp.unlink()
                    return
                self.log.exception('TTS segment failed %s: %s',item['id'],getattr(exc,'technical_traceback',''))
                if isinstance(engine,SharedLane) and isinstance(exc,EngineFailure):
                    with self.lock:
                        self.recover_parallel=True;self.cancel.set();engine.pool.cancel()
                    with self.store.transaction():
                        if self.store.owns(item):self.store.execute("UPDATE segments SET state='pending',attempt=NULL WHERE id=?",(item['id'],))
                    if temp and temp.exists():temp.unlink()
                    return
                if config['device']=='Auto' and engine.backend!=CPU and isinstance(exc,EngineFailure) and not self.cancel.is_set():
                    # No manifest commit happened: only the owned temp exists.
                    # Retire GPU first, then continue with a single CPU session.
                    self.retire(engine)
                    try:
                        engine=self.load_engine(config,CPU)
                        with self.store.transaction():
                            if self.store.owns(item):self.store.execute("UPDATE segments SET state='pending',attempt=NULL WHERE id=?",(item['id'],))
                        if temp and temp.exists():temp.unlink()
                        self.notify('notice','GPU gặp lỗi khi tổng hợp. Đã chuyển CPU, giữ các audio hoàn thành.');continue
                    except Exception as fallback:
                        exc=fallback;self.log.exception('CPU fallback failed')
                with self.store.transaction():
                    if self.store.owns(item):self.store.execute("UPDATE segments SET state='error',error=? WHERE id=?",(friendly(exc),item['id']))
                self.message=friendly(exc);self.notify('notice',self.message)
                # Text/validation failures are local; disk/runtime failures pause.
                if not isinstance(exc,(ValueError,SegmentFailure)):
                    self.cancel.set()
                    from .diagnostics import diagnostic
                    self.notify('error',diagnostic(exc,'Tổng hợp / ghi audio',run,dict(backend=engine.backend),item['id']))
            finally:
                # Keep partial files for recovery inspection, never delete a
                # successfully committed audio or unrelated file on failure.
                self.active.pop(slot,None);self.notify('segment',item['id'])
