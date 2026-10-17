"""Stable input splitting controls; the choice stack keeps ON/OFF geometry."""
from PySide6.QtCore import Signal,Qt,QSize,QRectF
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QCheckBox,QLabel,QStackedWidget,QButtonGroup
from .controls import QComboBox
from .glass import GlassButton
from .theme import colors


class SplitToggle(QCheckBox):
    def sizeHint(self):return QSize(self.fontMetrics().horizontalAdvance(self.text())+54,max(30,self.fontMetrics().height()+10))
    def minimumSizeHint(self):return self.sizeHint()
    def hitButton(self,pos):return self.rect().contains(pos)
    def paintEvent(self,event):
        c=colors(self);p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);rect=QRectF(1,(self.height()-22)/2,39,22)
        p.setPen(QPen(QColor(c['border']),1));p.setBrush(QColor(c['accent'] if self.isChecked() and self.isEnabled() else c['field']));p.drawRoundedRect(rect,11,11)
        p.setPen(Qt.NoPen);p.setBrush(QColor('#FFF8F2' if self.isEnabled() else c['muted']));p.drawEllipse(QRectF(22 if self.isChecked() else 4,rect.y()+3,16,16))
        p.setPen(QColor(c['ink'] if self.isEnabled() else c['muted']));p.drawText(self.rect().adjusted(48,0,0,0),Qt.AlignVCenter|Qt.AlignLeft,self.text())


class SplitControls(QWidget):
    changed=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.last_mode='lines'
        self.combo=QComboBox(self);self.combo.hide()
        for label,mode in [('Xuống dòng','lines'),('Theo dấu câu','sentences'),('Không tách','none')]:self.combo.addItem(label,mode)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(5)
        self.toggle=SplitToggle('Tách văn bản');self.toggle.setChecked(True);self.toggle.setToolTip('Tắt để tạo một audio cho toàn bộ văn bản');row.addWidget(self.toggle)
        self.count=QLabel('0 dòng');self.count.setMinimumWidth(self.fontMetrics().horizontalAdvance('99999 dòng'));row.addWidget(self.count)
        self.choices=QStackedWidget();row.addWidget(self.choices)
        options=QWidget();buttons=QHBoxLayout(options);buttons.setContentsMargins(0,0,0,0);buttons.setSpacing(4)
        self.group=QButtonGroup(self);self.group.setExclusive(True)
        self.sentence=GlassButton('Theo câu');self.line=GlassButton('Theo dòng')
        for button,mode in ((self.sentence,'sentences'),(self.line,'lines')):
            button.setCheckable(True);button.setToolTip('Tách theo câu' if mode=='sentences' else 'Tách theo dòng');self.group.addButton(button);buttons.addWidget(button);button.clicked.connect(lambda _,m=mode:self.choose(m))
        self.choices.addWidget(options);self.choices.addWidget(QWidget())
        self.toggle.toggled.connect(lambda value:self.choose(self.last_mode if value else 'none'));self.combo.currentIndexChanged.connect(self.sync);self.sync()
    def choose(self,mode):self.combo.setCurrentIndex(self.combo.findData(mode))
    def sync(self):
        mode=self.combo.currentData()
        if mode!='none':self.last_mode=mode
        self.toggle.blockSignals(True);self.toggle.setChecked(mode!='none');self.toggle.blockSignals(False)
        self.sentence.setChecked(mode=='sentences');self.line.setChecked(mode=='lines');self.choices.setCurrentIndex(1 if mode=='none' else 0);self.changed.emit()
    def set_count(self,count):self.count.setText(f'{count} '+('đoạn' if self.combo.currentData()=='none' and count else 'câu' if self.combo.currentData()=='sentences' or not count else 'dòng'))
