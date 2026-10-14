"""Read-only analysis of prior API evidence; metadata only, no credentials or HTTP."""
import json,sqlite3,statistics
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'artifacts/wrong-language/live/results.sqlite3'
c=sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)
rows=[json.loads(r[0]) for r in c.execute('SELECT diagnostics FROM request_attempts WHERE diagnostics IS NOT NULL')]
def stats(key,selected=rows):
    v=[r[key] for r in selected if isinstance(r.get(key),(float,int))]
    return {'count':len(v),'median':statistics.median(v) if v else 'unknown','max':max(v) if v else 'unknown'}
report={'requests':len(rows),'http_504':sum(r.get('http_status')==504 for r in rows),
        'http_429':sum(r.get('http_status')==429 for r in rows),
        'timings':{k:stats(k) for k in ('queue_wait_seconds','http_seconds','database_seconds','parse_seconds','gate_wait_seconds','reasoning_tokens')},
        'http_504_timings':stats('http_seconds',[r for r in rows if r.get('http_status')==504]),
        'active_at_dispatch':stats('active_at_dispatch'),
        'max_tokens_configurations':list({r.get('max_tokens') for r in rows}),
        'largest_outputs':[{k:r.get(k,'unknown') for k in ('source_chars','request_chars','context_lines','content_chars','finish_reason','reasoning_tokens')} |
                           {'completion_tokens':r.get('usage',{}).get('completion_tokens',0)} for r in sorted(rows,key=lambda r:r.get('usage',{}).get('completion_tokens',0),reverse=True)[:10]],
        'limitations':['old TCP and header timestamps unavailable','dashboard receipt time unavailable','no content recovery API documented','reasoning breakdown absent']}
c.close()
out=root/'artifacts/performance/old-log-analysis.json';out.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
