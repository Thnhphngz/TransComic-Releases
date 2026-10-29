"""Actual Store/Scheduler/Automation and Qt, with fake HTTP and no inference."""
import asyncio
import json
import threading
from pathlib import Path
import httpx
import pytest
from PySide6.QtWidgets import QApplication,QLineEdit,QMessageBox,QPlainTextEdit,QDialogButtonBox
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.deepseek import DeepSeekProvider, MODEL, save_key, read_key
from transcomic.deepseek_models import PRO_MODEL
from transcomic.translation import Scheduler
from transcomic.workspace_retry import fresh_retry_config
from transcomic.automation.repository import Repository
from transcomic.automation.adapters import Translation,provider_for
from transcomic.automation.validation import defaults,check_config
from transcomic.automation.services import Services
from transcomic.ui.main import MainWindow
from transcomic.ui.tts_page import TtsPage
from test_deepseek import envelope
from test_automation import add_group
from test_automation import setup as automation_setup


def response(request):
    body=json.loads(request.content)
    rows=json.loads(body['messages'][1]['content'])['lines']
    text='Sang pengelana sudah kembali ke rumah dengan selamat' if 'Target locale: id;' in body['messages'][0]['content'] else 'The traveler returns home safely'
    return httpx.Response(200,json=envelope(json.dumps({'lines':[dict(id=r['id'],text=text) for r in rows]})))


@pytest.mark.parametrize('status',[200,429,504,'invalid'])
def test_automation_single_pass_restart_and_explicit_manual_cycle(tmp_path,status):
    store=Store(tmp_path/'state.db');repo=Repository(store);cfg=defaults(store)
    cfg.update(provider='deepseek',model=MODEL,workers=1,translation_completion_policy=0)
    id=repo.create('DeepSeek synthetic',cfg)
    gid,path,folder=add_group(repo,id,tmp_path/'chapter',count=6)
    calls=[]
    def handler(request):
        calls.append(request)
        return response(request) if status==200 else httpx.Response(200,json=envelope('{}')) if status=='invalid' else httpx.Response(status,json={})
    adapter=Translation(repo,lambda s,j:DeepSeekProvider('fixture',transport=httpx.MockTransport(handler)),network_probe=lambda p:pytest.fail('DeepSeek may not network-probe or retry'))
    adapter.backoff=lambda phase:pytest.fail('DeepSeek may not retry')
    try:
        with store.transaction():store.db.execute("UPDATE automation_worksets SET state='running' WHERE id=?",(id,))
        # Repository owns create_job while active, exactly as the controller does.
        groups=repo.groups(id);stop=threading.Event();adapter.run(id,groups,cfg,stop,lambda:None)
        count=len(calls);assert count==(2 if status==200 else 1)
        assert all(j['provider']=='deepseek' and j['auto_retries']==0 for j in store.jobs())
        if status!=200:
            # Recovery can send the remaining UNSENT batch once, never replay the failed IDs.
            adapter.run(id,repo.groups(id),cfg,stop,lambda:None)
            assert len(calls)==2
            adapter.run(id,repo.groups(id),cfg,stop,lambda:None);assert len(calls)==2
            ids=[r['id'] for r in store.lines(groups[0]['document_id'])]
            adapter.run(id,repo.groups(id),cfg,stop,lambda:None,line_ids=ids,scope='explicit-user-cycle')
            assert len(calls)==3
        assert path.read_text(encoding='utf8').startswith('Văn bản')
    finally:store.close()


