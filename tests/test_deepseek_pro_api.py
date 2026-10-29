"""API accordion and Pro regression. Isolated DPAPI fixtures, mock HTTP only."""
import asyncio
import json
import threading
import time
from decimal import Decimal
from types import SimpleNamespace
import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox,QMessageBox
from transcomic import deepseek
from transcomic.deepseek_models import MODEL,PRO_MODEL
from transcomic.deepseek_pricing import DEFAULT,PRO_DEFAULT,load,load_catalog,estimate
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.translation import Scheduler
from transcomic.ui.main import MainWindow
from test_deepseek import LINES,envelope
from test_deepseek_integration import gui,response
from test_automation_ui import gui as automation_gui


@pytest.fixture(autouse=True)
def no_unexpected_dialogs(monkeypatch):
    def fail(*args,**kwargs):pytest.fail('Unexpected modal dialog: '+str(args[1:3]))
    for method in ('question','warning','information'):monkeypatch.setattr(QMessageBox,method,fail)


@pytest.mark.parametrize('dark',[False,True])
def test_accordion_exclusive_click_counts_and_unsaved_drafts(gui,dark):
    app,store,w=gui
    if w.dark!=dark:w.toggle_theme()
    w.pages.setCurrentIndex(2);app.processEvents()
    drafts={'kira':w.api_key_input,'deepseek':w.deepseek_key_input,'gemini':w.gemini_key_input}
    for p,editor in drafts.items():editor.setText('unsaved-synthetic-'+p)
    for p in ('deepseek','gemini','kira'):
        QTest.mouseClick(w.api_sections[p].header,Qt.LeftButton);app.processEvents()
        assert w._api_open_provider==p
        assert all(s.body.isVisible()==(name==p) for name,s in w.api_sections.items())
        assert all(editor.text()=='unsaved-synthetic-'+name for name,editor in drafts.items())
        QTest.mouseClick(w.api_sections[p].header,Qt.LeftButton);app.processEvents()
        assert not w._api_open_provider and not any(s.body.isVisible() for s in w.api_sections.values())
    store.add_kira_keys('synthetic-kira-one synthetic-kira-two');store.add_gemini_keys('synthetic-gemini-one synthetic-gemini-two')
    deepseek.save_key(store,'synthetic-deepseek-one');w.refresh_api_headers()
    assert w.api_sections['kira'].summary.text()=='Đã lưu 2 key'
    assert w.api_sections['gemini'].summary.text()=='Đã lưu 2 key'
    assert w.api_sections['deepseek'].summary.text()=='1/1 key đã lưu'
    assert 'chưa xác minh API' in w.deepseek_status.text()
    w.provider_selector.setCurrentIndex(w.provider_selector.findData('deepseek'))
    assert '0 model Gemini đã lưu' in w.gemini_offline.text()
    assert not any(c.findData(PRO_MODEL)>=0 or c.findData(MODEL)>=0 for c in w.pages.widget(2).findChildren(QComboBox))


@pytest.mark.parametrize('opened',['deepseek','gemini',''])
def test_open_state_survives_application_restart(gui,opened):
    app,store,w=gui;w.open_api_section(opened);path=store.path
    w._exit_authorized=True;w.close();app.processEvents()
    fresh=Store(path);fresh.set_setting('update_auto_check','0');other=MainWindow(fresh)
    try:assert other._api_open_provider==opened
    finally:other._exit_authorized=True;other.close();app.processEvents()


def test_replace_delete_cancel_isolation_and_redaction(gui,monkeypatch):
    app,store,w=gui
    store.add_kira_keys('other-kira-fixture');store.add_gemini_keys('other-gemini-fixture')
    w.deepseek_key_input.setText('old-deepseek-fixture');w.save_deepseek_key()
    old=deepseek.key_identity(store)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.No)
    w.deepseek_key_input.setText('new-deepseek-fixture');w.save_deepseek_key()
    assert deepseek.key_identity(store)==old and w.deepseek_key_input.text()=='new-deepseek-fixture'
    w.delete_deepseek_key();assert deepseek.read_key(store)=='old-deepseek-fixture'
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    w.save_deepseek_key();assert deepseek.read_key(store)=='new-deepseek-fixture'
    assert deepseek.key_identity(store)!=old and not w.deepseek_key_input.text()
    w.scheduler=Scheduler(store,deepseek.DeepSeekProvider('new-deepseek-fixture'))
    adapter=w.scheduler.provider
    w.delete_deepseek_key()
    assert deepseek.read_key(store) is None and not adapter.api_key
    assert w.api_sections['deepseek'].summary.text()=='0/1 key đã lưu'
    assert len(store.kira_keys())==1 and len(store.gemini_keys())==1
    assert 'new-deepseek-fixture' not in store.log.secrets
    store.log.emit('failure',provider='deepseek',reason='new-deepseek-fixture');store.log.flush()
    assert 'new-deepseek-fixture' not in store.log.path.read_text(encoding='utf8')
    w.scheduler=None


