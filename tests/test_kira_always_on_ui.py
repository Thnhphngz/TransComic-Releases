"""Isolated Qt recovery UI. No live provider, model runtime or user database."""
import json
import os
from pathlib import Path
import time
import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from test_automation_ui import gui,wait
from test_automation import add_group
from test_kira_auto_recovery import response
from transcomic.kira_pool import KiraPoolProvider


@pytest.mark.parametrize('dark',[False,True])
def test_consent_controls_freeze_and_recovery_summary(gui,tmp_path,dark):
    app,w,p,id=gui;store=p.repo.store
    if w.dark!=dark:w.toggle_theme()
    assert not hasattr(w,'restore_kira_key')
    assert not any('Khôi phục offline' in b.text() or 'Khôi phục key' in b.text() for b in w.findChildren(QPushButton))
    assert not w.kira_unknown_consent.isChecked()
    assert w.kira_recovery_controls['kira_retry_concurrency'].minimum()==1
    assert w.kira_recovery_controls['kira_recovery_seconds'].minimum()==1
    gid,_,_=add_group(p.repo,id,tmp_path/'synthetic',count=3)
    doc=p.repo.group(gid)['document_id']
    job=store.create_job(doc,'mock','vi','en',30,provider='kira',config={'kira_multi_key':True})
    before=json.loads(store.job(job)['config'])
    assert before['kira_recovery_version']==4 and before['uncertain_retry_authorized'] is False
    w.kira_unknown_consent.setChecked(True)
    assert store.setting('kira_allow_unknown_resend')=='1'
    assert json.loads(store.job(job)['config'])==before
    second=store.create_job(doc,'mock','vi','en',30,provider='kira',config={'kira_multi_key':True},allow_shared_document=True)
    assert json.loads(store.job(second)['config'])['uncertain_retry_authorized'] is True
    when=time.time()+30
    states={'provider_recovering':'Đang hồi phục','retry_scheduled':'Chờ thử lại','network_waiting':'Chờ mạng',
            'user_paused':'Đã tạm dừng','blocked_auth':'Key không hợp lệ','blocked_quota':'Hết quota',
            'blocked_budget':'Đã đạt giới hạn','needs_reconciliation':'Cần đối chiếu kết quả'}
    for state,label in states.items():
        p.repo.update_group(gid,state='needs_attention' if state.startswith('blocked') or state=='needs_reconciliation' else 'translating',
            translation_recovery_state=state,translation_recovery_reason='recovery_cost_budget_exhausted',next_retry_at=when)
        p.refresh();index=p.model.index(0,5)
        assert p.model.data(index)==label
        tooltip=p.model.data(index,Qt.ToolTipRole)
        assert 'trần chi phí' in tooltip and time.strftime('%H:%M:%S',time.localtime(when)) in tooltip
    p.repo.update_group(gid,state='translating',translation_recovery_state='retry_scheduled')
    p.refresh();app.processEvents()
    destination=os.environ.get('KIRA_RECOVERY_GUI_EVIDENCE')
    if destination:
        folder=Path(destination);folder.mkdir(parents=True,exist_ok=True)
        assert w.grab().save(str(folder/f'automation-{"dark" if dark else "light"}.png'))
        w.pages.setCurrentIndex(2);w.pages.widget(2).ensureWidgetVisible(w.kira_unknown_consent);app.processEvents()
        assert w.grab().save(str(folder/f'api-{"dark" if dark else "light"}.png'))
        (folder/'dpi.json').write_text(json.dumps({'dpr':w.devicePixelRatioF(),'platform':app.platformName()}),encoding='utf-8')
    assert not store.db.execute('SELECT 1 FROM request_attempts').fetchone()


@pytest.mark.parametrize('dark',[False,True])
def test_running_automation_recovery_pause_resume_controls(gui,tmp_path,dark):
    app,w,p,id=gui
    if w.dark!=dark:w.toggle_theme()
    gid,_,_=add_group(p.repo,id,tmp_path/'one-start',count=3)
    calls=[]
    def handler(req):
        calls.append(time.monotonic())
        return httpx.Response(503,headers={'Retry-After':'1.5'}) if len(calls)==1 else response(req)
    p.services.translation.provider_factory=lambda s,j:KiraPoolProvider(s,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    p.repo.store.set_setting('kira_retry_backoff','0')
    p.proof=p.controller.validate(id);assert p.proof['passed']
    p.controller.start(id)
    wait(app,lambda:p.repo.group_state(gid).get('translation_recovery_reason','').startswith('HTTP 503'))
    assert p.repo.group_state(gid)['next_retry_at']>time.time()
    p.refresh();assert p.start.text()=='Tạm dừng' and p.start.isEnabled()
    p.start.click();p.refresh();assert p.controller.paused.is_set() and p.start.text()=='Tiếp tục'
    deadline=time.monotonic()+1.7
    while time.monotonic()<deadline:app.processEvents();time.sleep(.02)
    assert len(calls)==1 and p.controller.busy
    p.start.click();assert not p.controller.paused.is_set()
    wait(app,lambda:not p.controller.busy,seconds=12)
    assert p.repo.workset(id)['state']=='completed' and len(calls)==2
    assert len(p.repo.store.jobs())==1
