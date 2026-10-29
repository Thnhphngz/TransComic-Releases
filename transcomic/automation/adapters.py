"""Adapters for the existing scheduler, Kokoro runtime and MAU exporter."""
from pathlib import Path
import json
import shutil
import threading
import time
import uuid
from .repository import file_hash,fingerprint
from .validation import speakable
from ..status import usable


class Stopped(Exception):pass
class NeedsRescue(ValueError):pass


def provider_for(store,job):
    if job['provider']=='deepseek':
        from ..deepseek import provider_for as deepseek_provider
        return deepseek_provider(store, job)
    if job['provider']=='kira':
        from ..kira_pool import KiraPoolProvider
        return KiraPoolProvider(store,job['model'],timeout=job['timeout'],prompt_version=job['prompt_version'])
    from ..gemini import GeminiProvider,QuotaLimiter
    cfg=json.loads(job['config']);all_keys={k['id']:k for k in store.gemini_keys(decrypt=True)}
    keys=[dict(all_keys[k],project=cfg['key_projects'].get(k,'')) for k in cfg['key_ids']]
    for key in keys:store.log.register_secret(key['secret'])
    limiter=QuotaLimiter(cfg['rpm'],cfg['tpm'],cfg['rpd'],reservation=lambda cost,rpm,tpm,rpd:store.reserve_gemini_quota('all-projects:'+job['model'],cost,rpm,tpm,rpd))
    return GeminiProvider(keys,job['model'],limiter=limiter,on_status=store.gemini_key_status,timeout=job['timeout'],prompt_version=job['prompt_version'])


