"""Bounded asynchronous thumbnails and a virtual details table."""
from collections import OrderedDict
import queue
import threading
from PySide6.QtCore import QObject, Signal, QAbstractTableModel, QModelIndex, Qt, QSize, QSortFilterProxyModel
from PySide6.QtGui import QImageReader, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import QTableView, QStyledItemDelegate, QStyle
from .theme import colors


class RowDelegate(QStyledItemDelegate):
    def initStyleOption(self,option,index):
        super().initStyleOption(option,index)
        # Native style draws a bright focus frame around the current cell.
        # Selection stays intact; keyboard focus is painted once per row below.
        option.state &= ~QStyle.State_HasFocus


class CapcutTable(QTableView):
    def __init__(self,parent=None):
        super().__init__(parent);self.keyboard_focus=False;self.setItemDelegate(RowDelegate(self))
    def focusInEvent(self,event):
        self.keyboard_focus=event.reason() in (Qt.TabFocusReason,Qt.BacktabFocusReason,Qt.ShortcutFocusReason)
        super().focusInEvent(event);self.viewport().update()
    def mousePressEvent(self,event):
        self.keyboard_focus=False;super().mousePressEvent(event);self.viewport().update()
    def keyPressEvent(self,event):
        self.keyboard_focus=True;super().keyPressEvent(event);self.viewport().update()
    def paintEvent(self,event):
        super().paintEvent(event)
        if self.hasFocus() and self.keyboard_focus and self.currentIndex().isValid():
            rect=self.visualRect(self.currentIndex());rect.setLeft(1);rect.setRight(self.viewport().width()-2);rect.adjust(0,1,0,-1)
            painter=QPainter(self.viewport());painter.setPen(QPen(QColor(colors(self)['accent']),1));painter.setBrush(Qt.NoBrush);painter.drawRect(rect);painter.end()


class Thumbnails(QObject):
    loaded=Signal(object,object)
    def __init__(self,parent,size=QSize(76,54),limit=128):
        super().__init__(parent);self.size=size;self.limit=limit;self.cache=OrderedDict();self.pending=set()
        self.queue=queue.Queue(32);self.stop=threading.Event();self.discarded=set();self.loaded.connect(self.receive,Qt.QueuedConnection)
        self.thread=threading.Thread(target=self.work,daemon=True,name='capcut-thumbnails');self.thread.start()

    def get(self,file):
        key=(file.path,file.size,file.mtime_ns)
        if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
        if key not in self.pending and len(self.pending)<32 and not self.stop.is_set():
            try:self.queue.put_nowait(key);self.pending.add(key)
            except queue.Full:pass
        return None

    def work(self):
        while not self.stop.is_set():
            try:key=self.queue.get(timeout=.1)
            except queue.Empty:continue
            if self.stop.is_set():break
            reader=QImageReader(key[0]);reader.setAutoTransform(True);size=reader.size()
            if size.isValid():reader.setScaledSize(size.scaled(self.size,Qt.KeepAspectRatio))
            image=reader.read()
            try:self.loaded.emit(key,image)
            except RuntimeError:return

    def receive(self,key,image):
        self.pending.discard(key)
        if key in self.discarded:self.discarded.discard(key);return
        if self.stop.is_set():return
        self.cache[key]=QPixmap.fromImage(image)
        while len(self.cache)>self.limit:self.cache.popitem(last=False)

    def forget(self,paths):
        paths=set(paths)
        for key in list(self.cache):
            if key[0] in paths:self.cache.pop(key)
        self.discarded.update(key for key in self.pending if key[0] in paths)

    def shutdown(self):
        self.stop.set();self.cache.clear();self.pending.clear();self.discarded.clear()


class PairModel(QAbstractTableModel):
    headers=('STT · Nhóm','Ảnh','Tên ảnh','File audio','Ngày tạo ảnh','Thời lượng','Trạng thái')
    def __init__(self,parent=None,thumbs=None):
        super().__init__(parent);self.rows=[];self.thumbs=thumbs if thumbs is not None else Thumbnails(self)
        self.thumbnail_visible=lambda index:True
        self.thumbs.loaded.connect(self.repaint_thumbnails,Qt.QueuedConnection)
    def repaint_thumbnails(self,*_):
        if self.rows:self.dataChanged.emit(self.index(0,1),self.index(len(self.rows)-1,1),[Qt.DecorationRole])
    def load(self,scans):
        self.beginResetModel();self.rows=[]
        for order,scan in enumerate(scans):
            for pair in scan.rows:self.rows.append((order,scan.group.name,pair,len(self.rows)+1))
        self.endResetModel()
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 7
    def headerData(self,n,orientation,role=Qt.DisplayRole):
        if role==Qt.DisplayRole and orientation==Qt.Horizontal:return self.headers[n]
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        order,name,pair,global_order=self.rows[index.row()]
        if role==Qt.DecorationRole and index.column()==1 and pair.images and not pair.images[0].error and self.thumbnail_visible(index):return self.thumbs.get(pair.images[0])
        if role==Qt.UserRole:return pair.id
        if role==Qt.ToolTipRole:return name+'\n'+'\n'.join(f.path for f in pair.images+pair.audios)+'\n'+'; '.join(pair.errors)
        if role==Qt.DisplayRole:
            from pathlib import Path
            from datetime import datetime
            created=pair.images[0].created_ns if pair.images else None
            return (f'{global_order} · {name} · #{pair.number}', '',
                ', '.join(Path(f.path).name for f in pair.images) or '—',
                ', '.join(Path(f.path).name for f in pair.audios) or '—',
                datetime.fromtimestamp(created/1e9).astimezone().strftime('%d/%m/%Y %H:%M:%S') if created else 'Không xác định',
                display_duration(pair.duration_us) if pair.duration_us else '—',
                '; '.join(pair.errors) or 'Khớp theo vị trí')[index.column()]


def display_duration(microseconds):
    """Round the display only; the snapshot keeps integer microseconds."""
    minutes,remainder=divmod((microseconds+500)//1000,60000)
    seconds,milliseconds=divmod(remainder,1000)
    return f'{minutes:02}:{seconds:02}.{milliseconds:03}'


class PairFilter(QSortFilterProxyModel):
    group=None;errors_only=False;query=''
    def configure(self,group=None,errors_only=False,query=''):
        self.beginFilterChange();self.group=group;self.errors_only=errors_only;self.query=query.casefold();self.endFilterChange()
    def filterAcceptsRow(self,row,parent):
        _,name,pair,_=self.sourceModel().rows[row]
        if self.group and pair.group_id!=self.group:return False
        if self.errors_only and not pair.errors:return False
        from pathlib import Path
        return not self.query or self.query in (name+' '+str(pair.number)+' '+' '.join(Path(f.path).name for f in pair.images+pair.audios)).casefold()
