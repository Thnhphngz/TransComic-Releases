"""Experimental scoped facts/context, frozen in existing job config; no global DB."""
from copy import deepcopy
from bisect import bisect_left
import json
import re

CONTEXT_LIMITS=(8,12,16)
CONTEXT_CHARS=4000
FACT_CHARS=1000
FACT_COUNT=8


def validate_profile(profile,series_id,document_id):
    if profile is None:return None
    if not isinstance(profile,dict) or set(profile)!={'series_id','revision','documents','facts'}:raise ValueError('Invalid series profile')
    if not isinstance(series_id,str) or not series_id or profile['series_id']!=series_id:raise ValueError('Facts belong to another series')
    if not isinstance(profile['revision'],str) or not profile['revision']:raise ValueError('Profile needs revision')
    documents=profile['documents']
    if not isinstance(documents,dict) or document_id not in documents or any(not isinstance(k,str) or type(v) is not int or v<0 for k,v in documents.items()):
        raise ValueError('Document not bound to this series profile')
    values=profile['facts']
    if not isinstance(values,list) or len(values)>50:raise ValueError('At most 50 evidenced facts')
    ids=set()
    for row in values:
        if not isinstance(row,dict) or set(row)!={'id','fact','aliases','evidence','valid_from','valid_until','scene','verified'}:raise ValueError('Invalid fact schema')
        if not isinstance(row['id'],str) or not row['id'] or row['id'] in ids:raise ValueError('Fact IDs must be unique')
        ids.add(row['id'])
        if row['verified'] is not True or not isinstance(row['fact'],str) or not row['fact'].strip() or len(row['fact'])>300:raise ValueError('Fact needs verification and bounded text')
        if not isinstance(row['aliases'],list) or not 1<=len(row['aliases'])<=8 or any(not isinstance(a,str) or not a.strip() or len(a)>60 for a in row['aliases']):raise ValueError('Fact aliases invalid')
        if type(row['valid_from']) is not int or row['valid_from']<0 or row['valid_until'] is not None and (type(row['valid_until']) is not int or row['valid_until']<row['valid_from']):raise ValueError('Fact interval invalid')
        if row['scene'] is not None and (not isinstance(row['scene'],str) or not row['scene']):raise ValueError('Invalid scene scope')
        if not isinstance(row['evidence'],list) or not 1<=len(row['evidence'])<=4:raise ValueError('Fact needs evidence')
        for evidence in row['evidence']:
            if not isinstance(evidence,dict) or set(evidence)!={'position','reference'} or type(evidence['position']) is not int or evidence['position']<0 or not isinstance(evidence['reference'],str) or not evidence['reference'].strip() or len(evidence['reference'])>200:raise ValueError('Evidence needs source position/reference')
    if len(json.dumps(profile,ensure_ascii=False))>20000:raise ValueError('Profile too large')
    return deepcopy(profile)


def select_facts(profile,series_id,document_id,ordinal,text,scene=None):
    profile=validate_profile(profile,series_id,document_id)
    if profile is None:return []
    position=profile['documents'][document_id]+ordinal
    selected=[];budget=FACT_CHARS
    for fact in profile['facts']:
        if fact['valid_from']>position or fact['valid_until'] is not None and position>=fact['valid_until']:continue
        if max(e['position'] for e in fact['evidence'])>position:continue
        if fact['scene'] is not None and fact['scene']!=scene:continue
        if not any(re.search(r'(?<!\w)'+re.escape(a)+r'(?!\w)',text,re.I) for a in fact['aliases']):continue
        if len(fact['fact'])>budget:continue
        selected.append(dict(fact=fact['fact'],evidence=[e['reference'] for e in fact['evidence']]))
        budget-=len(fact['fact'])
        if len(selected)==FACT_COUNT:break
    return selected


def references(rows,chunk,limit=8,mode='past'):
    if type(limit) is not int or limit not in CONTEXT_LIMITS or mode not in ('past','current'):raise ValueError('Unsupported experimental context')
    if mode=='current' and limit!=8:raise ValueError('Current context is fixed at eight')
    targets={r['id'] for r in chunk}
    if not chunk or len(targets)!=len(chunk):raise ValueError('Missing/duplicate target IDs')
    documents={r.get('document_id') for r in rows+chunk}
    if len(documents)!=1:raise ValueError('Foreign document context')
    if mode=='past':
        first=min(r['ordinal'] for r in chunk)
        # Store.lines is ordinal-ordered. Locate the boundary, then inspect at
        # most N neighbors rather than sort the entire prefix for each batch.
        boundary=bisect_left(rows,first,key=lambda r:r['ordinal'])
        neighbors=list(reversed(rows[max(0,boundary-limit):boundary]))
    else:
        # Exact legacy selection: four source neighbors on each side, then
        # nearest eight, with the existing 4000-character whole-line cap.
        candidates={r['id']:r for x in chunk for r in rows[max(0,x['ordinal']-4):x['ordinal']+5]}
        neighbors=sorted((r for r in candidates.values() if r['id'] not in targets),key=lambda r:min(abs(r['ordinal']-x['ordinal']) for x in chunk))[:8]
    result=[];budget=CONTEXT_CHARS
    order=sorted(neighbors,key=lambda r:r['ordinal'],reverse=mode=='past')
    for row in order:
        if len(row['source'])<=budget:
            result.append(dict(id=row['id'],source=row['source']));budget-=len(row['source'])
    by_id={r['id']:r['ordinal'] for r in neighbors}
    return sorted(result,key=lambda r:by_id[r['id']])


def freeze_options(config,document_id):
    config=deepcopy(config)
    if config.get('semantic_facts'):raise ValueError('V3 facts require an explicit series profile')
    limit=config.get('semantic_context_lines',8);mode=config.get('semantic_context_mode','past')
    if type(limit) is not int or limit not in CONTEXT_LIMITS or mode not in ('past','current') or mode=='current' and limit!=8:raise ValueError('Invalid context options')
    profile=validate_profile(config.get('semantic_profile'),config.get('semantic_series_id'),document_id)
    scene=config.get('semantic_scene')
    if scene is not None and (not isinstance(scene,str) or not scene):raise ValueError('Invalid scene')
    config.update(semantic_profile=profile,semantic_context_lines=limit,semantic_context_mode=mode)
    return config


def batch_context(rows,chunk,config,document_id):
    context=references(rows,chunk,config['semantic_context_lines'],config['semantic_context_mode'])
    # Fact relevance uses targets and past references only. A future reference
    # in the matched legacy ablation cannot trigger a future entity's facts.
    first=min(r['ordinal'] for r in chunk)
    past_ids={r['id'] for r in rows if r['ordinal']<first} if config['semantic_context_mode']=='current' else {r['id'] for r in context}
    text=' '.join(r['source'] for r in chunk)+ ' '+ ' '.join(r['source'] for r in context if r['id'] in past_ids)
    facts=select_facts(config.get('semantic_profile'),config.get('semantic_series_id'),document_id,first,text,config.get('semantic_scene'))
    return context,facts
