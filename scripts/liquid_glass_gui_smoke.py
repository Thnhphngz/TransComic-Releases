"""Native Windows visual acceptance via run_transcomic.py, isolated data, HTTP denied."""
import json
import hashlib
import os
import runpy
import shutil
import sys
import time
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx

BEFORE = '--before' in sys.argv
ROOT = Path('artifacts/liquid-glass-v3')
OUT = ROOT/('before' if BEFORE else 'after')/os.environ.get('QT_SCALE_FACTOR','1')
OUT.mkdir(parents=True,exist_ok=True)
if BEFORE:
    import transcomic.ui
    baseline = ROOT/'baseline-ui'
    shutil.copytree('transcomic/ui/assets',baseline/'assets',dirs_exist_ok=True)
    transcomic.ui.__path__.insert(0,str(baseline.resolve()))

from PySide6.QtCore import QTimer, Qt, QPoint
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QDialogButtonBox, QPushButton, QMessageBox
from transcomic.ui.main import MainWindow
from transcomic.documents import decode_txt
from transcomic.bulk import import_many
from transcomic.languages import language
import transcomic.app as application


def deny_http(*args,**kwargs):
    raise AssertionError('Native GUI smoke forbids HTTP')
httpx.Client.send = deny_http
httpx.AsyncClient.send = deny_http


