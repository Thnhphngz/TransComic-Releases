"""Dependency validation and fresh dispatch gates; synthetic files, no HTTP."""
import os
from pathlib import Path
import pytest
from transcomic.automation import validation as v
from transcomic.automation.services import Services
from test_automation import setup,add_group,FakeEngine


def monitor(monkeypatch,services):
    calls=[];sections=[]
    for name in ('read_source','image_manifest'):
        original=getattr(v,name)
        def wrapped(*args,_name=name,_original=original,**kwargs):calls.append(_name);return _original(*args,**kwargs)
        monkeypatch.setattr(v,name,wrapped)
    services.preflight_section=lambda name,cfg:sections.append(name)
    return calls,sections


@pytest.mark.parametrize('changed,expected',[
    ({'capcut_mode':'split','part_count':2,'project_name':'Parts'},'capcut'),
    ({'project_name':'Another name'},'capcut'),
    ({'provider':'gemini','model':'gemini-mock','workers':1},'translation'),
    ({'workers':12},'translation'),
    ({'voice':'af_heart','speed':1.1},'kokoro'),
])
def test_config_edits_reuse_verified_inputs_and_only_check_dependency(setup,tmp_path,monkeypatch,changed,expected):
    repo,id,s,c=setup
    for n in range(2):add_group(repo,id,tmp_path/str(n),name=str(n+1))
    calls,sections=monitor(monkeypatch,s);assert c.validate(id)['passed'];assert calls.count('image_manifest')==2
    calls.clear();sections.clear();cfg=repo.workset(id)['config'];cfg.update(changed);repo.configure(id,cfg)
    proof=c.validate(id)
    assert proof['passed'] and proof['checked_sections']==[expected] and sections==[expected]
    assert calls==[] and all(g['input_cached'] for g in proof['groups'])
    assert repo.store.jobs()==[] and FakeEngine.calls==[]


def test_new_image_folder_invalidates_only_affected_group(setup,tmp_path,monkeypatch):
    repo,id,s,c=setup;a,_,_=add_group(repo,id,tmp_path/'a');b,_,folder=add_group(repo,id,tmp_path/'b')
    assert c.validate(id)['passed'];slots=repo.group(a)['data']['slots'];repo.pair_images(a,folder)
    calls,sections=monitor(monkeypatch,s);proof=c.validate(id)
    assert proof['passed'] and calls==['read_source','image_manifest'] and not sections
    assert {g['id']:g['input_cached'] for g in proof['groups']}=={a:False,b:True}
    assert repo.group(a)['data']['slots']==slots


def test_key_configuration_change_rechecks_translation_without_media_scan(setup,tmp_path,monkeypatch):
    repo,id,s,c=setup;add_group(repo,id,tmp_path/'a');s.repo=repo
    s.validation_identity=lambda section,cfg:Services.validation_identity(s,section,cfg)
    calls,sections=monitor(monkeypatch,s);assert c.validate(id)['passed'];calls.clear();sections.clear()
    repo.store.add_kira_keys('another-synthetic-offline-key')
    proof=c.validate(id)
    assert proof['passed'] and proof['checked_sections']==['translation'] and sections==['translation'] and calls==[]


def test_account_group_change_rechecks_translation_without_media_scan(setup,tmp_path,monkeypatch):
    repo,id,s,c=setup;add_group(repo,id,tmp_path/'a');s.repo=repo
    s.validation_identity=lambda section,cfg:Services.validation_identity(s,section,cfg)
    calls,sections=monitor(monkeypatch,s);assert c.validate(id)['passed'];calls.clear();sections.clear()
    key=repo.store.kira_keys()[0]['id'];repo.store.set_kira_account_scope(key,key)
    proof=c.validate(id)
    assert proof['passed'] and proof['checked_sections']==['translation'] and sections==['translation'] and calls==[]


def test_failed_resource_validation_can_heal_without_rereading_inputs(setup,tmp_path,monkeypatch):
    repo,id,s,c=setup;add_group(repo,id,tmp_path/'a');ready=[False]
    def preflight(section,cfg):
        if section=='kokoro' and not ready[0]:raise ValueError('Synthetic runtime not ready')
    s.preflight_section=preflight;assert not c.validate(id)['passed'];ready[0]=True
    calls,_=monitor(monkeypatch,s);s.preflight_section=preflight
    proof=c.validate(id);assert proof['passed'] and proof['checked_sections']==['kokoro'] and calls==[]


@pytest.mark.parametrize('corrupt',['source','image'])
def test_fresh_dispatch_rejects_external_changes_even_after_cached_pass(setup,tmp_path,corrupt):
    repo,id,s,c=setup;gid,path,folder=add_group(repo,id,tmp_path/'a');assert c.validate(id)['passed']
    target=path if corrupt=='source' else folder/'0001.png';before=target.stat();raw=target.read_bytes()
    target.write_bytes((b'X'+raw[1:]) if corrupt=='source' else (b'badimage'+raw[8:]))
    os.utime(target,ns=(before.st_atime_ns,before.st_mtime_ns))
    c.start(id);c.join(8)
    assert not c.busy and repo.workset(id)['state']=='needs_attention'
    assert repo.store.jobs()==[] and FakeEngine.calls==[]


def test_resume_still_detects_same_layout_source_change(setup,tmp_path,monkeypatch):
    from test_automation import run
    repo,id,s,c=setup;gid,path,_=add_group(repo,id,tmp_path/'a');run(c,id)
    ids=[r['id'] for r in repo.store.lines(repo.group(gid)['document_id'])]
    path.write_text(path.read_text(encoding='utf8').replace('số 0','số mới'),encoding='utf8')
    proof=c.validate(id)
    assert proof['passed'] and not proof['groups'][0]['input_cached']
    assert [r['id'] for r in repo.store.lines(repo.group(gid)['document_id'])]==ids
    assert any(r['state']=='pending' for r in repo.store.lines(repo.group(gid)['document_id']))
