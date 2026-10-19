"""Small painted Automation visuals; no scheduler or persistence behavior."""
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QLinearGradient,QPainterPath,QRegion
from PySide6.QtWidgets import QWidget,QFrame,QLineEdit,QStyleOptionFrame,QStyle
from .theme import colors


STAGE_COLORS=('#39b968','#4bace5','#ac7ee1')


class RoundedTableFrame(QFrame):
    """One rounded boundary around adjacent table views, including their headers."""
    def __init__(self):
        super().__init__();self.setObjectName('automationTableFrame')
        self.setStyleSheet('QFrame#automationTableFrame, QWidget#automationTableContent {background:transparent; border:0;}')
        self.content=QWidget(self);self.content.setObjectName('automationTableContent')
    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.content.setGeometry(self.rect().adjusted(2,2,-2,-2))
        path=QPainterPath();path.addRoundedRect(QRectF(self.content.rect()),10,10)
        self.content.setMask(QRegion(path.toFillPolygon().toPolygon()))
    def paintEvent(self,event):
        c=colors(self);p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(c['panel']));p.setPen(QPen(QColor(c['border']),1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),12,12);p.end()


class ElidingPathEdit(QLineEdit):
    """Keep the full editable path; show its ends while the editor is unfocused."""
    def __init__(self):
        super().__init__();self.textChanged.connect(self.setToolTip)
    def paintEvent(self,event):
        if self.hasFocus() or not self.text():return super().paintEvent(event)
        option=QStyleOptionFrame();self.initStyleOption(option);p=QPainter(self)
        self.style().drawPrimitive(QStyle.PE_PanelLineEdit,option,p,self)
        rect=self.style().subElementRect(QStyle.SE_LineEditContents,option,self).adjusted(6,0,-6,0)
        p.setPen(QColor(colors(self)['ink' if self.isEnabled() else 'muted']))
        p.drawText(rect,Qt.AlignVCenter|Qt.AlignLeft,self.fontMetrics().elidedText(self.text(),Qt.ElideMiddle,rect.width()));p.end()


class AutomationCard(QFrame):
    def __init__(self):
        super().__init__();self.setObjectName('automationCard')
        self.setStyleSheet('QFrame#automationCard { background:transparent; border:0; }')
    def paintEvent(self,event):
        c=colors(self);p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        rect=QRectF(self.rect()).adjusted(.5,.5,-.5,-.5);gradient=QLinearGradient(rect.topLeft(),rect.bottomLeft())
        gradient.setColorAt(0,QColor(c['field']));gradient.setColorAt(.25,QColor(c['panel']));gradient.setColorAt(1,QColor(c['panel']))
        p.setBrush(gradient);p.setPen(QPen(QColor(c['border']),1));p.drawRoundedRect(rect,14,14);p.end()


def status_color(state,dark=True):
    if state in ('needs_attention','stale'):return '#ef8181' if dark else '#b92b35'
    if state=='completed':return '#6fd8a2' if dark else '#197944'
    if state in ('speaking','translating','running'):return '#6dc7ef' if dark else '#126c98'
    if state in ('waiting_capcut','exporting'):return '#c3a1ed' if dark else '#7848a7'
    return '#e2b96b' if dark else '#94620c'


class CompletionRing(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.done=0;self.total=0;self.setFixedSize(88,94)
        self.setAccessibleName('Số nhóm hoàn tất')
    def set_counts(self,done,total):
        self.done=done;self.total=total;self.setAccessibleDescription(f'{done}/{total} nhóm hoàn tất');self.update()
    def paintEvent(self,event):
        c=colors(self);p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.width()/108,self.width()/108)
        circle=QRectF(7,8,94,94);pen=QPen(QColor(c['border']),7);pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen);p.drawArc(circle,90*16,-360*16)
        if self.total and self.done:
            pen.setColor(QColor(STAGE_COLORS[0]));p.setPen(pen);p.drawArc(circle,90*16,-round(360*16*self.done/self.total))
        p.setPen(QColor(c['ink']));font=QFont(self.font());font.setPointSizeF(9);p.setFont(font)
        p.drawText(QRectF(10,29,88,19),Qt.AlignCenter,'Hoàn tất')
        font.setPointSizeF(17);font.setBold(True);p.setFont(font);p.drawText(QRectF(5,49,98,30),Qt.AlignCenter,f'{self.done}/{self.total}')
        font.setPointSizeF(9);font.setBold(False);p.setFont(font);p.setPen(QColor(c['muted']));p.drawText(QRectF(10,79,88,17),Qt.AlignCenter,'nhóm');p.end()
