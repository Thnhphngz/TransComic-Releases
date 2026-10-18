"""Derived cover only; no source copies. Paths follow the supplied native MAU."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QImage, QPainter, QColor
from .media import checkpoint


def write_cover(stage,timeline,image_path,cancel=None):
    checkpoint(cancel)
    reader=QImageReader(image_path);reader.setAutoTransform(True)
    size=reader.size()
    if size.isValid():reader.setScaledSize(size.scaled(640,360,Qt.KeepAspectRatio))
    image=reader.read()
    if image.isNull():raise ValueError('Không đọc được ảnh bìa: '+reader.errorString())
    cover=QImage(640,360,QImage.Format_RGB32);cover.fill(QColor('#161616'))
    scaled=image.scaled(640,360,Qt.KeepAspectRatio,Qt.SmoothTransformation)
    painter=QPainter(cover);painter.drawImage((640-scaled.width())//2,(360-scaled.height())//2,scaled);painter.end()
    for folder in (Path(stage),Path(stage)/'Timelines'/timeline):
        checkpoint(cancel);folder.mkdir(parents=True,exist_ok=True)
        if not cover.save(str(folder/'draft_cover.jpg'),'JPEG',90):raise OSError('Không ghi được thumbnail bìa project')