class Smoke(MainWindow):
    def __init__(self,store):
        super().__init__(store)
        QTimer.singleShot(180,self.exercise)

    def settle(self):
        QApplication.instance().processEvents();QTest.qWait(240);time.sleep(.003)
        QApplication.instance().processEvents()

    def shot(self,name,widget=None):
        self.settle();(widget or self).grab().save(str(OUT/f'{name}.png'))

    def exercise(self):
        try:
            app=QApplication.instance();assert app.platformName()=='windows'
            files=[Path('15-16.docx'),Path('17-18.docx'),Path('19-20.docx')]
            source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            imported=import_many(self.store,files,'Tiếng Việt','Tiếng Anh')
            assert len(imported['document_ids'])==3,imported['errors']
            docs=imported['document_ids'];self.workspace_ids=list(docs)
            _,jobs=self.store.create_run([docs[0]],['Tiếng Anh','Tiếng Indonesia'],provider='kira',model='mock',source_lang='Tiếng Việt',concurrency=1)
            variants=[self.store.job(j)['document_id'] for j in jobs]
            self.workspace_ids=list(dict.fromkeys(docs+variants));self.open_document(docs[0])
            for doc in variants:
                self.store.edit_line(self.store.lines(doc)[0]['id'],'translation','English sample' if language(self.store.document(doc)['target_lang']).locale=='en' else 'Contoh Indonesia')
            self.model.load(docs[0]);self.refresh()
            # View switching uses the real workspace interface; no translation starts.
            geometry=[]
            for dark in (False,True):
                if self.dark!=dark:self.toggle_theme()
                self.showMaximized();self.shot(f'full-{dark}')
                self.showNormal();self.resize(1200,720);self.shot(f'medium-{dark}')
                combo=self.view_language;combo.showPopup();self.settle()
                assert combo.count()==2 and combo.itemText(0)=='Tiếng Anh'
                self.shot(f'en-id-popup-{dark}',combo.view().window())
                self.shot(f'en-id-context-{dark}')
                QTest.mouseMove(combo.view().viewport(),combo.view().visualRect(combo.view().model().index(0,0)).center())
                self.shot(f'en-selected-hover-{dark}',combo.view().window())
                QTest.mouseClick(combo.view().viewport(),Qt.LeftButton,pos=combo.view().visualRect(combo.view().model().index(1,0)).center())
                assert language(self.store.document(self.doc_id)['target_lang']).locale=='id'
                combo.setCurrentIndex(0)
                self.source_lang.showPopup();self.shot(f'locales-11-{dark}',self.source_lang.view().window());self.source_lang.hidePopup()
                if not BEFORE:
                    self.target_chips['Tiếng Anh'].setChecked(True)
                    self.shot(f'buttons-normal-{dark}',self.actions_widget)
                    for name,b in [('primary',self.start_button),('secondary',self.pause_button),('danger',self.stop_button)]:
                        b.setEnabled(True);QTest.mouseMove(b);self.shot(f'hover-{name}-{dark}',b)
                        QTest.mousePress(b,Qt.LeftButton);self.shot(f'pressed-{name}-{dark}',b)
                        # Release outside: capture without executing a translation command.
                        QTest.mouseRelease(b,Qt.LeftButton,pos=b.rect().bottomRight()+QPoint(30,30))
                        b.setEnabled(False);self.shot(f'disabled-{name}-{dark}',b)
                    self.refresh()
                self.shot(f'sky-{dark}',self.sky_switch)
                view=self.document_panel.view;rect=view.visualRect(view.model().index(0))
                if not BEFORE:
                    from transcomic.ui.documents_panel import DocumentDelegate
                    QTest.mouseMove(view.viewport(),DocumentDelegate.close_rect(rect).center())
                self.shot(f'file-cards-{dark}',self.document_panel)
                if not BEFORE:
                    for page in (1,2,3,4,5):
                        self.pages.setCurrentIndex(page);self.shot(f'page-{page}-{dark}')
                    self.pages.setCurrentIndex(0)
                self.resize(900,580);self.shot(f'small-{dark}')
                assert self.table.viewport().height()>80
                geometry.append({'dark':dark,'size':[self.width(),self.height()],'table_height':self.table.viewport().height()})
                if self.sidebar.width()>100:self.toggle_sidebar()
                if not self.document_panel.isHidden():self.toggle_documents_panel()
                self.shot(f'collapsed-{dark}')
                if self.sidebar.width()<100:self.toggle_sidebar()
                if self.document_panel.isHidden():self.toggle_documents_panel()
            if not BEFORE:
                self.resize(1200,720);self.settle()
                longdoc=self.store.import_document(OUT/'9999.txt',decode_txt(('\n'.join(f'Line {i}' for i in range(9999))).encode()),'vi','en')[0]
                self.open_document(longdoc)
                for size in (12,22):
                    self.change_font(size);self.table.scrollToBottom();self.settle()
                    self.table.scrollToBottom();self.shot(f'gutter-9999-font-{size}')
                dialog=QDialog(self);dialog.setWindowTitle('Xuất tài liệu · xem trước giao diện')
                layout=QVBoxLayout(dialog);layout.addWidget(QLabel('Chọn ngôn ngữ xuất và xác nhận'))
                from transcomic.ui.controls import QComboBox
                choice=QComboBox();choice.addItems(['Tiếng Anh','Tiếng Indonesia']);layout.addWidget(choice)
                box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(box)
                dialog.show();self.shot('export-dialog-dark',dialog)
                self.toggle_theme();self.shot('export-dialog-light',dialog);dialog.close()
                self.source_lang.showPopup();self.toggle_theme();self.shot('popup-during-theme',self.source_lang.view().window());self.source_lang.hidePopup()
                # Exercise the close hit target in native Windows at this DPR too.
                paths=[];close_docs=[]
                for i in range(3):
                    path=Path(os.environ['LOCALAPPDATA'])/f'close-{i}.txt'
                    path.write_text('Source sample',encoding='utf-8');paths.append(path)
                    close_docs.append(self.store.import_document(path,decode_txt(path.read_bytes()),'vi','en')[0])
                protected=close_docs[0]
                protected_job=self.store.create_job(protected,'mock','vi','en',1)
                self.store.edit_line(self.store.lines(protected)[0]['id'],'translation','Retained sample')
                self.workspace_ids=close_docs.copy();self.open_document(protected);self.resize(900,580);self.settle()
                from transcomic.ui.documents_panel import DocumentDelegate
                def close_row(row,answer=None):
                    view=self.document_panel.view;index=view.model().index(row)
                    instance=index.data(Qt.UserRole)['instance'];view.scrollTo(index);self.settle()
                    rect=DocumentDelegate.close_rect(view.visualRect(index))
                    if answer is not None:
                        def choose():
                            modal=app.activeModalWidget();assert isinstance(modal,QMessageBox)
                            modal.button(answer).click()
                        QTimer.singleShot(40,choose)
                    QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=rect.center());self.settle()
                    return instance
                close_row(0,QMessageBox.No)
                assert self.workspace_ids==close_docs and self.doc_id==protected
                close_row(0,QMessageBox.Yes);assert protected not in self.workspace_ids
                last=close_docs[2];close_row(1);assert last not in self.workspace_ids
                close_row(0);assert not self.workspace_ids and self.doc_id is None
                assert all(p.read_text(encoding='utf-8')=='Source sample' for p in paths)
                assert self.store.job(protected_job) and self.store.lines(protected)[0]['translation']=='Retained sample'
                self.shot('native-x-empty')
            self._exit_authorized=True
            assert source_hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            report={'platform':app.platformName(),'entry_point':'run_transcomic.py','before':BEFORE,
                    'scale_factor':os.environ.get('QT_SCALE_FACTOR','1'),'device_pixel_ratio':self.devicePixelRatioF(),
                    'geometry':geometry,'real_api_requests':0,'source_files':[p.name for p in files],
                    'source_sha256':source_hashes,'source_files_unchanged':True}
            if not BEFORE:report.update(native_file_removals=3,native_cancel_preserved=True,native_source_history_preserved=True)
            (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            (OUT/'failure.txt').unlink(missing_ok=True)
            print(json.dumps(report),flush=True);self.close()
        except Exception:
            (OUT/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');traceback.print_exc()
            self._exit_authorized=True;self.close();QApplication.instance().exit(1)


if __name__=='__main__':
    with TemporaryDirectory() as root:
        os.environ['LOCALAPPDATA']=root
        os.environ['QT_QPA_PLATFORM']='windows'
        application.MainWindow=Smoke
        runpy.run_path('run_transcomic.py',run_name='__main__')
