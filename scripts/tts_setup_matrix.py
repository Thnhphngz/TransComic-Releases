"""Native DPI/theme checks for setup states using a labelled offline mock flow."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    p=argparse.ArgumentParser();p.add_argument('--scale',default='1');p.add_argument('--dark',action='store_true');p.add_argument('--output',required=True);args=p.parse_args()
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4));os.environ['QT_SCALE_FACTOR']=str(float(args.scale)/(ctypes.windll.user32.GetDpiForSystem()/96))
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QPushButton
    from scripts.test_runtime import TemporaryDirectory
    from transcomic.storage import Store
    from transcomic.ui.main import MainWindow
    from transcomic.ui.tts_page import TtsPage
    from transcomic.tts.setup import SetupFlow
    app=QApplication([]);TtsPage.check_runtime=lambda page:setattr(page,'runtime_ready',False);out=Path(args.output);out.mkdir(parents=True,exist_ok=True);tag=('dark' if args.dark else 'light')+'-'+args.scale
    def wait(condition):
        end=time.monotonic()+15
        while not condition() and time.monotonic()<end:app.processEvents();QTest.qWait(10)
        assert condition()
    with TemporaryDirectory() as folder:
        store=Store(Path(folder)/'translation.sqlite3');store.set_setting('dark','1' if args.dark else '0');window=MainWindow(store);window.confirm_exit=lambda running:'safe' if running else 'exit';window.resize(1380,820);window.show();window.pages.setCurrentIndex(7);page=window.tts_page;page.open_settings();app.processEvents();page.asset_status.setText('Kokoro — Chưa tải')
        def capture(name):
            app.processEvents();QTest.qWait(70)
            assert page.asset_status.height()>=page.asset_status.heightForWidth(page.asset_status.width()),'Setup status text clipped'
            assert page.settings_dialog.grab().save(str(out/(tag+'-'+name+'.png')))
        capture('not-installed')
        def cancellable(self,config,cancel,progress):
            progress(320000000,760000000,'Đang tải mô hình giọng đọc')
            if cancel.wait(10):raise InterruptedError('mock cancellation')
            raise RuntimeError('mock timeout')
        SetupFlow.run=cancellable;QTest.mouseClick(page.setup_button,Qt.LeftButton);wait(lambda:'320.0 MB' in page.asset_status.text());assert not page.runtime_ready;capture('progress')
        page.settings_dialog.resize(700,620);app.processEvents();assert page.settings_dialog.width()==700
        cancel=next(b for b in page.settings_dialog.findChildren(QPushButton) if b.text()=='Hủy tải');QTest.mouseClick(cancel,Qt.LeftButton);wait(lambda:not page.is_busy());capture('cancelled')
        def failed(*a,**k):raise RuntimeError('mock source server unavailable')
        SetupFlow.run=failed;page.install_models();wait(lambda:not page.is_busy());assert page.setup_button.text()=='Thử lại';page.error_dialog.hide();capture('retry')
        def ready(self,config,cancel,progress):return dict(backend='CPUExecutionProvider',probe_seconds=1,codecs={'wav':True,'mp3':True},fallback_reason='GPU chưa sử dụng được; Kokoro vẫn hoạt động bằng CPU.')
        SetupFlow.run=ready;QTest.mouseClick(page.setup_button,Qt.LeftButton);wait(lambda:page.runtime_ready and not page.is_busy());capture('ready-fallback');assert 'Thiết bị: CPU' in page.asset_status.text()
        dpr=window.devicePixelRatioF();assert abs(dpr-float(args.scale))<.02;report=dict(mock_flow=True,dark=args.dark,dpr=dpr,states=['not-installed','progress','cancelled','retry','ready-fallback'],responsive_resize=True,status_text_not_clipped=True)
        (out/(tag+'.json')).write_text(json.dumps(report,indent=2),encoding='utf8');page.request_stop();wait(lambda:not page.is_busy());window.close();wait(lambda:window._closed)
    return 0

if __name__=='__main__':raise SystemExit(main())
