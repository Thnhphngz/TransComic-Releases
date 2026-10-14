"""Read-only verification of the completed authorized round; no network calls."""
import json,hashlib,sqlite3,zipfile,io
from collections import Counter
from pathlib import Path
from transcomic.languages import language
from transcomic.quality import language_evidence,warnings

OUT=Path('artifacts/multilingual/live')

def main():
    ledger=json.loads((OUT/'authorization-ledger.json').read_text(encoding='utf-8'))
    db=sqlite3.connect((OUT/'results.sqlite3').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    results=[];barriers=[];semantic=[]
    for source in ledger['sources']:
        assert hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()==source['sha256']
        entries=[e for e in ledger['passes'] if e['source']==source['path']]
        assert len(entries)==3 and [e['locale'] for e in entries]==source['locales']
        for before,after in zip(entries,entries[1:]):
            end=max(r['ended_monotonic'] for r in before['requests']);begin=min(r['started_monotonic'] for r in after['requests'])
            assert begin>end
            barriers.append({'file':Path(source['path']).name,'before':before['locale'],'after':after['locale'],'last_response_to_next_http_seconds':begin-end,'overlap':False})
        for e in entries:
            assert e['state']=='completed' and e['summary']['done']==e['summary']['lines']
            doc=db.execute('SELECT * FROM documents WHERE id=?',(e['document_id'],)).fetchone()
            rows=[dict(r) for r in db.execute('SELECT * FROM lines WHERE document_id=? ORDER BY ordinal',(e['document_id'],))]
            evidence=Counter();kinds=Counter()
            for row in rows:
                evidence[language_evidence(row['source'],row['translation'],'vi',e['locale'])[0]]+=1
                for kind,_ in warnings({**row,'source_lang':'vi','target_lang':e['locale']}):kinds[kind]+=1
                for phrase in ('bị mù màu sao','ly hôn ư','dài như sớ'):
                    if phrase in row['source'].casefold():semantic.append({'file':Path(source['path']).name,'locale':e['locale'],'ordinal':row['ordinal']+1,'phrase':phrase,'source':row['source'],'translation':row['translation'],'warning_kinds':[k for k,_ in warnings({**row,'source_lang':'vi','target_lang':e['locale']})]})
            trace=db.execute('SELECT COUNT(*) FROM api_text_versions v JOIN lines l ON l.id=v.line_id WHERE l.document_id=? AND v.accepted=1',(e['document_id'],)).fetchone()[0]
            assert trace==len(rows)
            for output in e['exports']:
                target=Path(output['path']);assert target.name==Path(source['path']).stem+'_'+language(e['locale']).code+'.docx'
                with zipfile.ZipFile(io.BytesIO(doc['snapshot'])) as original,zipfile.ZipFile(target) as exported:
                    assert set(original.namelist())==set(exported.namelist())
                    assert all(original.read(n)==exported.read(n) for n in original.namelist() if n!='word/document.xml')
            requests=e['requests'];intervals=sorted([(r['started_monotonic'],1) for r in requests]+[(r['ended_monotonic'],-1) for r in requests]);active=peak=0
            for _,delta in intervals:active+=delta;peak=max(peak,active)
            assert peak<=30
            results.append({'file':Path(source['path']).name,'locale':e['locale'],**e['summary'],'peak_actual_http':peak,'local_evidence_current':dict(evidence),'warning_kinds_current':dict(kinds),'accepted_trace_count':trace,'docx_untranslated_parts_unchanged':True,'exports':e['exports']})
    assert not list(db.execute('PRAGMA foreign_key_check'));db.close()
    request_ids=[r['correlation_id'] for e in ledger['passes'] for r in e['requests']];assert len(set(request_ids))==len(request_ids)
    usage={k:sum(r['usage'].get(k,0) for r in results) for k in ('prompt_tokens','completion_tokens','total_tokens')}
    summary={'full_file_locale_passes':len(results),'passes_per_file':3,'requests':sum(r['requests'] for r in results),'done':sum(r['done'] for r in results),'lines':sum(r['lines'] for r in results),'retries':sum(r['retries'] for r in results),'429':sum(r['429'] for r in results),'504':sum(r['504'] for r in results),'max_attempt':max(r['max_attempt'] for r in results),'usage':usage,'requests_without_usage':sum(r['requests_without_usage'] for r in results),'original_files_unchanged':True,'gemini_requests':0,'semantic_quality_certified':False,'barriers_verified':len(barriers)}
    report={'summary':summary,'passes':results,'language_barriers':barriers,'aligned_user_phrase_candidates':semantic}
    (OUT.parent/'verification.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False));print(json.dumps(semantic,ensure_ascii=False))

if __name__=='__main__':main()
