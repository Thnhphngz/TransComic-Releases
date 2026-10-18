"""One virtual group list and one shared media inspector, keyed by group ID."""
from PySide6.QtCore import Qt,QAbstractListModel,QModelIndex,QSortFilterProxyModel,QSize,QRect
from PySide6.QtGui import QPainter,QColor,QPen,QFont
from PySide6.QtWidgets import (QWidget,QFrame,QVBoxLayout,QHBoxLayout,QListView,
    QLineEdit,QLabel,QSplitter,QStackedWidget,QStyle,QStyledItemDelegate,QSizePolicy)
from .theme import colors
from .glass import GlassButton
from .controls import QComboBox


class GroupListModel(QAbstractListModel):
    def __init__(self,page):super().__init__(page);self.page=page;self.items=[]
    def load(self):
        self.beginResetModel()
        self.items=[]
        for order,g in enumerate(self.page.manager.groups):
            scan=self.page.scans.get(g.id)
            directory_issue=scan and any(message.startswith(('Ảnh:', 'Audio:')) for message in scan.errors)
            status=('Đang quét' if self.page.busy and self.page.operation=='scan' else
                ('Chưa kiểm tra' if scan is None else ('Sẵn sàng' if scan.valid else ('Lỗi thư mục' if directory_issue else 'Cần kiểm tra'))))
            counts=(f'{sum(len(p.images) for p in scan.rows)} ảnh · {sum(len(p.audios) for p in scan.rows)} voice · {scan.matched} cặp' if scan else 'Chưa có kết quả kiểm tra')
            self.items.append((g,f'{order+1:02}. {g.name}',counts,status))
        self.endResetModel()
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.items)
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.items):return None
        g,title,counts,status=self.items[index.row()]
        if role==Qt.DisplayRole:return title
        if role==Qt.UserRole:return g.id
        if role==Qt.UserRole+1:return (title,counts,status)
        if role==Qt.ToolTipRole:return f'{title}\nẢnh: {g.image_dir}\nVoice: {g.audio_dir}\n{counts} · {status}'
        if role==Qt.UserRole+2:return g.name+' '+g.image_dir+' '+g.audio_dir


class GroupFilter(QSortFilterProxyModel):
    def __init__(self,parent):
        super().__init__(parent);self.setFilterRole(Qt.UserRole+2);self.setFilterCaseSensitivity(Qt.CaseInsensitive)


class GroupDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):return QSize(220,86)
    def paint(self,painter,option,index):
        c=colors(option.widget);selected=bool(option.state&QStyle.State_Selected)
        painter.save();painter.setRenderHint(QPainter.Antialiasing)
        rect=option.rect.adjusted(3,3,-3,-3)
        painter.setPen(QPen(QColor(c['accent'] if selected else c['border']),1.5 if selected else 1))
        painter.setBrush(QColor(c['field'] if selected else c['panel']));painter.drawRoundedRect(rect,10,10)
        title,counts,status=index.data(Qt.UserRole+1)
        text_rect=rect.adjusted(10,5,-10,-5);font=option.font;font.setPixelSize(15);font.setWeight(QFont.DemiBold);painter.setFont(font);painter.setPen(QColor(c['ink']))
        painter.drawText(QRect(text_rect.x(),text_rect.y(),text_rect.width(),25),Qt.AlignVCenter,painter.fontMetrics().elidedText(title,Qt.ElideRight,text_rect.width()))
        font.setPixelSize(12);font.setWeight(QFont.Normal);painter.setFont(font);painter.setPen(QColor(c['muted']))
        painter.drawText(QRect(text_rect.x(),text_rect.y()+27,text_rect.width(),20),Qt.AlignVCenter,painter.fontMetrics().elidedText(counts,Qt.ElideRight,text_rect.width()))
        color=('#71D7AB' if c['background']=='#1D1815' else '#16784C') if status=='Sẵn sàng' else (('#FF9999' if c['background']=='#1D1815' else '#B42323') if status in ('Cần kiểm tra','Lỗi thư mục') else c['muted'])
        painter.setPen(QColor(color));painter.drawText(QRect(text_rect.x(),text_rect.y()+48,text_rect.width(),20),Qt.AlignVCenter,status);painter.restore()


