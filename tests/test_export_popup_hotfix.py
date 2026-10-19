"""Exercise the actual export chooser's painted rows and click coordinates."""
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QApplication,QWidget,QComboBox,QDialog
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor
from transcomic.ui.exporting import ExportInputDialog,MODES
from transcomic.ui.controls import GlassComboDelegate,install_combo_popup
from transcomic.ui.theme import stylesheet,colors


@pytest.mark.parametrize('dark',[False,True])
@pytest.mark.parametrize('selected',[0,1,2])
def test_export_modal_popup_paints_and_clicks_each_actual_mode(monkeypatch,dark,selected):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');app=QApplication.instance() or QApplication([])
    owner=QWidget();owner.dark=dark;owner.setStyleSheet(stylesheet(dark));owner.resize(700,400);owner.show()
    faults=[]
    def choose():
        dialog=app.activeModalWidget()
        try:
            assert isinstance(dialog,ExportInputDialog)
            combo=dialog.findChild(QComboBox);combo.showPopup();app.processEvents()
            view=combo.view();assert isinstance(combo.itemDelegate(),GlassComboDelegate)
            assert [combo.itemText(i) for i in range(combo.count())]==[label for label,_ in MODES]
            assert view.window().isVisible()
            shot=view.viewport().grab().toImage()
            ink=QColor(colors(combo)['ink'])
            for i in range(combo.count()):
                rect=view.visualRect(combo.model().index(i,0))
                assert rect.height()>20 and view.viewport().rect().contains(rect.center())
                # Confirm text pixels are actually painted, not just stored in roles.
                crop=rect.adjusted(28,1,-10,-1).intersected(shot.rect())
                dark_ink=colors(combo)['ink'].startswith('#3')
                pixels=sum(1 for x in range(crop.left(),crop.right()) for y in range(crop.top(),crop.bottom())
                           if abs(shot.pixelColor(x,y).red()-ink.red())<12 and abs(shot.pixelColor(x,y).green()-ink.green())<12)
                if i!=combo.currentIndex():assert pixels>12,(dark,i,pixels)
            index=combo.model().index(selected,0)
            QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(index).center())
            assert combo.currentIndex()==selected
            dialog.accept()
        except BaseException as exc:
            faults.append(exc)
            if dialog:dialog.reject()
    QTimer.singleShot(100,choose)
    try:
        value,ok=ExportInputDialog.getItem(owner,'Phương thức xuất','Chọn vị trí xuất:',[s for s,_ in MODES],1,False)
        if faults:raise faults[0]
        assert ok and value==MODES[selected][0]
        # Shared installer must also cover a default Qt combo, theme changes and disabled rows.
        combo=QComboBox(owner);combo.addItems(['One','Two']);install_combo_popup(combo)
        combo.model().item(1).setEnabled(False);owner.dark=not dark;owner.setStyleSheet(stylesheet(not dark));install_combo_popup(combo)
        assert isinstance(combo.itemDelegate(),GlassComboDelegate)
    finally:owner.close();owner.deleteLater();app.processEvents()


def test_export_dialog_escape_has_no_selection_side_effect(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');app=QApplication.instance() or QApplication([])
    def escape():
        dialog=app.activeModalWidget();QTest.keyClick(dialog,Qt.Key_Escape)
    QTimer.singleShot(50,escape)
    assert ExportInputDialog.getItem(None,'Export','Mode',['A','B'],1,False)==('B',False)