@pytest.mark.parametrize('model',[MODEL,PRO_MODEL])
def test_multifile_multilanguage_frozen_config_and_manual_provider(tmp_path,model):
    store=Store(tmp_path/'state.db');docs=[]
    for n in range(2):
        doc,_=store.import_document(tmp_path/f'{n}.txt',decode_txt('Người lữ khách trở về nhà'.encode()),'vi','en');docs.append(doc)
    run,jobs=store.create_run(docs,['en','id'],provider='deepseek',model=model,source_lang='vi',concurrency=2)
    calls=[]
    def handler(r):calls.append(r);return response(r)
    s=Scheduler(store,DeepSeekProvider('fixture',model,transport=httpx.MockTransport(handler)))
    try:
        s.start_many(jobs,run);s.join(5)
        assert not s._thread.is_alive() and len(calls)==4
        assert all(json.loads(r.content)['model']==model for r in calls)
        assert all(j['provider']=='deepseek' and j['auto_retries']==0 for j in store.jobs())
        assert all(row['state']=='done' for j in jobs for row in store.lines(store.job(j)['document_id']))
        assert all('pengelana' in store.lines(store.job(j)['document_id'])[0]['translation'] for j in jobs if store.job(j)['target_lang']=='Tiếng Indonesia')
        assert store.run(run)['config']['deepseek_pricing']['verified']=='2026-10-26'
        assert 'deepseek_max_tokens' in fresh_retry_config(store,store.job(jobs[0]))
        save_key(store,'fixture')
        assert isinstance(provider_for(store,store.job(jobs[0])),DeepSeekProvider)
    finally:store.close()


@pytest.fixture
def gui(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(TtsPage,'check_runtime',lambda self:None)
    # This fixture cannot send a real HTTP request, even indirectly.
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',lambda *args:pytest.fail('Unexpected real network'))
    store=Store(tmp_path/'state.db');store.set_setting('update_auto_check','0')
    window=MainWindow(store);window.resize(1280,840);window.show();app.processEvents()
    yield app,store,window
    window._exit_authorized=True;window.close();app.processEvents()


@pytest.mark.parametrize('dark',[False,True])
def test_ui_provider_settings_theme_no_network(gui,dark,tmp_path,monkeypatch):
    app,store,w=gui
    if w.dark!=dark:w.toggle_theme()
    w.provider_selector.setCurrentIndex(w.provider_selector.findData('deepseek'));app.processEvents()
    assert w.provider_id()=='deepseek' and w.selected_model_id()==MODEL and w.model_name.count()==2
    assert w.concurrency.maximum()==30 and not w.auto_retry_combo.isEnabled()
    assert w.deepseek_key_input.echoMode()==QLineEdit.Password
    assert 'Chưa lưu' in w.deepseek_status.text()
    w.deepseek_key_input.setText('synthetic-deepseek-ui');w.save_deepseek_key()
    assert read_key(store)=='synthetic-deepseek-ui' and not w.deepseek_key_input.text()
    assert 'synthetic-deepseek-ui' not in w.deepseek_status.text()
    p=w.automation_page;p.fields['provider'].setCurrentIndex(p.fields['provider'].findData('deepseek'));p.fill_models()
    assert p.fields['model'].currentData()==MODEL and p.fields['model'].count()==2
    for width in (1024,1440):
        w.resize(width,840);app.processEvents()
        assert w.start_button.isVisible() and w.deepseek_translation_price.isVisible()
        from PySide6.QtCore import QPoint,QRect
        start=QRect(w.start_button.mapTo(w,QPoint()),w.start_button.size())
        price=QRect(w.deepseek_translation_price.mapTo(w,QPoint()),w.deepseek_translation_price.size())
        assert not start.intersects(price)
    # Actual UI start uses the saved DeepSeek credential and the shared Scheduler.
    doc,_=store.import_document(tmp_path/'ui.txt',decode_txt('Người lữ khách trở về nhà'.encode()),'vi','en')
    w.open_document(doc);w.workspace_ids=[doc];w.target_lang.setCurrentText('Tiếng Anh');w.sync_target_chips()
    original=w.make_provider;calls=[]
    def factory(job,key=None):
        p=original(job,key)
        def handler(request):calls.append(request);return response(request)
        p.transport=httpx.MockTransport(handler);return p
    monkeypatch.setattr(w,'make_provider',factory)
    w.start_stage2()
    from test_automation_ui import wait
    wait(app,lambda:w.scheduler is not None)
    w.scheduler.join(5);app.processEvents();w.refresh_stage2()
    wait(app,lambda:'Ước tính bảo thủ: $' in w.deepseek_translation_price.text())
    assert len(calls)==1 and store.jobs()[0]['provider']=='deepseek'
    assert 'Ước tính bảo thủ: $' in w.deepseek_translation_price.text()
    assert w.scheduler.provider.api_key=='synthetic-deepseek-ui'
    # Even after selecting Kira in the toolbar, manual retry keeps the original provider.
    w.model.refresh();w.model.set_checked([0],True)
    w.provider_selector.setCurrentIndex(w.provider_selector.findData('kira'))
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.Yes)
    w.retry_selected();w.scheduler.join(5);app.processEvents()
    assert len(calls)==2 and store.jobs()[0]['provider']=='deepseek'


