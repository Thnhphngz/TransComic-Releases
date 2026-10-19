"""Read-only Windows UI smoke: no app profile, network, inference or export."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dpi',type=int,choices=(100,150),required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--baseline',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if sys.platform!='win32':raise SystemExit('Native Windows required')
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    factor=ctypes.c_int()
    monitor=ctypes.windll.user32.MonitorFromWindow(None,1)
    ctypes.windll.shcore.GetScaleFactorForMonitor(monitor,ctypes.byref(factor))
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_OPENGL']='software';os.environ['QT_QUICK_BACKEND']='software'
    os.environ['QT_SCALE_FACTOR']=str((args.dpi/100)/(factor.value/100))
    os.environ.pop('QT_SCREEN_SCALE_FACTORS',None)
    from PySide6.QtWidgets import QApplication,QWidget,QComboBox,QInputDialog
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtGui import QPainter,QPixmap,QColor
    from PySide6.QtTest import QTest
    from transcomic.ui.exporting import ExportInputDialog,MODES
    from transcomic.ui.theme import stylesheet,colors
    from transcomic.ui.controls import GlassComboDelegate
    app=QApplication([]);results=[]
    dialog_class=QInputDialog if args.baseline else ExportInputDialog
    for dark in (True,False):
        owner=QWidget();owner.dark=dark;owner.setStyleSheet(stylesheet(dark));owner.resize(660,260);owner.setWindowTitle('TransComic — export popup smoke');owner.show()
        for selection in range(3):
            faults=[];record=dict(dark=dark,selection=selection,platform=app.platformName())
            def inspect():
                dialog=app.activeModalWidget()
                try:
                    assert isinstance(dialog,QInputDialog)
                    combo=dialog.findChild(QComboBox);combo.showPopup();QTest.qWait(100)
                    view=combo.view();popup=view.window();record['dpr']=dialog.devicePixelRatioF()
                    assert abs(record['dpr']-args.dpi/100)<.02,record
                    record['delegate']=combo.itemDelegate().metaObject().className()
                    assert (args.baseline or isinstance(combo.itemDelegate(),GlassComboDelegate)) and popup.isVisible()
                    QTest.mouseMove(view.viewport(),view.visualRect(combo.model().index(selection,0)).center());QTest.qWait(30)
                    bounds=popup.screen().availableGeometry()
                    assert bounds.contains(popup.frameGeometry()),(bounds,popup.frameGeometry())
                    record['labels']=[combo.itemText(i) for i in range(combo.count())];record['rows']=[]
                    for i in range(combo.count()):
                        rect=view.visualRect(combo.model().index(i,0));assert view.viewport().rect().contains(rect.center())
                        record['rows'].append([rect.x(),rect.y(),rect.width(),rect.height()])
                    # Composite only this dialog and its popup, excluding the user's desktop.
                    bounds=dialog.frameGeometry().united(popup.frameGeometry());pix=QPixmap(bounds.size()*dialog.devicePixelRatioF());pix.setDevicePixelRatio(dialog.devicePixelRatioF());pix.fill(QColor(colors(owner)['background']))
                    painter=QPainter(pix)
                    for widget in (dialog,popup):painter.drawPixmap(widget.geometry().topLeft()-bounds.topLeft(),widget.grab())
                    painter.end()
                    name=f'{"baseline" if args.baseline else "export"}-{"dark" if dark else "light"}-{args.dpi}-row{selection+1}.png';assert pix.save(str(args.output/name));record['image']=name
                    QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(combo.model().index(selection,0)).center());assert combo.currentIndex()==selection
                    dialog.accept()
                except BaseException as exc:
                    faults.append(repr(exc))
                    if dialog:dialog.reject()
            QTimer.singleShot(150,inspect)
            value,ok=dialog_class.getItem(owner,'Phương thức xuất','Chọn vị trí xuất:',[s for s,_ in MODES],1,False)
            record.update(ok=ok and value==MODES[selection][0],faults=faults);results.append(record)
        owner.close();owner.deleteLater();app.processEvents()
    report=dict(dpi=args.dpi,monitor_scale=factor.value,results=results,passed=all(r['ok'] and not r['faults'] for r in results))
    (args.output/f'{"baseline" if args.baseline else "native"}-{args.dpi}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(dpi=args.dpi,passed=report['passed'],cases=len(results))))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
