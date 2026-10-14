"""New authorization: VI→EN, exact three DOCX, <=3 full-file runs/file.

Each run includes the scheduler's initial requests and <=5 retries. Reservations
persist before HTTP; unfinished runs never replay. No prior ledger is reused.
"""
import argparse,json,time,math,hashlib,os
from pathlib import Path
from transcomic.storage import Store
from transcomic.bulk import import_many,plan_exports,write_exports
from transcomic.documents import translatable
from transcomic.translation import Scheduler
from transcomic.providers import KiraProvider
from transcomic.language_validator import validator,export_faults
from scripts.live_kira_three import key_readonly,save
import scripts.live_three_docx_speed as prior

OUT=Path('artifacts/wrong-language/live')
SOURCES=[Path('D:/Sourch Code/TransComic')/f'{stem}.docx' for stem in ('15-16','17-18','19-20')]
MODEL='deepseek-v4.1-flash'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pass-number',type=int,choices=(1,2,3),required=True)
    parser.add_argument('--files',nargs='+',choices=[p.stem for p in SOURCES],default=[p.stem for p in SOURCES])
    parser.add_argument('--concurrency',type=int,choices=range(1,51),default=30);args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);prior.OUT=OUT;path=OUT/'authorization-ledger.json'
    sources=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in SOURCES]
    if path.exists():
        ledger=json.loads(path.read_text(encoding='utf-8'));assert ledger['sources']==sources
        if any(e['state'] not in ('completed','stopped') for e in ledger['passes']):raise RuntimeError('Unfinished reservation: no replay')
    else:
        ledger={'authorization':'2026-10-13 urgent wrong-language fix: Kira DeepSeek, <=3 full-file tests per exact file, <=9 total, no budget question','model':MODEL,'max_passes_per_file':3,'sources':sources,'passes':[]}
        with path.open('x',encoding='utf-8') as f:json.dump(ledger,f);f.flush();os.fsync(f.fileno())
    key=key_readonly();store=Store(OUT/'results.sqlite3')
    try:
        store.set_setting('auto_retries','5')
        for source in SOURCES:
            if source.stem not in args.files:continue
            if any(e['source']==str(source) and e['pass_number']==args.pass_number for e in ledger['passes']):continue
            assert sum(e['source']==str(source) for e in ledger['passes'])<3 and len(ledger['passes'])<9
            doc=import_many(store,[source],'vi','en')['document_ids'][0]
            needed=sum(translatable(r['source']) for r in store.lines(doc));maximum=math.ceil(needed/3)*6
            job=store.create_job(doc,MODEL,'vi','en',args.concurrency,retry_504=True,max_requests=maximum)
            entry={'source':str(source),'pass_number':args.pass_number,'locale':'en','document_id':doc,'job_id':job,'max_requests':maximum,'state':'reserved_before_start','requests':[],'configuration':store.job(job)}
            ledger['passes'].append(entry);save(path,ledger)
            scheduler=Scheduler(store,None);transport=prior.LedgerTransport(ledger,entry,scheduler,store)
            scheduler.provider=KiraProvider(key,MODEL,timeout=90,transport=transport,prompt_version=store.job(job)['prompt_version'])
            start=time.monotonic();scheduler.start(job)
            while scheduler._thread.is_alive():
                scheduler.join(1)
                if time.monotonic()-start>1800:scheduler.stop()
            rows=store.lines(doc);attempts=[a for b in store.batches(job) for a in store.attempts(b['id'])]
            quality_attempts=[a for a in attempts if (a['diagnostics'] or {}).get('failure_kind')=='wrong_target_language']
            evidence={k:0 for k in ('VALID','WRONG_LANGUAGE_CONFIRMED','SUSPECTED_WRONG_LANGUAGE','INSUFFICIENT_EVIDENCE')}
            for row in rows:evidence[validator.validate(row['source'],row['translation'] or '','vi','en').conclusion]+=1
            entry['summary']={'state':store.job(job)['state'],'rows':len(rows),'done':sum(r['state']=='done' for r in rows),'requests':len(entry['requests']),'retry_requests':scheduler.retry_count,'max_attempt':max((a['attempt_number'] for a in attempts),default=0),'quality_rejected_attempts':len(quality_attempts),'quality_rejected_lines':sum(len((a['diagnostics'] or {}).get('wrong_language_ids',[])) for a in quality_attempts),'429':sum(r.get('http_status')==429 for r in entry['requests']),'504':sum(r.get('http_status')==504 for r in entry['requests']),'elapsed_seconds':time.monotonic()-start,'usage':scheduler.usage,'language_checks':evidence,'export_faults':export_faults(store.document(doc),rows),'source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==next(s['sha256'] for s in sources if s['path']==str(source))}
            entry['state']='stopped' if scheduler._stopped.is_set() or scheduler.intervention_reason else 'completed'
            save(path,ledger) # completed HTTP must never replay after an export/report exception
            entry['exports']=write_exports(store,plan_exports(store.export_snapshot([doc]),OUT/f'pass-{args.pass_number}',mode='custom'),allow_incomplete=True)
            save(path,ledger);save(OUT/f'{source.stem}-pass-{args.pass_number}-rows.json',rows);save(OUT/f'{source.stem}-pass-{args.pass_number}-warnings.json',store.warning_rows(doc));save(OUT/f'{source.stem}-pass-{args.pass_number}-console.json',store.log.snapshot())
            print(json.dumps({'file':source.name,'pass':args.pass_number,**entry['summary'],'exports':entry['exports']}),flush=True)
            if scheduler._stopped.is_set() or scheduler.intervention_reason:break
    finally:store.close()

if __name__=='__main__':main()
