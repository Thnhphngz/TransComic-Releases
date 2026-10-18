"""Existing safe audio controls with CapCut's long-path URL normalization."""
from pathlib import Path
from PySide6.QtCore import QUrl
from ..tts.player import AudioPlayer
from ..capcut.media import native_path
from ..capcut.exporter import reference


class CapcutPlayer(AudioPlayer):
    def load(self):
        if not 0<=self.index<len(self.entries):self.stop();return
        path,text=self.entries[self.index]
        if not native_path(path).is_file():self.stop();self.error.emit('Không tìm thấy audio: '+str(path));return
        if not self.renew_output():return
        self.title.setText(Path(path).name);self.title.setToolTip(text)
        self.player.setSource(QUrl.fromLocalFile(reference(path)));self.player.play()
