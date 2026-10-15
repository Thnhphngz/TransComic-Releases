"""Native glass surfaces and a finite day/night animation (no browser)."""
from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve, QRectF, QEvent, QObject, QPointF, QRect
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QPen, QPalette, QIcon, QPixmap, QBitmap, QRegion
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QApplication, QComboBox as QtComboBox, QDialogButtonBox, QSizePolicy
from .theme import colors, DARK, LIGHT


def reduced_motion():
    try:
        import ctypes
        enabled = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return not enabled.value
    except (AttributeError, OSError):
        pass
    return False


def centered_icon(icon, size, dpr):
    """Center visible ink, including SVG assets with asymmetric transparent margins."""
    source = icon.pixmap(size*dpr)
    bounds = QRegion(QBitmap.fromImage(source.toImage().createAlphaMask())).boundingRect()
    if bounds.isEmpty(): return icon
    # Copy in physical pixels, then restore DPR for Qt's logical painting.
    source.setDevicePixelRatio(1)
    result = QPixmap(source.size()); result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.drawPixmap((result.width()-bounds.width())//2, (result.height()-bounds.height())//2,
                       source.copy(bounds))
    painter.end(); result.setDevicePixelRatio(dpr)
    return QIcon(result)


class GlassButton(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)
        self._light = 0.0
        self.setProperty('glassRole','secondary')
        self.setProperty('keyboardFocus',False)
        self._hover = QPropertyAnimation(self, b'light', self)
        self._hover.setDuration(0 if reduced_motion() else 130)
        self._hover.setEasingCurve(QEasingCurve.OutCubic)

    def get_light(self): return self._light
    def set_light(self, value): self._light = value; self.update()
    light = Property(float, get_light, set_light)

    def enterEvent(self, event):
        self._hover.stop(); self._hover.setStartValue(self._light); self._hover.setEndValue(1); self._hover.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.stop(); self._hover.setStartValue(self._light); self._hover.setEndValue(0); self._hover.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        c=colors(self); dark=c is DARK
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        primary=self.objectName()=='primary' or self.property('glassRole')=='primary'
        danger=self.objectName()=='danger' or self.property('glassRole')=='danger'
        ghost=self.property('glassRole')=='ghost'
        selected=self.isCheckable() and self.isChecked()
        enabled=self.isEnabled();pressed=self.isDown() and enabled
        field=QColor(c['field']);edge=QColor(c['border']);text=QColor(c['ink'])
        if primary or selected:
            field=QColor(c['accent']);edge=QColor(c['accent']);text=QColor('#30231D' if dark else '#FFFCF9')
        elif danger:
            field=QColor('#58352D' if dark else '#F0D9CF');edge=QColor('#926250' if dark else '#C59683')
            text=QColor('#FFE4D8' if dark else '#853B2B')
        elif self.property('glassRole') == 'warning':
            text=QColor('#FF9999' if dark else '#B42323'); edge=QColor('#926250' if dark else '#C59683')
        elif self.property('glassRole') == 'success':
            text=QColor('#71D7AB' if dark else '#16784C')
        if not enabled:field=QColor(c['field']);text=QColor(c['muted']);edge=QColor(c['border'])
        light=getattr(self,'_light',float(self.underMouse()))
        if ghost:
            field.setAlpha(int(12+light*160));edge.setAlpha(int(light*90))
        rect=QRectF(self.rect()).adjusted(1,1 if pressed else 0,-1,-2 if pressed else -3)
        radius=min(10,rect.height()/2)
        # Two inexpensive inset shadow strokes; no offscreen blur surfaces.
        p.setPen(Qt.NoPen);p.setBrush(QColor(0,0,0,0 if ghost else 28 if dark else 18));p.drawRoundedRect(rect.translated(0,2),radius,radius)
        gradient=QLinearGradient(rect.topLeft(),rect.bottomLeft())
        top=field.lighter(112+int(light*6)) if dark else field.lighter(105+int(light*3))
        bottom=field.darker(112 if dark else 106)
        gradient.setColorAt(0,top);gradient.setColorAt(.5,field);gradient.setColorAt(1,bottom)
        if selected:
            # Stable checked fill under hover/press, matching the chip's selected identity.
            p.setBrush(field)
        else:p.setBrush(gradient)
        p.setPen(QPen(edge,1));p.drawRoundedRect(rect,radius,radius)
        gloss=QLinearGradient(rect.topLeft(),rect.bottomLeft())
        gloss.setColorAt(0,QColor(255,244,227,int(light*20) if ghost else 12 if not enabled else 38 if dark else 125))
        gloss.setColorAt(.35,QColor(255,244,227,0));gloss.setColorAt(1,QColor(255,244,227,0))
        p.setPen(Qt.NoPen);p.setBrush(gloss);p.drawRoundedRect(rect.adjusted(1,1,-1,-1),radius-1,radius-1)
        p.setPen(QPen(QColor(255,242,221,int(light*30) if ghost else 35 if dark else 155),1))
        p.drawLine(rect.topLeft()+QPointF(radius,1),rect.topRight()+QPointF(-radius,1))
        option=QStyleOptionButton()
        if isinstance(self,GlassButton):self.initStyleOption(option)
        else:
            option.initFrom(self);option.text=self.text();option.icon=self.icon();option.iconSize=self.iconSize()
            if self.isDown():option.state|=QStyle.State_Sunken
            if self.isChecked():option.state|=QStyle.State_On
        option.state &= ~QStyle.State_HasFocus
        option.rect=rect.toRect().adjusted(5,0,-5,0)
        if (primary or selected) and enabled and not option.icon.isNull():
            pixmap=option.icon.pixmap(option.iconSize*self.devicePixelRatioF())
            pixmap.setDevicePixelRatio(self.devicePixelRatioF())
            tint=QPainter(pixmap);tint.setCompositionMode(QPainter.CompositionMode_SourceIn)
            tint.fillRect(pixmap.rect(),text);tint.end();option.icon=QIcon(pixmap)
        for group in (QPalette.Active,QPalette.Inactive,QPalette.Disabled): option.palette.setColor(group,QPalette.ButtonText,text)
        # Drawing the label here prevents Qt-created dialog buttons from restoring
        # a cached white foreground over the dark theme's copper surface.
        p.setFont(self.font());p.setPen(text)
        mnemonic=Qt.TextShowMnemonic if self.style().styleHint(QStyle.SH_UnderlineShortcut,option,self) else Qt.TextHideMnemonic
        label_rect=option.rect
        if not option.icon.isNull():
            icon_size=option.iconSize
            icon_rect=QRect(0,0,icon_size.width(),icon_size.height())
            if not self.text():
                icon_rect.moveCenter(label_rect.center())
            else:
                width=self.fontMetrics().size(mnemonic,self.text()).width()
                left=max(label_rect.left(),int(label_rect.center().x()-(width+icon_size.width()+6)/2))
                icon_rect.moveTo(left,label_rect.center().y()-icon_size.height()//2)
            option.icon.paint(p,icon_rect,Qt.AlignCenter,QIcon.Normal if enabled else QIcon.Disabled)
            if self.text():
                label_rect=QRect(icon_rect.right()+7,label_rect.top(),max(0,label_rect.right()-icon_rect.right()-6),label_rect.height())
                p.drawText(label_rect,Qt.AlignVCenter|Qt.AlignLeft|mnemonic,self.text())
        else:
            label = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, label_rect.width()) if self.property('elideText') else self.text()
            p.drawText(label_rect,Qt.AlignCenter|mnemonic,label)
        if self.hasFocus() and self.property('keyboardFocus'):
            p.setPen(QPen(QColor(c['accent']),1.5));p.drawLine(rect.bottomLeft()+QPointF(radius,0),rect.bottomRight()+QPointF(-radius,0))
        p.end()


