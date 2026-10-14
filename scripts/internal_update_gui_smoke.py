"""Native Windows queue dialog + Internal download/helper + Signed Stable smoke."""
import json
import os
from pathlib import Path
import runpy
import sys
try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
os.environ.setdefault('TRANSCOMIC_SMOKE_EVIDENCE','internal-update-and-queue-clear')
from scripts import updater_gui_smoke as base
from test_internal_queue_clear import populated,fixture,service
from transcomic.ui.main import MainWindow
from transcomic.ui.queue_clear import ClearDialog
from transcomic.update.windows_helper import FakeWindowsRuntime,AppProcessIdentity
from transcomic.update.install import SafetySnapshot
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton


class Smoke(base.Smoke):
    def exercise(self):
        try:
            directory=Path(os.environ['LOCALAPPDATA'])
            store,doc=populated(directory)
            w=MainWindow(store);w.show();w.open_document(doc);w.pages.setCurrentIndex(1);w.refresh()
            reports=[]
            for dark in (False,True):
                if w.dark!=dark:w.toggle_theme()
                if not store.history():
                    job=store.create_job(doc,'fixture','Tiếng Việt','Tiếng Anh',1);store.job_state(job,'completed')
                w.refresh();QTest.qWait(200)
                for size in ((900,580),(1200,720)):
                    w.resize(*size);QTest.qWait(200)
                    assert w.clear_all_jobs_button.isVisible() and w.clear_all_jobs_button.width()>70
                    assert w.clear_all_jobs_button.geometry().right()<=w.clear_all_jobs_button.parentWidget().width()
                    w.grab().save(str(base.OUT/f'queue-{size[0]}-{dark}.png'))
                before=store.lines(doc)
                def cancel():
                    dialog=QApplication.activeModalWidget();assert isinstance(dialog,ClearDialog)
                    dialog.grab().save(str(base.OUT/f'clear-confirm-{dark}.png'))
                    assert any(b.isDefault() and b.text()=='Hủy' for b in dialog.findChildren(QPushButton))
                    dialog.reject()
                QTimer.singleShot(100,cancel);w.clear_all_jobs_button.click();assert store.history()
                QTimer.singleShot(100,lambda:QApplication.activeModalWidget().accept())
                w.clear_all_jobs_button.click()
                self.wait(lambda:not w.queue_clear_busy)
                assert not store.history() and w.job_list.count()==0 and not w.clear_all_jobs_button.isEnabled()
                assert store.lines(doc)==before
                w.grab().save(str(base.OUT/f'queue-cleared-{dark}.png'))
                # Real Search/Replace navigation and undo on retained manuscript.
                w.pages.setCurrentIndex(0);w.search.open(True);w.search.scope.setCurrentIndex(2)
                w.search.query.setText('saved');w.search.replacement.setText('edited');w.search.navigate(1);w.search.replace_current()
                assert store.lines(doc)[0]['translation']=='edited translation'
                w.search.undo();assert store.lines(doc)[0]['translation']=='saved translation'
                w.search.hide();w.pages.setCurrentIndex(1)
                reports.append({'dark':dark,'dpr':w.devicePixelRatioF(),'cancel_preserved':True,'clear_preserved_translation':True,'search_replace_undo':True})
            w._exit_authorized=True;w.close();QTest.qWait(300)
            release,envelope,contents=fixture();panel=self.update_panel
            panel.service=service(directory/'internal',release,contents);self.pages.setCurrentIndex(3)
            panel.check.click();self.wait(lambda:not panel.busy)
            assert panel.download.isEnabled() and panel.item.signature_status=='VERIFIED_INTERNAL_HTTPS_SHA256'
            if panel.update_dialog is not None:panel.update_dialog.reject()
            for dark in (False,True):
                if self.dark!=dark:self.toggle_theme()
                self.shot(f'internal-available-{dark}')
            panel.download.click();self.wait(lambda:not panel.busy)
            assert panel.downloaded_path and panel.downloaded_path.read_bytes()==contents[panel.item.filename]
            installation=directory/'installed';installation.mkdir()
            identity=AppProcessIdentity(123,456,str(installation/'TransComic.exe'))
            runtime=FakeWindowsRuntime();runtime.identity=identity;runtime.version=panel.item.version
            result=panel.simulate_production_helper(identity,SafetySnapshot(app_closed=True,process_exited=True,safe_exit_verified=True),runtime)
            assert result['simulated'] and not result['actual_install']
            (base.OUT/'internal-queue-report.json').write_text(json.dumps({'queue':reports,'internal_unsigned_verified':True,'internal_helper_mock':True,'auto_install':False,'real_api_requests':0},indent=2),encoding='utf8')
        except Exception:
            import traceback
            (base.OUT/'internal-queue-failure.txt').write_text(traceback.format_exc(),encoding='utf8')
            if 'w' in locals():w._exit_authorized=True;w.close()
            if 'store' in locals():store.close()
            self._exit_authorized=True;self.close();QApplication.instance().exit(1)
            return
        super().exercise()


if __name__=='__main__':
    with TemporaryDirectory(prefix='TransComic-internal-gui-') as directory:
        os.environ['LOCALAPPDATA']=directory;os.environ['QT_QPA_PLATFORM']='windows'
        base.application.MainWindow=Smoke
        runpy.run_path(str(ROOT/'run_transcomic.py'),run_name='__main__')
