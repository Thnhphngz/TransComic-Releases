"""CapCut export settings and the shared virtual media inspector."""
from PySide6.QtCore import Qt, QSize, QRect, QPoint, QPointF
from PySide6.QtGui import QPainter, QColor, QPolygonF,QPixmap,QIcon
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QLayout, QLineEdit, QTableView, QHeaderView, QSizePolicy, QMenu, QApplication,
    QScrollArea, QProgressBar, QGridLayout, QSpinBox,QToolButton)
from .controls import QComboBox
from .glass import GlassButton
from .capcut_media import PairModel, PairFilter, CapcutTable
from .theme import colors
from .capcut_actions import ActionPairModel,ActionTable,ImagePreview
from collections import OrderedDict


def build_page(page):
    layout=QVBoxLayout(page);layout.setContentsMargins(14,8,14,12);layout.setSpacing(4)
    page.title=QLabel('Xuất Project CapCut');page.title.setObjectName('section')
    page.totals=TotalsLabel();page.totals.setObjectName('capcutTotals');page.totals.setWordWrap(True);page.totals.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
    page.page_header=ResponsivePair(page.title,page.totals,(1,3),950)
    layout.addWidget(page.page_header)
    actions=ActionFlow();layout.addLayout(actions)
    for attr,text,fn in (
        ('add_button','+ Thêm nhóm',page.add_group),('scan_button','Kiểm tra tất cả',page.scan_all),
        ('clear_button','Xóa toàn bộ',page.clear_all)):
        button=GlassButton(text);setattr(page,attr,button);actions.addWidget(button);button.clicked.connect(fn)
    page.clear_button.setProperty('glassRole','warning');page.clear_button.setToolTip('Xóa các nhóm khỏi workspace; giữ nguyên media và project đã xuất')
    from .capcut_workspace import build_workspace
    build_workspace(page,layout)
    # The workspace scrolls independently; export actions stay on screen.
    page.settings_frame=QFrame();page.settings_frame.setObjectName('capcutExportPanel');outer_settings=QVBoxLayout(page.settings_frame)
    outer_settings.setContentsMargins(10,6,10,6);outer_settings.setSpacing(3)
    title_row=QHBoxLayout();title_row.addWidget(QLabel('Thiết lập xuất project CapCut'),1)
    page.settings_toggle=QToolButton();page.settings_toggle.setText('Thu gọn thiết lập');page.settings_toggle.setCheckable(True);title_row.addWidget(page.settings_toggle);outer_settings.addLayout(title_row)
    page.settings_manual=False;page.settings_toggle.clicked.connect(lambda: setattr(page,'settings_manual',True))
    page.settings_body=QWidget();page.settings_body.setObjectName('capcutSplitControls');outer_settings.addWidget(page.settings_body)
    page.settings_toggle.toggled.connect(lambda collapsed:page.settings_body.setVisible(not collapsed))
    page.settings_toggle.toggled.connect(lambda collapsed:page.settings_toggle.setText('Mở rộng thiết lập' if collapsed else 'Thu gọn thiết lập'))
    settings_box=QVBoxLayout(page.settings_body)
    settings_box.setContentsMargins(0,0,0,0);settings_box.setSpacing(3)
    row=QHBoxLayout();page.mode=QComboBox();page.mode.addItem('Xuất từng nhóm thành project riêng','separate');page.mode.addItem('Gộp tất cả thành một project','merged');page.mode.addItem('Chia đều thành nhiều project','split')
    page.mode.setCurrentIndex(max(0,page.mode.findData(page.manager.mode)));page.project_name=QLineEdit(page.manager.name)
    page.project_name.setPlaceholderText('Tên project chung');page.project_name.setToolTip('Tên chung cho chế độ gộp hoặc chia thành nhiều part')
    row.addWidget(page.mode);row.addWidget(page.project_name,1);settings_box.addLayout(row)
    page.split_controls=QWidget();page.split_controls.setObjectName('capcutSplitControls');split_box=QHBoxLayout(page.split_controls);split_box.setContentsMargins(0,0,0,0);split_box.setSpacing(6)
    split_info=QWidget();split_info.setObjectName('capcutSplitControls');split_info.setMaximumWidth(270);info_box=QVBoxLayout(split_info);info_box.setContentsMargins(0,0,0,0);info_box.setSpacing(2)
    row=QHBoxLayout();row.addWidget(QLabel('Số project muốn chia:'));page.part_count=QSpinBox();page.part_count.setRange(2,max(2,len(page.manager.groups)));page.part_count.setValue(min(page.manager.part_count,max(2,len(page.manager.groups))))
    row.addWidget(page.part_count);info_box.addLayout(row);page.split_notice=QLabel();page.split_notice.setWordWrap(True);info_box.addWidget(page.split_notice);split_box.addWidget(split_info)
    from .capcut_plan import SplitPlanModel,ProjectNameDelegate
    page.split_model=SplitPlanModel(page);page.split_preview=CapcutTable();page.split_preview.setObjectName('capcutSplitPreview');page.split_preview.setModel(page.split_model)
    page.split_preview.setItemDelegate(ProjectNameDelegate(page.split_preview))
    page.split_preview.verticalHeader().hide();page.split_preview.verticalHeader().setDefaultSectionSize(23);page.split_preview.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    page.split_preview.setSelectionBehavior(QTableView.SelectRows);page.split_preview.setMaximumHeight(136);split_box.addWidget(page.split_preview)
    page.split_preview.setContextMenuPolicy(Qt.CustomContextMenu);page.split_preview.customContextMenuRequested.connect(page.part_name_menu)
    page.split_preview.setToolTip('Các nhóm liên tiếp theo thứ tự hiện tại; rê chuột để xem tên nhóm. Tên trùng sẽ được thêm hậu tố khi xuất.')
    settings_box.addWidget(page.split_controls)
    row=QHBoxLayout();page.output=QLineEdit(page.manager.output);page.output.setPlaceholderText('Thư mục đầu ra');page.output.setToolTip('Thư mục đầu ra')
    page.output_browse=GlassButton('Chọn…');row.addWidget(page.output,1);row.addWidget(page.output_browse);settings_box.addLayout(row)
    page.output_browse.clicked.connect(page.choose_output)
    page.mode.currentIndexChanged.connect(page.save_options);page.project_name.editingFinished.connect(page.save_options);page.output.editingFinished.connect(page.save_options)
    page.project_name.textChanged.connect(page.update_split_controls);page.part_count.valueChanged.connect(page.save_options)
    row=QHBoxLayout();page.export_button=GlassButton('Xuất Project CapCut');page.export_button.setObjectName('primary')
    page.cancel_button=GlassButton('Hủy');page.open_button=GlassButton('Mở thư mục xuất')
    for button in (page.export_button,page.cancel_button,page.open_button):row.addWidget(button)
    outer_settings.addLayout(row);layout.addWidget(page.settings_frame)
    page.export_button.clicked.connect(page.export_projects);page.cancel_button.clicked.connect(page.request_stop);page.open_button.clicked.connect(page.open_output)
    page.bar=QProgressBar();page.bar.setRange(0,100);layout.addWidget(page.bar)
    page.status=QLabel('Thêm nhóm, kiểm tra thứ tự ảnh/voice rồi xuất.');page.status.setWordWrap(True);layout.addWidget(page.status)


