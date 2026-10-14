"""Offline export from accepted API paragraphs of the exact authorized sources.

No HTTP. Keep every live run's original state/counts; record per-line provenance
when an earlier run supplies a valid paragraph missing from a later run.
"""
import json,sqlite3,hashlib
from pathlib import Path
from transcomic.bulk import import_many,plan_exports,write_exports
from transcomic.storage import Store
from transcomic.status import usable
from transcomic.language_validator import validator,WRONG_LANGUAGE_CONFIRMED
from scripts.live_kira_three import save

OUT=Path('artifacts/wrong-language/live')
def main():
    ledger=json.loads((OUT/'authorization-ledger.json').read_text(encoding='utf-8'))
    assert all(e['state'] in ('completed','stopped') for e in ledger['passes'])
    source_db=sqlite3.connect((OUT/'results.sqlite3').resolve().as_uri()+'?mode=ro',uri=True);source_db.row_factory=sqlite3.Row
    source_db.execute('BEGIN')
    output_db=OUT/'verified.sqlite3'
    if output_db.exists():raise ValueError('Existing reconciliation retained; do not replace')
    store=Store(output_db);documents=[];reports=[]
    try:
        for source in ledger['sources']:
            path=Path(source['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==source['sha256']
            entries=sorted([e for e in ledger['passes'] if e['source']==str(path)],key=lambda e:e['pass_number'],reverse=True)
            doc=import_many(store,[path],'vi','en')['document_ids'][0];documents.append(doc);chosen=[]
            for row in store.lines(doc):
                candidate=None
                for entry in entries:
                    assert entry['locale']=='en' and entry['configuration']['model']==ledger['model']
                    old=source_db.execute('SELECT * FROM lines WHERE document_id=? AND ordinal=?',(entry['document_id'],row['ordinal'])).fetchone()
                    if old is None:continue
                    old=dict(old);assert old['source']==row['source']
                    if old['state']!='done' or not usable(old):continue
                    trace=source_db.execute('SELECT v.*,a.original_batch_id,a.attempt_number FROM api_text_versions v JOIN request_attempts a ON a.id=v.attempt_id JOIN batches b ON b.id=a.original_batch_id WHERE v.line_id=? AND v.processed_text=? AND v.accepted=1 AND b.job_id=? ORDER BY a.attempt_number DESC LIMIT 1',(old['id'],old['translation'],entry['job_id'])).fetchone()
                    if trace is None:continue
                    check=validator.validate(row['source'],old['translation'],'vi','en',old['id'])
                    if check.conclusion==WRONG_LANGUAGE_CONFIRMED:continue
                    candidate=(entry,old,dict(trace),check);break
                if candidate is None:raise ValueError(f"No accepted API paragraph: {path.name}, ordinal {row['ordinal']+1}")
                entry,old,trace,check=candidate
                store.edit_line(row['id'],'translation',old['translation'])
                chosen.append({'ordinal':row['ordinal']+1,'live_pass':entry['pass_number'],'original_line_id':old['id'],'attempt_id':trace['attempt_id'],'batch_id':trace['original_batch_id'],'attempt_number':trace['attempt_number'],'language_check':check.conclusion})
            reports.append({'file':path.name,'source_sha256':source['sha256'],'document_id':doc,'rows':len(chosen),'paragraph_provenance':chosen,'uses_earlier_pass':any(r['live_pass']!=entries[0]['pass_number'] for r in chosen)})
        exports=write_exports(store,plan_exports(store.export_snapshot(documents),OUT/'verified',mode='custom'))
        assert all(e['state']=='exported' for e in exports)
        save(OUT/'verified-provenance.json',{'kind':'offline reconciliation of accepted API text; not an additional live test or semantic certificate','live_runs':len(ledger['passes']),'documents':reports,'exports':exports})
        print(json.dumps({'exports':exports,'rows':sum(r['rows'] for r in reports),'uses_earlier_pass':{r['file']:r['uses_earlier_pass'] for r in reports}}),flush=True)
    finally:source_db.close();store.close()
if __name__=='__main__':main()
