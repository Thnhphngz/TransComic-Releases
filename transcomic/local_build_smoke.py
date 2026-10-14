"""Opt-in frozen devtest smoke: isolated data and HTTP mocks only, never install."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback
import httpx
from PySide6.QtCore import QTimer,Qt,QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from .storage import Store
from .documents import decode_txt
from .ui.main import MainWindow
from .update.internal import InternalUpdateService,manifest
from .update.metadata import canonical,asset_url,release_url
from .update.service import LATEST_URL
from .version import VERSION


def mock_service(directory):
    from .release_version import bumped
    version=bumped(VERSION);tag='v'+version;name=f'TransComic-Setup-{version}-windows-x64.testdata';data=b'nonexecutable update fixture'
    envelope=manifest(version,name.replace('.testdata','.exe'),len(data),hashlib.sha256(data).hexdigest(),'2026-10-14T00:00:00Z')
    envelope['payload']['installer_filename']=name;raw=canonical(envelope)
    contents={name:data,'transcomic-update.json':raw,'SHA256SUMS.txt':(hashlib.sha256(data).hexdigest()+'  '+name+'\n'+hashlib.sha256(raw).hexdigest()+'  transcomic-update.json\n').encode()}
    release={'tag_name':tag,'draft':False,'prerelease':False,'html_url':release_url(tag),'published_at':'2026-10-14T00:00:00Z','body':'Internal update smoke <script>text only</script>',
             'assets':[{'name':n,'size':len(b),'state':'uploaded','browser_download_url':asset_url(tag,n)} for n,b in contents.items()]}
    def respond(req):
        return httpx.Response(200,json=release) if str(req.url)==LATEST_URL else httpx.Response(200,content=contents[req.url.path.rsplit('/',1)[-1]])
    return InternalUpdateService(directory,httpx.Client(transport=httpx.MockTransport(respond)),testing=True)


def main():
    root=Path(os.environ.get('LOCALAPPDATA','')).resolve()
    # This mode cannot open the normal user database, even when called without isolation.
    if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not root.name.startswith('TransComic-build-smoke-') or not (root/'isolated-smoke.json').is_file():return 2
    if json.loads((root/'isolated-smoke.json').read_text())!={'mode':'isolated-build-smoke'}:return 2
    original=httpx.Client.send
    def guard(client,*args,**kwargs):
        if not isinstance(client._transport,httpx.MockTransport):raise AssertionError('Real HTTP forbidden')
        return original(client,*args,**kwargs)
    httpx.Client.send=guard
    httpx.AsyncClient.send=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Real HTTP forbidden'))
    app=QApplication(sys.argv);app.setApplicationName('TransComic');app.setAttribute(Qt.AA_DontUseNativeDialogs,True)
    store=Store(root/'TransComic/transcomic.sqlite3');window=MainWindow(store);window.update_panel.auto.setChecked(False)
    window.show();app.setQuitOnLastWindowClosed(False)
    def wait(condition):
        if condition():return
        loop=QEventLoop();poll=QTimer();poll.setInterval(20);poll.setTimerType(Qt.PreciseTimer)
        poll.timeout.connect(lambda:loop.quit() if condition() else None)
        deadline=QTimer();deadline.setSingleShot(True);deadline.setTimerType(Qt.PreciseTimer);deadline.timeout.connect(loop.quit)
        poll.start();deadline.start(5000)
        try:loop.exec()
        finally:poll.stop();deadline.stop()
        assert condition(),'Smoke condition timeout'
    def exercise():
        try:
            assert store.path.resolve().is_relative_to(root)
            from docx import Document
            from .docx_document import render_docx,inspect_docx
            text=root/'fixture.txt';text.write_bytes(b'Alpha one\nAlpha two')
            word=root/'fixture.docx';generated=Document();generated.add_paragraph('Alpha one');generated.add_paragraph('Alpha two');generated.save(word)
            original_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (text,word)}
            window.import_paths([str(text),str(word)]);wait(lambda:not window.import_busy)
            assert len(window.workspace_ids)==2
            doc=next(i for i in window.workspace_ids if store.document(i)['format']=='txt')
            word_id=next(i for i in window.workspace_ids if store.document(i)['format']=='docx')
            for row in store.units(word_id):store.edit_line(row['id'],'translation','Translated '+row['source'])
            rendered,missing=render_docx(word.read_bytes(),store.units(word_id))
            assert missing==0 and len(inspect_docx(rendered).units)==2
            window.open_document(word_id);QTest.qWait(40);window.grab().save(str(root/'docx-fixture.png'))
            window.open_document(doc);window.model.setData(window.model.index(0,1),'Alpha translation')
            QTest.qWait(300);QApplication.processEvents()
            before=store.lines(doc);targets=window.target_languages()
            for dark in (False,True):
                if window.dark!=dark:window.toggle_theme()
                for compact in (False,True):
                    if (window.sidebar.width()<100)!=compact:window.toggle_sidebar()
                    if compact:window.showMaximized()
                    else:window.showNormal();window.resize(900,580)
                    window.pages.setCurrentIndex(6);QTest.qWait(150)
                    assert window.navigation_group.button(6).isChecked()
                    assert window.nav_buttons[-1].geometry().bottom()<window.collapse_button.geometry().top()
                    assert window.sky_switch.geometry().bottom()<=window.sidebar.height()
                    window.grab().save(str(root/f'srt-{dark}-{compact}.png'))
                    window.pages.setCurrentIndex(0);assert store.lines(doc)==before and window.target_languages()==targets,repr({'lines_before':before,'lines_after':store.lines(doc),'targets_before':targets,'targets_after':window.target_languages()})
                window.search.open(True);window.search.scope.setCurrentIndex(2);window.search.query.setText('Alpha');window.search.replacement.setText('Beta');window.search.navigate(1);window.search.replace_current()
                assert store.lines(doc)[0]['translation']=='Beta translation';window.search.undo();window.search.hide()
                before=store.lines(doc)  # Replace/Undo deliberately advances edit revisions.
            job=store.create_job(doc,'fixture','Tiếng Việt','Tiếng Anh',1);store.job_state(job,'completed')
            window.pages.setCurrentIndex(1);window.refresh();window.confirm_clear_all=lambda count:True;window.clear_all_queue()
            wait(lambda:not window.queue_clear_busy);assert not store.history() and store.lines(doc)==before
            panel=window.update_panel;panel.service=mock_service(root/'Updates');window.pages.setCurrentIndex(3)
            panel.check_now(False);wait(lambda:not panel.busy);assert panel.update_dialog is None
            for dark in (False,True):
                if window.dark!=dark:window.toggle_theme()
                panel.check_now(True);wait(lambda:panel.update_dialog is not None)
                panel.update_dialog.grab().save(str(root/f'popup-{dark}.png'));panel.update_dialog.reject();wait(lambda:panel.update_dialog is None)
                assert panel.downloaded_path is None
            panel.check_now(True);wait(lambda:panel.update_dialog is not None);panel.update_dialog.download.click()
            wait(lambda:not panel.busy and panel.downloaded_path is not None)
            assert panel.downloaded_path.suffix=='.testdata'
            report={'passed':True,'frozen':bool(getattr(sys,'frozen',False)),'version':VERSION,'platform':app.platformName(),'dpr':window.devicePixelRatioF(),
                    'txt_docx_fixture':True,'docx_export_units':2,'source_files_unchanged':original_hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (text,word)},
                    'themes':['light','dark'],'srt_placeholder':True,'workspace_preserved':True,'queue_clear':True,'search_replace_undo':True,
                    'manual_popup':True,'auto_no_popup':True,'later_no_download':True,'download_verified':True,'real_http_requests':0,'installer_processes':0,
                    'isolated_database':str(store.path),'safe_exit_deadline_ms':900,'process_exit_observed_by_launcher':False}
            (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
            window.confirm_exit=lambda running:'safe'
            window.close()
            QTimer.singleShot(900,lambda:verify_close())
        except Exception:
            (root/'failure.txt').write_text(traceback.format_exc(),encoding='utf8');window._exit_authorized=True;window.close();app.exit(1)
    def verify_close():
        if not window._closed:
            (root/'failure.txt').write_text('Safe Exit 900ms failed',encoding='utf8');app.exit(1)
        else:
            report=json.loads((root/'report.json').read_text(encoding='utf8'));report['safe_exit_verified']=True
            (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8');app.quit()
    QTimer.singleShot(200,exercise)
    return app.exec()
