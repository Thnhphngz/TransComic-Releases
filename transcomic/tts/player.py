"""One compact shared playback surface; independent of inference controls."""
from pathlib import Path
from PySide6.QtCore import Qt,QUrl,Signal,QSize
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput,QAudioDevice,QMediaDevices
from PySide6.QtWidgets import QWidget,QGridLayout,QLabel,QSlider,QCheckBox,QSizePolicy
from ..ui.glass import GlassButton


class AudioPlayer(QWidget):
    error=Signal(str)
    closed=Signal()
    def __init__(self,parent=None,compact=False):
        super().__init__(parent);self.entries=[];self.index=-1;self.setObjectName('ttsSharedPlayer');self.setAttribute(Qt.WA_StyledBackground,True)
        self.setMaximumWidth(730);self.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Fixed)
        self.player=QMediaPlayer(self);self.output=QAudioOutput(self);self.player.setAudioOutput(self.output);self.output.setVolume(.7)
        self.devices=QMediaDevices(self);self.device_signature=self.output_signature()
        self.devices.audioOutputsChanged.connect(self.outputs_changed,Qt.QueuedConnection)
        self.grid=QGridLayout(self);self.grid.setContentsMargins(9,6,9,6);self.grid.setSpacing(5)
        self.toggle_button=GlassButton('▶');self.toggle_button.setMaximumWidth(38);self.toggle_button.setToolTip('Phát / Tạm dừng phát');self.toggle_button.clicked.connect(self.toggle)
        self.title=QLabel('Chưa chọn audio');self.title.setMinimumWidth(55);self.title.setMaximumWidth(135)
        self.seek=QSlider(Qt.Horizontal);self.seek.setMinimumWidth(75);self.time=QLabel('0:00 / 0:00');self.time.setMinimumWidth(self.fontMetrics().horizontalAdvance('00:00 / 00:00')+4);self.time.setAlignment(Qt.AlignCenter)
        self.volume=QSlider(Qt.Horizontal);self.volume.setToolTip('Âm lượng');self.volume.setRange(0,100);self.volume.setValue(70);self.volume.setFixedWidth(65)
        self.close_button=GlassButton('×');self.close_button.setMaximumWidth(36);self.close_button.setToolTip('Dừng phát và đóng player');self.close_button.clicked.connect(self.close_player)
        self.speaker=QLabel('♪');self.speaker.setToolTip('Âm lượng');self.continuous=QCheckBox(self);self.continuous.hide()
        self.widgets=[self.toggle_button,self.title,self.seek,self.time,self.speaker,self.volume,self.close_button];self.layout_player()
        self.volume.valueChanged.connect(lambda v:self.output.setVolume(v/100));self.seek.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(lambda v:self.seek.setMaximum(v));self.player.positionChanged.connect(self.position)
        self.player.playbackStateChanged.connect(lambda state:self.toggle_button.setText('Ⅱ' if state==QMediaPlayer.PlayingState else '▶'))
        self.player.mediaStatusChanged.connect(self.media_status);self.player.errorOccurred.connect(lambda *args:self.error.emit(self.player.errorString()))
    def layout_player(self):
        for widget in self.widgets:self.grid.removeWidget(widget)
        narrow=self.width()<570
        positions=[(0,0),(0,1),(1,0),(0,2),(1,3),(1,4),(0,4)] if narrow else [(0,n) for n in range(7)]
        for widget,(row,col) in zip(self.widgets,positions):self.grid.addWidget(widget,row,col,1,3 if narrow and widget==self.seek else 1)
        for col in range(7):self.grid.setColumnStretch(col,1 if col==(1 if narrow else 2) else 0)
    def resizeEvent(self,event):super().resizeEvent(event);self.layout_player()
    def sizeHint(self):return QSize(680,self.grid.sizeHint().height())
    def output_signature(self):
        return (bytes(QMediaDevices.defaultAudioOutput().id()),tuple(sorted(bytes(d.id()) for d in QMediaDevices.audioOutputs())))
    def renew_output(self):
        # Do not persist/pin an endpoint or choose audioOutputs()[0]. A fresh
        # default output asks the platform for its current routing each time.
        self.player.stop();old=self.output;volume=old.volume();muted=old.isMuted()
        self.player.setAudioOutput(None);self.output=QAudioOutput(QAudioDevice(),self)
        self.output.setVolume(volume);self.output.setMuted(muted);self.player.setAudioOutput(self.output);old.deleteLater()
        self.device_signature=self.output_signature()
        if QMediaDevices.defaultAudioOutput().isNull():
            self.stop();self.error.emit('Không có thiết bị đầu ra âm thanh. Kết nối thiết bị rồi nhấn Phát lại.');return False
        return True
    def outputs_changed(self):
        signature=self.output_signature()
        if signature==self.device_signature:return
        active=not self.player.source().isEmpty();self.stop();self.renew_output()
        if active:self.error.emit('Thiết bị âm thanh đã thay đổi. Đã dừng phát an toàn; nhấn Phát để dùng đầu ra hiện tại.')
    def position(self,value):
        if not self.seek.isSliderDown():self.seek.setValue(value)
        def clock(ms):return f'{int(ms)//60000}:{int(ms)//1000%60:02}'
        self.time.setText(clock(value)+' / '+clock(self.player.duration()))
    def play(self,entries,index=0):self.stop();self.entries=list(entries);self.index=index;self.load()
    def load(self):
        if not 0<=self.index<len(self.entries):self.stop();return
        path,text=self.entries[self.index]
        if not Path(path).is_file():self.stop();self.error.emit('Không tìm thấy audio: '+str(path));return
        if not self.renew_output():return
        self.title.setText(Path(path).name);self.title.setToolTip(text);self.player.setSource(QUrl.fromLocalFile(str(path)));self.player.play()
    def move(self,delta):self.player.stop();self.index+=delta;self.load()
    def toggle(self):
        if self.player.playbackState()==QMediaPlayer.PlayingState:self.player.pause()
        elif not self.player.source().isEmpty():
            if self.output_signature()!=self.device_signature:
                self.outputs_changed();return
            self.player.play()
    def media_status(self,status):
        if status==QMediaPlayer.EndOfMedia:
            if self.continuous.isChecked():self.move(1)
            else:self.stop()
    def stop(self):self.player.stop();self.player.setSource(QUrl())
    def close_player(self):self.stop();self.hide();self.closed.emit()
