"""Virtual tables and painted actions, without per-row widgets/audio buffers."""
import json
from pathlib import Path
from PySide6.QtCore import Qt,Signal,QAbstractTableModel,QEvent,QRect
from PySide6.QtGui import QColor,QPen,QKeySequence
from PySide6.QtWidgets import QStyledItemDelegate,QStyleOptionButton,QStyleOptionViewItem,QStyle,QHeaderView,QTableView,QAbstractItemView


class TtsTable(QTableView):
    """Native keyboard/editor behavior, with a quiet keyboard-only focus cue."""
    keyboard_focus=False
    def __init__(self,parent=None):
        super().__init__(parent);self.setItemDelegate(TtsDelegate(self));self.setStyleSheet('QTableView { outline: 0; }')
    def focusInEvent(self,event):
        if event.reason() in (Qt.TabFocusReason,Qt.BacktabFocusReason):self.keyboard_focus=True
        super().focusInEvent(event);self.viewport().update()
    def mousePressEvent(self,event):
        self.keyboard_focus=False;super().mousePressEvent(event);self.viewport().update()
    def keyPressEvent(self,event):
        self.keyboard_focus=True
        # An open QLineEdit receives its own native undo. Only intercept once
        # the delegate has committed/destroyed that editor.
        if event.matches(QKeySequence.Undo) and self.state()!=QAbstractItemView.EditingState and hasattr(self.model(),'undo_last_edit'):
            self.model().undo_last_edit();event.accept();return
        super().keyPressEvent(event);self.viewport().update()


class TtsDelegate(QStyledItemDelegate):
    def paint(self,painter,option,index):
        clean=QStyleOptionViewItem(option);clean.state &= ~QStyle.State_HasFocus
        super().paint(painter,clean,index)
        self.paint_focus(painter,option)
    def paint_focus(self,painter,option):
        if option.state & QStyle.State_HasFocus and getattr(self.parent(),'keyboard_focus',False):
            painter.save();painter.setPen(QPen(QColor('#b77d50'),1,Qt.DotLine));painter.drawRect(option.rect.adjusted(2,2,-3,-3));painter.restore()


