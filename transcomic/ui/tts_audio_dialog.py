"""Nonmodal virtual segment browser. Playback stays in the shared page player."""
import json
import threading
from pathlib import Path
from PySide6.QtCore import Qt,QSortFilterProxyModel,Signal,QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QLineEdit,QTableView,QHeaderView,QDialogButtonBox,QPlainTextEdit
from .tts_models import SegmentModel,ActionDelegate,TtsTable


class SentenceFilter(QSortFilterProxyModel):
    query=''
    def setFilterFixedString(self,text):self.beginFilterChange();self.query=text.casefold();self.endFilterChange()
    def filterAcceptsRow(self,row,parent):
        text=self.query;item=self.sourceModel().items[row]
        return not text or text in item['text'].casefold() or text in f'{item["position"]:04}'


class AudioDialog(QDialog):
    presence_ready=Signal(int,object)
    def __init__(self,page):
        super().__init__(page);self.page=page;self.document=None;self.generation=0;self.checking=False
        self.setWindowTitle('Chi tiết audio');self.resize(900,590);self.setMinimumSize(520,350)
        layout=QVBoxLayout(self);self.meta=QLabel();self.meta.setWordWrap(True);layout.addWidget(self.meta)
        self.search=QLineEdit();self.search.setPlaceholderText('Tìm câu hoặc nội dung...');layout.addWidget(self.search)
        self.model=SegmentModel(page.store,self);self.model.editable=False;self.model.columns=('STT','Nội dung văn bản','Dòng nguồn','Trạng thái','Audio','Giây','Nghe','Tạo lại')
        self.proxy=SentenceFilter(self);self.proxy.setSourceModel(self.model);self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table=TtsTable();self.table.setModel(self.proxy);self.table.verticalHeader().hide();self.table.setWordWrap(False);self.table.setAlternatingRowColors(True)
        for column in (2,4,5,7):self.table.hideColumn(column)
        self.table.setColumnWidth(0,64);self.table.setColumnWidth(3,112);self.table.setColumnWidth(6,86);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSelectionBehavior(QTableView.SelectRows);layout.addWidget(self.table,1)
        self.preview=QPlainTextEdit();self.preview.setReadOnly(True);self.preview.setMaximumHeight(90);self.preview.setPlaceholderText('Chọn một câu để xem toàn bộ nội dung');layout.addWidget(self.preview)
        self.table.selectionModel().currentChanged.connect(lambda index,_:self.preview.setPlainText(self.proxy.index(index.row(),1).data() or ''))
        delegate=ActionDelegate(self.table);delegate.activated.connect(lambda id,_:self.page.guard(lambda:self.page.play_segment(id)));self.table.setItemDelegateForColumn(6,delegate)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.button(QDialogButtonBox.Close).setText('Đóng');buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.presence_ready.connect(self.on_presence);self.poll=QTimer(self);self.poll.setInterval(1500);self.poll.timeout.connect(self.check_presence)
    def open_document(self,document):
        if self.document!=document:self.generation+=1;self.search.clear();self.preview.clear()
        self.document=document;self.refresh();screen=self.screen().availableGeometry();self.resize(min(900,screen.width()-40),min(590,screen.height()-60));self.show();self.raise_();self.poll.start();self.check_presence(all_rows=True)
    def refresh(self,changed=None):
        if not self.document:return
        doc=self.page.store.doc(self.document)
        if not doc:self.hide();self.document=None;return
        if changed is None:self.model.load(doc['run_id'],self.document)
        else:
            for id in changed:self.model.update_item(id)
        self.model.playing=self.page.playing;run=self.page.store.run(doc['run_id']);config=json.loads(run['config']);success=sum(i['state']=='success' for i in self.model.items)
        self.setWindowTitle('Chi tiết audio — '+doc['name']);self.meta.setText(f'{doc["name"]} · {config.get("voice","Chưa chọn giọng")} · {config.get("speed",1)}x · {success}/{self.model.rowCount()} audio')
    def check_presence(self,all_rows=False):
        if not self.isVisible() or self.checking or not self.document:return
        doc=self.page.store.doc(self.document)
        if not doc or not doc['folder']:return
        indexes=range(self.proxy.rowCount()) if all_rows else range(max(0,self.table.rowAt(0)),min(self.proxy.rowCount(),max(0,self.table.rowAt(self.table.viewport().height()-1))+2) if self.table.rowAt(self.table.viewport().height()-1)>=0 else min(self.proxy.rowCount(),30))
        values=[]
        for row in indexes:
            index=self.proxy.mapToSource(self.proxy.index(row,0));item=self.model.items[index.row()]
            if item['state']=='success' and item['filename']:values.append((item['id'],str(Path(doc['folder'])/item['filename'])))
        self.checking=True;generation=self.generation
        def check():
            result={}
            for id,path in values:
                try:result[id]=not Path(path).is_file()
                except OSError:result[id]=True
            try:self.presence_ready.emit(generation,result)
            except RuntimeError:pass  # Parent may have closed while checking disk paths.
        threading.Thread(target=check,daemon=True,name='tts-audio-presence').start()
    def on_presence(self,generation,values):
        self.checking=False
        if generation!=self.generation:return
        for id,missing in values.items():
            n=self.model.positions.get(id)
            if n is not None:self.model.items[n]['missing']=missing;self.model.dataChanged.emit(self.model.index(n,0),self.model.index(n,7))
    def hideEvent(self,event):self.poll.stop();super().hideEvent(event)
