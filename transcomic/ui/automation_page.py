"""Two-column Automation workspace; service calls run outside the GUI thread."""
import json
from pathlib import Path
import threading
import time
from PySide6.QtCore import Qt,Signal,QTimer,QAbstractTableModel,QModelIndex,QEvent,QUrl,QRect,QSize,QRectF,QPointF
from PySide6.QtGui import QColor,QDesktopServices,QPainter,QPen,QFont,QFontMetrics,QIcon
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFrame,QLabel,QLineEdit,QTableView,
    QAbstractItemView,QHeaderView,QScrollArea,QGraphicsOpacityEffect,QMessageBox,QFileDialog,QInputDialog,QMenu,QDialog,QDialogButtonBox,QPlainTextEdit,
    QTableWidget,QTableWidgetItem,QProgressBar,QSystemTrayIcon,QApplication,QSizePolicy,QStyledItemDelegate,QStyle)
from .controls import QComboBox,QSpinBox,QDoubleSpinBox
from .glass import GlassButton
from ..automation.validation import defaults,plan_parts,config_identity
from ..automation.repository import fingerprint
from .automation_widgets import AutomationCard,RoundedTableFrame,CompletionRing,ElidingPathEdit,STAGE_COLORS,status_color

STATES={'draft':'Chưa chạy','waiting':'Đợi dịch','translating':'Đang dịch','waiting_tts':'Đợi Kokoro','waiting_tts_rescue':'Đợi cứu lỗi voice','speaking':'Đang tạo voice',
        'waiting_capcut':'Đợi CapCut','exporting':'Đang xuất','completed':'Hoàn tất','needs_attention':'Cần xử lý','stale':'Cần cập nhật',
        'running':'Đang chạy','stopping':'Đang dừng an toàn','stopped':'Đã dừng','interrupted':'Bị gián đoạn'}


STATES['preparing']='Đang chuẩn bị…'


class AutomationButton(GlassButton):
    def minimumSizeHint(self):return QSize(28,self.sizeHint().height())


