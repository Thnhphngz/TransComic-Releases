"""The release probes exercise real contracts, without changing application policy."""
import json,os
import pytest
from test_automation_ui import gui,wait
from transcomic.workflow_smoke_202 import run
from transcomic.release_smoke import run_automation,verify_reopen
from PySide6.QtWidgets import QSystemTrayIcon
_native_tray_available=QSystemTrayIcon.isSystemTrayAvailable


def test_export_workflow(gui,tmp_path):
    app,window,page,wid=gui
    result=run(window,tmp_path)
    assert result['passed'] and len(result['themes'])==2
    assert all(r['popup_choices']==3 and len(r['popup_timings'])==3 for r in result['themes'])
    if os.environ.get('TRANSCOMIC_NATIVE_UI')=='1':
        assert result['platform']=='windows'
        assert all(r['input_method']==['Win32 mouse input'] for r in result['themes'])
    target=os.environ.get('TRANSCOMIC_PROBE_EVIDENCE')
    if target:
        from pathlib import Path
        out=Path(target);out.mkdir(parents=True,exist_ok=True)
        (out/'workflow.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        import shutil
        for p in tmp_path.glob('*.png'):shutil.copyfile(p,out/p.name)


def test_reopen_contract(gui,tmp_path,monkeypatch):
    app,window,page,wid=gui
    if os.environ.get('TRANSCOMIC_NATIVE_UI')!='1':pytest.skip('Full release fixture exercises native Windows tray; covered by native/frozen runs')
    # The shared UI fixture disables tray for ordinary tests. This integration
    # needs the real platform method, not a forced successful result.
    monkeypatch.setattr(QSystemTrayIcon,'isSystemTrayAvailable',_native_tray_available)
    assert _native_tray_available()
    assert run_automation(window,tmp_path,lambda condition,seconds=8:wait(app,condition,seconds))['passed']
    proof=json.loads((tmp_path/'reopen-expected.json').read_text())
    # A dead owner is the existing recovery boundary. Do not edit group labels
    # or manufacture the expected reconciliation result in the fixture.
    window.automation_repo.recover()
    verify_reopen(window,tmp_path)
    result=json.loads((tmp_path/'reopen-report.json').read_text())
    assert result['pending_reconciled_to_waiting'] and result['translated_reconciled_to_waiting_tts']
    assert result['completed_not_downgraded'] and result['new_translation_attempts']==0
    assert window.automation_repo.workset(proof['trial_id'])['state']=='interrupted'