class Translation:
    """Kira v4 uses one durable scheduler; legacy passes keep frozen behavior.

    Original chunks and request_attempts retain their identity across recovery.
    Historical DeepSeek jobs retain single-pass behavior; newly authorized
    completion jobs recover on the same durable scheduler.
    """
    def __init__(self,repo,provider_factory=provider_for,scheduler_factory=None,network_probe=None):
        from ..translation import Scheduler
        self.repo=repo;self.store=repo.store;self.provider_factory=provider_factory;self.factory=scheduler_factory or Scheduler;self.scheduler=None
        self.network_probe=network_probe or network_ready;self.dispatch_lock=threading.RLock();self.stopping=False
        self.backoff=lambda phase:min(8,2**phase)
    def reset(self):
        with self.dispatch_lock:self.stopping=False
    def stop(self):
        with self.dispatch_lock:
            self.stopping=True
            if self.scheduler:self.scheduler.stop()
    def run(self,id,groups,config,stop,changed,*,line_ids=None,scope=None,exclude_ids=()):
        cycle=self.repo.workset(id)['cycle'];boundaries={};line_groups={}
        from ..documents import translatable
        from ..deepseek_batch import job_size
        batch_size=job_size(config['provider'],config)
        for group in (() if config['provider']=='kira' and config.get('kira_dispatch_policy')==1 else groups):
            rows=[r for r in self.store.lines(group['document_id']) if translatable(r['source'])]
            boundaries[group['id']]=[rows[i:i+batch_size] for i in range(0,len(rows),batch_size)]
            line_groups.update({r['id']:group for r in rows})
        if config['provider']=='kira' and config.get('kira_dispatch_policy')==1:
            by_doc={g['document_id']:g for g in groups}
            for row in self.repo.rows('SELECT l.id,l.document_id FROM lines l JOIN automation_groups g ON g.document_id=l.document_id WHERE g.workset_id=?',(id,)):
                if row['document_id'] in by_doc:line_groups[row['id']]=by_doc[row['document_id']]
        def notify(ids):
            controller=getattr(self.repo,'controller',None);scheduler=self.scheduler
            if controller and controller.preparing.is_set() and scheduler and scheduler._thread and scheduler._thread.is_alive() and getattr(scheduler,'waiting',0):
                controller.preparing.clear();controller.checkpoint(id,preparing=False)
            candidates={line_groups[i]['id']:line_groups[i] for i in ids if i in line_groups}
            for gid,group in candidates.items():
                self.repo.progress(gid)
                meta=self.repo.group_state(gid)
                if meta.get('translation_ready_cycle')!=cycle and all(usable(r) for r in self.store.lines(group['document_id']) if translatable(r['source'])):
                    from ..line_structure import validate_snapshot
                    self.store.validate_document_language(group['document_id'])
                    rows=self.store.units(group['document_id'])
                    if all(usable(r) for r in rows if translatable(r['source'])) and not validate_snapshot(self.store.document(group['document_id']),rows).structural:
                        self.repo.update_group(gid,translation_ready_cycle=cycle,translation_ready_at=time.monotonic_ns())
            changed()
        deepseek = config['provider']=='deepseek'
        if deepseek and config.get('translation_completion_policy')==1:
            return self.continuous(id,groups,config,stop,notify,line_ids=line_ids,scope=scope,exclude_ids=exclude_ids)
        if config['provider']=='kira' and config.get('kira_recovery_version',2)>=4:
            return self.always_on(id,groups,config,stop,notify,line_ids=line_ids,scope=scope,exclude_ids=exclude_ids)
        for phase in range(1 if deepseek else 5):
            if stop.is_set():return
            jobs=[]
            with self.dispatch_lock:
                reserved=set(exclude_ids)
                if scope is None:
                    reserved.update(i for q in self.repo.workset(id)['checkpoint'].get('translation_retries',[])
                                    if q['state'] in ('pending','running') for i in q['line_ids'])
                for group in groups:
                    selected=[];mapping=self.repo.field(group['id'],'batch_jobs',{})
                    for index,chunk in enumerate(boundaries[group['id']]):
                        wanted=[r['id'] for old in chunk if not usable(r:=self.store.line(old['id'])) and
                                r['id'] not in reserved and (line_ids is None and r['attempt_kind']!='manual' or line_ids is not None and r['id'] in line_ids)]
                        if not wanted:continue
                        key=f'{scope or cycle}:{index}';prior=mapping.get(key,[])
                        attempts=[a for batch_id in self.repo.batch_ids(prior) for a in self.store.attempts(batch_id)]
                        if len(attempts)>=(1 if deepseek else 5):continue
                        if attempts and not retryable(attempts[-1].get('diagnostics') or {}):continue
                        selected.append((key,wanted,prior,index))
                    if not selected:continue
                    cfg={'automation_owner':id,'automation_cycle':cycle,'automation_boundaries':[ids for key,ids,prior,index in selected],
                         'auto_retries':0,'kira_multi_key':config['provider']=='kira','kira_retry_limit':0,'kira_retry_budget':0,'kira_recovery_version':2,'uncertain_retry_authorized':True}
                    if deepseek:
                        from ..deepseek import settings
                        cfg.update(settings(self.store, config['model'],batch_size))
                        cfg['translation_completion_policy']=config.get('translation_completion_policy',0)
                        for name in list(cfg):
                            if name.startswith('kira_') or name=='uncertain_retry_authorized':cfg.pop(name)
                    if config['provider']=='gemini':
                        keys=[k for k in self.store.gemini_keys() if k['status'] not in ('invalid','disabled','exhausted','authentication','permission','quota_exhausted','model_not_found')]
                        cfg.update(key_ids=[k['id'] for k in keys],key_projects={k['id']:k['project'] for k in keys},
                                   **{k:int(self.store.setting('gemini_'+k,str(v))) for k,v in (('rpm',1),('tpm',3000),('rpd',1))})
                    with self.store.transaction():
                        job=self.store.create_job(group['document_id'],config['model'],config['source_lang'],config['target_lang'],config['workers'],
                            [i for key,ids,prior,index in selected for i in ids],provider=config['provider'],config=cfg,max_requests=len(selected),retry_504=True,allow_shared_document=True)
                        frozen=json.loads(self.store.job(job)['config']);frozen.update(auto_retries=0)
                        self.store.db.execute('UPDATE jobs SET auto_retries=0,config=? WHERE id=?',(json.dumps(frozen),job))
                        by_ids={tuple(p['id'] for p in b['payload']):b['id'] for b in self.store.batches(job)}
                        mapping=dict(mapping)
                        for key,ids,prior,index in selected:mapping[key]=[*prior,by_ids[tuple(ids)]]
                        self.repo.update_group(group['id'],batch_jobs=mapping,state='translating')
                    jobs.append(job)
                    for key,ids,prior,index in selected:self.repo.event(id,group['id'],'translation',f'Batch {index+1}: '+('cứu lỗi cuối' if phase==4 else f'lượt {phase+1}/5'))
                if not jobs:return
            provider=self.provider_factory(self.store,self.store.job(jobs[0]))
            with self.dispatch_lock:
                if stop.is_set() or self.stopping:
                    for job in jobs:self.store.job_state(job,'stopped')
                    return
                self.scheduler=self.factory(self.store,provider,notify)
                self.scheduler.start_many(jobs)
            while self.scheduler._thread.is_alive():
                changed()
                if stop.is_set():self.scheduler.stop()
                time.sleep(.05)
            self.scheduler.join();changed()
            if deepseek:return  # No outer retry, network wait, or implicit replay.
            reason=self.scheduler.intervention_reason
            if self.scheduler.quota_paused or reason and ('key' in reason or 'quota' in reason or 'token_budget' in reason):
                self.repo.event(id,None,'translation','Cần bổ sung/kiểm tra API key: '+str(reason));return
            diagnostics=[a.get('diagnostics') or {} for job in jobs for batch in self.store.batches(job) for a in self.store.attempts(batch['id'])]
            network=reason=='network_unavailable' or any(d.get('failure_kind') in ('connect_error','connect_not_sent','network_error') for d in diagnostics)
            if network and phase<4:
                self.repo.event(id,None,'translation','Mất mạng; chờ kết nối. Kiểm tra mạng không gửi API và không tiêu thụ lượt thử.')
                while not stop.is_set() and not self.network_probe(config['provider']):stop.wait(3)
            if phase<4 and not stop.is_set():
                delay=max([self.backoff(phase),*[float(d.get('retry_after_seconds') or 0) for d in diagnostics if d.get('http_status') in (408,429,500,502,503,504)]])
                if delay>300:
                    self.repo.event(id,None,'translation','Retry-After vượt thời gian chờ; giữ checkpoint, không gửi sớm.');return
                stop.wait(delay)


    def always_on(self,id,groups,config,stop,notify,*,line_ids=None,scope=None,exclude_ids=()):
        """One durable scheduler, no outer replay jobs or UI-driven Continue."""
        if config.get('kira_dispatch_policy')==1:
            return self.admitted(id,groups,config,stop,notify,line_ids=line_ids,scope=scope,exclude_ids=exclude_ids)
        cycle=self.repo.workset(id)['cycle'];jobs=[];group_jobs={}
        with self.dispatch_lock:
            if stop.is_set() or self.stopping:return
            with self.store.transaction():
                checkpoint=self.repo.workset(id)['checkpoint']
                anchor=checkpoint.setdefault('kira_recovery_cycle',cycle)
                self.store.db.execute('UPDATE automation_worksets SET checkpoint=? WHERE id=?',(json.dumps(checkpoint),id))
            for group in groups:
                signature=fingerprint([(r['id'],r['source_revision']) for r in self.store.lines(group['document_id'])])
                mapping=self.repo.field(group['id'],'batch_jobs',{});key=f'{scope or anchor}:always4:{signature}'
                rows=[r for r in self.store.lines(group['document_id']) if not usable(r) and r['id'] not in exclude_ids and
                      (line_ids is not None and r['id'] in line_ids or line_ids is None and r['attempt_kind']!='manual')]
                if not rows:continue
                existing=mapping.get(key,[])
                if existing:
                    jobs.extend(existing);group_jobs[group['id']]=existing[0];continue
                # Do not invent a fresh lineage for legacy attempts/unknowns.
                legacy=[entry for k,entries in mapping.items() if k.startswith(f'{scope or anchor}:') and ':always4' not in k for entry in entries]
                if legacy and any(self.store.attempts(b) for b in self.repo.batch_ids(legacy)):
                    self.repo.update_group(group['id'],translation_recovery_state='needs_reconciliation',translation_recovery_reason='legacy_checkpoint_requires_review')
                    self.repo.event(id,group['id'],'translation','Giữ checkpoint cũ; không tạo request mới để vượt quyền/budget.');continue
                cfg={k:v for k,v in config.items() if k.startswith('kira_') or k in ('uncertain_retry_authorized','translation_completion_policy')}
                cfg.update(automation_owner=id,automation_cycle=anchor,kira_multi_key=True,kira_recovery_version=4)
                with self.store.transaction():
                    job=self.store.create_job(group['document_id'],config['model'],config['source_lang'],config['target_lang'],config['workers'],
                        [r['id'] for r in rows],provider='kira',config=cfg,allow_shared_document=True)
                    self.repo.update_group(group['id'],batch_jobs={**mapping,key:[job]},state='translating')
                jobs.append(job)
                group_jobs[group['id']]=job
            if not jobs:return
            provider=self.provider_factory(self.store,self.store.job(jobs[0]))
            self.scheduler=self.factory(self.store,provider,notify)
        while True:
            with self.dispatch_lock:
                if stop.is_set() or self.stopping:return
                paused=getattr(getattr(self.repo,'controller',None),'paused',None)
                if paused is None or not paused.is_set():
                    self.scheduler.start_many(list(dict.fromkeys(jobs)));break
            stop.wait(.1)
        while self.scheduler._thread.is_alive():
            for group in groups:
                if group['id'] not in group_jobs:continue
                state=self.store.job(group_jobs[group['id']])['state']
                detail=getattr(self.scheduler,'recovery_details',{}).get(group_jobs[group['id']],{}) if state in ('provider_recovering','retry_scheduled','network_waiting','waiting_rate_limit','blocked_budget','blocked','needs_reconciliation') else {}
                self.repo.update_group(group['id'],translation_recovery_state=state,
                    translation_recovery_reason=detail.get('reason') or self.scheduler.intervention_reason or state,
                    next_retry_at=detail.get('next_retry_at'))
            notify([])
            if stop.wait(.25):self.scheduler.stop()
        self.scheduler.join()
        for gid,job in group_jobs.items():
            state=self.store.job(job)['state']
            reason='' if state=='finished' else getattr(self.scheduler,'job_block_reasons',{}).get(job) or self.scheduler.intervention_reason or ''
            self.repo.update_group(gid,translation_recovery_state=state,translation_recovery_reason=reason,next_retry_at=None)
        notify([])

    def admitted(self,id,groups,config,stop,notify,*,line_ids=None,scope=None,exclude_ids=()):
        """Prepare admitted files only; keep one scheduler and durable job IDs."""
        from .validation import validate,check_current
        from ..documents import translatable
        from ..line_structure import validate_snapshot
        deepseek=config['provider']=='deepseek';cycle_key='deepseek_completion_cycle' if deepseek else 'kira_recovery_cycle'
        cycle=self.repo.workset(id)['cycle'];cp=self.repo.workset(id)['checkpoint'];anchor=cp.get(cycle_key,cycle)
        if deepseek:
            from ..deepseek_rolling import admission_policy
            deepseek_policy=admission_policy(cp.get('deepseek_admission_policy'))
        if cycle_key not in cp:
            cp[cycle_key]=anchor
            with self.store.transaction():self.store.db.execute('UPDATE automation_worksets SET checkpoint=? WHERE id=?',(json.dumps(cp),id))
        docs={r['id']:r for r in self.repo.rows('SELECT id,source_instance FROM documents WHERE id IN (SELECT document_id FROM automation_groups WHERE workset_id=?)',(id,))}
        by_source={docs[g['document_id']]['source_instance']:g for g in groups};source_order=list(by_source)
        complete=set();group_jobs={};job_groups={};dispatched=set()
        for source,g in by_source.items():
            rows=self.store.lines(g['document_id'])
            if all(usable(r) and r['state']=='done' for r in rows if translatable(r['source'])):
                report=validate_snapshot(self.store.document(g['document_id']),self.store.units(g['document_id']))
                if not report.structural and not report.missing and not report.errors:complete.add(source)
        def load(source):
            check_current(lambda:stop.is_set() or self.stopping)
            g=self.repo.group(by_source[source]['id'])
            proof=validate(self.repo,id,groups=[g],inputs_only=True,cancelled=lambda:stop.is_set() or self.stopping)
            if not proof['passed']:raise ValueError(' · '.join(proof['errors']+[', '.join(v['errors']) for v in proof['groups'] if v['errors']]))
            rows=self.store.lines(g['document_id']);signature=fingerprint([(r['id'],r['source_revision']) for r in rows]);policy='completion1' if config.get('translation_completion_policy')==1 else 'always4';key=f'{scope or anchor}:{policy}:{signature}'
            mapping=self.repo.field(g['id'],'batch_jobs',{});existing=mapping.get(key,[])
            selected=[r['id'] for r in rows if not usable(r) and r['id'] not in exclude_ids and
                      (line_ids is not None and r['id'] in line_ids or line_ids is None and r['attempt_kind']!='manual')]
            if not selected:complete.add(source);return None
            with self.dispatch_lock:
                check_current(lambda:stop.is_set() or self.stopping)
                if existing:
                    job=existing[0]
                    if deepseek and admission_policy(json.loads(self.store.job(job)['config']).get('deepseek_admission_policy'))!=deepseek_policy:
                        raise ValueError('DeepSeek job admission policy differs from its workset; preserve checkpoint')
                    from ..completion import reconcile_unknown
                    reconcile_unknown(self.store,[job])
                else:
                    if deepseek:
                        from ..deepseek import settings
                        cfg=settings(self.store,config['model'],config.get('deepseek_batch_size',3))
                        cfg.update(automation_owner=id,automation_cycle=anchor,deepseek_admission_policy=deepseek_policy)
                    else:
                        cfg={k:v for k,v in config.items() if k.startswith('kira_') or k in ('uncertain_retry_authorized','translation_completion_policy')}
                        cfg.update(automation_owner=id,automation_cycle=anchor,kira_multi_key=True,kira_recovery_version=4,
                                   kira_dispatch_order=source_order,kira_initial_completed=list(complete),kira_admission_key=str(scope or anchor))
                    with self.store.transaction():
                        job=self.store.create_job(g['document_id'],config['model'],config['source_lang'],config['target_lang'],config['workers'],selected,provider=config['provider'],config=cfg,allow_shared_document=True)
                        self.repo.update_group(g['id'],batch_jobs={**mapping,key:[job]},state='preparing')
                group_jobs[g['id']]=job;job_groups[job]=g['id']
                return job
        jobs=[]
        for source in source_order:
            if source in complete:continue
            job=load(source)
            if job:jobs.append(job)
            if len(jobs)>=(1 if config.get('translation_completion_policy')==1 else 10):break
        if not jobs:
            controller=getattr(self.repo,'controller',None)
            if controller:controller.preparing.clear();controller.checkpoint(id,preparing=False)
            return
        with self.dispatch_lock:
            if stop.is_set() or self.stopping:return
            self.scheduler=self.factory(self.store,self.provider_factory(self.store,self.store.job(jobs[0])),notify)
            self.scheduler.job_loader=load;self.scheduler.loader_complete=complete
            if deepseek:self.scheduler.source_order=source_order;self.scheduler.admission_key=str(scope or anchor)
            self.scheduler.network_probe=lambda:self.network_probe(config['provider'])
            def dispatch(job):
                if job not in dispatched:
                    dispatched.add(job);self.repo.update_group(job_groups[job],state='translating')
                controller=getattr(self.repo,'controller',None)
                if controller and controller.preparing.is_set():
                    controller.preparing.clear();controller.checkpoint(id,preparing=False)
                    notify([])
            self.scheduler.on_dispatch=dispatch
        while not stop.is_set() and not self.stopping:
            paused=getattr(getattr(self.repo,'controller',None),'paused',None)
            if paused is None or not paused.is_set():break
            stop.wait(.05)
        if stop.is_set() or self.stopping:return
        self.scheduler.start_many(jobs)
        while self.scheduler._thread.is_alive():
            for gid,job in list(group_jobs.items()):
                state=self.store.job(job)['state'];detail=getattr(self.scheduler,'recovery_details',{}).get(job,{})
                self.repo.update_group(gid,translation_recovery_state=state,translation_recovery_reason=detail.get('reason') or state,
                                       next_retry_at=detail.get('next_retry_at'))
            notify([])
            if stop.wait(.25):self.scheduler.stop()
        self.scheduler.join()
        for gid,job in list(group_jobs.items()):
            state=self.store.job(job)['state'];reason='' if state=='finished' else self.scheduler.job_block_reasons.get(job) or self.scheduler.intervention_reason or ''
            self.repo.update_group(gid,translation_recovery_state=state,translation_recovery_reason=reason,next_retry_at=None)
        notify([])


    def continuous(self,id,groups,config,stop,notify,*,line_ids=None,scope=None,exclude_ids=()):
        """DeepSeek keeps durable lineage and its creation-time admission policy."""
        return self.admitted(id,groups,config,stop,notify,line_ids=line_ids,scope=scope,exclude_ids=exclude_ids)