def test_unreadable_key_count_and_actual_ciphertext_removal(gui,monkeypatch):
    app,store,w=gui
    with store.transaction():store.db.execute("INSERT INTO secrets VALUES ('deepseek',?)",(b'broken-test-ciphertext',))
    w.refresh_api_headers()
    assert w.api_sections['deepseek'].summary.text()=='1/1 key đã lưu'
    assert 'không thể giải mã' in w.deepseek_status.text()
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    w.delete_deepseek_key();assert deepseek.key_identity(store) is None
    assert w.deepseek_status.text()=='Chưa lưu key'


@pytest.mark.parametrize('provider',['kira','deepseek','gemini'])
def test_delete_guard_including_modal_race_and_provider_isolation(gui,monkeypatch,tmp_path,provider):
    app,store,w=gui
    store.add_kira_keys('guard-kira-fixture');store.add_gemini_keys('guard-gemini-fixture');deepseek.save_key(store,'guard-deepseek-fixture')
    w.refresh_kira_keys();w.refresh_gemini_keys();w.refresh_api_headers()
    w.kira_keys_list.setCurrentRow(0);w.gemini_keys_list.setCurrentRow(0)
    doc,_=store.import_document(tmp_path/'guard.txt',decode_txt(b'synthetic source'),'vi','en')
    model=MODEL if provider=='deepseek' else 'models/test' if provider=='gemini' else 'mock'
    job=store.create_job(doc,model,'vi','en',1,provider=provider)
    action={'kira':w.delete_kira_key,'deepseek':w.delete_deepseek_key,'gemini':lambda:w.edit_gemini_key(delete=True)}[provider]
    notices=[];monkeypatch.setattr(QMessageBox,'information',lambda *a:notices.append(a[2]))
    def race(*a):store.job_state(job,'running');return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox,'question',race)
    action()
    assert notices and len(store.kira_keys())==len(store.gemini_keys())==1 and deepseek.key_identity(store)
    store.job_state(job,'stopped');monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    action()
    assert len(store.kira_keys())==(0 if provider=='kira' else 1)
    assert len(store.gemini_keys())==(0 if provider=='gemini' else 1)
    assert (deepseek.key_identity(store) is None)==(provider=='deepseek')
    assert store.job(job)['state']=='stopped' and len(store.lines(doc))==1


def test_failed_save_does_not_claim_saved(gui,monkeypatch):
    app,store,w=gui
    monkeypatch.setattr(deepseek,'save_key',lambda *a:(_ for _ in ()).throw(OSError('synthetic failure')))
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:None)
    w.deepseek_key_input.setText('not-saved-fixture');w.save_deepseek_key()
    assert not deepseek.key_identity(store) and w.api_sections['deepseek'].summary.text()=='0/1 key đã lưu'


@pytest.mark.parametrize('model,defaults',[(MODEL,DEFAULT),(PRO_MODEL,PRO_DEFAULT)])
def test_both_model_request_json_and_per_attempt_price(model,defaults):
    calls=[]
    def handler(r):calls.append(r);return httpx.Response(200,json=envelope())
    adapter=deepseek.DeepSeekProvider('synthetic-key',model,transport=httpx.MockTransport(handler))
    result=asyncio.run(adapter.translate(LINES,'vi','en'))
    payload=json.loads(calls[0].content)
    assert payload['model']==model and payload['thinking']=={'type':'disabled'}
    assert payload['response_format']=={'type':'json_object'} and not payload['stream'] and not result.error
    assert result.diagnostics['model']==model and result.diagnostics['pricing']==defaults
    expected=estimate(envelope()['usage'],defaults[result.diagnostics['price_period']])
    assert result.diagnostics['cost_estimate']==expected


def test_legacy_prices_not_rewritten_and_model_scoped_save(tmp_path):
    store=Store(tmp_path/'state.db');legacy=json.loads(json.dumps(DEFAULT));legacy['peak']['input']='0.42'
    try:
        store.set_setting('deepseek_pricing',json.dumps(legacy));raw=store.setting('deepseek_pricing')
        assert load(store,MODEL)['peak']['input']=='0.42'
        assert load(store,PRO_MODEL)['peak']['input']=='1.32'
        assert store.setting('deepseek_pricing')==raw
        catalog=load_catalog(store);catalog['models'][PRO_MODEL]['peak']['input']='1.4'
        store.set_setting('deepseek_pricing',json.dumps(catalog))
        assert load(store,MODEL)==legacy and load(store,PRO_MODEL)['peak']['input']=='1.4'
    finally:store.close()


