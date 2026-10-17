import json
from pathlib import Path
import pytest
from tests.test_tts import make,prepare,finish
from transcomic.tts.output import Outputs,MANIFEST
from transcomic.tts.documents import segments


def test_existing_inprogress_other_job_gets_unique_name(tmp_path):
    store,run=make(tmp_path,'Hello','1-2.en-US');old=tmp_path/'1-2.en-US_TTS_inprogress';old.mkdir();(old/MANIFEST).write_text(json.dumps(dict(run='other',document='other',segments={})))
    (old/'keep.txt').write_text('Keep')
    plan=Outputs(store).plan(run,'custom',str(tmp_path),'wav')
    assert plan[0]['folder']!=str(old) and plan[0]['base']=='1-2.en-US_2'
    assert (old/'keep.txt').read_text()=='Keep';store.close()


def test_existing_unknown_folder_and_final_are_never_reused(tmp_path):
    store,run=make(tmp_path,'Hello');(tmp_path/'Chap 9_TTS_inprogress').mkdir();(tmp_path/'Chap 9_2_1tts').mkdir()
    plan=Outputs(store).plan(run,'custom',str(tmp_path),'wav');assert plan[0]['base']=='Chap 9_3';store.close()


def test_current_job_manifest_recovers_missing_db_folder(tmp_path):
    store,run,output,root=prepare(tmp_path,'Hello');finish(store,run,output);doc=store.docs(run)[0];folder=doc['folder'];sha=store.items(run)[0]['sha256']
    store.execute('UPDATE documents SET folder=NULL WHERE id=?',(doc['id'],));store.status(run,'paused')
    plans=output.plan(run,'custom',str(root),'wav');assert plans[0]['folder']==folder
    output.confirm(run,json.loads(store.run(run)['config']),plans);output.reconcile(run)
    assert store.docs(run)[0]['folder']==folder and store.items(run)[0]['sha256']==sha and store.items(run)[0]['state']=='success';store.close()


def test_none_split_preserves_one_logical_segment():
    text='Mr. Smith 3.14!\nNext?\n\nLast line.'
    items=segments(text,'none');assert len(items)==1 and items[0]['text']==text and items[0]['line_end']==4
