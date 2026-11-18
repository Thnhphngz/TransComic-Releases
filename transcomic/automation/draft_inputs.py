"""Input intents for the current session only; never replayed after app restart."""
import json
from uuid import uuid4


def pending(repo, workset, key):
    work=repo.workset(workset)
    return work['checkpoint'].get(key,[]) if work else []


def remember(repo,workset,key,**fields):
    entry=dict(token=str(uuid4()),**fields)
    with repo.store.transaction():
        repo.editable(workset);work=repo.workset(workset);cp=work['checkpoint']
        entries=cp.get(key,[])
        if 'group' in fields:entries=[e for e in entries if e['group']!=fields['group']]
        cp[key]=[*entries,entry]
        repo.execute('UPDATE automation_worksets SET checkpoint=? WHERE id=?',(json.dumps(cp,ensure_ascii=False),workset))
    return entry


def forget(repo,workset,key,token):
    with repo.store.transaction():
        work=repo.workset(workset)
        if not work:return
        cp=work['checkpoint'];cp[key]=[e for e in cp.get(key,[]) if e['token']!=token]
        repo.execute('UPDATE automation_worksets SET checkpoint=? WHERE id=?',(json.dumps(cp,ensure_ascii=False),workset))