def build_workspace(page,layout):
    from .capcut_cards import PathLabel,ActionFlow,GroupDetails,ResponsivePair
    page.workspace=QSplitter(Qt.Horizontal);page.workspace.setObjectName('capcutWorkspace');page.workspace.setChildrenCollapsible(False);page.workspace.setHandleWidth(7)
    left=QFrame();left.setObjectName('capcutWorkspacePanel');left.setMinimumWidth(220)
    box=QVBoxLayout(left);box.setContentsMargins(6,6,6,6);box.setSpacing(4)
    page.group_count=QLabel('Danh sách nhóm (0)');page.group_count.setObjectName('section');box.addWidget(page.group_count)
    page.group_search=QLineEdit();page.group_search.setPlaceholderText('Tìm nhóm…');page.group_search.setClearButtonEnabled(True);box.addWidget(page.group_search)
    page.group_model=GroupListModel(page);page.group_proxy=GroupFilter(page);page.group_proxy.setSourceModel(page.group_model)
    page.groups=QListView();page.groups.setObjectName('capcutGroupList');page.groups.setModel(page.group_proxy);page.groups.setItemDelegate(GroupDelegate(page.groups));page.groups.setUniformItemSizes(True)
    page.groups.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);page.groups.setMinimumWidth(0);box.addWidget(page.groups,1)
    page.list_empty=QLabel('Chưa có nhóm nào. Nhấn Thêm nhóm để bắt đầu.');page.list_empty.setWordWrap(True);box.addWidget(page.list_empty)
    right=QFrame();right.setObjectName('capcutWorkspacePanel');right.setMinimumWidth(310)
    right_box=QVBoxLayout(right);right_box.setContentsMargins(8,6,8,6);right_box.setSpacing(4)
    page.inspector=QStackedWidget();page.inspector.setObjectName('capcutInspector');right_box.addWidget(page.inspector)
    page.inspector_empty=QLabel('Chọn một nhóm bên trái để xem ảnh và voice.');page.inspector_empty.setWordWrap(True);page.inspector_empty.setAlignment(Qt.AlignCenter);page.inspector.addWidget(page.inspector_empty)
    page.inspector_body=QWidget();page.inspector_body.setObjectName('capcutInspector');body=QVBoxLayout(page.inspector_body);body.setContentsMargins(0,0,0,0);body.setSpacing(3)
    page.group_heading=PathLabel();page.group_heading.setObjectName('capcutGroupName')
    actions_widget=QWidget();actions_widget.setObjectName('capcutSplitControls');actions=ActionFlow(actions_widget)
    page.group_sort=QComboBox();page.group_sort.addItem('Theo tên file','name');page.group_sort.addItem('Theo ngày tạo','created');actions.addWidget(page.group_sort)
    for attr,label,fn in [('group_edit','Sửa',lambda:page.edit_group(page.selected_group_id)),('group_up','↑ Lên',lambda:page.move_group(page.selected_group_id,-1)),('group_down','↓ Xuống',lambda:page.move_group(page.selected_group_id,1)),('group_remove','Xóa',lambda:page.remove_group(page.selected_group_id))]:
        button=GlassButton(label);setattr(page,attr,button);actions.addWidget(button);button.clicked.connect(fn)
    title_actions=ResponsivePair(page.group_heading,actions_widget,(1,4),520)
    page.group_image_path=PathLabel();page.group_audio_path=PathLabel()
    for path in (page.group_image_path,page.group_audio_path):path.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
    paths=ResponsivePair(page.group_image_path,page.group_audio_path,(1,1),300);paths.setObjectName('capcutSplitControls')
    page.group_header=ResponsivePair(title_actions,paths,(3,2),1000);body.addWidget(page.group_header)
    page.group_summary=QLabel();page.group_summary.setObjectName('capcutStatus');page.group_summary.setWordWrap(True);body.addWidget(page.group_summary)
    page.details=GroupDetails(page,None,page.inspector_body);body.addWidget(page.details,1)
    page.inspector.addWidget(page.inspector_body);page.workspace.addWidget(left);page.workspace.addWidget(right)
    page.workspace.setStretchFactor(0,0);page.workspace.setStretchFactor(1,1);page.workspace.setSizes([285,800]);layout.addWidget(page.workspace,1)
    page.group_search.textChanged.connect(page.filter_groups)
    page.groups.selectionModel().currentChanged.connect(page.group_current_changed)
    page.group_sort.currentIndexChanged.connect(lambda:page.change_sort(page.selected_group_id,page.group_sort.currentData()) if page.selected_group_id else None)


