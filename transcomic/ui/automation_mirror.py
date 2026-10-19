"""Read-only CapCut projection of Automation's existing checkpoints."""
from pathlib import Path
import threading
from PySide6.QtCore import Qt,Signal,QTimer,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QDialog,QHeaderView
from .controls import QComboBox
from .glass import GlassButton
from .automation_page import STATES


class AutomationMirror(QWidget):
    loaded=Signal(object,object)
    def __init__(self,page):
        super().__init__(page);self.page=page;self.owner=page.owner;self.repo=self.owner.automation_repo;self.services=self.owner.automation_services
        self.loaded.connect(self.show_preview,Qt.QueuedConnection)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(QLabel('Automation · cùng checkpoint'));self.worksets=QComboBox();row.addWidget(self.worksets,1);self.worksets.currentIndexChanged.connect(self.refresh_rows)
        preview=GlassButton('Xem ảnh / voice');preview.clicked.connect(self.preview_selected);row.addWidget(preview)
        open_button=GlassButton('Mở project');open_button.clicked.connect(self.open_project);row.addWidget(open_button)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Nhóm','Trạng thái','Voice','Project']);self.table.verticalHeader().hide();self.table.setMaximumHeight(135)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.table.setEditTriggers(QTableWidget.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectRows);layout.addWidget(self.table)
        self.refresh()
    def refresh(self):
        works=self.repo.workset_summaries();self.setVisible(bool(works))
        wanted=self.worksets.currentData() or self.repo.active()
        if [self.worksets.itemData(i) for i in range(self.worksets.count())]!=[w['id'] for w in works]:
            self.worksets.blockSignals(True);self.worksets.clear()
            for w in works:self.worksets.addItem(w['name'],w['id'])
            self.worksets.setCurrentIndex(max(0,self.worksets.findData(wanted)));self.worksets.blockSignals(False)
        self.refresh_rows()
    def refresh_rows(self,*args):
        id=self.worksets.currentData();groups=self.repo.group_summaries(id) if id else [];self.table.setRowCount(len(groups))
        for i,g in enumerate(groups):
            meta=g['data'];values=[Path(g['path']).name,STATES.get(meta['state'],meta['state']),meta.get('audio_folder') or 'Đang chờ',meta.get('project') or 'Đang chờ']
            for j,text in enumerate(values):
                item=QTableWidgetItem(text);item.setData(Qt.UserRole,g['id']);item.setToolTip(text);self.table.setItem(i,j,item)
    def selected(self):
        row=self.table.currentRow();return self.table.item(row,0).data(Qt.UserRole) if row>=0 else None
    def open_project(self):
        id=self.selected()
        if id:
            path=self.repo.group(id)['data'].get('project')
            if path:QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    def preview_selected(self):
        id=self.selected()
        if not id:return
        def load():
            try:
                from ..capcut.media import MediaGroup,MediaPair,GroupScan,probe
                group=self.repo.group(id);meta=group['data'];tts=meta.get('tts_run');docs=self.services.tts_store.docs(tts) if tts else [];items=self.services.tts_store.items(tts) if tts else []
                folder=docs[0]['folder'] if docs else '';media=MediaGroup(id,Path(self.repo.store.document(group['document_id'])['path']).stem,meta['image_folder'],folder,meta['image_sort']);pairs=[]
                for i,image in enumerate(meta.get('images',[])):
                    audio=(probe(Path(folder)/items[i]['filename'],False),) if i<len(items) and items[i]['state']=='success' else ()
                    pairs.append(MediaPair(meta['slots'][i],id,i+1,(probe(image['path'],True),),audio,() if audio else ('Voice chưa hoàn tất',)))
                self.loaded.emit(GroupScan(media,tuple(pairs)),None)
            except Exception as exc:self.loaded.emit(None,str(exc))
        thread=threading.Thread(target=load,daemon=True,name='automation-preview');self.owner.background_threads.append(thread);thread.start()
    def show_preview(self,scan,error):
        if self.owner._closed:return
        if error:self.page.status.setText(error);return
        from .capcut_cards import GroupDetails
        dialog=QDialog(self);dialog.setWindowTitle('Automation · '+scan.group.name);dialog.resize(1000,650);layout=QVBoxLayout(dialog)
        details=GroupDetails(self.page,scan.group.id,dialog);details.load(scan);layout.addWidget(details)
        timer=QTimer(dialog);timer.setInterval(250);timer.timeout.connect(details.sync_audio);timer.start()
        dialog.finished.connect(lambda *_:self.page.stop_audio());dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.show();self.dialog=dialog