def network_ready(provider):
    """TCP reachability only; no HTTP, key, token, or translation request."""
    import socket
    from urllib.parse import urlparse
    from ..providers import KIRA_CHAT_URL
    from ..gemini import BASE_URL
    try:
        with socket.create_connection((urlparse(KIRA_CHAT_URL if provider=='kira' else BASE_URL).hostname,443),timeout=2):return True
    except OSError:return False


def runtime_for(packs,config):
    if not packs:return None
    from ..tts.devices import CPU
    runtime=packs.active()
    if config['device']=='CPU' and (not runtime or runtime.get('backend')!=CPU):
        candidate=packs.root/(packs.identity+'-cpu')
        return packs.verify(candidate,CPU) if candidate.is_dir() else None
    return runtime


def retryable(diagnostics):
    kind=diagnostics.get('failure_kind');status=diagnostics.get('http_status')
    if status in (400,401,403,404,413,422) or kind in ('authentication','permission','quota_exhausted','model_or_request','shutdown_cancelled'):return False
    if diagnostics.get('finish_reason') in ('SAFETY','RECITATION','content_filter'):return False
    return status in (408,429,500,502,503,504) or kind in ('partial_response','invalid_line_response','invalid_schema','wrong_target_language','client_timeout','connect_error','network_error','internal_error','http_server_error','http_504','restart_unknown','connect_not_sent','not_sent')