class CompactStatusButton(GlassButton):
    """One-line badge: elide painting only, preserving full text and click bounds."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty('elideText', True)
        self.setMinimumWidth(0)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def setToolTip(self, text):
        self._status_hint = text
        super().setToolTip(self.text()+'\n'+text)

    def setText(self, text):
        super().setText(text)
        self.setAccessibleName(text)
        super().setToolTip(text+'\n'+getattr(self, '_status_hint', ''))


class PrimaryGlassButton(GlassButton):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.setProperty('glassRole','primary');self.setObjectName('primary')


class SecondaryGlassButton(GlassButton):pass


class DangerGlassButton(GlassButton):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.setProperty('glassRole','danger');self.setObjectName('danger')


class GhostGlassButton(GlassButton):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.setProperty('glassRole','ghost')


class IconGlassButton(GlassButton):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.setProperty('glassRole','icon')
        self.setFixedWidth(36);self.setMinimumHeight(32)


class SkySwitch(GlassButton):
    def __init__(self, dark=False, parent=None):
        super().__init__(parent)
        self._night = float(dark)
        self.setCheckable(True); self.setChecked(dark)
        self.setFixedSize(62, 32)
        self.setAccessibleName('Giao diện sáng / tối')
        self.setToolTip('Chuyển giao diện sáng / tối · Space')
        self._slide = QPropertyAnimation(self, b'night', self)
        self._slide.setDuration(0 if reduced_motion() else 210)
        self._slide.setEasingCurve(QEasingCurve.InOutCubic)

    def get_night(self): return self._night
    def set_night(self, value): self._night=value; self.update()
    night=Property(float,get_night,set_night)

    def set_dark(self, dark):
        self.setChecked(dark)
        self.setAccessibleDescription('Đêm' if dark else 'Ngày')
        self._slide.stop(); self._slide.setStartValue(self._night); self._slide.setEndValue(float(dark)); self._slide.start()

    def paintEvent(self, event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        t=self._night
        p.setPen(QPen(QColor('#D3BBA9'),1))
        p.setBrush(QColor(int(144-112*t),int(194-155*t),int(214-160*t)))
        p.drawRoundedRect(QRectF(1,1,60,30),15,15)
        p.setPen(Qt.NoPen)
        if t<.5:
            p.setBrush(QColor('#FFFCF4')); p.drawEllipse(QRectF(32,17,20,8)); p.drawEllipse(QRectF(42,14,13,11))
        else:
            p.setBrush(QColor('#FFF5DD'))
            for x,y in ((12,9),(25,7),(17,23)): p.drawEllipse(QRectF(x,y,2,2))
        x=5+28*t
        p.setBrush(QColor('#F9CF70') if t<.5 else QColor('#F6EDE5')); p.drawEllipse(QRectF(x,5,22,22))
        if t>=.5:
            p.setBrush(QColor('#C7BEB7'))
            p.drawEllipse(QRectF(x+5,9,5,5)); p.drawEllipse(QRectF(x+12,17,4,4))
        if self.hasFocus() and self.property('keyboardFocus'):
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor('#D88A4E'),1)); p.drawLine(14,30,48,30)
        p.end()


def install_glass_skin(owner):
    """One application filter, without retaining any workspace window."""
    app=QApplication.instance()
    skin=getattr(app,'transcomic_glass_skin',None)
    if skin is None:
        skin=GlassSkin(app);app.transcomic_glass_skin=skin
    owner.setProperty('glassRoot',True)
    return skin


class GlassSkin(QObject):
    """Keyboard focus and skins for Qt-created dialog buttons/combos too."""
    def __init__(self,app):
        super().__init__(app)
        app.installEventFilter(self)

    def eventFilter(self,widget,event):
        kind=event.type()
        if kind not in (QEvent.FocusIn,QEvent.MouseButtonPress,QEvent.Polish,QEvent.Show,QEvent.Paint):return False
        if not isinstance(widget,(QPushButton,QtComboBox)):return False
        if kind==QEvent.Paint and (not isinstance(widget,QPushButton) or isinstance(widget,GlassButton)):return False
        parent=widget
        while parent is not None and not parent.property('glassRoot'):parent=parent.parentWidget()
        if parent is None or parent._closed:return False
        if kind==QEvent.Paint:
            GlassButton.paintEvent(widget,event)
            return True
        if kind in (QEvent.Polish,QEvent.Show) and isinstance(widget,QPushButton) and isinstance(widget.parentWidget(),QDialogButtonBox):
            role=widget.parentWidget().buttonRole(widget)
            widget.setProperty('glassRole','primary' if role in (QDialogButtonBox.AcceptRole,QDialogButtonBox.YesRole) else 'danger' if role==QDialogButtonBox.DestructiveRole else 'secondary')
            if kind==QEvent.Show and not widget.property('glassRolePolished'):
                widget.setProperty('glassRolePolished',True)
                widget.style().unpolish(widget);widget.style().polish(widget)
        if kind in (QEvent.FocusIn,QEvent.MouseButtonPress):
            keyboard=kind==QEvent.FocusIn and event.reason() in (Qt.TabFocusReason,Qt.BacktabFocusReason,Qt.ShortcutFocusReason)
            if widget.property('keyboardFocus')!=keyboard:
                widget.setProperty('keyboardFocus',keyboard)
                widget.update()
        # setView transfers ownership and replaces Qt's existing popup. Do this
        # after construction, never from a Polish callback inside initialization.
        if kind==QEvent.Show and isinstance(widget,QtComboBox) and not widget.property('glassPopupInstalled'):
            from .controls import install_combo_popup
            install_combo_popup(widget)
        return False