class ActionFlow(QLayout):
    """Small action buttons wrap inside a card rather than widening the page."""
    def __init__(self, parent=None):
        super().__init__(parent);self.items=[];self.setContentsMargins(0,0,0,0);self.setSpacing(5)
    def addItem(self,item):self.items.append(item)
    def count(self):return len(self.items)
    def itemAt(self,i):return self.items[i] if 0<=i<len(self.items) else None
    def takeAt(self,i):return self.items.pop(i) if 0<=i<len(self.items) else None
    def expandingDirections(self):return Qt.Orientations()
    def hasHeightForWidth(self):return True
    def heightForWidth(self,width):return self.arrange(QRect(0,0,width,0),False)
    def setGeometry(self,rect):super().setGeometry(rect);self.arrange(rect,True)
    def sizeHint(self):return self.minimumSize()
    def minimumSize(self):
        size=QSize()
        for item in self.items:size=size.expandedTo(item.minimumSize())
        return size
    def arrange(self,rect,apply):
        x=rect.x();y=rect.y();height=0
        for item in self.items:
            if item.isEmpty():continue
            size=item.sizeHint();width=min(size.width(),rect.width())
            if x>rect.x() and x+width>rect.right()+1:x=rect.x();y+=height+self.spacing();height=0
            if apply:item.setGeometry(QRect(QPoint(x,y),QSize(width,size.height())))
            x+=width+self.spacing();height=max(height,size.height())
        return y-rect.y()+height


