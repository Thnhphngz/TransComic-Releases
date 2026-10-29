"""Input for opt-in release probes; never used by ordinary application flows."""
import os
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def click(widget,point=None):
    """Use native Windows mouse input, after checking the target belongs to us."""
    point=point or widget.rect().center()
    if QApplication.platformName()!='windows':
        QTest.mouseClick(widget,Qt.LeftButton,pos=point)
        return 'QTest'
    import ctypes
    from ctypes import wintypes
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetForegroundWindow.restype=wintypes.HWND
    user.SetForegroundWindow.argtypes=[wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
    user.WindowFromPoint.argtypes=[wintypes.POINT];user.WindowFromPoint.restype=wintypes.HWND
    window=widget.window();handle=int(window.winId())
    assert widget.isVisible() and widget.isEnabled()
    if not QApplication.activePopupWidget():
        window.raise_();window.activateWindow();user.SetForegroundWindow(handle)
    def process_id(hwnd):
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));return pid.value
    assert process_id(user.GetForegroundWindow())==os.getpid(),'Probe window is not foreground; refuse desktop click'
    origin=wintypes.POINT();assert user.ClientToScreen(handle,ctypes.byref(origin))
    local=widget.mapTo(window,point);dpr=window.devicePixelRatioF()
    target=wintypes.POINT(origin.x+round(local.x()*dpr),origin.y+round(local.y()*dpr))
    assert process_id(user.WindowFromPoint(target))==os.getpid(),'Desktop target belongs to another process'
    assert user.SetCursorPos(target.x,target.y)
    user.mouse_event(0x0002,0,0,0,0);user.mouse_event(0x0004,0,0,0,0)
    return 'Win32 mouse input'
