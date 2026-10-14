"""Shared wheel-safe selection controls."""
from PySide6.QtWidgets import QComboBox as QtComboBox, QSpinBox as QtSpinBox, QDoubleSpinBox as QtDoubleSpinBox, QAbstractScrollArea, QApplication
from PySide6.QtGui import QWheelEvent, QColor, QPalette, QLinearGradient, QPen, QPainter
from PySide6.QtCore import QPointF, Qt, QSize, QRectF
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyle, QAbstractItemView
from .theme import colors, DARK


class GlassComboDelegate(QStyledItemDelegate):
    def __init__(self, combo):
        super().__init__(combo)
        self.combo = combo

    def sizeHint(self, option, index):
        return QSize(option.fontMetrics.horizontalAdvance(str(index.data() or '')) + 44,
                     option.fontMetrics.height() + 14)

    def paint(self, painter, option, index):
        c = colors(self.combo)
        selected = index.row() == self.combo.currentIndex()
        hover = bool(option.state & (QStyle.State_MouseOver | QStyle.State_Selected))
        enabled = bool(index.flags() & Qt.ItemIsEnabled)
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 1, -2, -1)
        if selected or hover:
            base = QColor(c['accent'] if selected else c['field'])
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0, base.lighter(108)); gradient.setColorAt(1, base)
            painter.setBrush(gradient); painter.setPen(QPen(QColor(c['border']), 1))
            painter.drawRoundedRect(rect, 7, 7)
        ink = c['muted'] if not enabled else ('#30231D' if c is DARK else '#FFFCF9') if selected else c['ink']
        painter.setPen(QColor(ink)); painter.setFont(option.font)
        text_rect = option.rect.adjusted(28, 0, -10, 0)
        text = option.fontMetrics.elidedText(str(index.data() or ''), Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        if selected:
            painter.drawText(option.rect.adjusted(7, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, '✓')
        painter.restore()


def install_combo_popup(combo):
    if not combo.property('glassPopupInstalled'):
        combo.setProperty('glassPopupInstalled', True)
        view = QListView(combo); view.setObjectName('glassPopup')
        view.setMouseTracking(True); view.setUniformItemSizes(True)
        view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        combo.setView(view); combo.setItemDelegate(GlassComboDelegate(combo))
        combo.setMaxVisibleItems(11)
    c = colors(combo); palette = combo.view().palette()
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        palette.setColor(group, QPalette.Base, QColor(c['panel']))
        palette.setColor(group, QPalette.Text, QColor(c['ink'] if group != QPalette.Disabled else c['muted']))
        palette.setColor(group, QPalette.Highlight, QColor(c['accent']))
        palette.setColor(group, QPalette.HighlightedText, QColor('#30231D' if c is DARK else '#FFFCF9'))
    combo.view().setPalette(palette)
    combo.view().viewport().setPalette(palette)
    combo.view().setMaximumHeight((combo.fontMetrics().height()+14)*min(11, max(1, combo.count()))+10)


def scroll_parent(widget, event):
    parent = widget.parentWidget()
    while parent:
        if isinstance(parent, QAbstractScrollArea):
            viewport = parent.viewport()
            position = QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint()))
            forwarded = QWheelEvent(position, event.globalPosition(), event.pixelDelta(), event.angleDelta(), event.buttons(), event.modifiers(), event.phase(), event.inverted())
            QApplication.sendEvent(viewport, forwarded)
            event.setAccepted(forwarded.isAccepted())
            return
        parent = parent.parentWidget()
    event.ignore()


class QComboBox(QtComboBox):
    def paintEvent(self, event):
        if self.isEditable(): return super().paintEvent(event)
        c = colors(self); painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1,1,-1,-3)
        base = QColor(c['field'])
        gradient = QLinearGradient(rect.topLeft(),rect.bottomLeft())
        gradient.setColorAt(0,QColor(c['panel']));gradient.setColorAt(.45,base)
        gradient.setColorAt(1,base.darker(108 if c is DARK else 103))
        painter.setPen(Qt.NoPen);painter.setBrush(QColor(0,0,0,20 if c is DARK else 12))
        painter.drawRoundedRect(rect.translated(0,2),9,9)
        painter.setPen(QPen(QColor(c['border']),1));painter.setBrush(gradient)
        painter.drawRoundedRect(rect,9,9)
        painter.setPen(QPen(QColor(255,244,227,30 if c is DARK else 150),1))
        painter.drawLine(rect.topLeft()+QPointF(9,1),rect.topRight()+QPointF(-9,1))
        painter.setPen(QColor(c['ink'] if self.isEnabled() else c['muted']));painter.setFont(self.font())
        text_rect = self.rect().adjusted(11,0,-31,-2)
        icon = self.itemIcon(self.currentIndex())
        if not icon.isNull():
            icon.paint(painter,text_rect.left(),text_rect.center().y()-8,16,16)
            text_rect.adjust(22,0,0,0)
        painter.drawText(text_rect,Qt.AlignVCenter|Qt.AlignLeft,self.fontMetrics().elidedText(self.currentText(),Qt.ElideRight,text_rect.width()))
        painter.setPen(QPen(QColor(c['accent'] if self.isEnabled() else c['muted']),1.8,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        x=self.width()-17;y=self.height()/2-1
        painter.drawPolyline([QPointF(x-4,y-2),QPointF(x,y+2),QPointF(x+4,y-2)])
        if self.hasFocus() and self.property('keyboardFocus'):
            painter.drawLine(rect.bottomLeft()+QPointF(9,0),rect.bottomRight()+QPointF(-9,0))
        painter.end()

    def showPopup(self):
        install_combo_popup(self)
        super().showPopup()

    def wheelEvent(self, event):
        # Popup's view receives its own wheel events and scrolls normally.
        scroll_parent(self, event)


class QSpinBox(QtSpinBox):
    def wheelEvent(self, event):
        if self.property('allowWheel'):
            super().wheelEvent(event)
        else:
            scroll_parent(self, event)


class QDoubleSpinBox(QtDoubleSpinBox):
    def wheelEvent(self, event):
        scroll_parent(self, event)
