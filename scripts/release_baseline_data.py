"""Seed synthetic v1.2 data using Store code from the actual baseline EXE."""
import argparse
import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import wave
from PyInstaller.archive.readers import CArchiveReader


def main():
    parser=argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--current',default='1.2.0',choices=('1.2.0','2.0.0','2.0.1'))
    args=parser.parse_args();root=args.root.resolve()
    assert root.name.startswith('TransComic-build-smoke-') and (root/'isolated-smoke.json').is_file()
    assert not (root/'TransComic/transcomic.sqlite3').exists()
    archive=CArchiveReader(str(args.baseline.resolve())).open_embedded_archive('PYZ.pyz')
    class Baseline(importlib.abc.MetaPathFinder,importlib.abc.Loader):
        def find_spec(self,name,path=None,target=None):
            if name=='transcomic' or name.startswith('transcomic.'):
                if name not in archive.toc:raise ImportError(name)
                return importlib.util.spec_from_loader(name,self,is_package=archive.toc[name][0]==1)
        def create_module(self,spec):return None
        def exec_module(self,module):
            module.__file__=str(root/'baseline-code'/Path(*module.__name__.split('.')).with_suffix('.py'))
            exec(archive.extract(module.__name__),module.__dict__)
    sys.meta_path.insert(0,Baseline())
    from transcomic.storage import Store
    from transcomic.tts.storage import TtsStore
    from transcomic.documents import import_txt
    from transcomic.version import VERSION
    assert VERSION==args.current
    source=root/'legacy-source.txt';source.write_text('Synthetic legacy source',encoding='utf8')
    app=root/'TransComic';store=Store(app/'transcomic.sqlite3')
    assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='automation_worksets'").fetchone()
    store.set_setting('update_auto_check','0');store.set_setting('dark','1');store.set_setting('release_migration_fixture','preserve-me')
    store.add_kira_keys('release-synthetic-key')
    doc,_=store.import_document(source,import_txt(source))
    job=store.create_job(doc,'fixture','vi','en',1);store.job_state(job,'completed')
    store.edit_line(store.lines(doc)[0]['id'],'translation','Preserved synthetic translation')
    tts=TtsStore(app/'TTS/tts.sqlite3');run=tts.draft()
    tts.add_document(run,{'name':'Legacy voice','path':str(source),'text':'Preserved voice text','line_count':1})
    tts.execute("UPDATE runs SET state='completed',history_accepted=1 WHERE id=?",(run,))
    audio=root/'legacy.wav'
    with wave.open(str(audio),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\x01\x00'*2400)
    for rel in ('legacy-project/draft_content.json','TransComic/TTS/Models/fixture-cache.txt','TransComic/TTS/Runtimes/fixture-cache.txt'):
        p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic-preserved-cache-or-project',encoding='utf8')
    failed_doc=None
    if VERSION in ('2.0.0','2.0.1'):
        from transcomic.automation.repository import Repository
        from transcomic.automation.validation import defaults
        repo=Repository(store);work=repo.create('Legacy v2 checkpoint',defaults(store))
        repo.execute("UPDATE automation_worksets SET state='stopped',checkpoint=? WHERE id=?",(json.dumps({'preserved':'v2-checkpoint'}),work))
        failed_source=root/'legacy-504.txt';failed_source.write_text('Synthetic old failed source',encoding='utf8')
        failed_doc,_=store.import_document(failed_source,import_txt(failed_source))
        failed_job=store.create_job(failed_doc,'longcat-2.5-preview-free','vi','en',1,config={'kira_multi_key':True,'kira_recovery_version':2})
        batch=store.batches(failed_job)[0];store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
        failure={'failure_kind':'http_504','http_status':504}
        store.finish_batch(batch['id'],{},'Synthetic legacy 504',True,failure,expected_attempt_id=attempt);store.complete_attempt(attempt,failure)
        cfg=json.loads(store.job(failed_job)['config']);cfg.update(kira_main_drained=True,kira_recovery_phase=2,kira_wait_used=300,kira_wait_reserved=300)
        store.db.execute("UPDATE jobs SET config=?,state='completed_with_errors' WHERE id=?",(json.dumps(cfg),failed_job))
    def rows(db,table):
        return [[v.hex() if isinstance(v,bytes) else v for v in tuple(row)] for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')]
    proof={'version':VERSION,'baseline_exe_sha256':hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
           'tables':{t:rows(store.db,t) for t in ('documents','lines','line_edits','jobs','batches','secrets','kira_keys')},
           'settings':dict(store.db.execute('SELECT key,value FROM settings')),
           'tts_tables':{t:rows(tts.db,t) for t in ('documents','segments')},
           'tts_history':rows(tts.db,'runs'),
           'files':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,audio,root/'legacy-project/draft_content.json',app/'TTS/Models/fixture-cache.txt',app/'TTS/Runtimes/fixture-cache.txt')}}
    proof['failed_document']=failed_doc
    if VERSION in ('2.0.0','2.0.1'):proof['tables']['automation_worksets']=rows(store.db,'automation_worksets')
    (root/'baseline-expected.json').write_text(json.dumps(proof),encoding='utf8');tts.close();store.close()
    print(json.dumps({'seeded':True,'version':VERSION,'production_data_accessed':False}))


if __name__=='__main__':main()
