"""Read-only comparison of the authorized six passes and offline benchmarks."""
import hashlib
import json
import sqlite3
from pathlib import Path
from zipfile import ZipFile

ROOT=Path('artifacts/retry-speed')


def peak_concurrency(requests):
    events=[pair for r in requests if r.get('ended_monotonic') for pair in [(r['started_monotonic'],1),(r['ended_monotonic'],-1)]]
    active=peak=0
    for _,delta in sorted(events):active+=delta;peak=max(peak,active)
    return peak


def analyze():
    ledger=json.loads((ROOT/'live/authorization-ledger.json').read_text(encoding='utf-8'))
    passes=[];db=sqlite3.connect(ROOT/'live/results.sqlite3');db.row_factory=sqlite3.Row
    for entry in ledger['passes']:
        assert entry['state']=='completed' and entry['summary']['missing']==0
        requests=entry['requests'];summary={**entry['summary']};retry_timing=[]
        for r in requests:
            if r['attempt_number']<=1:continue
            previous=next(p for p in requests if p['batch_id']==r['batch_id'] and p['attempt_number']==r['attempt_number']-1)
            diag=json.loads(db.execute('SELECT diagnostics FROM request_attempts WHERE id=?',(previous['correlation_id'],)).fetchone()[0])
            retry_timing.append({'reason':diag.get('failure_kind'),'previous_http_status':previous['http_status'],'initial_line_count':len(previous['line_ids']),'retry_line_count':len(r['line_ids']),'response_to_retry_http_seconds':r['started_monotonic']-previous['ended_monotonic'],'retry_http_seconds':r['http_seconds'],'retry_started_before_last_initial_completed':r['started_monotonic']<max(p['ended_monotonic'] for p in requests if p['attempt_number']==1),'saved_successful_lines_not_resent':r['line_ids']==previous['line_ids'] if previous['http_status']==504 else len(r['line_ids'])<len(previous['line_ids'])})
        for name,initial in [('initial',True),('retry',False)]:
            phase=[r for r in requests if (r['attempt_number']==1)==initial]
            summary['phases'][name]['peak_phase_http_concurrency']=peak_concurrency(phase)
            summary['phases'][name]['gui_timing_available']=False # Headless live runner; native GUI smoke tests acknowledgments separately.
        trace=db.execute('SELECT COUNT(*) FROM api_text_versions a JOIN lines l ON a.line_id=l.id WHERE l.document_id=? AND accepted=1',(entry['document_id'],)).fetchone()[0]
        assert trace==summary['done']
        exported=Path(entry['exports'][0]['path']);assert exported.is_file()
        with ZipFile(entry['source']) as source_zip, ZipFile(exported) as output_zip:
            unchanged_parts=all(source_zip.read(n)==output_zip.read(n) for n in source_zip.namelist() if n!='word/document.xml')
            assert set(source_zip.namelist())==set(output_zip.namelist()) and unchanged_parts
        source_hash=hashlib.sha256(Path(entry['source']).read_bytes()).hexdigest()
        assert source_hash==next(s['sha256'] for s in ledger['sources'] if s['path']==entry['source'])
        passes.append({'file':Path(entry['source']).name,'source':entry['source'],'pass_number':entry['pass_number'],'summary':summary,'retry_timing':retry_timing,'export':str(exported),'accepted_trace_rows':trace,'source_unchanged':True,'docx_other_parts_unchanged':unchanged_parts})
    counts={s['path']:sum(e['source']==s['path'] for e in ledger['passes']) for s in ledger['sources']}
    assert all(n==2 for n in counts.values()) and not db.execute('PRAGMA foreign_key_check').fetchall()
    assert len({r['correlation_id'] for e in ledger['passes'] for r in e['requests']})==sum(len(e['requests']) for e in ledger['passes'])
    max_attempt=db.execute('SELECT MAX(attempt_number) FROM request_attempts').fetchone()[0]
    db.close()
    before=json.loads((ROOT/'before.json').read_text(encoding='utf-8'));after=json.loads((ROOT/'after.json').read_text(encoding='utf-8'))
    offline=[{'scenario':a['scenario'],'before':b,'after':a,'elapsed_reduction_percent':(1-a['elapsed_seconds']/b['elapsed_seconds'])*100} for b,a in zip(before,after)]
    totals={'full_file_passes':len(passes),'requests':sum(p['summary']['requests'] for p in passes),'lines_done':sum(p['summary']['done'] for p in passes),'missing':0,'429':sum(p['summary']['429'] for p in passes),'504':sum(p['summary']['504'] for p in passes),'retries':sum(p['summary']['retry_requests'] for p in passes),'max_attempt':max_attempt,'usage':{k:sum(p['summary']['usage'].get(k,0) for p in passes) for k in ['prompt_tokens','completion_tokens','total_tokens']},'estimated_original_vnd_reported_usage':sum(p['summary']['estimated_vnd_original_reported_usage'] for p in passes),'estimated_sale_vnd_reported_usage':sum(p['summary']['estimated_vnd_sale_reported_usage'] for p in passes),'requests_without_usage':sum(p['summary']['requests_without_usage'] for p in passes),'provider':'kira','model':ledger['model'],'gemini_requests':0}
    report={'offline_benchmarks':offline,'passes':passes,'totals':totals,'authorization_counts':counts,'limits':'At most two whole-file passes per supplied path, five retries after initial; no separate price/token ceiling per user','cost_limitations':'Usage-derived estimate only, not wallet charge. HTTP 504 supplied no usage. No real 429 in these six passes; recovery verified using mock.'}
    (ROOT/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(totals))


if __name__=='__main__':analyze()
