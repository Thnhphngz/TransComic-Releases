import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from tempfile import TemporaryDirectory
from pathlib import Path
from PySide6.QtWidgets import QApplication
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.documents import decode_txt
app=QApplication([])
with TemporaryDirectory() as d:
    store=Store(Path(d)/'a.db'); doc,_=store.import_document(Path(d)/'a.txt',decode_txt(b'one\ntwo'))
    w=MainWindow(store);w.resize(1600,1000);w.show();w.open_document(doc);app.processEvents()
    print('window',w.size(),'table',w.table.geometry(),'viewport',w.table.viewport().height())
    for widget in [w.editor_page,w.source_lang,w.start_button,w.filter_combo,w.sidebar,w.pages,w.console]:
        print(type(widget).__name__,widget.geometry(),widget.sizeHint(),widget.minimumSizeHint())
    for i in range(w.editor_page.layout().count()):
        item=w.editor_page.layout().itemAt(i); print('item',i,item.geometry(),item.sizeHint(),item.minimumSize())
    w._exit_authorized=True;w.close()
