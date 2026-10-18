"""Painted row controls: no per-row widgets, players or persistent editors."""
from collections import OrderedDict
from PySide6.QtCore import Qt,QRect,QRectF,QEvent,QPointF,QSize,QItemSelectionModel,QSignalBlocker
from PySide6.QtGui import QPainter,QPen,QColor,QPolygonF,QLinearGradient
from PySide6.QtWidgets import QToolTip,QStyle,QLabel,QToolButton
from .capcut_media import PairModel,RowDelegate,CapcutTable
from .theme import colors


def glass_surface(painter,bounds,c,enabled=True,hover=False,pressed=False,selected=False,focus=False):
    """The secondary/checked GlassButton recipe, without a widget or blur effect."""
    dark=c['background']=='#1D1815';pressed=pressed and enabled;light=float(hover and enabled)
    field=QColor(c['accent'] if selected and enabled else c['field']);edge=QColor(c['accent'] if selected and enabled else c['border'])
    ink=QColor(('#30231D' if dark else '#FFFCF9') if selected and enabled else c['ink'] if enabled else c['muted'])
    rect=QRectF(bounds).adjusted(1,1 if pressed else 0,-1,-2 if pressed else -3);radius=min(10,rect.height()/2)
    painter.setPen(Qt.NoPen);painter.setBrush(QColor(0,0,0,28 if dark else 18));painter.drawRoundedRect(rect.translated(0,2),radius,radius)
    gradient=QLinearGradient(rect.topLeft(),rect.bottomLeft())
    gradient.setColorAt(0,field.lighter(112+int(light*6)) if dark else field.lighter(105+int(light*3)))
    gradient.setColorAt(.5,field);gradient.setColorAt(1,field.darker(112 if dark else 106))
    painter.setBrush(field if selected and enabled else gradient);painter.setPen(QPen(edge,1));painter.drawRoundedRect(rect,radius,radius)
    gloss=QLinearGradient(rect.topLeft(),rect.bottomLeft())
    gloss.setColorAt(0,QColor(255,244,227,12 if not enabled else 38 if dark else 125));gloss.setColorAt(.35,QColor(255,244,227,0));gloss.setColorAt(1,QColor(255,244,227,0))
    painter.setPen(Qt.NoPen);painter.setBrush(gloss);painter.drawRoundedRect(rect.adjusted(1,1,-1,-1),radius-1,radius-1)
    painter.setPen(QPen(QColor(255,242,221,35 if dark else 155),1));painter.drawLine(rect.topLeft()+QPointF(radius,1),rect.topRight()+QPointF(-radius,1))
    if focus:
        painter.setPen(QPen(QColor(c['accent']),1.5));painter.drawLine(rect.bottomLeft()+QPointF(radius,0),rect.bottomRight()+QPointF(-radius,0))
    return rect,ink


class ActionPairModel(PairModel):
    def columnCount(self,parent=None):return 8
    def headerData(self,n,orientation,role=Qt.DisplayRole):
        if n==7 and orientation==Qt.Horizontal and role==Qt.DisplayRole:return 'Thao tác'
        return super().headerData(n,orientation,role)
    def data(self,index,role=Qt.DisplayRole):
        if index.isValid() and index.column()==7:
            if role==Qt.UserRole and 0<=index.row()<len(self.rows):return self.rows[index.row()][2].id
            if role==Qt.AccessibleTextRole and 0<=index.row()<len(self.rows):
                pair=self.rows[index.row()][2]
                return ('Dừng voice' if self.parent().playing_pair_id==pair.id else 'Phát voice')+'; Xem ảnh'
            if role==Qt.AccessibleDescriptionRole:return 'Trái/phải chọn thao tác, Enter hoặc Space kích hoạt.'
            return None
        return super().data(index,role)


