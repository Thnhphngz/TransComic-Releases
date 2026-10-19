"""Manual batch folder pairing. Cancel never writes persisted workspace."""
from pathlib import Path
import os
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QLineEdit,QScrollArea,QWidget,QFrame,QFileDialog,QDialogButtonBox,QMessageBox,QLayout)
from .controls import QComboBox
from .glass import GlassButton
from ..capcut.media import MediaGroup
from .theme import colors


class FolderDropEdit(QLineEdit):
    """Accept exactly one Explorer folder without inspecting its contents."""
    @staticmethod
    def folder(mime):
        if not mime.hasUrls() or len(mime.urls())!=1:return None
        url=mime.urls()[0]
        if not url.isLocalFile():return None
        try:
            path=Path(url.toLocalFile()).resolve()
            return str(path) if path.is_dir() else None
        except (OSError,ValueError):return None
    def highlight(self,on):
        self.setProperty('folderDrop',on)
        self.setStyleSheet(f'QLineEdit[folderDrop="true"] {{ border:1px solid {colors(self)["accent"]}; }}')
    def dragEnterEvent(self,event):
        accepted=self.folder(event.mimeData()) is not None
        self.highlight(accepted)
        if accepted:event.acceptProposedAction()
        else:event.ignore()
    def dragMoveEvent(self,event):self.dragEnterEvent(event)
    def dragLeaveEvent(self,event):self.highlight(False);event.accept()
    def dropEvent(self,event):
        folder=self.folder(event.mimeData());self.highlight(False)
        if folder is None:event.ignore();return
        self.setText(folder);event.acceptProposedAction()


class PairEntry(QFrame):
    def __init__(self,dialog,group=None):
        super().__init__(dialog);self.dialog=dialog;self.group=group;self.setObjectName('card')
        form=QFormLayout(self);form.setContentsMargins(10,8,10,8)
        self.heading=QLabel();form.addRow(self.heading)
        self.name=QLineEdit(group.name if group else '');form.addRow('Tên nhóm',self.name)
        self.image=FolderDropEdit(group.image_dir if group else '');self.audio=FolderDropEdit(group.audio_dir if group else '')
        self.image.setToolTip('Kéo đúng một thư mục ảnh vào đây hoặc bấm Chọn…')
        self.audio.setToolTip('Kéo đúng một thư mục audio vào đây hoặc bấm Chọn…')
        for label,field in [('Thư mục ảnh',self.image),('Thư mục audio',self.audio)]:
            row=QHBoxLayout();row.addWidget(field,1);button=GlassButton('Chọn…');row.addWidget(button)
            button.clicked.connect(lambda _=False,f=field:self.browse(f));form.addRow(label,row)
        self.sort=QComboBox();self.sort.addItem('Theo tên file','name');self.sort.addItem('Theo ngày tạo file','created')
        self.sort.setCurrentIndex(1 if group and group.image_sort=='created' else 0)
        row=QHBoxLayout();row.addWidget(self.sort,1);self.remove=GlassButton('Xóa cặp');self.remove.clicked.connect(lambda:dialog.remove_entry(self));row.addWidget(self.remove)
        form.addRow('Sắp xếp ảnh',row)
        self.image.textChanged.connect(self.image_changed)
        for field in (self.image,self.audio,self.name):field.textChanged.connect(dialog.schedule_spare)

    def image_changed(self,text):
        if text.strip() and not self.name.text().strip():self.name.setText(Path(text.strip()).name)

    def blank(self):return not any(field.text().strip() for field in (self.image,self.audio,self.name))

    def complete(self):
        try:return all(field.text().strip() and Path(field.text().strip()).is_dir() for field in (self.image,self.audio))
        except (OSError,ValueError):return False

    def browse(self,field):
        start=field.text().strip() or self.image.text().strip()
        folder=QFileDialog.getExistingDirectory(self,'Chọn thư mục ảnh' if field is self.image else 'Chọn thư mục audio',start)
        if folder:
            field.setText(folder)
            if field is self.image and not self.name.text().strip():self.name.setText(Path(folder).name)

    def value(self):
        if not self.image.text().strip() or not self.audio.text().strip():raise ValueError('Chọn đủ thư mục ảnh và audio')
        g=MediaGroup.create(self.name.text(),self.image.text().strip(),self.audio.text().strip(),self.sort.currentData())
        if self.group:
            from dataclasses import replace
            g=replace(g,id=self.group.id)
        return g


