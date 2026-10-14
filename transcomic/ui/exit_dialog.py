"""Keyboard-accessible close confirmation and application icon."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from .glass import GlassButton as QPushButton


def app_icon(dark=False):
    from pathlib import Path
    from PySide6.QtCore import QSize
    assets = Path(__file__).parent/'assets'
    icon = QIcon(str(assets/('transcomic-dark.svg' if dark else 'transcomic-light.svg')))
    for size in (16, 20, 24): icon.addFile(str(assets/'transcomic-small.svg'), QSize(size, size))
    return icon


class ExitDialog(QDialog):
    def __init__(self, parent, running=False, tray_available=False):
        super().__init__(parent)
        self.choice = "cancel"
        self.setWindowTitle("Thoát TransComic")
        self.setModal(True)
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        title = QLabel("TransComic đang thực hiện công việc.\nBạn muốn làm gì?" if running else "Bạn muốn thoát TransComic?")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        note = QLabel("Thoát an toàn dừng gửi request mới và chờ các request đang chạy lưu kết quả." if running else "Các chỉnh sửa nội bộ đã được tự lưu.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        self.buttons = {}
        row = QHBoxLayout()
        if running and tray_available:
            self.add_choice(row, "background", "Chạy nền")
        elif running:
            notice = QLabel("System tray không khả dụng; ứng dụng cần giữ cửa sổ mở để tiếp tục công việc.")
            notice.setWordWrap(True)
            notice.setObjectName("muted")
            layout.addWidget(notice)
        self.add_choice(row, "safe" if running else "exit", "Thoát an toàn" if running else "Thoát")
        cancel = self.add_choice(row, "cancel", "Hủy")
        cancel.setDefault(True)
        layout.addLayout(row)
        self.resize(min(520, parent.screen().availableGeometry().width()-40), self.sizeHint().height())

    def add_choice(self, layout, key, text):
        button = QPushButton(text)
        button.clicked.connect(lambda: self.choose(key))
        self.buttons[key] = button
        layout.addWidget(button)
        return button

    def choose(self, choice):
        self.choice = choice
        self.accept()
