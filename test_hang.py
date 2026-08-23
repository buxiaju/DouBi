"""Diagnose hang in icon load."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
sys.path.insert(0, r'C:\A\03Projects\DeepSeekHarness\DouBi\src')

from PySide6.QtWidgets import QApplication
print("Creating QApplication")
app = QApplication.instance() or QApplication([])
print("QApplication ok")
from doubi.ui.resources import load_app_icon
print("imported")
icon = load_app_icon(64)
print("icon:", icon is not None)
icon2 = load_app_icon()
print("icon2:", icon2 is not None)
print("==DONE==")