class CenterCheckDelegate(TtsDelegate):
    @staticmethod
    def check_rect(option):
        size=option.widget.style().pixelMetric(QStyle.PM_IndicatorWidth,None,option.widget)
        height=option.widget.style().pixelMetric(QStyle.PM_IndicatorHeight,None,option.widget)
        return QRect(option.rect.x()+(option.rect.width()-size)//2,option.rect.y()+(option.rect.height()-height)//2,size,height)
    def paint(self,painter,option,index):
        clean=QStyleOptionViewItem(option);self.initStyleOption(clean,index);clean.features &= ~QStyleOptionViewItem.HasCheckIndicator;clean.state &= ~QStyle.State_HasFocus
        option.widget.style().drawControl(QStyle.CE_ItemViewItem,clean,painter,option.widget)
        check=QStyleOptionButton();check.rect=self.check_rect(option);check.state=QStyle.State_Enabled | (QStyle.State_On if index.data(Qt.CheckStateRole)==Qt.Checked else QStyle.State_Off)
        option.widget.style().drawControl(QStyle.CE_CheckBox,check,painter,option.widget)
        self.paint_focus(painter,option)
    def editorEvent(self,event,model,option,index):
        click=event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton and option.rect.contains(event.position().toPoint())
        key=event.type()==QEvent.KeyPress and event.key()==Qt.Key_Space
        if click or key:return model.setData(index,Qt.Unchecked if index.data(Qt.CheckStateRole)==Qt.Checked else Qt.Checked,Qt.CheckStateRole)
        return False

STATES={'draft':'Nháp','ready':'Chờ xử lý','pending':'Chưa tạo','running':'Đang tạo','success':'Hoàn tất','error':'Lỗi','unknown':'Cần kiểm tra','paused':'Tạm dừng','pausing':'Đang tạm dừng','stopping':'Đang dừng','stopped':'Đã dừng','partial':'Còn lỗi','completed':'Hoàn tất','interrupted':'Gián đoạn','failed':'Lỗi'}


STATES.update(cancelled='Đã hủy',stopped='Đã dừng (cũ)')


class RowsModel(QAbstractTableModel):
    changed=Signal()
    def __init__(self,columns,parent=None):super().__init__(parent);self.columns=columns;self.items=[];self.positions={}
    def rowCount(self,parent=None):return 0 if parent and parent.isValid() else len(self.items)
    def columnCount(self,parent=None):return len(self.columns)
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if role==Qt.DisplayRole:return self.columns[section] if orientation==Qt.Horizontal else section+1
    def replace(self,items):
        old_ids=[i['id'] for i in self.items];new_ids=[i['id'] for i in items];old_set=set(old_ids)
        if old_ids==new_ids:
            self.items=items
            if items:self.dataChanged.emit(self.index(0,0),self.index(len(items)-1,len(self.columns)-1))
        elif old_ids and old_ids==[id for id in new_ids if id in old_set]:
            # New completed audio may arrive out of order in Hybrid. Insert
            # ranges without resetting selection, scroll or persistent indexes.
            position=0
            while position<len(items):
                if position<len(self.items) and self.items[position]['id']==items[position]['id']:position+=1;continue
                end=position+1
                while end<len(items) and items[end]['id'] not in old_set:end+=1
                self.beginInsertRows(self.index(-1,-1),position,end-1);self.items[position:position]=items[position:end];self.endInsertRows();position=end
            self.items=items;self.positions={i['id']:n for n,i in enumerate(items)}
            self.dataChanged.emit(self.index(0,0),self.index(len(items)-1,len(self.columns)-1))
        else:
            self.beginResetModel();self.items=items;self.positions={i['id']:n for n,i in enumerate(items)};self.endResetModel()
    def flags(self,index):return Qt.ItemIsEnabled|Qt.ItemIsSelectable


class DocumentModel(RowsModel):
    def __init__(self,store,parent=None):super().__init__(('','Tài liệu','Loại','Dòng nguồn','Đoạn TTS','Audio','Trạng thái','Tiến độ','Chi tiết'),parent);self.store=store;self.checked=set();self.omitted=set()
    def load(self,run):
        stats={s['id']:s for s in self.store.document_stats(run)};state=self.store.run(run)['state'];items=[]
        for doc in self.store.docs(run):
            item=dict(doc,**{k:v for k,v in stats[doc['id']].items() if k not in ('id','name','started','ended')});item['state']=state;items.append(item)
        record=self.store.one('SELECT value FROM preferences WHERE name=?',('import_errors:'+run,))
        for issue in json.loads(record['value']) if record else []:
            items.append(dict(issue,id='import:'+issue['path'],name=Path(issue['path']).name,state='error',line_count=0,total=0,success=0,busy=0,errors=1,import_error=True))
        self.replace([i for i in items if i['id'] not in self.omitted]);self.checked.intersection_update(self.positions)
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid():return
        item=self.items[index.row()]
        if role==Qt.UserRole:return item['id']
        if role==Qt.CheckStateRole and index.column()==0:return Qt.Checked if item['id'] in self.checked else Qt.Unchecked
        if role==Qt.ToolTipRole:return item.get('error') or item['path'] or 'Văn bản nhập trực tiếp'
        if role==Qt.DisplayRole:
            if item.get('import_error'):return ('',item['name'],Path(item['path']).suffix[1:].upper(),'—','—','—','Lỗi đọc file','—','Đọc lại')[index.column()]
            total=item['total'];success=item['success'] or 0
            state='success' if total and success==total else 'running' if item['busy'] else 'error' if item['errors'] else item['state']
            return ('',item['name'],Path(item['path']).suffix[1:].upper() if item['path'] else 'Văn bản',item['line_count'],total,f'{success}/{total}',STATES.get(state,state),f'{round(100*success/max(1,total))}%','Chi tiết')[index.column()]
    def flags(self,index):return super().flags(index)|(Qt.ItemIsUserCheckable if index.column()==0 else Qt.NoItemFlags)
    def setData(self,index,value,role=Qt.CheckStateRole):
        if not index.isValid() or role!=Qt.CheckStateRole or index.column()!=0:return False
        id=self.items[index.row()]['id']
        if value in (Qt.Checked,Qt.Checked.value):self.checked.add(id)
        else:self.checked.discard(id)
        self.dataChanged.emit(index,index,[role]);self.headerDataChanged.emit(Qt.Horizontal,0,0);return True


class CheckHeader(QHeaderView):
    def __init__(self,model,parent=None):super().__init__(Qt.Horizontal,parent);self.records=model;self.setSectionsClickable(True)
    def paintSection(self,painter,rect,index):
        super().paintSection(painter,rect,index)
        if index==0:
            from PySide6.QtWidgets import QStyleOptionButton
            from PySide6.QtCore import QRect
            option=QStyleOptionButton();option.rect=QRect(rect.center().x()-8,rect.center().y()-8,16,16);option.state=QStyle.State_Enabled
            option.state|=QStyle.State_On if self.records.items and len(self.records.checked)==len(self.records.items) else QStyle.State_NoChange if self.records.checked else QStyle.State_Off
            self.style().drawControl(QStyle.CE_CheckBox,option,painter,self)
    def mouseReleaseEvent(self,event):
        if self.logicalIndexAt(event.position().toPoint())==0:
            self.records.checked=set() if len(self.records.checked)==len(self.records.items) else {i['id'] for i in self.records.items}
            if self.records.items:self.records.dataChanged.emit(self.records.index(0,0),self.records.index(len(self.records.items)-1,0),[Qt.CheckStateRole])
            self.viewport().update();return
        super().mouseReleaseEvent(event)


class SegmentModel(RowsModel):
    def __init__(self,store,parent=None):
        super().__init__(('Đoạn','Văn bản đoạn','Dòng nguồn','Trạng thái','Audio','Giây','Nghe','Tạo lại'),parent)
        self.store=store;self.editable=True;self.default_format='wav';self.document=None;self.playing=None;self.last_edit=None
    def load(self,run,document=None):
        self.document=document
        self.replace(self.store.rows('SELECT * FROM segments WHERE document_id=? ORDER BY position',(document,)) if document else self.store.items(run))
    def update_item(self,id):
        n=self.positions.get(id)
        if n is not None:
            item=self.store.segment(id)
            if item:self.items[n].update(item);self.dataChanged.emit(self.index(n,0),self.index(n,7))
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid():return
        item=self.items[index.row()]
        if role==Qt.UserRole:return item['id']
        if role==Qt.ToolTipRole:return item['error'] or ('Audio chưa hoàn tất' if index.column()==6 and item['state']!='success' else item['text'])
        if role in (Qt.DisplayRole,Qt.EditRole):
            return (f'{item["position"]:04}',item['text'],f'{item["line_start"]}–{item["line_end"]}','Thiếu file' if item.get('missing') else STATES.get(item['state'],item['state']),item['filename'] or f'{item["position"]:04}.{self.default_format}',round(item['duration'],2) if item['duration'] else '',('Dừng' if self.playing==item['id'] else 'Phát') if item['state']=='success' and not item.get('missing') else '','Tạo lại' if item['state'] in ('error','unknown','pending') and item['filename'] else '')[index.column()]
    def flags(self,index):
        flags=super().flags(index)
        if self.editable and index.column()==1:flags|=Qt.ItemIsEditable
        return flags
    def setData(self,index,value,role=Qt.EditRole):
        if not index.isValid() or not self.editable or index.column()!=1 or role!=Qt.EditRole:return False
        item=self.store.segment(self.items[index.row()]['id'])
        if not item:return False
        if item['text']==str(value):return True
        doc=self.store.doc(item['document_id']);run=self.store.run(doc['run_id'])
        if run['state'] in ('running','pausing','stopping','cancelled'):return False
        try:self.store.edit(item['id'],str(value))
        except ValueError:return False
        self.last_edit=(item['id'],item['document_id'],run['id'],item['text'],str(value),item['revision']+1)
        self.update_item(item['id']);self.changed.emit();return True
    def undo_last_edit(self):
        if not self.editable or not self.last_edit:return False
        id,document,run,old,new,revision=self.last_edit;item=self.store.segment(id);record=self.store.run(run)
        if id not in self.positions or not item or item['document_id']!=document or item['revision']!=revision or item['text']!=new or not record or record['state'] in ('running','pausing','stopping','cancelled'):return False
        self.store.edit(id,old);self.last_edit=None;self.update_item(id);self.changed.emit();return True


class AudioModel(RowsModel):
    def __init__(self,parent=None):super().__init__(('Audio','Giây','Nghe'),parent);self.playing=None
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid():return
        item=self.items[index.row()]
        if role==Qt.UserRole:return item['id']
        if role==Qt.ToolTipRole:return item['text']
        if role==Qt.DisplayRole:return (item['filename'],round(item['duration'] or 0,2),'Dừng' if self.playing==item['id'] else 'Phát')[index.column()]


class ActionDelegate(TtsDelegate):
    activated=Signal(str,int)
    def paint(self,painter,option,index):
        text=index.data(Qt.DisplayRole)
        if not text:return
        button=QStyleOptionButton();button.rect=option.rect.adjusted(4,4,-4,-4);button.text=str(text);button.state=QStyle.State_Enabled
        if option.state & QStyle.State_MouseOver:button.state|=QStyle.State_MouseOver
        option.widget.style().drawControl(QStyle.CE_PushButton,button,painter,option.widget)
        self.paint_focus(painter,option)
    def editorEvent(self,event,model,option,index):
        if event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton and option.rect.adjusted(4,4,-4,-4).contains(event.position().toPoint()) and index.data():
            self.activated.emit(index.data(Qt.UserRole),index.column());return True
        if event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Return,Qt.Key_Space) and index.data():
            self.activated.emit(index.data(Qt.UserRole),index.column());return True
        return False
