"""Reports are derived from the same checkpoints, without provider credentials."""
import html
import json
from pathlib import Path
import time
from .repository import fingerprint


def snapshot(repo,id,tts=None):
    work=repo.workset(id);groups=repo.groups(id);cfg=work['config'];items=[]
    from ..status import usable
    from ..documents import translatable
    for g in groups:
        rows=repo.store.lines(g['document_id']);meta=g['data'];waves=tts.items(meta['tts_run']) if tts and meta.get('tts_run') else []
        batches=[]
        for key,jobs in meta.get('batch_jobs',{}).items():
            attempts=[a for bid in repo.batch_ids(jobs) for a in repo.store.attempts(bid)]
            batches.append(dict(cycle_batch=key,attempts=[dict(number=i+1,state=a['state'],http_status=(a.get('diagnostics') or {}).get('http_status'),failure_kind=(a.get('diagnostics') or {}).get('failure_kind'),usage=(a.get('diagnostics') or {}).get('usage')) for i,a in enumerate(attempts)]))
        items.append(dict(id=g['id'],name=Path(repo.store.document(g['document_id'])['path']).name,state=meta['state'],error=meta.get('error',''),batches=batches,
                          translated=sum(usable(r) for r in rows if translatable(r['source'])),translation_total=sum(translatable(r['source']) for r in rows),
                          wav_valid=sum(i['state']=='success' for i in waves),wav_total=len(meta.get('slots',[])),wave_attempts=meta.get('wave_attempts',{}),wave_attempt_history=meta.get('wave_attempt_history',{})))
    checkpoints=work['checkpoint'];parts=checkpoints.get('parts',[])
    return dict(workset=id,name=work['name'],state=work['state'],cycle=work['cycle'],created=work['created'],started=checkpoints.get('started'),ended=checkpoints.get('ended'),
                provider=cfg['provider'],model=cfg['model'],tts={k:cfg[k] for k in ('voice','speed','variant','device','format')},capcut_mode=cfg['capcut_mode'],
                groups=items,parts=parts,artifacts=repo.artifacts(id),events=list(reversed(repo.events(id))),
                totals=dict(groups=len(items),completed=sum(i['state']=='completed' for i in items),needs_attention=sum(i['state']=='needs_attention' for i in items),
                            translation_done=sum(i['translated'] for i in items),translation_total=sum(i['translation_total'] for i in items),
                            wav_done=sum(i['wav_valid'] for i in items),wav_total=sum(i['wav_total'] for i in items),
                            projects_done=sum(p.get('state')=='completed' for p in parts),projects_total=len(parts)))


def write(repo,id,tts=None,folder=None,*,state=None):
    from ..documents import atomic_export
    groups=repo.groups(id)
    if not groups:raise ValueError('Bộ công việc chưa có tài liệu.')
    folder=Path(folder) if folder else Path(repo.store.document(groups[0]['document_id'])['path']).parent/'TransComic_Automation_Reports'
    folder.mkdir(parents=True,exist_ok=True);data=snapshot(repo,id,tts);name=f'Automation_{id}_cycle{data["cycle"]}_{time.time_ns()}'
    if state:data['state']=state
    raw=json.dumps(data,ensure_ascii=False,indent=2).encode('utf8')
    page='<html lang="vi"><meta charset="utf-8"><title>TransComic Automation</title><style>body{font:16px system-ui;max-width:1000px;margin:30px auto}pre{white-space:pre-wrap}</style><h1>'+html.escape(data['name'])+'</h1><pre>'+html.escape(raw.decode())+'</pre></html>'
    json_path=folder/(name+'.json');html_path=folder/(name+'.html')
    atomic_export(json_path,raw,False);atomic_export(html_path,page.encode('utf8'),False)
    return dict(json=str(json_path),html=str(html_path))
