"""Read the Windows Qt base DPR in a short-lived process, without user profiles."""
import os
os.environ['QT_QPA_PLATFORM']='windows'
os.environ['QT_SCALE_FACTOR']='1'
from PySide6.QtWidgets import QApplication
app=QApplication([])
print(app.primaryScreen().devicePixelRatio())