class PathLabel(QLabel):
    def __init__(self,parent=None):
        super().__init__(parent);self.full='';self.copy_text='';self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
    def set_path(self,text,copy_text=None):self.full=text;self.copy_text=text if copy_text is None else copy_text;self.setToolTip(text);self.elide()
    def elide(self):self.setText(self.fontMetrics().elidedText(self.full,Qt.ElideMiddle,max(1,self.width())))
    def resizeEvent(self,event):super().resizeEvent(event);self.elide()
    def contextMenuEvent(self,event):
        menu=QMenu(self);copy=menu.addAction('Sao chép đường dẫn đầy đủ')
        if menu.exec(event.globalPos())==copy:QApplication.clipboard().setText(self.copy_text)


class ResponsivePair(QWidget):
    """Two columns at usable widths, stacked without losing label content."""
    def __init__(self,left,right,weights=(1,1),breakpoint=900):
        super().__init__();self.left=left;self.right=right;self.weights=weights;self.breakpoint=breakpoint;self.stacked=None
        self.grid=QGridLayout(self);self.grid.setContentsMargins(0,0,0,0);self.grid.setHorizontalSpacing(12);self.grid.setVerticalSpacing(3)
        self.reflow()
    def reflow(self):
        threshold=self.breakpoint() if callable(self.breakpoint) else self.breakpoint
        stacked=self.width()<threshold
        if stacked==self.stacked:return
        self.stacked=stacked
        self.grid.removeWidget(self.left);self.grid.removeWidget(self.right)
        self.grid.addWidget(self.left,0,0,1,2 if stacked else 1)
        self.grid.addWidget(self.right,1 if stacked else 0,0 if stacked else 1,1,2 if stacked else 1)
        self.grid.setColumnStretch(0,self.weights[0]);self.grid.setColumnStretch(1,self.weights[1]);self.updateGeometry()
    def resizeEvent(self,event):super().resizeEvent(event);self.reflow()


class TotalsLabel(QLabel):
    """Palette-aware status icon; no font-dependent symbols or animation worker."""
    state='empty'
    def __init__(self):super().__init__();self.setContentsMargins(22,0,0,0);self.setMinimumWidth(0)
    def set_state(self,state):
        self.state=state;self.setProperty('scanState',state);self.style().unpolish(self);self.style().polish(self);self.update()
    def paintEvent(self,event):
        super().paintEvent(event)
        from PySide6.QtGui import QPen
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.setPen(QPen(self.palette().windowText().color(),1.5));p.setBrush(Qt.NoBrush)
        x=max(10,self.width()-self.fontMetrics().horizontalAdvance(self.text())-12);y=self.height()/2;p.drawEllipse(QPointF(x,y),7,7)
        if self.state=='ready':
            p.drawLine(QPointF(x-4,y),QPointF(x-1,y+3));p.drawLine(QPointF(x-1,y+3),QPointF(x+4,y-3))
        elif self.state=='review':
            p.drawLine(QPointF(x,y-4),QPointF(x,y+1));p.drawPoint(QPointF(x,y+4))
        elif self.state in ('scanning','pending'):
            p.drawLine(QPointF(x,y-4),QPointF(x,y));p.drawLine(QPointF(x,y),QPointF(x+3,y+2))
        else:p.drawLine(QPointF(x-3,y),QPointF(x+3,y))
        p.end()