class Kokoro:
    def __init__(self,repo,tts_store,manager,packs=None,engine_factory=None):
        self.repo=repo;self.store=tts_store;self.manager=manager;self.packs=packs;self.engine_factory=engine_factory
        self.backoff=lambda phase:min(4,2**phase)
        self.before_finalize=lambda:None
    def config(self,config):
        return dict(language=config['tts_language'],voice=config['voice'],variant=config['variant'],speed=config['speed'],device=config['device'],
                    device_id=-1,format='wav',workers=1,split='lines',bitrate=128)
    def prepare(self,group,config):
        """Only the same group's owned outputs can be reused; preserve old WAVs."""
        from ..tts.output import Outputs,atomic_json,MANIFEST
        meta=group['data'];rows=[self.repo.store.line(i) for i in meta['slots']]
        if any(not usable(r) and any(c.isalpha() for c in r['source']) or not speakable(r['translation'] if r['translation'] is not None else r['source']) for r in rows):raise ValueError('Bản dịch/mapping không đủ nội dung đọc.')
        from ..tts.documents import segments
        texts=[segments(r['translation'] if r['translation'] is not None else r['source'],'none')[0]['text'] for r in rows]
        output=Outputs(self.store);run=meta.get('tts_run')
        if not run:
            run=str(uuid.uuid4());self.store.execute('INSERT INTO runs(id,created) VALUES (?,?)',(run,time.time()))
            path=Path(self.repo.store.document(group['document_id'])['path'])
            from ..languages import language
            base=path.stem+'_'+language(config['target_lang']).code
            doc=self.store.add_document(run,dict(name=base,path=str(path),text='\n'.join(texts),line_count=len(texts)),'lines')
            output.confirm(run,self.config(config),output.plan(run,'beside',None,'wav'))
            self.repo.update_group(group['id'],tts_run=run,tts_document=doc)
            group=self.repo.group(group['id']);meta=group['data']
        doc=self.store.docs(run)[0];items=self.store.items(run)
        if len(items)!=len(rows):raise ValueError('Mapping TTS thay đổi số slot; cần kiểm tra.')
        changed=[(item,text) for item,text in zip(items,texts) if item['text']!=text]
        output.reconcile(run)
        # A new text revision must not mutate the media referenced by old projects.
        folder,data=output.manifest(doc)
        conflicts=[item for item in items if (folder/item['filename']).is_file() and (record:=data['segments'].get(item['id'])) and file_hash(folder/item['filename'])!=record['sha256']]
        if changed or conflicts:
            folder,data=output.manifest(doc);n=2
            while (folder.parent/(doc['base']+f'_v{n}_{len(items)}tts')).exists():n+=1
            target=folder.parent/(doc['base']+f'_v{n}_{len(items)}tts');target.mkdir()
            copied=dict(data,segments={})
            try:
                for item in items:
                    record=data['segments'].get(item['id']);source=folder/item['filename']
                    if record and source.is_file() and file_hash(source)==record['sha256']:
                        shutil.copyfile(source,target/item['filename']);copied['segments'][item['id']]=record
                atomic_json(target/MANIFEST,copied)
            except BaseException:
                # Never delete existing outputs; this unique newly-created folder is inspectable.
                raise
            self.store.execute('UPDATE documents SET folder=?,base=? WHERE id=?',(str(target),doc['base']+f'_v{n}',doc['id']))
            for item,text in changed:self.store.edit(item['id'],text,automation_owner=group['workset_id'])
        with self.store.transaction():
            for item in self.store.items(run):
                if item['state']!='success':self.store.execute("UPDATE segments SET state='pending',attempt=NULL,overwrite_allowed=1 WHERE id=?",(item['id'],))
            self.store.execute("UPDATE runs SET state='ready',config=?,history_accepted=1 WHERE id=?",(json.dumps(self.config(config)),run))
        return run
    def run(self,group,config,stop,changed,*,rescue=False):
        from ..tts.scheduler import Scheduler
        from ..tts.devices import backend_plan,CPU
        from ..tts.output import Outputs,safe_path
        from ..tts.audio import encode
        from ..tts.process_engine import SegmentFailure,EngineFailure
        run=self.prepare(group,config);output=Outputs(self.store);cfg=self.config(config)
        if all(i['state']=='success' for i in self.store.items(run)):return self.finish(run,output)
        if shutil.disk_usage(self.store.docs(run)[0]['folder']).free<4*1024*1024:raise OSError(28,'Disk full')
        scheduler=Scheduler(self.store,self.manager,engine_factory=self.engine_factory) if self.engine_factory else Scheduler(self.store,self.manager)
        backend=backend_plan(cfg['device'])[0]
        if self.packs:
            scheduler.external_runtime=runtime_for(self.packs,config)
            if scheduler.external_runtime:backend=scheduler.external_runtime.get('backend',CPU)
        try:engine=scheduler.load_engine(cfg,backend)
        except BaseException:
            for engine in list(scheduler.engines):scheduler.retire(engine)
            raise
        counts={};cycle=self.repo.workset(group['workset_id'])['cycle'];meta=self.repo.group(group['id'])['data'];history=dict(meta.get('wave_attempt_history',{}))
        counts=dict(meta.get('wave_attempts',{})) if meta.get('wave_cycle')==cycle else {}
        self.store.status(run,'running');self.repo.update_group(group['id'],state='speaking')
        try:
            for phase in range(1 if rescue else 4):
                if stop.is_set():raise Stopped()
                for row in self.store.items(run):
                    if stop.is_set():raise Stopped()
                    if row['state']=='success' or counts.get(row['id'],0)>=5:continue
                    if row['state']=='error' and phase>0:self.store.execute("UPDATE segments SET state='pending',attempt=NULL,overwrite_allowed=1 WHERE id=?",(row['id'],))
                    item=self.store.claim(run,[row['document_id']])
                    if not item:continue
                    # Durable reservation precedes synthesis, including crash/unknown outcomes.
                    counts[item['id']]=counts.get(item['id'],0)+1
                    history[str(cycle)]=dict(counts)
                    self.repo.update_group(group['id'],wave_cycle=cycle,wave_attempts=counts,wave_attempt_history=history)
                    doc=self.store.doc(item['document_id']);folder,_=output.manifest(doc);temp=safe_path(folder/(item['id']+'.'+item['attempt']+'.part'))
                    try:
                        if shutil.disk_usage(folder).free<4*1024*1024:raise OSError(28,'Disk full')
                        info=encode(temp,engine.synthesize(item['text'],cfg['voice'],cfg['speed'],cfg['language']),'wav')
                        if not output.commit(item,temp,info,engine.backend):raise ValueError('TTS lease đã thay đổi.')
                    except (SegmentFailure,ValueError) as exc:
                        self.store.execute("UPDATE segments SET state='error',error=? WHERE id=?",(type(exc).__name__,item['id']))
                        self.repo.event(group['workset_id'],group['id'],'kokoro',f'Slot {item["position"]}: {type(exc).__name__}, lượt {counts[item["id"]]}/5')
                    except BaseException:
                        self.store.execute("UPDATE segments SET state='unknown',error='Lỗi runtime/ghi file; kiểm tra trước khi tiếp tục' WHERE id=?",(item['id'],));raise
                    finally:
                        if temp.exists():temp.unlink()
                        self.repo.progress(group['id'])
                        changed()
                if all(i['state']=='success' for i in self.store.items(run)):return self.finish(run,output)
                if not rescue and phase<3:stop.wait(self.backoff(phase))
            self.store.status(run,'partial')
            if not rescue:raise NeedsRescue('TTS còn WAV lỗi; chờ cứu lỗi sau hàng đợi thông thường.')
            raise ValueError('TTS còn WAV lỗi sau cứu lỗi cuối.')
        finally:
            scheduler.retire(engine)
            if stop.is_set():self.store.status(run,'stopped')
    def finish(self,run,output):
        docs=self.store.docs(run)
        if any(Path(d['folder']).name!=d['base']+f'_{len(self.store.items(run))}tts' for d in docs):self.before_finalize()
        output.finalize(run);self.store.status(run,'completed');return self.store.docs(run)[0]['folder']


