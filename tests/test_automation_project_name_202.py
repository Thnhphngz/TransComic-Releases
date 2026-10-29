"""New workset naming is explicit; saved worksets never get reset."""
import pytest
from PySide6.QtWidgets import QInputDialog
from test_automation_ui import gui
from test_automation import setup,add_group,run


def test_new_worksets_blank_names_saved_names_reopen_and_focus(gui,monkeypatch):
    app,w,p,original=gui;repo=p.repo;old=repo.workset(original)
    repo.store.set_setting('automation_last_config','{"project_name":"Old project","part_names":{"1":"Old part"},"speed":1.2}')
    monkeypatch.setattr(QInputDialog,'getText',lambda *a:('New workset',True))
    ids=[]
    for name in ('First distinct project','Second distinct project'):
        p.new_workset();id=p.current;ids.append(id)
        cfg=repo.workset(id)['config'];assert cfg['project_name']=='' and cfg['part_names']=={} and cfg['speed']==1.2
        assert p.fields['project_name'].text()==''
        p.start_clicked();app.processEvents();assert not p.controller.busy
        assert p.fields['project_name'].hasFocus() and 'Tên project' in p.project_warning.text()
        p.fields['project_name'].setText('   ');p.start_clicked();assert not p.controller.busy
        p.fields['project_name'].setText(name);p.config_changed()
    for id,name in zip(ids,('First distinct project','Second distinct project')):
        p.load_worksets(id);assert p.fields['project_name'].text()==name and repo.workset(id)['config']['project_name']==name
    assert repo.workset(original)==old


@pytest.mark.parametrize('name',['','   ','bad/name','CON','a'*81])
def test_controller_blocks_invalid_common_name_even_separate_mode(setup,tmp_path,name):
    repo,id,s,c=setup;add_group(repo,id,tmp_path/'g',count=1)
    cfg=repo.workset(id)['config'];cfg['project_name']=name;repo.configure(id,cfg)
    proof=c.validate(id);assert not proof['passed'] and proof['errors']
    with pytest.raises(ValueError):c.start(id)
    assert not c.busy and repo.workset(id)['config']['project_name']==name


def test_resume_and_existing_project_collision_preserve_confirmed_name(setup,tmp_path):
    repo,id,s,c=setup;gid,_,_=add_group(repo,id,tmp_path/'g',count=1)
    cfg=repo.workset(id)['config'];cfg.update(project_name='Named project',capcut_mode='merged');repo.configure(id,cfg)
    (tmp_path/'capcut'/'Named project').mkdir();run(c,id)
    assert repo.workset(id)['state']=='completed' and repo.workset(id)['config']['project_name']=='Named project'
    assert repo.group(gid)['data']['project'].endswith('Named project_v2')
    checkpoint=repo.workset(id)['checkpoint'];c.validate(id)
    assert repo.workset(id)['config']['project_name']=='Named project'
    assert checkpoint['parts']==repo.workset(id)['checkpoint']['parts']
