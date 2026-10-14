"""Nonblocking manual Internal update decision; changelog is plain text."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPlainTextEdit
from .glass import GlassButton,PrimaryGlassButton
from ..version import VERSION


class UpdateDialog(QDialog):
    def __init__(self,parent,item,cached=False):
        super().__init__(parent);self.setWindowTitle('Đã có phiên bản TransComic mới!')
        self.setAttribute(Qt.WA_DeleteOnClose)
        layout=QVBoxLayout(self)
        title=QLabel('Đã có phiên bản TransComic mới!');title.setObjectName('section');layout.addWidget(title)
        text=QLabel(f'Phiên bản hiện tại: {VERSION}\nPhiên bản mới: {item.version}\nBạn có muốn tải và cài đặt phiên bản mới không?')
        text.setTextFormat(Qt.PlainText);text.setWordWrap(True);layout.addWidget(text)
        if cached:layout.addWidget(QLabel('Kết quả từ dữ liệu cache đã xác minh.'))
        notes=QPlainTextEdit();notes.setReadOnly(True);notes.setPlainText(item.changelog[:3000]);notes.setMaximumHeight(120)
        if item.changelog:layout.addWidget(notes)
        else:notes.deleteLater()
        row=QHBoxLayout();row.addStretch()
        self.later=GlassButton('Để sau');self.download=PrimaryGlassButton('Tải và cài đặt')
        self.later.clicked.connect(self.reject);self.download.clicked.connect(self.accept)
        self.later.setDefault(True);row.addWidget(self.later);row.addWidget(self.download);layout.addLayout(row)
        self.resize(500,300);self.later.setFocus()