class Capcut:
    def __init__(self,repo,tts_store):self.repo=repo;self.tts=tts_store
    def scans(self,groups):
        from ..capcut.media import MediaGroup,MediaPair,GroupScan,probe
        result=[]
        for group in groups:
            meta=self.repo.group(group['id'])['data'];doc=self.tts.docs(meta['tts_run'])[0];items=self.tts.items(meta['tts_run'])
            from ..documents import translatable
            if any(not usable(r) for r in self.repo.store.lines(group['document_id']) if translatable(r['source'])):raise ValueError('Bản dịch đã bị đánh dấu không hợp lệ; không xuất project.')
            if len(items)!=len(meta['images']) or any(i['state']!='success' for i in items):raise ValueError('Voice/mapping chưa đầy đủ.')
            media=MediaGroup(group['id'],Path(self.repo.store.document(group['document_id'])['path']).stem,meta['image_folder'],doc['folder'],meta['image_sort']);pairs=[]
            for i,(image,item) in enumerate(zip(meta['images'],items),1):
                if file_hash(image['path'])!=image['sha256']:raise ValueError('Ảnh thay đổi khi đang chạy.')
                audio=Path(doc['folder'])/item['filename']
                if file_hash(audio)!=item['sha256']:raise ValueError('WAV thay đổi khi đang chạy.')
                pairs.append(MediaPair(meta['slots'][i-1],group['id'],i,(probe(image['path'],True),),(probe(audio,False),),()))
            result.append(GroupScan(media,tuple(pairs)))
        return tuple(result)
    def run(self,id,part,config,stop,changed):
        from ..capcut.exporter import write_project,reference
        scans=self.scans(part['groups']);fp=self.fingerprint(scans,part,config)
        owned=[a for a in self.repo.artifacts(id) if a['kind']=='capcut' and a['unit']==part['id']]
        for artifact in reversed(owned):
            path=Path(artifact['path'])
            if artifact['fingerprint']==fp and path.is_dir():
                try:
                    owner=json.loads((path/'transcomic-automation.json').read_text(encoding='utf8'))
                    digest=project_hash(path)
                    if owner==dict(workset=id,unit=part['id'],fingerprint=fp) and (artifact['state']=='intent' or artifact['sha256']==digest):
                        self.repo.complete_artifact(artifact['id'],digest);return str(path)
                except (ValueError,OSError):pass
        output=Path(config['output']);name=part['name'];n=2
        while (output/name).exists():name=part['name']+f'_v{n}';n+=1
        target=output/name;aid=self.repo.artifact(id,part['id'],'capcut',fp,target)
        ownership=dict(workset=id,unit=part['id'],fingerprint=fp)
        for attempt in range(4):
            if stop.is_set():raise Stopped()
            try:
                self.repo.event(id,None,'capcut',f'{name}: lượt xuất {attempt+1}/4')
                if shutil.disk_usage(output).free<16*1024*1024:raise OSError(28,'Disk full')
                # Safe Stop does not interrupt the current atomic project.
                path=write_project(scans,output,name,progress=lambda *args:changed(),ownership=ownership,strict_target=True)
                if reference(path)!=reference(target):raise ValueError('Output collision; không nhận project ngoài kế hoạch.')
                self.repo.complete_artifact(aid,project_hash(path));return reference(path)
            except OSError as exc:
                if getattr(exc,'errno',None) not in (11,16,24) or attempt==3:raise
                if target.exists():
                    marker=target/'transcomic-automation.json'
                    if marker.is_file() and json.loads(marker.read_text(encoding='utf8'))==ownership:
                        self.repo.complete_artifact(aid,project_hash(target));return str(target)
                stop.wait(min(4,2**attempt))
    def fingerprint(self,scans,part,config):
        snapshot=[(s.group.id,[(p.id,p.images[0].path,file_hash(p.images[0].path),p.audios[0].path,file_hash(p.audios[0].path),p.duration_us) for p in s.rows]) for s in scans]
        return fingerprint(dict(name=part['name'],output=config['output'],snapshot=snapshot))


def project_hash(path):
    return fingerprint([(str(p.relative_to(path)),file_hash(p)) for p in sorted(Path(path).rglob('*')) if p.is_file()])