class InspectorFilter(PairFilter):
    """Compact display only; source pair IDs and export ordering stay untouched."""
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if section==0 and orientation==Qt.Horizontal and role==Qt.DisplayRole:return 'STT'
        return super().headerData(section,orientation,role)
    def filterAcceptsColumn(self,column,parent):return column!=4
    def data(self,index,role=Qt.DisplayRole):
        if index.isValid() and index.column()==0 and role==Qt.DisplayRole:
            source=self.mapToSource(index)
            if source.isValid():return str(self.sourceModel().rows[source.row()][2].number)
        if index.isValid() and self.mapToSource(index).column()==6:
            source=self.mapToSource(index);pair=self.sourceModel().rows[source.row()][2]
            if role==Qt.DisplayRole:
                if not pair.images:return 'Thiếu ảnh'
                if not pair.audios:return 'Thiếu voice'
                if any(f.error for f in pair.images+pair.audios):return 'Lỗi file'
                return 'Cần kiểm tra' if pair.errors else 'Khớp'
            if role==Qt.ToolTipRole:return '; '.join(pair.errors) or 'Khớp theo vị trí'
            if role==Qt.ForegroundRole:
                c=colors(self.parent())
                return QColor(('#FF9999' if c['background']=='#1D1815' else '#B42323') if pair.errors else ('#71D7AB' if c['background']=='#1D1815' else '#16784C'))
        return super().data(index,role)


