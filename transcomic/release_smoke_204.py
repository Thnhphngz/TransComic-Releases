"""Opt-in frozen hotfix checks under the existing isolated smoke guard."""
import hashlib
import json
from pathlib import Path
import threading
import time
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox
from .version import VERSION


def run(window,root,wait,phase):
    app=QApplication.instance();p=window.automation_page
    window.confirm_exit=lambda running:'safe' if running else 'exit'
    proof=dict(version=VERSION,phase=phase,frozen=bool(getattr(__import__('sys'),'frozen',False)),platform=app.platformName(),requests=0)
    from .ui.startup_ack import StartupAcknowledgement
    from .update.timing import UpdateTrace
    acknowledgements=[]
    window._hotfix_ack=StartupAcknowledgement(window,lambda:acknowledgements.append(True),UpdateTrace(root/'TransComic/Updates','startup_probe'))
    wait(lambda:bool(acknowledgements));assert acknowledgements==[True];proof['paint_ack_event_loop']=True
    record=root/'hotfix-expected.json'
    if phase=='seed':
        window.pages.setCurrentIndex(7);app.processEvents();page=window.tts_page;page.runtime_ready=True
        class PCM:
            backend='CPUExecutionProvider'
            def __init__(self,*a):pass
            def probe(self,*a):pass
            def synthesize(self,*a):
                import numpy as np
                yield np.sin(np.arange(800,dtype=np.float32)*.12)*.1
            def close(self):pass
        page.scheduler.factory=PCM
        source=root/'History.txt';source.write_text('A synthetic completed audio sentence',encoding='utf8')
        page.import_paths([source]);wait(lambda:not page.is_busy());QTest.mouseClick(page.start_button,Qt.LeftButton);wait(lambda:not page.is_busy())
        doc=page.store.docs(page.run_id)[0];audio=Path(doc['folder'])/'0001.wav';assert page.store.run(page.run_id)['state']=='completed'
        from .automation.validation import defaults,check_current
        wid=p.repo.create('Frozen draft 204',defaults(window.store));p.load_worksets(wid)
        p.fields['speed'].setValue(1.25)
        paths=[]
        from docx import Document
        for i in range(100):
            path=root/(f'{i:03}.docx' if i%2 else f'{i:03}.txt')
            if i%2:
                d=Document();d.add_paragraph('A synthetic input line');d.save(path)
            else:path.write_text('A synthetic input line',encoding='utf8')
            paths.append(str(path))
        original=p.repo.add;entered=threading.Event()
        def delayed(*args,**kwargs):
            entered.set()
            while not kwargs['cancelled']():time.sleep(.005)
            check_current(kwargs['cancelled'])
        p.repo.add=delayed;p.drop_paths(paths);wait(entered.is_set)
        record.write_text(json.dumps(dict(document=doc['id'],audio=str(audio),sha256=hashlib.sha256(audio.read_bytes()).hexdigest(),workset=wid)),encoding='utf8')
        proof['close_during_draft_import']=True
    else:
        expected=json.loads(record.read_text(encoding='utf8'));wait(lambda:not p.import_busy,20)
        assert len(p.repo.group_summaries(expected['workset']))==100
        work=p.repo.workset(expected['workset']);assert work['state']=='draft' and not work['started'] and work['config']['speed']==1.25
        window.pages.setCurrentIndex(7);app.processEvents();page=window.tts_page
        if phase=='delete':
            # Reopening TTS while a runtime check is still busy must allow delete.
            entered=threading.Event();release=threading.Event()
            def probe():entered.set();release.wait(4)
            page.background(probe);wait(entered.is_set)
            card=page.history_panel.cards[expected['document']];menu=card.context_menu()
            action=next(a for a in menu.actions() if a.text().startswith('Xóa bản ghi'));assert action.isEnabled()
            def confirm():
                for dialog in app.topLevelWidgets():
                    if isinstance(dialog,QMessageBox) and dialog.isVisible():QTest.mouseClick(dialog.button(QMessageBox.Yes),Qt.LeftButton)
            menu.popup(card.mapToGlobal(card.rect().center()));QTest.qWait(80);QTimer.singleShot(120,confirm)
            QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(action).center());release.set();wait(lambda:not page.is_busy())
        assert expected['document'] not in page.history_panel.cards
        assert hashlib.sha256(Path(expected['audio']).read_bytes()).hexdigest()==expected['sha256']
        proof.update(history_absent=True,audio_unchanged=True,draft_groups=100,started=0,config_preserved=True)
        for tab in (0,9,7,9):window.pages.setCurrentIndex(tab);app.processEvents();p.table.scrollToBottom()
        if phase=='verify':
            from .automation.validation import check_current
            entered=threading.Event()
            def validation(id,**kwargs):
                entered.set()
                while True:check_current(kwargs['cancelled']);time.sleep(.005)
            p.controller.validate=validation;p.queue_validation(force=True);wait(entered.is_set)
            proof['close_during_validation']=True
    assert not window.store.jobs() and not p.controller.busy
    QTest.qWait(40);assert window.grab().save(str(root/('hotfix-'+phase+'.png')))
    begin=time.perf_counter();window.close();wait(lambda:window._closed,5)
    proof.update(passed=True,close_seconds=time.perf_counter()-begin)
    (root/('hotfix-'+phase+'.json')).write_text(json.dumps(proof,indent=2),encoding='utf8')
    return 0
