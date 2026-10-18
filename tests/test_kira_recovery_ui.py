"""Software/offscreen Qt controls; never run a provider, GPU or Sandbox."""
import json
import pytest
from PySide6.QtTest import QTest
from test_kira_multikey_ui import gui
from transcomic.models import KIRA_MODELS
from transcomic.providers import KiraProvider
import asyncio
import httpx


@pytest.mark.parametrize('dark',[False,True])
def test_recovery_controls_labels_and_saved_model(gui,dark):
    app,store,window=gui
    window.update_panel.auto.setChecked(False)
    if window.dark!=dark:window.toggle_theme()
    window.set_model_id('mimo-v2.6-flash')
    store.set_setting('kira_model','mimo-v2.6-flash')
    window.change_provider()
    assert window.selected_model_id()=='mimo-v2.6-flash'
    for model in ('beam-free','deepseek-v4.1-flash-free','mimo-v2.6-flash-free','longcat-2.5-preview-free'):
        assert window.model_name.findData(model)>=0
    assert window.model_name.findData('longcat-2.5-preview-fre')<0
    controls=window.kira_recovery_controls
    assert controls['kira_retry_limit'].value()==2
    controls['kira_retry_limit'].setValue(0)
    controls['kira_request_limit'].setValue(7)
    assert store.setting('kira_retry_limit')=='0' and store.setting('kira_request_limit')=='7'
    store.add_kira_keys('fixture-ui-recovery-key');key=store.kira_keys()[0]['id']
    store.kira_key_status(key,'TEMPORARY_ERROR',__import__('time').time()+60)
    window.refresh_kira_keys();app.processEvents()
    assert 'Lỗi tạm thời' in window.kira_keys_list.item(0).text()
    assert 'fixture-ui-recovery-key' not in window.kira_keys_list.item(0).text()


@pytest.mark.parametrize('model',['beam-free','deepseek-v4.1-flash-free','mimo-v2.6-flash-free','longcat-2.5-preview-free'])
def test_free_id_is_sent_exactly_without_paid_alias(model):
    assert model in {i for _,i in KIRA_MODELS}
    seen=[]
    def handler(req):
        body=json.loads(req.content);seen.append(body['model'])
        return httpx.Response(403)
    async def run():
        provider=KiraProvider('fixture',model,transport=httpx.MockTransport(handler),max_tokens=256)
        return await provider.translate([{'id':'stable','source':'Nguồn'}],'vi','en')
    result=asyncio.run(run())
    assert seen==[model] and result.diagnostics['failure_kind']=='permission'