class GroupDetails(QWidget):
    def __init__(self,page,group_id,parent):
        super().__init__(parent);self.setObjectName('capcutInspector');self.page=page;self.group_id=group_id;self.scan=None
        self.selected_pair=None;self.preview_file=None;self.preview_pair_id=None
        self.audio_pair=None;self.playing_pair_id=None;self.pair_rows={};self.availability=OrderedDict();self.bad_previews=set()
        box=QVBoxLayout(self);box.setContentsMargins(0,6,0,0);box.setSpacing(5)
        row=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Tìm tên ảnh, voice hoặc STT…')
        self.errors=QComboBox();self.errors.addItems(['Tất cả file','Chỉ hàng lỗi'])
        row.addWidget(self.search,1);row.addWidget(self.errors);box.addLayout(row)
        self.notice=QLabel();self.notice.setWordWrap(True);box.addWidget(self.notice)
        self.model=ActionPairModel(self,page.thumbs);self.proxy=InspectorFilter(self);self.proxy.setSourceModel(self.model)
        self.table=ActionTable(self);self.table.setObjectName('capcutPairTable');self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectRows);self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setWordWrap(False);self.table.verticalHeader().hide();self.table.verticalHeader().setDefaultSectionSize(62)
        self.table.setIconSize(QSize(76,54));self.table.setMinimumHeight(80);self.table.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for col,width in enumerate((46,88,140,140,100,100,104)):self.table.setColumnWidth(col,width)
        header=self.table.horizontalHeader();header.setMinimumSectionSize(24)
        for col in (0,1,4,5,6):header.setSectionResizeMode(col,QHeaderView.Fixed)
        header.setSectionResizeMode(2,QHeaderView.Stretch);header.setSectionResizeMode(3,QHeaderView.Interactive)
        self.table.setTextElideMode(Qt.ElideMiddle);header.setStretchLastSection(False);box.addWidget(self.table,1)
        self.model.thumbnail_visible=self.thumbnail_visible
        self.preview=ImagePreview('Chọn một hàng để xem ảnh');self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(120);self.preview.hide();self.preview.setMinimumWidth(0);self.preview.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);box.addWidget(self.preview)
        self.player_layout=box
        self.search.textChanged.connect(self.apply_filter);self.errors.currentIndexChanged.connect(self.apply_filter)
        self.table.selectionModel().currentChanged.connect(self.select_pair)
        page.preview_cache.loaded.connect(self.preview_ready,Qt.QueuedConnection)
        self.sync_audio()

    def thumbnail_visible(self,index):
        if not self.isVisible():return False
        proxy=self.proxy.mapFromSource(index)
        if not proxy.isValid():return False
        rect=self.table.visualRect(proxy).intersected(self.table.viewport().rect())
        if rect.isEmpty():return False
        return True

    def load(self,scan):
        if scan is self.scan:return
        self.scan=scan;self.clear_preview();self.availability.clear();self.bad_previews.clear();self.table.hover=None;self.table.pressed=None
        self.pair_rows={pair.id:i for i,pair in enumerate(scan.rows)} if scan else {}
        self.model.load([scan] if scan else []);self.apply_filter()
        largest=max((pair.number for pair in scan.rows),default=0) if scan else 0
        metrics=self.table.fontMetrics();header_metrics=self.table.horizontalHeader().fontMetrics()
        self.table.setColumnWidth(0,max(metrics.horizontalAdvance('9'*len(str(largest)))+14,header_metrics.horizontalAdvance('STT')+12))
        messages=scan.errors if scan else ('Chưa kiểm tra nhóm.',)
        self.notice.setText('\n'.join(messages[:2]));self.notice.setToolTip('\n'.join(messages));self.notice.setVisible(bool(messages))

    def clear_preview(self):
        if self.page.active_details is self:self.page.stop_audio()
        self.selected_pair=None;self.preview_file=None;self.preview_pair_id=None;self.preview.clear();self.preview.hide()
        self.sync_audio()

    def pair_at(self,index):
        if not index.isValid():return None
        source=self.proxy.mapToSource(index)
        return self.model.rows[source.row()][2] if source.isValid() and 0<=source.row()<len(self.model.rows) else None

    def repaint_pair(self,id):
        row=self.pair_rows.get(id)
        if row is None:return
        index=self.proxy.mapFromSource(self.model.index(row,7))
        if index.isValid():self.table.viewport().update(self.table.visualRect(index))

    def action_available(self,pair,action,refresh=False):
        key=(pair.id,action)
        if refresh:self.availability.pop(key,None)
        if key not in self.availability:
            files=pair.audios if action==0 else pair.images
            self.availability[key]=bool(len(files)==1 and not files[0].error and files[0].unchanged())
            if action==1 and pair.id in self.bad_previews:self.availability[key]=False
            while len(self.availability)>256:self.availability.popitem(last=False)
        return self.availability[key]

    def sync_audio(self,*_):
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtCore import QUrl
        from ..capcut.exporter import reference
        shared=self.page.player;pair=self.audio_pair;old=self.playing_pair_id
        playing=bool(shared and pair and self.page.active_details is self and shared.player.playbackState()==QMediaPlayer.PlayingState and shared.player.source()==QUrl.fromLocalFile(reference(pair.audios[0].path)))
        self.playing_pair_id=pair.id if playing else None
        if old!=self.playing_pair_id:
            for id in (old,self.playing_pair_id):
                if id:
                    self.repaint_pair(id);row=self.pair_rows.get(id)
                    if row is not None:self.model.dataChanged.emit(self.model.index(row,7),self.model.index(row,7),[Qt.AccessibleTextRole])

    def audio_error(self,*_):self.page.stop_audio()

    def invoke_action(self,index,action):
        pair=self.pair_at(index)
        if pair is None:return
        if action==0 and self.playing_pair_id==pair.id:self.page.stop_audio();return
        if not self.action_available(pair,action,refresh=True):
            self.repaint_pair(pair.id);return
        if action==0:self.page.play_audio(self,pair);return
        self.preview_file=pair.images[0];self.preview_pair_id=pair.id;self.preview.clear();self.preview.show()
        pixmap=self.page.preview_cache.get(self.preview_file)
        if pixmap is not None:self.display_preview(pixmap)

    def apply_filter(self,*_):
        self.clear_preview();self.proxy.configure(self.group_id,self.errors.currentIndex()==1,self.search.text())

    def select_pair(self,index,*_):
        self.page.stop_audio();self.clear_preview()
        if not index.isValid():return
        source=self.proxy.mapToSource(index);pair=self.model.rows[source.row()][2];self.selected_pair=pair
        self.sync_audio()
        if pair.images and not pair.images[0].error:
            self.preview_file=pair.images[0];self.preview_pair_id=pair.id;pixmap=self.page.preview_cache.get(self.preview_file)
            if pixmap is not None:self.display_preview(pixmap)
        self.preview.setToolTip('; '.join(pair.errors) or f'#{pair.number} · {pair.duration_us/1e6:.6f} giây')

    def display_preview(self,pixmap):
        if pixmap.isNull():
            self.preview.setText('Không thể đọc ảnh; hãy kiểm tra lại nhóm.')
            if self.preview_pair_id:
                self.bad_previews.add(self.preview_pair_id)
                self.availability[(self.preview_pair_id,1)]=False;self.repaint_pair(self.preview_pair_id)
            return
        self.preview.setPixmap(pixmap.scaled(max(1,self.preview.width()),120,Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def preview_ready(self,key,*_):
        f=self.preview_file
        if self.isVisible() and f and key==(f.path,f.size,f.mtime_ns):
            pixmap=self.page.preview_cache.cache.get(key)
            if pixmap is not None:self.display_preview(pixmap)