class NoticeLabel(QLabel):
    """Inline status: changing text/visibility cannot move folder-drop targets."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.setFixedHeight(30);self.setMinimumWidth(0)
        policy=QSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);policy.setRetainSizeWhenHidden(True);self.setSizePolicy(policy)
        self.setAlignment(Qt.AlignRight|Qt.AlignVCenter);self.setTextFormat(Qt.PlainText)
    def sizeHint(self):return QSize(0,30)
    def minimumSizeHint(self):return QSize(0,30)
    def paintEvent(self,event):
        painter=QPainter(self);painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.contentsRect(),self.alignment(),self.fontMetrics().elidedText(self.text(),Qt.ElideRight,self.contentsRect().width()))
    def setText(self,text):
        if self.text()==text:return
        super().setText(text);self.setToolTip(text);self.setVisible(bool(text))


class GroupModel(QAbstractTableModel):
    def __init__(self,parent=None):super().__init__(parent);self.rows=[];self.max_sequence=1;self.can_mutate=True;self.compact_headers=False;self.drop_group_id=None;self.image_pairings={}
    def set_image_pairing(self,id,folder=None):
        # Presentation only: acknowledge the drop before background validation.
        if folder is None:self.image_pairings.pop(id,None)
        else:self.image_pairings[id]=str(folder)
        for i,row in enumerate(self.rows):
            if row['id']==id:self.dataChanged.emit(self.index(i,1),self.index(i,1),[Qt.ForegroundRole,Qt.ToolTipRole]);break
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 7
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if role==Qt.ToolTipRole and orientation==Qt.Horizontal:return ['Số thứ tự nhóm trong bộ công việc','Tên tài liệu','Thư mục ảnh','Kiểm tra số lượng','Tiến độ Dịch / Kokoro / CapCut','Trạng thái','Ảnh / Dịch / Xóa'][section]
        if role==Qt.DisplayRole and orientation==Qt.Horizontal:return (['STT','Tài liệu','Ảnh','Số lượng','Tiến độ','Trạng thái','Thao tác'] if self.compact_headers else ['STT','Tài liệu','Thư mục ảnh','Kiểm tra số lượng','Tiến độ các bước','Trạng thái','Thao tác'])[section]
    def flags(self,index):
        return Qt.ItemIsEnabled|Qt.ItemIsSelectable
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid():return None
        row=self.rows[index.row()];column=index.column();meta=row['data']
        if role==Qt.UserRole:return row['id']
        if role==Qt.AccessibleTextRole and column==6:return 'Chọn thư mục ảnh; Mở bản dịch; Bỏ nhóm'
        if role==Qt.ToolTipRole:
            from ..kira_recovery import reason_label
            if column==1 and row['id'] in self.image_pairings:return 'Đã nhận thư mục ảnh, đang kiểm tra: '+self.image_pairings[row['id']]
            return str(self.data(index,Qt.DisplayRole) or '')+'\n'+(row.get('path') or '')+'\n'+(meta.get('image_folder') or '')+'\n'+(meta.get('error') or '')+'\n'+reason_label(meta.get('translation_recovery_reason'))+('\nThử lại: '+time.strftime('%H:%M:%S',time.localtime(meta['next_retry_at'])) if meta.get('next_retry_at') else '')+'\nThao tác: chọn ảnh · mở Dịch · xóa nhóm'
        if role==Qt.ForegroundRole:
            if column==1 and (row['id'] in self.image_pairings or meta.get('image_folder')):
                from .theme import colors
                return QColor(status_color('completed',self.parent() is not None and colors(self.parent())['background']=='#1D1815'))
            if column in (3,5):return QColor('#ef7878' if meta.get('error') or meta['state']=='needs_attention' else '#49cda0')
        if role==Qt.DisplayRole:
            recovery=meta.get('translation_recovery_state')
            if column==5 and meta['state'] in ('preparing','waiting','translating','needs_attention') and recovery in ('ready','parked','provider_recovering','retry_scheduled','waiting_rate_limit','network_waiting','user_paused','paused','needs_reconciliation','blocked_auth','blocked_quota','blocked_budget'):
                if recovery in ('ready','parked'):return 'Chờ slot dịch' if recovery=='parked' else 'Đợi dịch'
                return {'provider_recovering':'Đang hồi phục','retry_scheduled':'Chờ thử lại','waiting_rate_limit':'Chờ giới hạn tốc độ','network_waiting':'Chờ mạng','user_paused':'Đã tạm dừng','paused':'Đã tạm dừng','needs_reconciliation':'Cần đối chiếu kết quả','blocked_auth':'Key không hợp lệ','blocked_quota':'Hết quota','blocked_budget':'Đã đạt giới hạn'}.get(recovery,recovery)
            values=[row.get('sequence',row['position']+1),Path(row['path']).name,meta.get('image_folder') or 'Chưa chọn ảnh',
                    f'{meta.get("slot_count",len(meta.get("slots",[])))} dòng · {meta.get("image_count",len(meta.get("images",[])))} ảnh' if meta.get('slot_count') else 'Chờ kiểm tra',
                    f'Dịch {row.get("translated",0)}/{row.get("translation_total",0)}\nKokoro {row.get("waves",0)}/{meta.get("slot_count",len(meta.get("slots",[])))} · CapCut '+('✓' if meta['state']=='completed' else '—'),
                    STATES.get(meta.get('display_state',meta['state']),meta['state']),'']
            return values[column]
    def update(self,rows,total=None):
        settled=set()
        for row in rows:
            if row['id'] in self.image_pairings and row['data'].get('image_folder')==self.image_pairings[row['id']]:
                self.image_pairings.pop(row['id']);settled.add(row['id'])
        self.max_sequence=max(1,total if total is not None else max((r.get('sequence',r['position']+1) for r in rows),default=1))
        old={r['id']:r for r in self.rows};wanted={r['id'] for r in rows}
        for i in range(len(self.rows)-1,-1,-1):
            if self.rows[i]['id'] not in wanted:
                self.beginRemoveRows(QModelIndex(),i,i);self.rows.pop(i);self.endRemoveRows()
        existing={r['id'] for r in self.rows}
        for i,row in enumerate(rows):
            if row['id'] not in existing:
                self.beginInsertRows(QModelIndex(),i,i);self.rows.insert(i,row);self.endInsertRows();existing.add(row['id'])
        if [r['id'] for r in self.rows]!=[r['id'] for r in rows]:
            self.layoutAboutToBeChanged.emit();persistent=self.persistentIndexList();keys=[(self.rows[i.row()]['id'],i.column()) for i in persistent]
            self.rows=rows;positions={r['id']:i for i,r in enumerate(rows)}
            self.changePersistentIndexList(persistent,[self.index(positions[key],col) for key,col in keys]);self.layoutChanged.emit()
        else:self.rows=rows
        for i,row in enumerate(rows):
            if old.get(row['id'])!=row or row['id'] in settled:self.dataChanged.emit(self.index(i,0),self.index(i,6))


def group_button_rects(rect):
    width=max(20,(rect.width()-18)//3);height=min(32,rect.height()-8);left=rect.center().x()-(width*3+6)//2
    return tuple(QRect(left+i*(width+3),rect.center().y()-height//2,width,height) for i in range(3))


class QuietItemDelegate(QStyledItemDelegate):
    def initStyleOption(self,option,index):
        super().initStyleOption(option,index)
        option.state &= ~(QStyle.State_HasFocus|QStyle.State_MouseOver)


class GroupActions(QuietItemDelegate):
    def paint(self,painter,option,index):
        from .capcut_actions import glass_surface
        from .theme import colors
        table=self.parent();c=colors(table);dark=c['background']=='#1D1815';rect=option.rect
        row=index.model().rows[index.row()];meta=row['data'];selected=bool(option.state&QStyle.State_Selected)
        painter.save();painter.setRenderHint(QPainter.Antialiasing);painter.fillRect(rect,QColor(c['panel']))
        if selected:
            tint=QColor(c['accent']);tint.setAlpha(24 if dark else 16);painter.fillRect(rect,tint)
        if index.model().drop_group_id==row['id']:
            tint=QColor(c['accent']);tint.setAlpha(38 if dark else 25);painter.fillRect(rect,tint)
            painter.setPen(QPen(QColor(c['accent']),1));painter.drawLine(rect.bottomLeft(),rect.bottomRight())
        painter.setPen(QPen(QColor(c['border']),.7));painter.drawLine(rect.bottomLeft(),rect.bottomRight())
        content=rect.adjusted(8,5,-8,-5);column=index.column();painter.setFont(option.font)
        if column==0:
            painter.setPen(QColor(c['muted']));painter.drawText(rect.adjusted(4,0,-4,0),Qt.AlignCenter,str(index.data()))
        elif column==4:
            width=(content.width()-10)/3
            parts=((row.get('translated',0),row.get('translation_total',0)),(row.get('waves',0),meta.get('slot_count',0)),(int(meta['state']=='completed'),1))
            for i,((done,total),label) in enumerate(zip(parts,('Dịch','Kokoro','CapCut'))):
                x=content.x()+i*(width+5);painter.setPen(QColor(c['muted']));painter.drawText(QRectF(x,rect.center().y()-23,width,17),Qt.AlignCenter,label)
                bar=QRectF(x,rect.center().y()-2,width,16);painter.setPen(Qt.NoPen);painter.setBrush(QColor(c['border']));painter.drawRoundedRect(bar,4,4)
                ratio=min(1,done/total) if total else 0
                if ratio:painter.setBrush(QColor(STAGE_COLORS[i]));painter.drawRoundedRect(QRectF(bar.x(),bar.y(),bar.width()*ratio,bar.height()),4,4)
                painter.setPen(QColor('#ffffff' if ratio>.45 else c['ink']));small=QFont(option.font);small.setPointSizeF(max(7,small.pointSizeF()-1));painter.setFont(small);painter.drawText(bar,Qt.AlignCenter,f'{round(ratio*100)}%');painter.setFont(option.font)
        elif column==5:
            color=QColor(status_color(meta.get('display_state',meta['state']),dark));badge=QRectF(content);badge.setHeight(29);badge.moveCenter(QPointF(content.center()));shade=QColor(color);shade.setAlpha(23 if dark else 15)
            painter.setPen(Qt.NoPen);painter.setBrush(shade);painter.drawRoundedRect(badge,10,10);painter.setPen(color);painter.drawText(badge.adjusted(5,0,-5,0),Qt.AlignCenter,painter.fontMetrics().elidedText(str(index.data() or ''),Qt.ElideRight,int(badge.width()-10)))
        elif column!=6:
            paired_ink=index.data(Qt.ForegroundRole) if column==1 else None
            painter.setPen(paired_ink if paired_ink is not None else QColor(status_color('needs_attention' if meta.get('error') else 'completed',dark) if column==3 and meta.get('slot_count') else c['muted'] if column==3 else c['ink']))
            text=str(index.data() or '');painter.drawText(content,Qt.AlignVCenter|Qt.AlignLeft,painter.fontMetrics().elidedText(text,Qt.ElideRight,content.width()))
        if table.keyboard_focus and table.currentIndex()==index and column!=6:
            painter.setPen(QPen(QColor(c['accent']),1));painter.drawLine(content.bottomLeft(),content.bottomRight())
        if column!=6:painter.restore();return
        for action,(rect,label) in enumerate(zip(group_button_rects(option.rect),('Ảnh','Dịch','×'))):
            key=(index.data(Qt.UserRole),('images','editor','remove')[action]);enabled=action==1 or table.model().can_mutate
            bounds,ink=glass_surface(painter,rect,c,enabled,table.hover==key,table.pressed_action==key,focus=table.hasFocus() and table.keyboard_focus and table.currentIndex()==index and table.keyboard_action==action)
            painter.setPen(QColor('#ef7878') if action==2 and enabled else ink);painter.drawText(bounds,Qt.AlignCenter,label)
        painter.restore()


class GroupTable(QTableView):
    dropped=Signal(object,object)
    action_clicked=Signal(str,str)
    drop_target=Signal(object)
    drop_rejected=Signal(str)
    def __init__(self):
        super().__init__();self.setAcceptDrops(True);self.viewport().setAcceptDrops(True);self.setDragDropMode(QAbstractItemView.DropOnly)
        self.pressed_action=None;self.hover=None;self.keyboard_action=0;self.keyboard_focus=False;self.setMouseTracking(True);self.setItemDelegate(GroupActions(self));self.setStyleSheet('QTableView { outline:0; border:0; border-radius:0; } QHeaderView { border:0; border-radius:0; }')
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel);self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.horizontalScrollBar().setSingleStep(24)
    def wheelEvent(self,event):
        target=getattr(self,'scroll_table',self)
        if event.modifiers()&Qt.ShiftModifier or event.pixelDelta().x() or event.angleDelta().x():
            delta=event.pixelDelta().x() or event.pixelDelta().y()
            if not delta:delta=(event.angleDelta().x() or event.angleDelta().y())/120*target.horizontalScrollBar().singleStep()*3
            bar=target.horizontalScrollBar();bar.setValue(bar.value()-round(delta));event.accept();return
        super().wheelEvent(event)
    def focusInEvent(self,event):
        self.keyboard_focus=event.reason() in (Qt.TabFocusReason,Qt.BacktabFocusReason);super().focusInEvent(event)
    def action_at(self,position):
        index=self.indexAt(position)
        if not index.isValid() or index.column()!=6:return None
        for i,rect in enumerate(group_button_rects(self.visualRect(index))):
            if rect.contains(position) and (i==1 or self.model().can_mutate):return index.data(Qt.UserRole),('images','editor','remove')[i]
        return None
    def mouseMoveEvent(self,event):
        self.hover=self.action_at(event.position().toPoint());self.viewport().setCursor(Qt.PointingHandCursor if self.hover else Qt.ArrowCursor);self.viewport().update();super().mouseMoveEvent(event)
    def leaveEvent(self,event):self.hover=None;self.viewport().update();super().leaveEvent(event)
    def mouseDoubleClickEvent(self,event):
        if self.action_at(event.position().toPoint()):event.accept();return
        super().mouseDoubleClickEvent(event)
    def keyPressEvent(self,event):
        self.keyboard_focus=True
        index=self.currentIndex()
        panes=getattr(self,'panes',())
        if panes and event.key() in (Qt.Key_Tab,Qt.Key_Backtab):
            direction=-1 if event.key()==Qt.Key_Backtab or event.modifiers()&Qt.ShiftModifier else 1
            next_pane=panes.index(self)+direction
            if not 0<=next_pane<len(panes):self.window().focusNextPrevChild(direction>0);event.accept();return
            pane=panes[next_pane];column=next(c for c in range(7) if not pane.isColumnHidden(c))
            pane.setFocus(Qt.TabFocusReason);pane.setCurrentIndex(self.model().index(max(0,index.row()),column));event.accept();return
        if index.isValid() and index.column()==6:
            if event.key() in (Qt.Key_Left,Qt.Key_Right):self.keyboard_action=(self.keyboard_action+(1 if event.key()==Qt.Key_Right else -1))%3;self.viewport().update();return
            if event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
                if self.keyboard_action==1 or self.model().can_mutate:self.action_clicked.emit(index.data(Qt.UserRole),('images','editor','remove')[self.keyboard_action])
                event.accept();return
        super().keyPressEvent(event)
    def mousePressEvent(self,event):
        self.keyboard_focus=False
        self.pressed_action=self.action_at(event.position().toPoint()) if event.button()==Qt.LeftButton else None
        super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        action=self.action_at(event.position().toPoint());pressed=self.pressed_action;self.pressed_action=None
        super().mouseReleaseEvent(event)
        if action and action==pressed:self.action_clicked.emit(*action)
    def dragEnterEvent(self,event):
        self.update_drop(event)
    def valid_drop(self,event):
        paths=[Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if len(paths)==1 and paths[0].is_dir():return self.model().can_mutate and self.indexAt(event.position().toPoint()).isValid()
        return self.model().can_mutate and bool(paths) and all(p.is_file() and p.suffix.lower() in ('.txt','.docx') for p in paths)
    def dragMoveEvent(self,event):
        self.update_drop(event)
    def update_drop(self,event):
        paths=[Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        folder=len(paths)==1 and paths[0].is_dir()
        if self.valid_drop(event):
            index=self.indexAt(event.position().toPoint());self.drop_target.emit(index.data(Qt.UserRole) if folder else None);event.acceptProposedAction()
        else:
            self.drop_target.emit(None);event.ignore()
            if folder and not self.model().can_mutate:self.drop_rejected.emit('Đang chạy Automation; dừng an toàn trước khi thay thư mục ảnh.')
    def dragLeaveEvent(self,event):
        self.drop_target.emit(None);super().dragLeaveEvent(event)
    def dropEvent(self,event):
        self.drop_target.emit(None)
        if not self.valid_drop(event):event.ignore();return
        paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()];index=self.indexAt(event.position().toPoint())
        id=index.data(Qt.UserRole) if index.isValid() else None
        self.dropped.emit(paths,id);event.acceptProposedAction()


def panel(title):
    frame=AutomationCard();layout=QVBoxLayout(frame);layout.setContentsMargins(14,12,14,12);layout.setSpacing(9)
    label=QLabel(title);label.setObjectName('section');label.setStyleSheet('font-weight:600;');layout.addWidget(label);return frame,layout


class AutomationPage(QWidget):
    task_done=Signal(object,object)
    refresh_requested=Signal()
    completion=Signal(str,str)
    group_changed=Signal(str)
    audio_release=Signal(object)
    def __init__(self,owner,repo,services,controller):
        super().__init__(owner);self.owner=owner;self.repo=repo;self.services=services;self.controller=controller;self.setObjectName('automationPage')
        self.setStyleSheet('QWidget#automationPage QLabel, QWidget#automationPage QWidget#automationField { background: transparent; }')
        self.current=None;self.loading=False;self.proof=None;self.dirty=True;self.tasks=[];self.progress_cache={};self.dirty_groups=set();self.setAcceptDrops(True)
        self.validation_details='Chưa kiểm tra đầu vào.';self.validation_busy=False;self.validation_again=False;self.validation_force=False;self.validation_generation=0;self._adapting=False;self.pair_generation={};self.pair_pending=set()
        self.import_busy=False;self.import_queue=[];self.project_error_requested=False;self._preview_signature=None
        self.pair_slots=threading.BoundedSemaphore(2)
        self.validation_timer=QTimer(self);self.validation_timer.setSingleShot(True);self.validation_timer.setInterval(250);self.validation_timer.timeout.connect(self.run_validation)
        self.task_done.connect(self.on_done,Qt.QueuedConnection);self.refresh_requested.connect(self.mark_dirty,Qt.QueuedConnection);self.completion.connect(self.on_finished,Qt.QueuedConnection)
        self.repo.listeners.append(lambda *args:self.refresh_requested.emit())
        self.group_changed.connect(self.mark_group_dirty,Qt.QueuedConnection);self.repo.group_listeners.append(self.group_changed.emit)
        self.audio_release.connect(self.release_audio_files,Qt.QueuedConnection)
        self.owner.pages.currentChanged.connect(self.tab_changed)
        self.columns=QHBoxLayout(self);self.columns.setContentsMargins(12,2,12,10);self.columns.setSpacing(14)
        left=QWidget();self.left_pane=left;left.setMinimumWidth(280);left.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Expanding);left.installEventFilter(self)
        body=QVBoxLayout(left);body.setContentsMargins(0,0,0,0);body.setSpacing(2)
        header=QWidget();self.header_grid=QGridLayout(header);self.header_grid.setContentsMargins(0,0,0,0);self.header_grid.setHorizontalSpacing(8);self.header_grid.setVerticalSpacing(0);body.addWidget(header)
        self.title_label=QLabel('Bộ công việc tự động');self.title_label.setObjectName('title');self.title_label.setWordWrap(True)
        self.validation_badge=AutomationButton('Chưa kiểm tra');self.validation_badge.setFixedHeight(30);self.validation_badge.setMinimumWidth(80);self.validation_badge.setProperty('elideText',True);self.validation_badge.clicked.connect(self.show_validation_details)
        self.notice=NoticeLabel();self.notice.hide()
        self.validation_badge.setToolTip('Xem chi tiết kiểm tra đầu vào và cấu hình');self.header_grid.addWidget(self.title_label,0,0);self.header_grid.addWidget(self.notice,0,1);self.header_grid.addWidget(self.validation_badge,0,2,Qt.AlignRight)
        subtitle=QLabel('Dịch → Kokoro → CapCut');self.subtitle=subtitle;subtitle.setObjectName('muted')
        self.group_summary=QLabel('Hoàn tất 0/0 nhóm · Cần xử lý 0');self.group_summary.setObjectName('muted')
        selection=QHBoxLayout();body.addLayout(selection);self.worksets=QComboBox();selection.addWidget(self.worksets,1)
        self.new_button=self.add_button(selection,'Bộ mới',self.new_workset);self.delete_button=self.add_button(selection,'Xóa bộ',self.delete_workset)
        self.worksets.currentIndexChanged.connect(self.select_workset)
        self.toolbar=QWidget();self.toolbar_grid=QGridLayout(self.toolbar);self.toolbar_grid.setContentsMargins(0,0,0,0);self.toolbar_grid.setHorizontalSpacing(6);self.toolbar_grid.setVerticalSpacing(0);body.addWidget(self.toolbar)
        actions=QHBoxLayout()
        self.validate_button=self.add_button(actions,'Kiểm tra lại',self.validate_clicked);self.validate_button.setIcon(QIcon(str(Path(__file__).parent/'assets/automation-check.svg')));self.validate_button.setIconSize(QSize(16,16))
        self.add=self.add_button(actions,'+ Thêm tài liệu',self.choose_files,True)
        self.start=self.add_button(actions,'Bắt đầu',self.start_clicked)
        self.stop=self.add_button(actions,'Dừng an toàn',self.controller.stop)
        self.start.setProperty('glassRole','primary');self.stop.setProperty('glassRole','danger')
        self.toolbar_buttons=(self.add,self.validate_button,self.start,self.stop)
        for i,button in enumerate(self.toolbar_buttons):actions.removeWidget(button);self.toolbar_grid.addWidget(button,0,i)
        filters=QHBoxLayout();body.addLayout(filters)
        self.search=QLineEdit();self.search.setPlaceholderText('Tìm tên file, thư mục…');filters.addWidget(self.search,1)
        self.filter=QComboBox()
        for label,value in (('Tất cả','all'),('Đang xử lý','active'),('Cần xử lý','needs_attention'),('Hoàn thành','completed')):self.filter.addItem(label,value)
        filters.addWidget(self.filter);self.up=self.add_button(filters,'↑',lambda:self.move(-1));self.down=self.add_button(filters,'↓',lambda:self.move(1))
        self.search.textChanged.connect(self.mark_dirty);self.filter.currentIndexChanged.connect(self.mark_dirty)
        # Adjacent number/content/action views share selection and pixel offsets.
        self.table=GroupTable();self.model=GroupModel(self.table);self.table.setModel(self.model)
        self.number_table=GroupTable();self.action_table=GroupTable();self.table_shell=RoundedTableFrame();table_row=QHBoxLayout(self.table_shell.content);table_row.setContentsMargins(0,0,0,0);table_row.setSpacing(0)
        self.table_panes=(self.number_table,self.table,self.action_table)
        for pane,columns in zip(self.table_panes,((0,),(1,2,3,4,5),(6,))):
            pane.setModel(self.model);pane.setSelectionModel(self.table.selectionModel());pane.panes=self.table_panes;pane.scroll_table=self.table
            pane.setSelectionBehavior(QAbstractItemView.SelectRows);pane.setSelectionMode(QAbstractItemView.SingleSelection);pane.setEditTriggers(QAbstractItemView.NoEditTriggers);pane.setWordWrap(False)
            pane.setFrameShape(QFrame.NoFrame);pane.verticalHeader().hide();pane.verticalHeader().setDefaultSectionSize(72);pane.setShowGrid(False)
            pane.horizontalHeader().setFixedHeight(36);pane.horizontalHeader().setStretchLastSection(pane!=self.number_table)
            pane.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed);pane.horizontalHeader().setSectionsMovable(False)
            pane.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn);pane.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if pane==self.action_table else Qt.ScrollBarAlwaysOff)
            for c in range(7):pane.setColumnHidden(c,c not in columns)
            for i,width in enumerate((30,145,150,145,180,125,140)):pane.setColumnWidth(i,width)
            if pane!=self.table:
                pane.horizontalScrollBar().setEnabled(False);pane.horizontalScrollBar().setStyleSheet('QScrollBar:horizontal {background:transparent;} QScrollBar::handle:horizontal,QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal {background:transparent;}')
            pane.action_clicked.connect(self.row_action);pane.doubleClicked.connect(self.open_translation_index);pane.dropped.connect(self.drop_paths)
            pane.drop_target.connect(self.set_drop_target);pane.drop_rejected.connect(self.notice.setText)
            pane.setContextMenuPolicy(Qt.CustomContextMenu);pane.customContextMenuRequested.connect(lambda pos,view=pane:self.row_context_menu(pos,view))
            table_row.addWidget(pane,1 if pane==self.table else 0)
            for other in self.table_panes:
                if other!=pane:pane.verticalScrollBar().valueChanged.connect(other.verticalScrollBar().setValue)
        # Include the themed frame and the right view's vertical scrollbar gutter.
        self.number_table.setFixedWidth(30);self.action_table.setFixedWidth(160)
        self.table.viewport().installEventFilter(self)
        self.table.horizontalScrollBar().rangeChanged.connect(self.horizontal_range_changed)
        self.table_shell.setMinimumHeight(110);body.addWidget(self.table_shell,1)
        self.empty_state=QLabel('Thêm hoặc kéo thả file văn bản vào đây',self.table_shell);self.empty_state.setObjectName('muted');self.empty_state.setAlignment(Qt.AlignCenter);self.empty_state.setWordWrap(True)
        self.empty_state.setAttribute(Qt.WA_TransparentForMouseEvents);self.empty_state.setAcceptDrops(False)
        self.table_shell.installEventFilter(self)
        self.table.horizontalHeader().sectionResized.connect(self.bound_column_width)
        self.columns.addWidget(left,70)
        right_scroll=QScrollArea();self.right_scroll=right_scroll;right_scroll.setWidgetResizable(True);right_scroll.setFrameShape(QFrame.NoFrame);right_scroll.setMinimumWidth(300);right_scroll.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Expanding);right_scroll.viewport().installEventFilter(self)
        right=QWidget();right_layout=QVBoxLayout(right);right_layout.setContentsMargins(0,0,0,0);right_layout.setSpacing(8);right_scroll.setWidget(right)
        progress_frame,progress_layout=panel('Tiến độ tổng thể');self.progress_frame=progress_frame;right_layout.addWidget(progress_frame)
        progress_title=progress_layout.takeAt(0).widget();self.progress_title=progress_title;progress_title.setWordWrap(True);progress_header=QHBoxLayout();progress_header.setSpacing(6);progress_layout.addLayout(progress_header);progress_header.addWidget(progress_title)
        self.summary=QLabel('Chưa chạy · 00:00');self.summary.setWordWrap(True);self.summary.setAlignment(Qt.AlignRight|Qt.AlignVCenter);progress_header.addWidget(self.summary,1)
        self.progress_labels={};self.progress_bars={};self.stage_icons=[];self.stage_cards=[];self.stage_headers=[];self.stage_row=QGridLayout();stage_row=self.stage_row;stage_row.setSpacing(6);progress_layout.addLayout(stage_row)
        for i,stage in enumerate(('Dịch','Kokoro','CapCut')):
            card=QFrame();self.stage_cards.append(card);card.setMinimumWidth(0);card.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);card.setObjectName('automationStage');card.setStyleSheet('QFrame#automationStage { border:1px solid rgba(170,135,110,65); border-radius:10px; background:transparent; }');column=QVBoxLayout(card);column.setContentsMargins(7,6,7,6);column.setSpacing(4)
            stage_header=QHBoxLayout();self.stage_headers.append(stage_header);stage_header.setSpacing(5);column.addLayout(stage_header);icon=QLabel();icon.setPixmap(QIcon(str(Path(__file__).parent/'assets'/('nav-translate.svg','nav-audio.svg','nav-capcut.svg')[i])).pixmap(18,18));icon.setFixedSize(18,18);self.stage_icons.append(icon);stage_header.addWidget(icon)
            title=QLabel(stage);title.setStyleSheet('font-weight:600;');stage_header.addWidget(title);stage_header.addStretch()
            label=QLabel('0/0');label.setStyleSheet('font-size:17px; font-weight:600;');column.addWidget(label);bar=QProgressBar();bar.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);bar.setRange(0,100);bar.setTextVisible(False);bar.setFixedHeight(5);bar.setStyleSheet(f'QProgressBar::chunk {{background:{STAGE_COLORS[i]}; border-radius:2px;}}');column.addWidget(bar);stage_row.addWidget(card,0,i)
            self.progress_labels[stage]=label;self.progress_bars[stage]=bar
        self.completion_ring=CompletionRing();stage_row.addWidget(self.completion_ring,0,3)
        self.config_frame,config_layout=panel('Cấu hình chung');right_layout.addWidget(self.config_frame)
        self.lock_note=QLabel('');self.lock_note.setWordWrap(True);config_layout.addWidget(self.lock_note)
        self.kokoro_lanes=QLabel('Kokoro: 1 luồng · 1 nhóm mỗi lượt');self.kokoro_lanes.setObjectName('muted');config_layout.addWidget(self.kokoro_lanes)
        self.fields={};self.field_titles={};form=None
        from ..languages import LANGUAGES
        for key,title in (('source_lang','Ngôn ngữ nguồn'),('target_lang','Ngôn ngữ đích')):
            box=QComboBox()
            for entry in LANGUAGES:box.addItem(entry.name,entry.locale)
            self.field(form,key,title,box)
        provider=QComboBox();provider.addItem('Kira','kira');provider.addItem('Gemini','gemini');provider.addItem('DeepSeek','deepseek');self.field(form,'provider','API dịch',provider)
        self.field(form,'model','Mô hình',QComboBox())
        from ..deepseek_batch import BATCH_SIZES
        batch=QComboBox()
        for size in BATCH_SIZES:batch.addItem(f'{size} dòng',size)
        self.field(form,'deepseek_batch_size','Số dòng mỗi batch',batch)
        workers=QSpinBox();workers.setRange(1,30);self.field(form,'workers','Luồng tổng',workers)
        from ..tts.catalog import LANGUAGES as TTS_LANGUAGES
        lang=QComboBox()
        for key,(name,*_) in TTS_LANGUAGES.items():lang.addItem(name,key)
        self.field(form,'tts_language','Ngôn ngữ Kokoro',lang)
        self.field(form,'voice','Voice',QComboBox())
        speed=QDoubleSpinBox();speed.setRange(.5,2);speed.setSingleStep(.05);self.field(form,'speed','Tốc độ',speed)
        output_format=QComboBox();output_format.addItem('WAV','wav');self.field(form,'format','Định dạng',output_format)
        mode=QComboBox()
        for label,key in (('Xuất từng nhóm','separate'),('Gộp toàn bộ','merged'),('Chia đều thành nhiều part','split')):mode.addItem(label,key)
        self.field(form,'capcut_mode','Xuất CapCut',mode)
        count=QSpinBox();count.setRange(2,100000);self.field(form,'part_count','Số part',count)
        self.field(form,'project_name','Tên project chung',QLineEdit())
        folder=QWidget();folder.setObjectName('automationField');folder_row=QHBoxLayout(folder);folder_row.setContentsMargins(0,0,0,0);self.output=ElidingPathEdit();folder_row.addWidget(self.output,1)
        self.output_choose=self.add_button(folder_row,'Chọn…',self.choose_output);self.fields['output']=self.output;self.field_titles['output']='Thư mục CapCut';self.output.textEdited.connect(self.config_changed)
        # Group related settings into compact rows like the approved mockup.
        labels=self.field_titles
        self.field_cells={};self.fields_grid=QGridLayout();self.fields_grid.setHorizontalSpacing(8);self.fields_grid.setVerticalSpacing(6);config_layout.addLayout(self.fields_grid)
        for keys in (('source_lang','target_lang'),('provider','model','workers'),('deepseek_batch_size',),('tts_language','voice','speed'),('format','capcut_mode','part_count'),('project_name',),('output',)):
            for key in keys:
                cell=QWidget();cell.setObjectName('automationField');self.field_cells[key]=cell;cell.setMinimumWidth(0);cell.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);column=QVBoxLayout(cell);column.setContentsMargins(0,0,0,0);column.setSpacing(2)
                label=QLabel(labels[key]);label.setObjectName('muted');label.setWordWrap(True);column.addWidget(label)
                control=folder if key=='output' else self.fields[key];control.setMinimumWidth(0);control.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);column.addWidget(control)
        self.project_warning=QLabel();self.project_warning.setWordWrap(True);self.project_warning.setFixedHeight(34);self.project_warning.setStyleSheet('color:#C85344;')
        self.field_cells['project_name'].layout().addWidget(self.project_warning)
        self.fields['project_name'].editingFinished.connect(lambda:self.check_project_name(focus=False) if not self.loading else None)
        self.preview=QTableWidget(0,2);self.preview.setHorizontalHeaderLabels(['Project / sửa tên','Nhóm']);self.preview.verticalHeader().hide();self.preview.setFixedHeight(120)
        self.preview.setItemDelegate(QuietItemDelegate(self.preview));self.preview.setStyleSheet('QTableWidget { outline: 0; }')
        self.preview.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);self.preview.setColumnWidth(1,80);config_layout.addWidget(self.preview);self.preview.itemChanged.connect(self.rename_part)
        self.config_opacity=QGraphicsOpacityEffect(self.config_frame);self.config_frame.setGraphicsEffect(self.config_opacity)
        right_layout.addStretch();self.columns.addWidget(right_scroll,30)
        self.fields['provider'].currentIndexChanged.connect(self.fill_models);self.fields['tts_language'].currentIndexChanged.connect(self.fill_voices)
        from .automation_snapshots import AutomationSnapshots
        self.snapshots=AutomationSnapshots(self)
        self.timer=QTimer(self);self.timer.setInterval(150);self.timer.timeout.connect(self.flush);self.timer.start()
        self.load_worksets()
    def add_button(self,layout,text,callback,primary=False):
        control=AutomationButton(text)
        if primary:control.setProperty('glassRole','primary')
        control.setMinimumWidth(28);control.setFixedHeight(36);control.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Fixed);control.setToolTip(text);control.setProperty('elideText',True);control.clicked.connect(lambda *_:self.safe(callback));layout.addWidget(control);return control
    def bound_column_width(self,section,old,width):
        minimum=(28,105,80,100,165,100,140)[section];maximum=28 if section==0 else max(width,140) if section==6 else 700
        bounded=max(minimum,min(maximum,width))
        if width!=bounded:self.table.horizontalHeader().resizeSection(section,bounded)
    def horizontal_range_changed(self,minimum,maximum):
        # Equal viewport heights without permanently displaying an unused track.
        policy=Qt.ScrollBarAlwaysOn if maximum>minimum else Qt.ScrollBarAlwaysOff
        for pane in self.table_panes:pane.setHorizontalScrollBarPolicy(policy)
    def resizeEvent(self,event):
        compact=self.height()<700
        self.subtitle.setVisible(not compact)
        self.adapt_layout()
        super().resizeEvent(event)
    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Resize,QEvent.FontChange,QEvent.StyleChange,QEvent.PaletteChange,QEvent.DevicePixelRatioChange):
            if event.type()!=QEvent.Resize:self._table_width=None
            self.adapt_layout()
        return super().eventFilter(watched,event)
    def adapt_layout(self):
        if self._adapting or not hasattr(self,'fields_grid'):return
        self._adapting=True
        try:
            header_font=QFont(self.number_table.horizontalHeader().font());header_font.setBold(True)
            number_width=max(QFontMetrics(header_font).horizontalAdvance('STT')+12,self.number_table.fontMetrics().horizontalAdvance(str(self.model.max_sequence))+12)
            self.number_table.setFixedWidth(number_width);self.number_table.setColumnWidth(0,number_width)
            available=self.table.viewport().width();fm=self.table.fontMetrics();identity=(available,fm.height(),fm.averageCharWidth(),self.devicePixelRatioF())
            if getattr(self,'_table_width',None)!=identity:
                self._table_width=identity;minimum=(max(105,fm.horizontalAdvance('Tài liệu')+20),max(80,fm.horizontalAdvance('Ảnh')+20),max(125,fm.horizontalAdvance('999 dòng · 999 ảnh')+16),max(165,3*fm.horizontalAdvance('Kokoro')+35),max(100,fm.horizontalAdvance('Đang tạo voice')+20));extra=max(0,available-sum(minimum))
                for i,(base,weight) in enumerate(zip(minimum,(2,3,2,2,2)),1):self.table.setColumnWidth(i,base+extra*weight//11)
                compact=available<700
                if self.model.compact_headers!=compact:self.model.compact_headers=compact;self.model.headerDataChanged.emit(Qt.Horizontal,1,5)
                action_width=max(160,3*(max(fm.horizontalAdvance('Ảnh'),fm.horizontalAdvance('Dịch'))+18)+24+self.style().pixelMetric(QStyle.PM_ScrollBarExtent))
                self.action_table.setFixedWidth(action_width)
                for pane in self.table_panes:
                    pane.horizontalHeader().setFixedHeight(max(36,fm.height()+18));pane.verticalHeader().setDefaultSectionSize(max(72,2*fm.height()+30))
            self.position_empty_state()
            narrow=self.left_pane.width()<610
            if getattr(self,'_header_layout',None)!=narrow:
                self._header_layout=narrow
                for widget in (self.title_label,self.notice,self.validation_badge,self.group_summary,self.subtitle):self.header_grid.removeWidget(widget)
                self.header_grid.addWidget(self.title_label,0,0,1,3 if narrow else 1)
                self.header_grid.addWidget(self.notice,1 if narrow else 0,0 if narrow else 1,1,2 if narrow else 1)
                self.header_grid.addWidget(self.validation_badge,1 if narrow else 0,2,Qt.AlignRight)
                self.header_grid.addWidget(self.subtitle,2 if narrow else 1,0)
                self.header_grid.addWidget(self.group_summary,3 if narrow else 1,0 if narrow else 1,1,3 if narrow else 2,Qt.AlignLeft if narrow else Qt.AlignRight)
                self.header_grid.setColumnStretch(0,0);self.header_grid.setColumnStretch(1,1);self.header_grid.setColumnStretch(2,0)
                for button in self.toolbar_buttons:self.toolbar_grid.removeWidget(button)
                columns=2 if narrow else 4
                for i,button in enumerate(self.toolbar_buttons):self.toolbar_grid.addWidget(button,i//columns,i%columns)
                for i in range(4):self.toolbar_grid.setColumnStretch(i,int(i<columns))
            width=self.right_scroll.viewport().width();small=width<500;tiny=width<370;stacked=width<400
            if getattr(self,'_stage_stacked',None)!=stacked:
                self._stage_stacked=stacked
                while self.stage_row.count():self.stage_row.takeAt(0)
                for i,(stage,card) in enumerate(zip(self.progress_labels,self.stage_cards)):
                    label=self.progress_labels[stage];card.layout().removeWidget(label);self.stage_headers[i].removeWidget(label)
                    if stacked:self.stage_headers[i].addWidget(label)
                    else:card.layout().insertWidget(1,label)
                    self.stage_row.addWidget(card,i if stacked else 0,0 if stacked else i)
                self.stage_row.addWidget(self.completion_ring,0,1 if stacked else 3,3 if stacked else 1,1,Qt.AlignCenter)
                for i in range(4):self.stage_row.setColumnStretch(i,int(i==0 if stacked else i<3))
            for icon in self.stage_icons:icon.setVisible(True)
            split=bool(self.current and self.fields['capcut_mode'].currentData()=='split')
            is_deepseek=self.fields['provider'].currentData()=='deepseek'
            self.field_cells['deepseek_batch_size'].setVisible(is_deepseek)
            if getattr(self,'_field_layout',None)!=(small,tiny,is_deepseek):
                self._field_layout=(small,tiny,is_deepseek)
                while self.fields_grid.count():self.fields_grid.takeAt(0)
                groups=(('source_lang','target_lang'),('provider','workers'),('model',),('tts_language','speed','format'),('voice',),('capcut_mode','part_count'),('project_name',),('output',)) if small else (('source_lang','target_lang'),('provider','model','workers'),('tts_language','voice','speed'),('format','capcut_mode','part_count'),('project_name',),('output',))
                if tiny:groups=(('source_lang','target_lang'),('provider','workers'),('model',),('tts_language','speed'),('voice',),('capcut_mode',),('format','part_count'),('project_name',),('output',))
                if is_deepseek:
                    groups=list(groups);groups.insert(3 if small else 2,('deepseek_batch_size',))
                for row,keys in enumerate(groups):
                    col=0
                    spans=[12//len(keys)]*len(keys)
                    if small and not tiny and keys[0]=='tts_language':spans=[5,4,3]
                    if small and not tiny and keys[0]=='capcut_mode':spans=[8,4]
                    if not small and len(keys)==3:spans=[3,6,3] if keys[0] in ('provider','format') else [4,5,3]
                    for key,span in zip(keys,spans):self.fields_grid.addWidget(self.field_cells[key],row,col,1,span);col+=span
                for i in range(12):self.fields_grid.setColumnStretch(i,1)
            self.fields['part_count'].setEnabled(split and self.config_frame.isEnabled())
            self.fields['part_count'].setToolTip('Số project muốn chia' if split else 'Chỉ dùng trong chế độ Chia part')
        finally:self._adapting=False
    def field(self,form,key,title,control):
        self.fields[key]=control;self.field_titles[key]=title;control.setMinimumWidth(0)
        if isinstance(control,QComboBox):control.currentIndexChanged.connect(self.config_changed)
        elif isinstance(control,QLineEdit):control.textEdited.connect(self.config_changed)
        else:control.valueChanged.connect(self.config_changed)
    def safe(self,fn):
        try:return fn()
        except Exception as exc:self.notice.setText(str(exc));return None
    def position_empty_state(self):
        if not hasattr(self,'empty_state'):return
        top=self.table.horizontalHeader().height()+2
        self.empty_state.setGeometry(12,top,max(1,self.table_shell.width()-24),max(1,self.table.viewport().height()-4));self.empty_state.raise_()
    def update_empty_state(self,total):
        self.empty_state.setText('Không tìm thấy tài liệu phù hợp' if total else 'Thêm hoặc kéo thả file văn bản vào đây')
        self.empty_state.setVisible(self.model.rowCount()==0);self.position_empty_state()
    def set_drop_target(self,id):
        old=self.model.drop_group_id
        if old==id:return
        self.model.drop_group_id=id
        for row,g in enumerate(self.model.rows):
            if g['id'] in (old,id):self.model.dataChanged.emit(self.model.index(row,0),self.model.index(row,6))
    def mark_dirty(self,*args):self.dirty=True
    def mark_group_dirty(self,id):self.dirty_groups.add(id);self.dirty=True
    def release_audio(self):
        released=threading.Event();self.audio_release.emit(released)
        if not released.wait(5):raise RuntimeError('Chờ player nhả file trước khi chốt thư mục WAV; giữ checkpoint để tiếp tục.')
    def release_audio_files(self,released):
        try:
            if hasattr(self.owner,'tts_page'):self.owner.tts_page.stop_playback()
            if hasattr(self.owner,'capcut_page'):self.owner.capcut_page.stop_audio()
        finally:released.set()
    def tab_changed(self,index):
        if index==9:self.snapshots.request()
        if index in (0,7,8):self.sync_views(force=True)
        if index==9 and self.current and self.repo.workset(self.current)['checkpoint'].get('validation_sections'):self.queue_validation()
    def flush(self):
        if self.owner._closed or self.owner._exit_pending:return
        if self.dirty:self.dirty=False;self.snapshots.request()
    def background(self,work,done):
        def run():
            try:result=(work(),None)
            except Exception as exc:result=(None,str(exc))
            self.task_done.emit(done,result)
        thread=threading.Thread(target=run,daemon=True,name='automation-ui-task');self.tasks.append(thread);self.owner.background_threads.append(thread);thread.start()
    def on_done(self,callback,value):
        if self.owner._closed:return
        result,error=value
        if error:self.notice.setText(error)
        else:self.safe(lambda:callback(result))
        self.mark_dirty()
    def load_worksets(self,select=None):
        self.loading=True;self.worksets.clear()
        for work in self.repo.workset_summaries():self.worksets.addItem(work['name'],work['id'])
        wanted=select or self.current;index=self.worksets.findData(wanted)
        self.worksets.setCurrentIndex(max(0,index));self.loading=False;self.select_workset()
    def select_workset(self,*args):
        if self.loading:return
        self.current=self.worksets.currentData();self.proof=None;self.validation_generation+=1;self.validation_timer.stop();self.validation_again=False;self.validation_force=False
        self.project_error_requested=False;self.project_warning.setText('')
        self.set_validation_status('Chưa kiểm tra','Kết quả lưu trước đó sẽ được xác minh lại trước khi sử dụng.')
        if self.current:
            self.loading=True;cfg=self.repo.workset(self.current)['config']
            for key in ('provider','tts_language'):self.set_field(key,cfg[key])
            self.fill_models();self.fill_voices()
            for key,value in cfg.items():
                if key in self.fields:self.set_field(key,value)
            self.loading=False
        self.refresh()
        if self.current and self.repo.workset(self.current)['checkpoint'].get('validation_sections'):self.queue_validation()
    def set_field(self,key,value):
        control=self.fields[key]
        if isinstance(control,QComboBox):
            index=control.findData(value)
            if index<0:control.addItem(str(value),value);index=control.count()-1
            control.setCurrentIndex(index)
        elif isinstance(control,QLineEdit):control.setText(str(value))
        else:control.setValue(value)
    def fill_models(self,*args):
        was=self.loading;self.loading=True;box=self.fields['model'];old=box.currentData();box.clear()
        from ..deepseek_models import MODEL_NAMES
        if old in MODEL_NAMES:self._deepseek_selection=old
        if self.fields['provider'].currentData()=='kira':
            from ..models import KIRA_MODELS
            for label,id in KIRA_MODELS:box.addItem(label,id)
        elif self.fields['provider'].currentData()=='deepseek':
            from ..deepseek_models import MODELS
            for model,name in MODELS:box.addItem(name,model)
            old=getattr(self,'_deepseek_selection',old)
        else:
            try:models=json.loads(self.repo.store.setting('gemini_models','[]'))
            except ValueError:models=[]
            for model in models:
                name=model.get('name','') if isinstance(model,dict) else str(model)
                if name:box.addItem(name,name)
        box.setCurrentIndex(max(0,box.findData(old)));self.loading=was
        if not was:self.config_changed()
    def fill_voices(self,*args):
        from ..tts.catalog import voice_names
        was=self.loading;self.loading=True;box=self.fields['voice'];old=box.currentData();box.clear()
        for voice in voice_names(self.fields['tts_language'].currentData() or 'en-us'):box.addItem('Jessica (US Female)' if voice=='af_jessica' else voice,voice)
        box.setCurrentIndex(box.findData(old or 'af_jessica'));self.loading=was
        if not was:self.config_changed()
    def config_changed(self,*args):
        if self.loading or not self.current:return
        saved=self.repo.workset(self.current)['config'];cfg=dict(saved)
        for key,control in self.fields.items():cfg[key]=control.currentData() if isinstance(control,QComboBox) else control.text() if isinstance(control,QLineEdit) else control.value()
        try:self.repo.configure(self.current,cfg)
        except ValueError as exc:
            self.notice.setText(str(exc));self.loading=True
            try:
                for key in self.fields:self.set_field(key,saved[key])
            finally:self.loading=False
            self.mark_dirty();return
        self.proof=None;self.mark_dirty();self.adapt_layout()
        self.check_project_name(focus=False,explicit=False)
        self.queue_validation()
    def preview_parts(self,groups):
        cfg=getattr(self,'_render_work',None)
        cfg=cfg['config'] if cfg and cfg['id']==self.current else self.repo.workset(self.current)['config'] if self.current else {}
        signature=(self.current,fingerprint(cfg),tuple((g['id'],g['path']) for g in groups))
        if signature==self._preview_signature:return
        self._preview_signature=signature
        self.preview.blockSignals(True)
        try:
            parts=plan_parts(groups,cfg) if self.current else ();self.preview.setRowCount(len(parts))
            for i,part in enumerate(parts):
                name=QTableWidgetItem(part.name);name.setData(Qt.UserRole,str(i+1) if cfg['capcut_mode']!='separate' else part.groups[0]['id']);self.preview.setItem(i,0,name)
                group=QTableWidgetItem(f'{part.start}–{part.end}');group.setFlags(group.flags()&~Qt.ItemIsEditable);self.preview.setItem(i,1,group)
        except ValueError:self.preview.setRowCount(0)
        finally:self.preview.blockSignals(False)
    def rename_part(self,item):
        if self.loading or not self.current or item.column()!=0:return
        cfg=self.repo.workset(self.current)['config'];cfg['part_names']=dict(cfg.get('part_names',{}));cfg['part_names'][item.data(Qt.UserRole)]=item.text()
        try:self.repo.configure(self.current,cfg)
        except ValueError as exc:self.notice.setText(str(exc));self.preview_parts(self.repo.group_summaries(self.current));return
        self.proof=None;self.mark_dirty();self.queue_validation()
    def new_workset(self):
        name,ok=QInputDialog.getText(self,'Bộ công việc mới','Tên bộ truyện:')
        if ok and name.strip():
            cfg=defaults(self.repo.store);cfg.update(project_name='',part_names={})
            self.load_worksets(self.repo.create(name,cfg))
    def delete_workset(self):
        if not self.current:return
        self.repo.editable(self.current)
        if QMessageBox.question(self,'Xóa bộ công việc','Chỉ xóa metadata/checkpoint của bộ này; giữ toàn bộ file nguồn và kết quả ngoài ổ đĩa.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            self.repo.delete(self.current);self.current=None;self.load_worksets()
    def choose_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Thêm DOCX/TXT từ nhiều thư mục','','DOCX/TXT (*.docx *.txt)')
        if paths:self.drop_paths(paths,None)
    def drop_paths(self,paths,id=None):
        if not self.current:self.notice.setText('Tạo/chọn bộ công việc trước.');return
        if len(paths)==1 and Path(paths[0]).is_dir():
            if id:self.safe(lambda:self.pair_folder(id,paths[0]))
            else:self.notice.setText('Thả thư mục ảnh vào đúng hàng; không nhận thư mục tài liệu để quét.')
            return
        workset=self.current
        self.validation_generation+=1;self.proof=None;self.validation_timer.stop();self.import_queue.append((workset,tuple(paths)))
        if not self.import_busy:self.import_next()
    def import_next(self):
        if not self.import_queue:
            self.import_busy=False;self.queue_validation();self.mark_dirty();return
        self.import_busy=True;workset,paths=self.import_queue.pop(0)
        self.set_validation_status('Đang nhập tài liệu','Đọc tài liệu trong nền; giữ thứ tự các đợt thêm.');self.start.setEnabled(False)
        def done(result):self.import_done(workset);self.import_next()
        def work():
            try:return self.repo.add(workset,paths),None
            except Exception as exc:return (),str(exc)
        def finish(value):
            result,error=value
            if error:self.notice.setText(error)
            done(result)
        self.background(work,finish)
    def pair_folder(self,id,folder,sort=None):
        """Validate a proposed mapping off-thread before changing any saved mapping."""
        group=self.repo.group(id);workset=group['workset_id'];self.repo.editable(workset)
        if workset!=self.current:raise ValueError('Nhóm không thuộc bộ công việc đang xem.')
        sort=sort or group['data'].get('image_sort','name');generation=self.pair_generation.get(id,0)+1;self.pair_generation[id]=generation
        self.pair_pending.add(id);self.start.setEnabled(False)
        self.model.set_image_pairing(id,folder)
        original=(group['data'].get('image_folder'),group['data'].get('image_sort','name'))
        self.notice.setText('Đang kiểm tra thư mục ảnh…')
        def inspect():
            import os
            from ..automation.validation import image_manifest,input_stamp,speakable
            path=Path(folder)
            if not path.is_dir() or not os.access(path,os.R_OK):raise ValueError('Thư mục ảnh không tồn tại hoặc không đọc được.')
            path=path.resolve();doc=self.repo.store.document(group['document_id']);rows=self.repo.store.lines(group['document_id'])
            proposed={**group,'data':{**group['data'],'image_folder':str(path),'image_sort':sort}}
            stamp=input_stamp(proposed,Path(doc['path']),rows)
            images=image_manifest(path,sort,cancelled=lambda:self.owner._closed or self.pair_generation.get(id)!=generation or self.current!=workset)
            if not images:raise ValueError('Thư mục không có ảnh hợp lệ; giữ nguyên mapping trước đó.')
            if input_stamp(proposed,Path(doc['path']),rows)!=stamp:raise ValueError('Đầu vào thay đổi khi kiểm tra; giữ mapping trước đó.')
            return dict(folder=str(path),images=images,stamp=stamp,slots=[r['id'] for r in rows if speakable(r['source'])])
        def checked(result):
            if self.pair_generation.get(id)!=generation:return
            self.pair_pending.discard(id)
            value,error=result
            if self.current!=workset:self.model.set_image_pairing(id);return
            if error:self.model.set_image_pairing(id);self.notice.setText(error);return
            current=self.repo.group(id);self.repo.editable(workset)
            if (current['data'].get('image_folder'),current['data'].get('image_sort','name'))!=original:self.model.set_image_pairing(id);return
            self.repo.pair_images(id,value['folder'],sort,inspection=value);self.proof=None;self.mark_dirty();self.notice.setText('')
            self.model.set_image_pairing(id,value['folder'])
            if self.current==workset:self.queue_validation()
        def check():
            try:
                with self.pair_slots:return inspect(),None
            except Exception as exc:return None,str(exc) or 'Đã hủy kiểm tra thư mục ảnh lỗi thời.'
        self.background(check,checked)
    def import_done(self,id):
        if id==self.current:self.proof=None;self.mark_dirty();self.queue_validation()
    def selected(self):
        index=self.table.currentIndex()
        return index.data(Qt.UserRole) if index.isValid() else None
    def choose_images(self,id=None):
        id=id or self.selected()
        if not id:return
        self.repo.editable(self.repo.group(id)['workset_id']);folder=QFileDialog.getExistingDirectory(self,'Ghép thư mục ảnh cho '+Path(self.repo.store.document(self.repo.group(id)['document_id'])['path']).name)
        if not folder:return
        sort,ok=QInputDialog.getItem(self,'Sắp xếp ảnh','Thứ tự ảnh:',['Theo tên tự nhiên','Theo Date created'],0,False)
        if ok:self.pair_folder(id,folder,'name' if sort.startswith('Theo tên') else 'created')
    def row_action(self,id,action):
        if action=='images':self.safe(lambda:self.choose_images(id))
        elif action=='editor':self.safe(lambda:self.open_translation(id))
        else:
            if QMessageBox.question(self,'Bỏ nhóm','Bỏ metadata nhóm; giữ nguồn và tất cả kết quả?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:self.safe(lambda:self.repo.remove_group(id));self.proof=None;self.mark_dirty();self.queue_validation()
    def move(self,delta):
        id=self.selected()
        if id:self.repo.move(id,delta);self.proof=None;self.mark_dirty();self.queue_validation()
    def open_translation_index(self,index):
        if index.isValid():self.open_translation(index.data(Qt.UserRole))
    def open_translation(self,id=None):
        id=id or self.selected()
        if id:self.owner.open_document(self.repo.group(id)['document_id']);self.owner.pages.setCurrentIndex(0)
    def open_result(self,id=None):
        id=id or self.selected()
        if not id:return
        group=self.repo.group(id);meta=group['data'];path=meta.get('project') or meta.get('audio_folder') or str(Path(self.repo.store.document(group['document_id'])['path']).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    def row_context_menu(self,position,view=None):
        view=view or self.table;index=view.indexAt(position)
        if not index.isValid():return
        id=index.data(Qt.UserRole);menu=QMenu(self.table)
        for title,callback in (('Ảnh / sắp xếp',lambda:self.choose_images(id)),('Mở trong Dịch',lambda:self.open_translation(id)),('Mở kết quả',lambda:self.open_result(id))):
            action=menu.addAction(title);action.setEnabled(title!='Ảnh / sắp xếp' or self.model.can_mutate);action.triggered.connect(lambda checked=False,fn=callback:self.safe(fn))
        self.row_menu=menu;menu.popup(view.viewport().mapToGlobal(position))
    def choose_output(self):
        folder=QFileDialog.getExistingDirectory(self,'Thư mục project CapCut',self.output.text())
        if folder:
            self.output.setText(folder);self.config_changed()
            # Share the path preference, preserving manual CapCut groups/options.
            try:value=json.loads(self.repo.store.setting('capcut_workspace_v1','{"groups":[]}'))
            except ValueError:value={'groups':[]}
            value['output']=folder;self.repo.store.set_setting('capcut_workspace_v1',json.dumps(value))
    def validate_clicked(self):
        self.project_error_requested=True;self.check_project_name(focus=False,explicit=False)
        if not self.current:return
        self.queue_validation(force=True)
    def set_validation_status(self,text,details=None,role='secondary'):
        self.validation_badge.setText(text);self.validation_badge.setProperty('glassRole',role);self.validation_badge.update()
        if details is not None:self.validation_details=details
        self.validation_badge.setToolTip(self.validation_details+'\nNhấn để xem chi tiết.')
        if getattr(self,'validation_detail_text',None):self.validation_detail_text.setPlainText(self.validation_details)
    def show_validation_details(self):
        if getattr(self,'validation_dialog',None) and self.validation_dialog.isVisible():self.validation_dialog.raise_();self.validation_dialog.activateWindow();return
        dialog=QDialog(self);dialog.setWindowTitle('Chi tiết kiểm tra');dialog.resize(650,420);layout=QVBoxLayout(dialog)
        text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(self.validation_details);layout.addWidget(text)
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(dialog.reject);layout.addWidget(close)
        self.validation_dialog=dialog;self.validation_detail_text=text;dialog.finished.connect(lambda *_:setattr(self,'validation_detail_text',None));dialog.show()
    def queue_validation(self,force=False):
        self.validation_generation+=1;self.proof=None
        if self.import_busy:self.validation_again=True;self.validation_force=self.validation_force or force;return
        if not self.current or self.repo.active() or self.controller.busy:return
        verified=bool(self.repo.workset(self.current)['checkpoint'].get('validation_sections'))
        if not force and not verified:
            self.set_validation_status('Chưa kiểm tra','Thêm tài liệu, ghép ảnh và bấm Kiểm tra lại để xác minh đầu vào.');return
        self.validation_force=self.validation_force or force;self.validation_again=True
        self.set_validation_status('Đang kiểm tra','Đang xác minh đầu vào và cấu hình liên quan.');self.start.setEnabled(False)
        self.validation_timer.start();self.mark_dirty()
    def run_validation(self):
        if self.owner._closed or self.owner._exit_pending:return
        if self.import_busy:return
        if self.validation_busy:self.validation_timer.start();return
        if not self.current or not self.validation_again or self.controller.busy or self.repo.active():return
        self.validation_again=False;self.validation_busy=True;self.validate_button.setEnabled(False)
        id=self.current;generation=self.validation_generation;force=self.validation_force;self.validation_force=False
        def finished(proof):
            self.validation_busy=False
            if id==self.current and generation==self.validation_generation and proof['config_fingerprint']==fingerprint(self.repo.workset(id)['config']):self.validated(id,proof)
            if self.validation_again:self.validation_timer.start()
        def work():
            from ..automation.validation import ValidationSuperseded
            try:return self.controller.validate(id,force_config=force,cancelled=lambda:self.owner._closed or self.validation_generation!=generation or self.current!=id)
            except ValidationSuperseded:return {'validation_cancelled':True}
            except Exception as exc:return {'validation_error':str(exc),'config_fingerprint':''}
        def done(proof):
            if 'validation_cancelled' in proof:
                self.validation_busy=False
                if self.validation_again:self.validation_timer.start()
            elif 'validation_error' in proof:
                self.validation_busy=False
                if id==self.current and generation==self.validation_generation:self.proof=None;self.set_validation_status('⚠ Cần kiểm tra',proof['validation_error'],'warning')
                if self.validation_again:self.validation_timer.start()
            else:finished(proof)
        self.background(work,done)
    def validated(self,id,proof):
        if id!=self.current:return
        self.proof=proof
        faults=proof['errors']+[g['name']+': '+', '.join(g['errors']) for g in proof['groups'] if not g['valid']]
        bad=sum(not g['valid'] for g in proof['groups'])
        text='✓ Đầu vào hợp lệ' if proof['passed'] else f'⚠ {bad} nhóm cần kiểm tra' if bad else '⚠ Kiểm tra cấu hình'
        self.set_validation_status(text,'Đầu vào và cấu hình đã được xác minh.' if proof['passed'] else '\n'.join(faults),'success' if proof['passed'] else 'warning');self.refresh()
        self.check_project_name(focus=False,explicit=False)
    def check_project_name(self,focus=True,explicit=True):
        from ..automation.validation import project_name_error
        if explicit:self.project_error_requested=True
        if self.current and (error:=project_name_error(self.repo.workset(self.current)['config'])):
            message='Tên project CapCut: '+error if self.project_error_requested else ''
            self.project_warning.setText(message);self.project_warning.setToolTip(message)
            if focus:self.fields['project_name'].setFocus(Qt.OtherFocusReason)
            return False
        self.project_warning.setText('')
        return True
    def start_clicked(self):
        if self.controller.busy and self.controller.current==self.current:
            if self.controller.preparing.is_set() and not self.controller.paused.is_set():return
            if self.controller.paused.is_set():self.controller.resume()
            else:self.controller.pause()
            self.start.setText('Tiếp tục' if self.controller.paused.is_set() else 'Tạm dừng')
            self.refresh();return
        if not self.check_project_name():return
        if not self.current or not self.proof:return
        id=self.current;work=self.repo.workset(id);cfg=work['config']
        if not work['started']:
            groups=self.proof['groups'];text=f'{work["name"]} · {len(groups)} nhóm\n{sum(g["line_count"] for g in groups)} dòng voice / {sum(g["image_count"] for g in groups)} ảnh\n{cfg["provider"]} / {cfg["model"]} · {cfg["workers"]} worker tổng\n{cfg["source_lang"]} → {cfg["target_lang"]}\nKokoro {cfg["voice"]}, {cfg["speed"]}×, {cfg["variant"]}, WAV\nCapCut {cfg["capcut_mode"]} · {len(self.proof["parts"])} project\n'+ '\n'.join(p['name'] for p in self.proof['parts'])+'\n'+cfg['output']+'\nTất cả validation PASS. Bắt đầu sẽ gửi API dịch theo cấu hình.'
            if QMessageBox.question(self,'Xác nhận bộ công việc',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        self.controller.start(id);self.refresh()
    def sync_views(self,force=False,snapshot=None):
        snapshot=snapshot or self.snapshots.last
        if not snapshot:return
        ids=snapshot['scope_docs'] if self.controller.current else [g['document_id'] for g in snapshot['groups']]
        old=set(self.owner.workspace_ids);self.owner.workspace_ids=list(dict.fromkeys([*self.owner.workspace_ids,*ids]))
        page=self.owner.pages.currentIndex()
        updates=getattr(self.owner,'translation_updates',None)
        if updates:
            updates.set_automation_scope(snapshot)
            if page==0 and ids:
                scope_groups=snapshot['scope_groups']
                dirty_docs={g['document_id'] for g in scope_groups if g['id'] in self.dirty_groups}
                cached=(updates.last or {}).get('rows_by_document',{})
                changed=[r['id'] for d in dirty_docs for r in cached.get(d,())]
                full=force or not set(ids)<=old or any(d not in cached for d in dirty_docs)
                if not self.owner.doc_id and ids:self.owner.open_document(ids[0]);full=True
                # Idle Automation refreshes cannot replace a manual edit with
                # an unchanged cached text snapshot from an unrelated workset.
                if full or changed or self.controller.busy:updates.request(changed,full=full)
                self.dirty_groups.difference_update(g['id'] for g in scope_groups)
        if page==7 and hasattr(self.owner,'tts_page') and force:
            self.owner.tts_page.refresh_history();self.owner.tts_page.refresh()
        if page==8 and hasattr(self.owner,'capcut_page'):
            capcut=self.owner.capcut_page
            if not capcut.busy:capcut.set_busy(False)
            if snapshot['active']:capcut.export_button.setEnabled(False);capcut.export_button.setToolTip('CapCut đang thuộc Automation; dừng an toàn trước khi xuất thủ công.')
    def refresh(self,snapshot=None):
        if self.owner._closed or self.owner._exit_pending:return
        if snapshot is None:
            if self.controller.busy or self.import_busy or self.validation_busy:self.snapshots.request()
            else:self.snapshots.read_now()
            return
        self.sync_views(snapshot=snapshot)
        if self.owner.pages.currentIndex()!=9:return
        active=snapshot['active'];work=snapshot['work'];self._render_work=work;locked=bool(active==self.current or self.controller.busy and self.controller.current==self.current)
        self.model.can_mutate=not locked
        self.worksets.setEnabled(True);self.add.setEnabled(bool(work) and not locked);self.delete_button.setEnabled(bool(work) and not locked)
        self.up.setEnabled(bool(work) and not locked);self.down.setEnabled(bool(work) and not locked)
        self.stop.setEnabled(bool(active) and self.controller.busy and work and work['id']==active and work['state']=='running')
        running_control=bool(work and work['state']=='running' and work['config']['provider']=='kira' and work['config'].get('kira_recovery_version',2)>=4 and self.controller.busy and self.controller.current==self.current)
        can_start=bool(work) and not self.controller.busy and not self.import_busy and not self.pair_pending and self.proof is not None and self.proof.get('pending',True) and (self.proof['passed'] or work['started'] and not self.proof['errors'])
        self.start.setEnabled(running_control or can_start)
        self.start.setText(('Tiếp tục' if self.controller.paused.is_set() else 'Tạm dừng') if running_control else 'Tiếp tục' if work and work['started'] else 'Bắt đầu')
        if self.controller.busy and self.controller.current==self.current and self.controller.preparing.is_set():
            self.start.setText('Tiếp tục' if self.controller.paused.is_set() else 'Đang chuẩn bị…');self.start.setEnabled(self.controller.paused.is_set())
        self.validate_button.setEnabled(bool(work) and not locked and not self.validation_busy and not any(t.is_alive() for t in self.tasks))
        if self.controller.pending_terminal and not self.controller.busy:
            self.validate_button.setEnabled(self.current==self.controller.current)
            self.notice.setText('Chưa lưu được checkpoint cuối; giải phóng dung lượng và bấm Kiểm tra lại. Không tự gửi API.')
        self.config_frame.setEnabled(bool(work) and not locked);self.config_opacity.setOpacity(.8 if locked else 1)
        self.lock_note.setText('Cấu hình đã khóa trong khi đang chạy. Dừng an toàn để chỉnh sửa.' if locked else 'Giọng đọc và tốc độ giữ nguyên cho bộ đã chạy.' if work and work['started'] else '')
        self.lock_note.setVisible(bool(locked or work and work['started']))
        from ..automation.repository import IMMUTABLE
        for key in IMMUTABLE:
            if key in self.fields:self.fields[key].setEnabled(bool(work) and not locked and not work['started'])
        for key in ('source_lang','target_lang','provider','model'):self.fields[key].setEnabled(bool(work) and not locked and not work['started'])
        for control in self.fields.values():
            if isinstance(control,QComboBox):control.setToolTip(control.currentText())
        self.adapt_layout()
        self.output.setToolTip(self.output.text())
        if not work:self.model.update([]);self.adapt_layout();self.update_empty_state(0);self.summary.setText('Chưa chạy · 00:00');self.group_summary.setText('Hoàn tất 0/0 nhóm · Cần xử lý 0');self.preview.setRowCount(0);self.completion_ring.set_counts(0,0);return
        lanes=self.services.kokoro.config(work['config'])['workers'];self.kokoro_lanes.setText(f'Kokoro: {lanes} luồng · 1 nhóm mỗi lượt')
        groups=snapshot['groups']
        exporting={gid for part in work['checkpoint'].get('parts',[]) if part.get('state')=='exporting' for gid in part['group_ids']}
        for sequence,g in enumerate(groups,1):
            g['sequence']=sequence
            g['data']['display_state']='exporting' if g['id'] in exporting else g['data']['state']
            self.dirty_groups.discard(g['id'])
        query=self.search.text().casefold();mode=self.filter.currentData();filtered=[g for g in groups if query in (g['path']+' '+g['data'].get('image_folder','')).casefold() and (mode=='all' or mode=='active' and g['data']['state'] in ('translating','speaking','waiting_capcut') or mode=='needs_attention' and g['data']['state'] in ('needs_attention','stale') or mode==g['data']['state'])]
        self.model.update(filtered,total=len(groups));self.adapt_layout()
        self.update_empty_state(len(groups))
        completed=sum(g['data']['state']=='completed' for g in groups);errors=sum(g['data']['state']=='needs_attention' for g in groups)
        self.completion_ring.set_counts(completed,len(groups))
        elapsed=max(0,int((work['checkpoint'].get('ended') or time.time())-(work['checkpoint'].get('started') or time.time())))
        state=STATES.get(work['state'],work['state'])
        if self.controller.busy and self.controller.current==self.current and self.controller.preparing.is_set():state='Đang chuẩn bị…'
        if work['state']=='needs_attention':state='Hoàn tất nhưng cần xử lý'
        self.summary.setText(f'{state} · {elapsed//60:02}:{elapsed%60:02}')
        from .theme import colors
        summary_style=f'font-size:11px; color:{status_color(work["state"],colors(self)["background"]=="#1D1815")};'
        if self.summary.styleSheet()!=summary_style:self.summary.setStyleSheet(summary_style)
        self.group_summary.setText(f'Hoàn tất {completed}/{len(groups)} nhóm · Cần xử lý {errors}')
        parts=work['checkpoint'].get('parts',[])
        if not work['started'] and self.proof:parts=self.proof['parts']
        for stage,done,total in (('Dịch',sum(g['translated'] for g in groups),sum(g['translation_total'] for g in groups)),('Kokoro',sum(g['waves'] for g in groups),sum(g['data'].get('slot_count',0) for g in groups)),('CapCut',sum(p.get('state')=='completed' for p in parts),len(parts))):
            self.progress_labels[stage].setText(f'{done}/{total}');self.progress_labels[stage].setToolTip(f'{stage}: {done}/{total}');self.progress_bars[stage].setValue(round(done*100/total) if total else 0)
        if not self.preview.state()==QAbstractItemView.EditingState:self.preview_parts(groups)
    def on_finished(self,id,state):
        if self.owner._closed:return
        self.proof=None;self.sync_views();self.mark_dirty()
        if state=='stopped':self.notice.setText('Đã dừng an toàn và lưu checkpoint. Kiểm tra lại trước khi Tiếp tục.');return
        title='Automation hoàn tất' if state=='completed' else 'Automation cần xử lý'
        self.notice.setText(title+' · '+self.repo.workset(id)['name'])
        if QSystemTrayIcon.isSystemTrayAvailable():
            if self.owner.tray is None:self.owner.tray=QSystemTrayIcon(self.owner.windowIcon(),self.owner)
            self.owner.tray.show();self.owner.tray.showMessage(title,self.repo.workset(id)['name'],QSystemTrayIcon.Information if state=='completed' else QSystemTrayIcon.Warning,10000)
        if self.repo.store.setting('automation_sound','0')=='1':QApplication.beep()
    def dragEnterEvent(self,event):
        paths=[Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if not self.repo.active() and paths and all(p.is_file() and p.suffix.lower() in ('.txt','.docx') for p in paths):event.acceptProposedAction()
        else:event.ignore()
    def dropEvent(self,event):self.drop_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]);event.acceptProposedAction()