@pytest.mark.parametrize('dark',[False,True])
def test_pro_selector_persistence_retry_and_cost_uses_actual_job(gui,tmp_path,monkeypatch,dark):
    app,store,w=gui
    if w.dark!=dark:w.toggle_theme()
    w.provider_selector.setCurrentIndex(w.provider_selector.findData('deepseek'))
    assert w.selected_model_id()==MODEL
    w.model_name.setCurrentIndex(w.model_name.findData(PRO_MODEL))
    assert store.setting('deepseek_model')==PRO_MODEL and 'V4 Pro' in w.deepseek_translation_price.text()
    for provider in ('kira','gemini','deepseek'):w.provider_selector.setCurrentIndex(w.provider_selector.findData(provider))
    assert w.selected_model_id()==PRO_MODEL
    deepseek.save_key(store,'pro-ui-fixture')
    doc,_=store.import_document(tmp_path/'pro.txt',decode_txt(b'synthetic source'),'vi','en')
    w.open_document(doc);w.workspace_ids=[doc];w.target_lang.setCurrentText('Tiếng Anh');w.sync_target_chips()
    factory=w.make_provider;calls=[]
    def mock(job,key=None):
        p=factory(job,key)
        def handler(r):calls.append(r);return response(r)
        p.transport=httpx.MockTransport(handler);return p
    monkeypatch.setattr(w,'make_provider',mock)
    w.start_stage2()
    from test_automation_ui import wait
    wait(app,lambda:w.scheduler is not None)
    w.scheduler.join(5);app.processEvents()
    job=store.job(w.scheduler.job_id)
    assert job['model']==PRO_MODEL and json.loads(job['config'])['deepseek_pricing']['peak']['output']=='3.96'
    w.refresh_api_headers();assert 'bằng chứng API thành công' in w.deepseek_status.text()
    w.model_name.setCurrentIndex(w.model_name.findData(MODEL));w.refresh_deepseek_display()
    assert 'Lượt DeepSeek V4 Pro' in w.deepseek_translation_price.text()
    assert w.scheduler.provider.pricing['peak']['output']=='3.96'
    w.model.refresh();w.model.set_checked([0],True)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    w.retry_selected();w.scheduler.join(5);app.processEvents()
    assert len(calls)==2 and all(json.loads(r.content)['model']==PRO_MODEL for r in calls)


def test_automation_pro_choice_persists_and_survives_provider_switch(automation_gui):
    app,w,p,id=automation_gui
    p.fields['provider'].setCurrentIndex(p.fields['provider'].findData('deepseek'))
    p.fields['model'].setCurrentIndex(p.fields['model'].findData(PRO_MODEL));app.processEvents()
    assert p.repo.workset(id)['config']['model']==PRO_MODEL
    p.fields['provider'].setCurrentIndex(p.fields['provider'].findData('kira'))
    p.fields['provider'].setCurrentIndex(p.fields['provider'].findData('deepseek'));app.processEvents()
    assert p.fields['model'].currentData()==PRO_MODEL
    p.load_worksets(id);assert p.fields['model'].currentData()==PRO_MODEL


def test_pro_checkpoint_resume_never_replays_successful_batch(tmp_path):
    store=Store(tmp_path/'state.db');deepseek.save_key(store,'pro-checkpoint-fixture')
    doc,_=store.import_document(tmp_path/'pro.txt',decode_txt(b'first source\nsecond source\nthird source\nfourth source\nfifth source\nsixth source'),'vi','en')
    job=store.create_job(doc,PRO_MODEL,'vi','en',1,provider='deepseek')
    entered=threading.Event();release=threading.Event();calls=[]
    async def handler(r):
        calls.append(r);entered.set()
        while not release.is_set():await asyncio.sleep(.005)
        return response(r)
    p=deepseek.provider_for(store,store.job(job));p.transport=httpx.MockTransport(handler);s=Scheduler(store,p)
    try:
        s.start(job);assert entered.wait(2);s.pause();release.set();time.sleep(.1);s.stop();s.join(3)
        assert len(calls)==1
        store.close();store=Store(tmp_path/'state.db');p=deepseek.provider_for(store,store.job(job));p.transport=httpx.MockTransport(handler)
        s=Scheduler(store,p);s.start(job);s.join(5)
        assert len(calls)==2 and all(json.loads(r.content)['model']==PRO_MODEL for r in calls)
        ids=[[r['id'] for r in json.loads(json.loads(c.content)['messages'][1]['content'])['lines']] for c in calls]
        assert not set(ids[0])&set(ids[1])
    finally:release.set();s.stop();s.join(3);store.close()