class MultiGroupDialog(QDialog):
    def __init__(self,parent,existing=(),group=None):
        super().__init__(parent);self.existing=tuple(existing);self.entries=[];self.result_groups=();self.editing=group is not None;self.spare_scheduled=False
        self.pending_scroll=None;self.scroll_timer=QTimer(self);self.scroll_timer.setSingleShot(True);self.scroll_timer.setInterval(20)
        self.scroll_timer.timeout.connect(lambda:self.scroll_to_spare(self.pending_scroll))
        self.setWindowTitle('Sửa cặp thư mục' if group else 'Thêm các cặp thư mục ảnh và audio')
        screen=self.screen().availableGeometry();self.resize(min(760,screen.width()-40),min(640,screen.height()-60));self.setMinimumSize(460,300)
        layout=QVBoxLayout(self)
        note=QLabel('Chọn thủ công từng cặp. Ảnh/audio chỉ lấy trực tiếp trong thư mục đã chọn; không tự tìm thư mục voice.');note.setWordWrap(True);layout.addWidget(note)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body=QWidget();self.rows=QVBoxLayout(body);self.rows.setSizeConstraint(QLayout.SetMinAndMaxSize);self.rows.setContentsMargins(0,0,0,0);self.rows.addStretch();self.scroll.setWidget(body);layout.addWidget(self.scroll,1)
        self.add_button=GlassButton('+ Thêm cặp thư mục');self.add_button.clicked.connect(lambda:self.add_entry());self.add_button.setVisible(group is None);layout.addWidget(self.add_button)
        self.error=QLabel();self.error.setWordWrap(True);layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Xác nhận tất cả' if group is None else 'Lưu thay đổi')
        buttons.button(QDialogButtonBox.Cancel).setText('Hủy')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.add_entry(group)

    def add_entry(self,group=None):
        if group is None and self.entries and self.entries[-1].blank():return self.entries[-1]
        entry=PairEntry(self,group);self.entries.append(entry);self.rows.insertWidget(self.rows.count()-1,entry);entry.show();self.renumber();return entry
    def remove_entry(self,entry):
        self.entries.remove(entry);self.rows.removeWidget(entry);entry.deleteLater();self.renumber()
        self.schedule_spare()
    def schedule_spare(self,*args):
        if self.editing or self.spare_scheduled:return
        self.spare_scheduled=True;QTimer.singleShot(0,self,self.ensure_spare)
    def ensure_spare(self):
        self.spare_scheduled=False
        if self.editing:return
        # Empty rows in the middle carry no input. Partial/name-only rows stay
        # visible and must pass validation; only the trailing spare is ignored.
        for entry in list(self.entries[:-1]):
            if entry.blank():
                self.entries.remove(entry);self.rows.removeWidget(entry);entry.deleteLater()
        added=None
        if not self.entries or self.entries[-1].complete():added=self.add_entry()
        self.renumber()
        if added:self.pending_scroll=added;self.scroll_timer.start()
    def scroll_to_spare(self,entry):
        if entry in self.entries:
            # The queued callback can precede QScrollArea's resize/layout event.
            # Realize the new row geometry before asking Qt to reveal it.
            self.rows.activate();self.scroll.widget().adjustSize()
            bar=self.scroll.verticalScrollBar();bar.setValue(bar.maximum())
    def renumber(self):
        for i,entry in enumerate(self.entries):entry.heading.setText(f'Cặp {i+1:02}')
    def values(self):
        if not self.editing:self.ensure_spare()
        entries=self.entries[:-1] if not self.editing and self.entries and self.entries[-1].blank() else self.entries
        if not entries:raise ValueError('Thêm ít nhất một cặp; không tạo nhóm rỗng')
        values=[]
        for i,entry in enumerate(entries):
            try:values.append(entry.value())
            except ValueError as exc:raise ValueError(f'Cặp {i+1}: {exc}') from exc
        return tuple(values)
    def accept(self):
        try:values=self.values()
        except ValueError as exc:self.error.setText(str(exc));return
        def pair_key(g):return tuple(os.path.normcase(os.path.abspath(p)) for p in (g.image_dir,g.audio_dir))
        seen={pair_key(g) for g in self.existing if all(g.id!=v.id for v in values)};duplicates=[]
        for i,g in enumerate(values):
            key=pair_key(g)
            if key in seen:duplicates.append(str(i+1))
            seen.add(key)
        if duplicates and QMessageBox.question(self,'Cặp thư mục trùng','Cặp '+', '.join(duplicates)+' trùng đường dẫn đã chọn. Vẫn thêm?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        self.result_groups=values;super().accept()
