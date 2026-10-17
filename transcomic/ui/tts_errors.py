"""Temporary, removable TTS diagnostic dialog. No translation/secret state."""
import json
import re
import traceback
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPlainTextEdit,QDialogButtonBox,QApplication


from ..tts.diagnostics import diagnostic,redact


class ErrorDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('Chẩn đoán Text to Speech');self.resize(640,420);self.seen=set();self.payload={}
        layout=QVBoxLayout(self);self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.hide();layout.addWidget(self.details,1)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);layout.addWidget(buttons)
        more=buttons.addButton('Chi tiết kỹ thuật',QDialogButtonBox.ActionRole);more.clicked.connect(lambda:self.details.setVisible(self.details.isHidden()))
        self.copy_button=buttons.addButton('Sao chép lỗi',QDialogButtonBox.ActionRole);self.copy_button.clicked.connect(self.copy);buttons.rejected.connect(self.reject)
    def present(self,payload):
        signature=(payload['type'],payload['message'],payload['stage'],payload['run'])
        if signature in self.seen:return
        self.seen.add(signature);self.payload=payload;self.summary.setText(payload['stage']+'\n'+payload['message']);self.details.setPlainText(json.dumps(payload,ensure_ascii=False,indent=2));self.show();self.raise_()
    def copy(self):QApplication.clipboard().setText(self.details.toPlainText())
