"""Read-only audit of exact sources, actual exports, and new authorization ledger."""
import json,sqlite3,hashlib
from pathlib import Path
from zipfile import ZipFile
from transcomic.docx_document import import_docx
from transcomic.language_validator import validator,WRONG_LANGUAGE_CONFIRMED,SUSPECTED_WRONG_LANGUAGE

OUT=Path('artifacts/wrong-language/live')
def main():
    ledger=json.loads((OUT/'authorization-ledger.json').read_text(encoding='utf-8'))
    db=sqlite3.connect((OUT/'results.sqlite3').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    audits=[]
    for entry in ledger['passes']:
        if entry['state'] not in ('completed','stopped'):raise ValueError('Live pass still running')
        source=Path(entry['source']);rows=[dict(r) for r in db.execute('SELECT * FROM lines WHERE document_id=? ORDER BY ordinal',(entry['document_id'],))]
        attempts=[dict(r) for r in db.execute('SELECT a.* FROM request_attempts a JOIN batches b ON b.id=a.original_batch_id WHERE b.job_id=?',(entry['job_id'],))]
        audit={'file':source.name,'pass':entry['pass_number'],'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_unchanged':entry['summary']['source_unchanged'],'all_attempts_finished':all(a['state']=='finished' for a in attempts),'max_attempt':max(a['attempt_number'] for a in attempts),'attempt_count_matches_ledger':len(attempts)==len(entry['requests']),'exports':[]}
        for export in entry['exports']:
            if export['state']!='exported':audit['exports'].append(export);continue
            target=Path(export['path']);s,t=import_docx(source),import_docx(target)
            checks=[validator.validate(a.text,b.text,'vi','en') for a,b in zip(s.units,t.units)]
            with ZipFile(source) as original,ZipFile(target) as output:
                same_parts=set(original.namelist())==set(output.namelist())
                untouched=same_parts and all(original.read(name)==output.read(name) for name in original.namelist() if name!='word/document.xml')
            audit['exports'].append({'path':str(target),'source_units':len(s.units),'export_units':len(t.units),'all_export_units_match_saved_text':len(t.units)==len(rows) and all(u.text.strip()==(r['translation'] or r['source']).strip() for u,r in zip(t.units,rows)),'confirmed_language_fault_ordinals':[i+1 for i,c in enumerate(checks) if c.conclusion==WRONG_LANGUAGE_CONFIRMED],'suspected_language_fault_ordinals':[i+1 for i,c in enumerate(checks) if c.conclusion==SUSPECTED_WRONG_LANGUAGE],'unchanged_zip_part_set':same_parts,'unchanged_non_document_parts':untouched})
        audits.append(audit)
    requests=[r for e in ledger['passes'] for r in e['requests']]
    report={'full_file_runs':len(ledger['passes']),'runs_per_file':{s['path']:sum(e['source']==s['path'] for e in ledger['passes']) for s in ledger['sources']},'unique_http_correlations':len({r['correlation_id'] for r in requests})==len(requests),'requests':len(requests),'requests_without_usage':sum(not r.get('usage') for r in requests),'audits':audits}
    provenance_path=OUT/'verified-provenance.json'
    if provenance_path.exists():
        provenance=json.loads(provenance_path.read_text(encoding='utf-8'))
        verified_db=sqlite3.connect((OUT/'verified.sqlite3').resolve().as_uri()+'?mode=ro',uri=True);verified_db.row_factory=sqlite3.Row
        report['verified_exports']=[]
        for exported in provenance['exports']:
            doc=next(d for d in provenance['documents'] if d['document_id']==exported['document_id'])
            source=next(Path(s['path']) for s in ledger['sources'] if Path(s['path']).name==doc['file']);target=Path(exported['path'])
            original_units,export_units=import_docx(source).units,import_docx(target).units
            rows=[dict(r) for r in verified_db.execute('SELECT * FROM lines WHERE document_id=? ORDER BY ordinal',(doc['document_id'],))]
            checks=[validator.validate(a.text,b.text,'vi','en') for a,b in zip(original_units,export_units)]
            with ZipFile(source) as original,ZipFile(target) as output:
                same_parts=set(original.namelist())==set(output.namelist())
                untouched=same_parts and all(original.read(name)==output.read(name) for name in original.namelist() if name!='word/document.xml')
            verified={'file':source.name,'path':str(target),'rows':len(rows),'all_export_units_match_saved_text':len(rows)==len(export_units)==len(original_units) and all(u.text.strip()==r['translation'].strip() for u,r in zip(export_units,rows)),'confirmed_language_fault_ordinals':[i+1 for i,c in enumerate(checks) if c.conclusion==WRONG_LANGUAGE_CONFIRMED],'suspected_language_fault_ordinals':[i+1 for i,c in enumerate(checks) if c.conclusion==SUSPECTED_WRONG_LANGUAGE],'unchanged_non_document_parts':untouched,'paragraph_pass_counts':{str(p):sum(r['live_pass']==p for r in doc['paragraph_provenance']) for p in (1,2,3)}}
            assert verified['all_export_units_match_saved_text'] and untouched and not verified['confirmed_language_fault_ordinals']
            report['verified_exports'].append(verified)
        verified_db.close()
    (OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
    db.close()
if __name__=='__main__':main()
