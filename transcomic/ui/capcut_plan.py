"""Small virtual preview of immutable, consecutive group partitions."""
from PySide6.QtCore import QAbstractTableModel,QModelIndex,Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLineEdit
from dataclasses import replace
from ..capcut.planning import name_errors
from .theme import colors
from .capcut_media import RowDelegate


class ProjectNameDelegate(RowDelegate):
    """A compact, opaque editor; ordinary form padding cannot fit a 23px row."""
    def createEditor(self,parent,option,index):
        editor=QLineEdit(parent);editor.setObjectName('capcutNameEditor')
        editor.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        editor.setTextMargins(0,0,0,0)
        return editor

    def updateEditorGeometry(self,editor,option,index):
        # Cover the entire cell, including its display text, without growing rows.
        editor.setGeometry(option.rect)


class SplitPlanModel(QAbstractTableModel):
    def __init__(self,parent=None):super().__init__(parent);self.page=parent;self.parts=();self.errors={}
    def load(self,parts):self.beginResetModel();self.parts=tuple(parts);self.errors=name_errors(self.parts);self.endResetModel()
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.parts)
    def columnCount(self,parent=QModelIndex()):return 3
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if role==Qt.DisplayRole and orientation==Qt.Horizontal:return ('Project','Các nhóm','Số nhóm')[section]
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.parts):return None
        part=self.parts[index.row()]
        if role in (Qt.DisplayRole,Qt.EditRole):return (part.name,f'{part.start}–{part.end}',str(len(part.groups)))[index.column()]
        if role==Qt.ForegroundRole and index.column()==0 and index.row()+1 in self.errors:return QColor('#FF9999' if colors(self.page)['background']=='#1D1815' else '#B42323')
        if role==Qt.ToolTipRole:return part.name+'\n'+self.errors.get(index.row()+1,'Nhấp đúp để đổi tên; chuột phải để dùng tên mặc định.')+'\n'+'\n'.join(f'{part.start+i:02}. {g.name}' for i,g in enumerate(part.groups))
        if role==Qt.UserRole:return tuple(g.id for g in part.groups)
    def flags(self,index):
        flags=super().flags(index)
        if index.isValid() and index.column()==0 and not self.page.busy:flags|=Qt.ItemIsEditable
        return flags
    def setData(self,index,value,role=Qt.EditRole):
        if role!=Qt.EditRole or not index.isValid() or index.model() is not self or not 0<=index.row()<len(self.parts) or index.column()!=0 or self.page.busy:return False
        text=str(value)
        if self.parts[index.row()].name==text:return True
        try:self.page.manager.set_part_name(index.row()+1,text)
        except Exception as exc:self.page.status.setText(str(exc));return False
        parts=list(self.parts);parts[index.row()]=replace(parts[index.row()],name=text);self.parts=tuple(parts);self.errors=name_errors(parts)
        self.dataChanged.emit(self.index(0,0),self.index(len(parts)-1,0))
        self.page.update_name_validation();return True