def button_rects(rect):
    width=max(24,min(40,(rect.width()-14)//2));height=min(30,rect.height()-8)
    x=rect.center().x()-width-3;y=rect.center().y()-height//2
    return QRect(x,y,width,height),QRect(x+width+6,y,width,height)


class ActionDelegate(RowDelegate):
    def paint(self,painter,option,index):
        if index.column()!=6:return super().paint(painter,option,index)
        table=self.parent();details=table.details;pair=details.pair_at(index)
        if pair is None:return
        # Keep selection/background rendering, without text underneath the controls.
        super().paint(painter,option,index)
        c=colors(table);painter.save();painter.setRenderHint(QPainter.Antialiasing)
        for action,rect in enumerate(button_rects(option.rect)):
            active=action==0 and details.playing_pair_id==pair.id
            enabled=active or details.action_available(pair,action)
            hover=table.hover==(pair.id,action);pressed=table.pressed==(pair.id,action) and hover
            focus=table.hasFocus() and table.keyboard_focus and table.currentIndex()==index and table.keyboard_action==action
            surface,ink=glass_surface(painter,rect,c,enabled,hover,pressed,active,focus)
            painter.setPen(QPen(ink,1.5));painter.setBrush(Qt.NoBrush)
            x=surface.center().x();y=surface.center().y()
            if action==0:
                painter.setBrush(ink);painter.setPen(Qt.NoPen)
                if active:painter.drawRect(QRectF(x-5,y-5,10,10))
                else:painter.drawPolygon(QPolygonF([QPointF(x-4,y-6),QPointF(x+6,y),QPointF(x-4,y+6)]))
            else:
                painter.drawRoundedRect(QRectF(x-7,y-6,14,12),2,2)
                painter.drawEllipse(QPointF(x+3,y-2),1.2,1.2)
                painter.drawPolyline(QPolygonF([QPointF(x-6,y+4),QPointF(x-2,y),QPointF(x+1,y+3),QPointF(x+3,y+1),QPointF(x+6,y+4)]))
        painter.restore()


class ActionTable(CapcutTable):
    def __init__(self,details):
        super().__init__();self.details=details;self.hover=None;self.pressed=None;self.keyboard_action=0
        self.setItemDelegate(ActionDelegate(self));self.setMouseTracking(True)
        self.setAccessibleName('Ảnh và voice; cột Thao tác: trái/phải chọn Phát hoặc Xem ảnh, Enter/Space kích hoạt')
    def focusInEvent(self,event):
        # Window activation can precede mouse focus. Neither event should pick
        # a row before our action hit handler runs; keyboard navigation still
        # uses Qt's normal focus behavior.
        selection=self.selectionModel()
        if selection is None or event.reason() in (Qt.TabFocusReason,Qt.BacktabFocusReason,Qt.ShortcutFocusReason):
            return super().focusInEvent(event)
        current=self.currentIndex();saved=selection.selection()
        with QSignalBlocker(selection):
            super().focusInEvent(event)
            selection.select(saved,QItemSelectionModel.ClearAndSelect)
            selection.setCurrentIndex(current,QItemSelectionModel.NoUpdate)
    def hit(self,pos):
        index=self.indexAt(pos)
        if not index.isValid() or index.column()!=6:return None
        for action,rect in enumerate(button_rects(self.visualRect(index))):
            if rect.contains(pos):return index,action
    def update_control(self,key):
        if key:self.details.repaint_pair(key[0])
    def mouseMoveEvent(self,event):
        hit=self.hit(event.position().toPoint());key=(hit[0].data(Qt.UserRole),hit[1]) if hit else None
        if key!=self.hover:
            old=self.hover;self.hover=key;self.update_control(old);self.update_control(key)
        self.viewport().setCursor(Qt.PointingHandCursor if key else Qt.ArrowCursor)
        super().mouseMoveEvent(event)
    def mousePressEvent(self,event):
        hit=self.hit(event.position().toPoint())
        if event.button()==Qt.LeftButton and hit:
            self.keyboard_focus=False;self.setFocus(Qt.MouseFocusReason)
            self.pressed=(hit[0].data(Qt.UserRole),hit[1]);self.hover=self.pressed;self.update_control(self.pressed);event.accept();return
        super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.pressed:
            old=self.pressed;self.pressed=None;hit=self.hit(event.position().toPoint());self.update_control(old)
            if hit and old==(hit[0].data(Qt.UserRole),hit[1]):self.details.invoke_action(hit[0],hit[1])
            event.accept();return
        super().mouseReleaseEvent(event)
    def mouseDoubleClickEvent(self,event):
        if self.hit(event.position().toPoint()):event.accept();return
        super().mouseDoubleClickEvent(event)
    def leaveEvent(self,event):
        old=self.hover;self.hover=None;self.update_control(old);super().leaveEvent(event)
    def keyPressEvent(self,event):
        index=self.currentIndex()
        if index.isValid() and index.column()==6:
            self.keyboard_focus=True
            if event.key() in (Qt.Key_Left,Qt.Key_Right):
                self.keyboard_action=0 if event.key()==Qt.Key_Left else 1;self.viewport().update(self.visualRect(index));event.accept();return
            if event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
                self.details.invoke_action(index,self.keyboard_action);event.accept();return
        super().keyPressEvent(event)
    def viewportEvent(self,event):
        if event.type()==QEvent.ToolTip:
            hit=self.hit(event.pos())
            if hit:
                pair=self.details.pair_at(hit[0]);action=hit[1]
                text=('Dừng voice' if self.details.playing_pair_id==pair.id else 'Phát voice') if action==0 else 'Xem ảnh'
                if not self.details.action_available(pair,action):text+=' · File thiếu, lỗi hoặc đã thay đổi; kiểm tra lại nhóm.'
                QToolTip.showText(event.globalPos(),text,self.viewport(),self.visualRect(hit[0]));return True
        return super().viewportEvent(event)


class ImagePreview(QLabel):
    def __init__(self,text):
        super().__init__(text);self.close_button=QToolButton(self);self.close_button.setText('×')
        self.close_button.setToolTip('Đóng xem trước ảnh');self.close_button.setAccessibleName('Đóng xem trước ảnh')
        self.close_button.setFixedSize(26,26);self.close_button.clicked.connect(self.hide)
    def resizeEvent(self,event):
        super().resizeEvent(event);self.close_button.move(max(0,self.width()-28),2)