def refresh_groups(page,reload=True):
    if reload:
        page.groups.selectionModel().blockSignals(True);page.group_model.load();page.groups.selectionModel().blockSignals(False)
    count=page.group_proxy.rowCount();page.group_count.setText(f'Danh sách nhóm ({len(page.manager.groups)})')
    page.list_empty.setVisible(count==0)
    page.list_empty.setText('Không có nhóm phù hợp.' if page.manager.groups else 'Chưa có nhóm nào. Nhấn Thêm nhóm để bắt đầu.')
    if page.selected_group_id and any(g.id==page.selected_group_id for g in page.manager.groups):page.show_group(page.selected_group_id,scroll=False)
    else:page.select_group(None)


def select_group(page,id):
    group=next((g for g in page.manager.groups if g.id==id),None)
    if not group:
        selection=page.groups.selectionModel();blocked=selection.blockSignals(True)
        page.groups.clearSelection();page.groups.setCurrentIndex(QModelIndex());selection.blockSignals(blocked)
        page.stop_audio();page.selected_group_id=None;page.details.group_id=None;page.details.load(None);page.details.search.clear();page.details.errors.setCurrentIndex(0)
        page.inspector_empty.setText('Chọn một nhóm bên trái để xem ảnh và voice.' if page.manager.groups else 'Chưa có nhóm nào. Nhấn Thêm nhóm để bắt đầu.')
        page.inspector.setCurrentWidget(page.inspector_empty);return
    changed=id!=page.selected_group_id
    if changed:
        page.stop_audio();page.details.load(None);page.details.search.clear();page.details.errors.setCurrentIndex(0)
    page.selected_group_id=id;page.details.group_id=id
    order=next(i for i,g in enumerate(page.manager.groups) if g.id==id)
    page.group_heading.set_path(f'{order+1:02}. {group.name}');page.group_image_path.set_path('Ảnh: '+group.image_dir,copy_text=group.image_dir);page.group_audio_path.set_path('Voice: '+group.audio_dir,copy_text=group.audio_dir)
    page.group_sort.blockSignals(True);page.group_sort.setCurrentIndex(1 if group.image_sort=='created' else 0);page.group_sort.blockSignals(False)
    scan=page.scans.get(id);page.details.load(scan)
    state='pending';text='Đang quét' if page.busy and page.operation=='scan' else 'Chưa kiểm tra'
    if scan:
        state='ready' if scan.valid else 'review';text=f'{sum(len(p.images) for p in scan.rows)} ảnh · {sum(len(p.audios) for p in scan.rows)} voice · {scan.matched} cặp hợp lệ · '+('Sẵn sàng' if scan.valid else 'Cần kiểm tra')
    page.group_summary.setText(text);page.group_summary.setToolTip('\n'.join(scan.errors) if scan else text);page.group_summary.setProperty('scanState',state)
    page.group_summary.style().unpolish(page.group_summary);page.group_summary.style().polish(page.group_summary)
    locked=page.busy
    page.group_up.setEnabled(not locked and order>0);page.group_down.setEnabled(not locked and order<len(page.manager.groups)-1)
    for control in (page.group_edit,page.group_remove,page.group_sort):control.setEnabled(not locked)
    page.inspector.setCurrentWidget(page.inspector_body)
