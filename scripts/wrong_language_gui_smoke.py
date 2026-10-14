"""Native Windows entry point, user historical DOCX, local validation only."""
import json,os,runpy,traceback
from pathlib import Path
try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QListWidget,QPushButton
from PySide6.QtTest import QTest
from transcomic.ui.main import MainWindow
from transcomic.bulk import import_many,plan_exports,write_exports
from transcomic.docx_document import import_docx
import transcomic.app as application

OUT=Path('artifacts/wrong-language/gui')
class Smoke(MainWindow):
    def __init__(self,store):
        super().__init__(store);QTimer.singleShot(200,self.exercise)
    def exercise(self):
        try:
            app=QApplication.instance();assert app.platformName()=='windows'
            source=Path('D:/word 50 cach/17-18.docx')
            doc=import_many(self.store,[source],'vi','en')['document_ids'][0]
            old=import_docx(source.parent/'TransComic/English/17-18_EN.docx')
            with self.store.transaction():
                for row,unit in zip(self.store.lines(doc),old.units):
                    self.store.db.execute("UPDATE lines SET translation=?,state='done',translation_source_revision=source_revision WHERE id=?",(unit.text,row['id']))
            self.open_document(doc);self.refresh()
            assert [r['ordinal']+1 for r in self.model.all_rows if r['state']=='wrong_target_language']==[67,68,69]
            assert self.scheduler is None
            for dark in (False,True):
                if self.dark!=dark:self.toggle_theme()
                self.resize(1400,850);QTest.qWait(80);self.navigate_to_line(self.store.lines(doc)[66]['id'])
                self.grab().save(str(OUT/f'history-{dark}.png'))
            def close_dialog():
                for w in app.topLevelWidgets():
                    if isinstance(w,QDialog) and w.isVisible():w.accept()
            def click_wrong_line():
                for widget in app.topLevelWidgets():
                    if not isinstance(widget,QDialog) or not widget.isVisible():continue
                    listing=widget.findChild(QListWidget)
                    for i in range(listing.count()):
                        item=listing.item(i);line_id=item.data(Qt.UserRole)
                        if self.store.line(line_id)['state']=='wrong_target_language':
                            listing.itemClicked.emit(item);return
            QTimer.singleShot(150,click_wrong_line);self.show_warnings()
            assert self.model.rows[self.table.currentIndex().row()]['ordinal']==66
            old_question=QMessageBox.question; confirmations=[]
            def decline(*args,**kwargs):confirmations.append(True);return QMessageBox.No
            QMessageBox.question=decline
            def click_retry():
                for widget in app.topLevelWidgets():
                    if isinstance(widget,QDialog) and widget.isVisible():
                        for b in widget.findChildren(QPushButton):
                            if 'ngôn ngữ' in b.text():b.click();return
            try:
                QTimer.singleShot(150,click_retry);self.show_warnings()
                assert confirmations and self.scheduler is None
            finally:QMessageBox.question=old_question
            plan=plan_exports(self.store.export_snapshot([doc]),OUT/'export',mode='custom')
            results=write_exports(self.store,plan,allow_incomplete=True)
            assert results[0]['state']=='blocked_language' and not plan[0]['target'].exists()
            QTimer.singleShot(150,close_dialog);self.stage2_result({'kind':'export','result':results})
            line=self.store.lines(doc)[66];self.store.edit_line(line['id'],'translation','Cael quickly let go of her, I thought you were an intruder')
            self.update_editorial();self.model.refresh()
            assert self.store.line(line['id'])['attempt_kind']=='manual' and self.store.line(line['id'])['state']=='done'
            assert sum(r['state']=='wrong_target_language' for r in self.store.lines(doc))==2
            report={'platform':app.platformName(),'historical_fault_ordinals':[67,68,69],'manual_revalidation':True,'export_blocked':True,'dialog_navigation':True,'light_dark':True,'real_api_requests':0}
            (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
            self._exit_authorized=True;self.close();app.quit()
        except Exception:
            (OUT/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');traceback.print_exc();QApplication.instance().exit(1)

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory() as root:
        os.environ['LOCALAPPDATA']=root;application.MainWindow=Smoke
        runpy.run_path('run_transcomic.py',run_name='__main__')
