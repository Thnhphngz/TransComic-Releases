"""Real Windows entry point, isolated data and simulated signed data downloads."""
import json
import os
from pathlib import Path
import runpy
import sys
import threading
import time
import traceback
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import httpx
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from transcomic.ui.main import MainWindow
from transcomic.update.service import UpdateService, LATEST_URL
from transcomic.update.install import State, SafetySnapshot, FakeInstaller
from transcomic.update.helper import ProcessIdentity, FakeProcess, FakeEnvironment
from transcomic.update.metadata import UpdateError
from test_updater_stage_a import fixture_release
import transcomic.app as application

OUT=ROOT/'artifacts/release-stage-b2-1/windows'/os.environ.get('QT_SCALE_FACTOR','1')
OUT.mkdir(parents=True,exist_ok=True)
send=httpx.Client.send
def guard(self,*args,**kwargs):
    if not isinstance(self._transport,httpx.MockTransport):raise AssertionError('Real HTTP forbidden in smoke')
    return send(self,*args,**kwargs)
httpx.Client.send=guard
httpx.AsyncClient.send=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('API forbidden'))

class Smoke(MainWindow):
    def __init__(self,store):
        super().__init__(store);self.update_panel.auto.setChecked(False)
        QTimer.singleShot(100,self.exercise)
    def settle(self):QApplication.processEvents();QTest.qWait(180)
    def shot(self,name):self.settle();self.grab().save(str(OUT/(name+'.png')))
    def wait(self,condition):
        end=time.monotonic()+5
        while not condition() and time.monotonic()<end:self.settle()
        assert condition()
    def exercise(self):
        try:
            assert QApplication.instance().platformName()=='windows'
            panel=self.update_panel
            assert not self.workspace_ids and not self.target_languages() and not self.start_button.isEnabled()
            self.pages.setCurrentIndex(3)
            panel.service=UpdateService(Path(os.environ['LOCALAPPDATA'])/'NoRelease',httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(404))))
            panel.check.click();self.wait(lambda:not panel.busy)
            assert 'Chưa có bản cập nhật' in panel.status.text()
            self.showMaximized();self.shot('no-release-light')
            r,e,m,keys,data=fixture_release(b'fixture data '*16000)
            slow_started=threading.Event();slow_release=threading.Event();slow=[False];threads=[]
            class Stream(httpx.SyncByteStream):
                def __iter__(self):
                    yield data[:65536];slow_started.set();slow_release.wait(5);yield data[65536:]
            def respond(req):
                threads.append(threading.get_ident())
                if str(req.url)==LATEST_URL:return httpx.Response(200,json=r)
                if req.url.path.endswith('json'):return httpx.Response(200,content=m)
                return httpx.Response(200,stream=Stream()) if slow[0] else httpx.Response(200,content=data)
            panel.service=UpdateService(Path(os.environ['LOCALAPPDATA'])/'FixtureUpdates',httpx.Client(transport=httpx.MockTransport(respond)),keys=keys,testing=True)
            panel.check.click();self.wait(lambda:not panel.busy)
            assert panel.download.isEnabled()
            for dark in (False,True):
                if self.dark!=dark:self.toggle_theme()
                self.showMaximized();self.shot(f'update-full-{dark}')
                self.showNormal();self.resize(1200,720);self.shot(f'update-medium-{dark}')
                self.resize(900,580);self.shot(f'update-small-{dark}')
                self.toggle_sidebar();self.shot(f'update-collapsed-{dark}');self.toggle_sidebar()
            self.resize(1200,720);slow[0]=True
            self.pages.widget(3).ensureWidgetVisible(panel.download)
            panel.download.click();self.wait(slow_started.is_set);self.shot('download-progress')
            panel.cancel.click();slow_release.set();self.wait(lambda:not panel.busy)
            assert panel.machine.state==State.CANCELLED and not list(panel.service.directory.glob('*.part'))
            self.shot('download-cancelled')
            slow[0]=False;panel.check.click();self.wait(lambda:not panel.busy)
            panel.download.click();self.wait(lambda:not panel.busy)
            assert panel.progress.value()==100 and panel.machine.state==State.READY_TO_INSTALL
            assert not list(panel.service.directory.glob('*.exe'))
            self.shot('verified-simulation-only')
            identity=ProcessIdentity(42,'mock-original')
            process=FakeProcess(identity,True)
            installer=FakeInstaller();env=FakeEnvironment(installed_version=panel.item.version)
            blocked=panel.simulate_helper(identity,process,SafetySnapshot(),installer,env)
            assert blocked['blocked_by'] and installer.calls==0
            self.shot('safe-exit-blocked')
            safe=SafetySnapshot(app_closed=True,process_exited=True,safe_exit_verified=True)
            assert panel.simulate_helper(identity,process,safe,installer,env)['success']
            assert env.restarts==1 and installer.calls==1
            self.shot('helper-success-simulated')
            from transcomic.update.windows_helper import AppProcessIdentity,FakeWindowsRuntime,HandoffSafety
            original=AppProcessIdentity(42,123,str(Path(os.environ['LOCALAPPDATA'])/'Installed/TransComic.exe'))
            runtime=FakeWindowsRuntime();runtime.identity=original;runtime.version=panel.item.version
            try:panel.simulate_production_helper(original,safe,runtime,HandoffSafety(logger_flushing=True))
            except UpdateError:pass
            else:raise AssertionError('Logger flush accepted')
            assert 'install' not in runtime.calls
            assert panel.simulate_production_helper(original,safe,runtime)['actual_install'] is False
            self.shot('windows-helper-simulated')
            panel.downloaded_path.write_bytes(b'tampered between download and install')
            try:panel.simulate_helper(identity,process,safe,installer,env)
            except UpdateError:pass
            else:raise AssertionError('Tampered file accepted by helper')
            assert installer.calls==1
            panel.downloaded_path.unlink()
            panel.service.client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'x'*len(data))))
            panel.download_now();self.wait(lambda:not panel.busy)
            assert panel.machine.state==State.ERROR
            self.shot('verify-failed')
            panel.service=UpdateService(Path(os.environ['LOCALAPPDATA'])/'Offline',httpx.Client(transport=httpx.MockTransport(lambda req:(_ for _ in ()).throw(httpx.ConnectError('mock offline')))))
            panel.check.click();self.wait(lambda:not panel.busy)
            assert panel.machine.state==State.ERROR and not panel.download.isEnabled()
            self.shot('offline')
            panel.auto.setChecked(True);assert self.store.setting('update_auto_check')=='1'
            panel.auto.setChecked(False);assert self.store.setting('update_auto_check')=='0'
            assert all(t!=threading.get_ident() for t in threads)
            self.pages.setCurrentIndex(0);self.shot('editor-unchanged')
            assert not self.workspace_ids and not self.target_languages() and self.sky_switch.isVisible()
            report={'platform':'windows','entry_point':'run_transcomic.py','dpr':self.devicePixelRatioF(),
                'sizes':[[900,580],[1200,720],'maximized'],'themes':['light','dark'],'real_api_requests':0,
                'installer_processes':0,'fixture_extension':'.testdata','cancel_checked':True,'worker_thread_checked':True,
                'workspace_empty':True,'target_chips_empty':True,'user_data_isolated':True,
                'verify_failure_checked':True,'safe_exit_block_checked':True,'helper_simulated_success':True,
                'tamper_before_install_blocked':True,'actual_install':False,'offline_checked':True,
                'windows_helper_algorithm_simulated':True,'logger_flush_blocked':True}
            (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            (OUT/'failure.txt').unlink(missing_ok=True);print(json.dumps(report),flush=True)
            self._exit_authorized=True;self.close()
        except Exception:
            (OUT/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');traceback.print_exc()
            self._exit_authorized=True;self.close();QApplication.instance().exit(1)

if __name__=='__main__':
    with TemporaryDirectory() as directory:
        os.environ['LOCALAPPDATA']=directory;os.environ['QT_QPA_PLATFORM']='windows'
        application.MainWindow=Smoke
        runpy.run_path(str(ROOT/'run_transcomic.py'),run_name='__main__')
