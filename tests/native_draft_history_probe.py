"""Opt-in native Windows subprocess probe. Requires an explicit isolated root.

Synthetic DOCX/TXT/PNG/PCM only; runtime inference and all HTTP are fenced.
The baseline overlay reads HEAD modules without touching the working tree.
"""
import argparse
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))


def baseline_overlay():
    names=('automation.repository','automation.validation','tts.storage','ui.automation_page','ui.main','ui.tts_history','ui.tts_page')
    sources={f'transcomic.{n}':subprocess.check_output(['git','show','v2.0.3:transcomic/'+n.replace('.','/')+'.py'],cwd=ROOT).decode('utf8') for n in names}
    class Loader(importlib.abc.MetaPathFinder,importlib.abc.Loader):
        def find_spec(self,fullname,path=None,target=None):
            if fullname in sources:return importlib.util.spec_from_loader(fullname,self)
        def create_module(self,spec):return None
        def exec_module(self,module):
            module.__file__=str(ROOT/(module.__name__.replace('.','/')+'.py'))
            exec(compile(sources[module.__name__],module.__file__,'exec'),module.__dict__)
    sys.meta_path.insert(0,Loader())


def child(args):
    if args.baseline:baseline_overlay()
    os.environ['QT_QPA_PLATFORM']='windows'
    if args.scale:
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        os.environ['QT_SCALE_FACTOR']=str(args.scale/(ctypes.windll.user32.GetDpiForSystem()/96))
    import threading
    import httpx
    def forbidden(*a,**k):raise AssertionError('No HTTP is permitted in this lifecycle probe')
    httpx.Client.send=forbidden;httpx.AsyncClient.send=forbidden
    from PySide6.QtCore import QTimer,Qt,QMimeData,QUrl,QPointF
    from PySide6.QtGui import QDragEnterEvent,QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QInputDialog,QMessageBox,QSystemTrayIcon
    from transcomic.storage import Store
    from transcomic.ui.main import MainWindow
    from transcomic.ui.tts_page import TtsPage
    from test_tts import FakeEngine
    from test_automation_ui import wait
    from transcomic.automation.validation import check_current
    import transcomic.automation.validation as validation
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs,True)
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    QSystemTrayIcon.isSystemTrayAvailable=lambda:False
    # A bounded stand-in for a slow installed runtime check, not inference.
    def runtime(page):
        def work():time.sleep(.6)
        page.background(work)
    TtsPage.check_runtime=runtime
    started=time.perf_counter();store=Store(args.profile/'translation.sqlite3');store.set_setting('update_auto_check','0')
    w=MainWindow(store);screen=app.primaryScreen().availableGeometry()
    w.resize(min(1280,max(900,screen.width()-24)),min(820,max(580,screen.height()-50)));w.show();app.processEvents()
    metrics=dict(platform=app.platformName(),pid=os.getpid(),window_visible_s=time.perf_counter()-started,window_shown_at_perf=time.perf_counter(),dpr=w.devicePixelRatioF())
    if args.dark and not w.dark:w.toggle_theme()
    p=w.automation_page
    def confirm_close():
        def trace_wait():
            if not w._closed:
                import faulthandler
                with (args.profile/(args.action+'-close-wait-trace.txt')).open('w',encoding='utf8') as trace:faulthandler.dump_traceback(file=trace)
        def accept():
            from transcomic.ui.exit_dialog import ExitDialog
            for dialog in app.topLevelWidgets():
                if isinstance(dialog,ExitDialog) and dialog.isVisible():
                    # The normal ExitDialog action, not a production install/update.
                    QTest.mouseClick(dialog.buttons.get('safe') or dialog.buttons['exit'],Qt.LeftButton)
        QTimer.singleShot(80,accept)
        QTimer.singleShot(450,trace_wait)
        start=time.perf_counter();w.close();wait(app,lambda:w._closed,8)
        metrics['close_to_window_closed_s']=time.perf_counter()-start
        metrics['closed_at_perf']=time.perf_counter()
    def documents_drop(paths):
        mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths]);pos=QPointF(40,40)
        enter=QDragEnterEvent(pos.toPoint(),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        QApplication.sendEvent(p,enter)
        drop=QDropEvent(pos,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(p,drop)
        assert drop.isAccepted()
    if args.action.startswith('tts'):
        import hashlib
        w.pages.setCurrentIndex(7);app.processEvents();page=w.tts_page
        if args.action=='tts-create':
            wait(app,lambda:not page.is_busy());page.scheduler.factory=FakeEngine;page.runtime_ready=True
            source=args.profile/'history.txt';source.write_text('Synthetic audio line',encoding='utf8')
            page.import_paths([source]);wait(app,lambda:not page.is_busy())
            QTest.mouseClick(page.start_button,Qt.LeftButton);wait(app,lambda:not page.is_busy())
            page.load_history();doc=page.store.docs(page.run_id)[0]
            assert page.store.run(page.run_id)['state']=='completed'
            audio=Path(doc['folder'])/'0001.wav'
            (args.profile/'audio.json').write_text(json.dumps(dict(doc=doc['id'],audio=str(audio),sha256=hashlib.sha256(audio.read_bytes()).hexdigest())),encoding='utf8')
        else:
            info=json.loads((args.profile/'audio.json').read_text(encoding='utf8'));metrics['audio_exists']=Path(info['audio']).is_file()
            metrics['audio_unchanged']=hashlib.sha256(Path(info['audio']).read_bytes()).hexdigest()==info['sha256'];assert metrics['audio_unchanged']
            if args.action=='tts-delete':
                card=page.history_panel.cards[info['doc']];menu=card.context_menu()
                action=next(a for a in menu.actions() if a.text().startswith('Xóa bản ghi'))
                metrics['delete_enabled_during_probe']=action.isEnabled()
                if action.isEnabled():
                    def yes():
                        for dialog in app.topLevelWidgets():
                            if isinstance(dialog,QMessageBox) and dialog.isVisible():QTest.mouseClick(dialog.button(QMessageBox.Yes),Qt.LeftButton)
                    menu.popup(card.mapToGlobal(card.rect().center()));QTest.qWait(60)
                    QTimer.singleShot(120,yes);QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(action).center());app.processEvents()
                    assert info['doc'] not in page.history_panel.cards
            else:metrics['deleted_still_absent']=info['doc'] not in page.history_panel.cards
        QTest.qWait(60);assert w.grab().save(str(args.profile/(args.action+'.png')))
        confirm_close()
    else:
        w.pages.setCurrentIndex(9);app.processEvents()
        if args.action=='add':
            def name():
                for dialog in app.topLevelWidgets():
                    if isinstance(dialog,QInputDialog) and dialog.isVisible():dialog.setTextValue('Native draft');dialog.accept()
            QTimer.singleShot(100,name);p.new_workset();wid=p.current
            from docx import Document
            inputs=args.profile/'inputs';inputs.mkdir(exist_ok=True);paths=[]
            for i in range(args.count):
                path=inputs/(f'{i:03}.docx' if i%2 else f'{i:03}.txt')
                if i%2:
                    doc=Document();doc.add_paragraph('Synthetic input line');doc.save(path)
                else:path.write_text('Synthetic input line',encoding='utf8')
                paths.append(path)
            if args.stage=='reading':
                import transcomic.docx_document as docx
                original=docx.import_docx;first_read=[True]
                def slow(path):
                    if first_read[0]:first_read[0]=False;time.sleep(.25)
                    return original(path)
                docx.import_docx=slow
            documents_drop(paths)
            if args.stage!='immediate':
                if args.stage=='reading':wait(app,lambda:p.import_busy)
                else:wait(app,lambda:not p.import_busy,20)
            if args.stage in ('images','validated'):
                from PIL import Image
                images=args.profile/'images';images.mkdir(exist_ok=True);Image.new('RGB',(8,8)).save(images/'1.png')
                gid=p.repo.group_summaries(wid)[0]['id']
                if args.stage=='images':
                    original=validation.image_manifest
                    def slow(folder,mode,*,cancelled=None):
                        end=time.monotonic()+2
                        while time.monotonic()<end:check_current(cancelled);time.sleep(.01)
                        return original(folder,mode,cancelled=cancelled)
                    validation.image_manifest=slow
                p.pair_folder(gid,images)
                if args.stage=='validated':wait(app,lambda:not p.pair_pending)
            if args.stage=='validated':
                wait(app,lambda:p.validate_button.isEnabled())
                QTest.mouseClick(p.validate_button,Qt.LeftButton);wait(app,lambda:p.proof is not None,20)
            metrics['accepted_inputs']=len(paths)
            assert not w.store.jobs() and not p.controller.busy
            confirm_close()
        else:
            # Traceable validation delay checks tab/scroll handling while a worker
            # is live. It honors cancellation and does not hold SQLite's lock.
            entered=threading.Event();original=p.controller.validate
            def slow(id,**kwargs):
                entered.set();end=time.monotonic()+2
                while time.monotonic()<end:check_current(kwargs.get('cancelled'));time.sleep(.01)
                return original(id,**kwargs)
            p.controller.validate=slow;p.queue_validation(force=True);wait(app,entered.is_set)
            ticks=[];timer=QTimer(w);timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(time.perf_counter()));timer.start()
            interaction=time.perf_counter()
            for index in (2,9,0,9):w.pages.setCurrentIndex(index);app.processEvents();p.table.scrollToBottom();QTest.qWait(25)
            metrics['visible_to_interactive_s']=time.perf_counter()-started-metrics['window_visible_s']
            metrics['tab_scroll_sequence_s']=time.perf_counter()-interaction
            metrics['validation_worker_live']=any(t.is_alive() for t in p.tasks)
            metrics['heartbeat_ticks']=len(ticks);timer.stop()
            # Allow recovered input intents to finish without starting execution.
            wait(app,lambda:not p.import_busy and not p.pair_pending,20)
            metrics['restored_inputs']=len(p.repo.group_summaries(p.current))
            metrics['jobs']=len(w.store.jobs());metrics['started']=p.repo.workset(p.current)['started']
            assert metrics['restored_inputs']==args.count and metrics['jobs']==0 and metrics['started']==0
            assert w.grab().save(str(args.profile/'reopened.png'))
            confirm_close()
    metrics['exit_perf']=time.perf_counter()
    (args.profile/(args.action+'-result.json')).write_text(json.dumps(metrics,indent=2),encoding='utf8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--child',action='store_true');parser.add_argument('--baseline',action='store_true');parser.add_argument('--profile',type=Path);parser.add_argument('--action');parser.add_argument('--stage',default='immediate');parser.add_argument('--count',type=int,default=3);parser.add_argument('--dark',action='store_true');parser.add_argument('--trials',nargs='*');parser.add_argument('--scale',type=float);args=parser.parse_args()
    if args.child:return child(args)
    args.root.mkdir(parents=True,exist_ok=True);results=[]
    trials=[('tts',0,'tts')]+[(f'{count}-{stage}',count,stage) for count in (3,100) for stage in ('immediate','reading','images','validated')]
    for name,count,stage in trials:
        if args.trials and name not in args.trials:continue
        profile=args.root/name;profile.mkdir(exist_ok=False)
        for action in (('tts-create','tts-delete','tts-verify') if stage=='tts' else ('add','reopen')):
            cmd=[sys.executable,__file__,'--root',str(args.root),'--child','--profile',str(profile),'--action',action,'--stage',stage,'--count',str(count)]
            if args.baseline:cmd.append('--baseline')
            if args.dark:cmd.append('--dark')
            if args.scale:cmd.extend(['--scale',str(args.scale)])
            begin=time.perf_counter()
            with (profile/(action+'.log')).open('w',encoding='utf8') as log:
                proc=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=55)
            path=profile/(action+'-result.json');item=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
            item.update(trial=name,action=action,returncode=proc.returncode,total_process_s=time.perf_counter()-begin)
            if 'window_shown_at_perf' in item:item['launch_to_visible_s']=item['window_shown_at_perf']-begin
            if 'closed_at_perf' in item:item['window_closed_to_process_exit_s']=time.perf_counter()-item['closed_at_perf']
            results.append(item);(args.root/'results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
            print(name,action,proc.returncode,flush=True)
    return int(any(r['returncode'] for r in results))


if __name__=='__main__':raise SystemExit(main())