def test_preflight_credential_separation_and_configuration(tmp_path):
    from types import SimpleNamespace
    store=Store(tmp_path/'state.db');repo=Repository(store)
    services=Services.__new__(Services);services.repo=repo
    cfg=defaults(store);cfg.update(provider='deepseek',model=MODEL,workers=30)
    try:
        check_config('translation',cfg)
        store.add_kira_keys('unrelated-kira-key')
        with pytest.raises(ValueError,match='DeepSeek'):services.preflight_translation(cfg)
        before=services.validation_identity('translation',cfg)
        save_key(store,'deepseek-fixture')
        services.preflight_translation(cfg)
        assert before!=services.validation_identity('translation',cfg)
        cfg['model']='deepseek-pro'
        with pytest.raises(ValueError):check_config('translation',cfg)
    finally:store.close()


def test_edit_prices_dialog_and_missing_key_action(gui,monkeypatch):
    app,store,w=gui
    w.provider_selector.setCurrentIndex(w.provider_selector.findData('deepseek'))
    def edit():
        dialog=app.activeModalWidget();editor=dialog.findChild(QPlainTextEdit)
        config=json.loads(editor.toPlainText());config['models'][MODEL]['peak']['input']='0.35'
        editor.setPlainText(json.dumps(config));dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
    QTimer.singleShot(0,edit);w.edit_deepseek_prices()
    assert json.loads(store.setting('deepseek_pricing'))['models'][MODEL]['peak']['input']=='0.35'
    notices=[];monkeypatch.setattr(QMessageBox,'information',lambda *args:notices.append(args[2]))
    w.target_lang.setCurrentText('Tiếng Anh');w.sync_target_chips();w.start_stage2()
    assert w.scheduler is None and any('Chưa có key DeepSeek' in n for n in notices)


@pytest.mark.parametrize('status',[200,504])
@pytest.mark.parametrize('model',[MODEL,PRO_MODEL])
def test_controller_pipeline_uses_deepseek_and_retains_failed_checkpoint(automation_setup,tmp_path,status,model):
    repo,id,services,controller=automation_setup
    cfg=repo.workset(id)['config'];cfg.update(provider='deepseek',model=model,workers=1)
    repo.configure(id,cfg);save_key(repo.store,'controller-deepseek-fixture')
    add_group(repo,id,tmp_path/'g1',name='1-2',count=3)
    add_group(repo,id,tmp_path/'g2',name='3-4',count=3)
    calls=[]
    def handler(request):
        calls.append(request)
        return response(request) if status==200 else httpx.Response(status,json={})
    def factory(store,job):
        p=provider_for(store,job);p.transport=httpx.MockTransport(handler);return p
    services.translation=Translation(repo,factory,network_probe=lambda p:pytest.fail('No automatic probe or retry'))
    proof=controller.validate(id);assert proof['passed']
    controller.start(id);controller.join(8);assert not controller.busy
    assert len(calls)==(2 if status==200 else 1)
    assert all(json.loads(r.content)['model']==model for r in calls)
    assert all(r.headers['authorization']=='Bearer controller-deepseek-fixture' for r in calls)
    if status==200:
        assert repo.workset(id)['state']=='completed'
        assert len([a for a in repo.artifacts(id) if a['kind']=='translation' and a['state']=='complete'])==2
    else:
        assert repo.workset(id)['state']=='needs_attention'
        assert any(row['state']=='unknown' for g in repo.groups(id) for row in repo.store.lines(g['document_id']))
        attempts=[a for j in repo.store.jobs() for b in repo.store.batches(j['id']) for a in repo.store.attempts(b['id'])]
        assert len(attempts)==1 and attempts[0]['diagnostics']['http_status']==504
