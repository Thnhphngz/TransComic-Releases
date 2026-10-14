"""Monitor-aware startup, using validated Windows EDID rather than resolution."""
from __future__ import annotations

import ctypes
import json
import math
import sys
from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import QCursor, QGuiApplication


def edid_inches(data: bytes) -> float | None:
    if len(data) < 128 or data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00" or sum(data[:128]) % 256:
        return None
    width, height = data[21] * 10, data[22] * 10
    if not width or not height:
        for offset in (54, 72, 90, 108):
            block = data[offset:offset+18]
            if block[0] or block[1]:
                width = block[12] | ((block[14] & 0xF0) << 4)
                height = block[13] | ((block[14] & 0x0F) << 8)
                if width and height:
                    break
    diagonal = math.hypot(width, height) / 25.4
    if not width or not height or not 8 <= diagonal <= 100 or not 0.5 <= width / height <= 4:
        return None
    return diagonal


def monitor_inches(screen) -> float | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        from ctypes import wintypes

        class DisplayDevice(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                        ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                        ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

        device = DisplayDevice()
        device.cb = ctypes.sizeof(device)
        enum = ctypes.windll.user32.EnumDisplayDevicesW
        enum.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DisplayDevice), wintypes.DWORD]
        if not enum(screen.name(), 0, ctypes.byref(device), 0):
            return None
        pieces = device.DeviceID.split("\\")
        if len(pieces) < 2 or pieces[0].upper() != "MONITOR":
            return None
        base = "SYSTEM\\CurrentControlSet\\Enum\\DISPLAY\\" + pieces[1]
        sizes = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as monitor:
            for i in range(winreg.QueryInfoKey(monitor)[0]):
                instance = winreg.EnumKey(monitor, i)
                try:
                    with winreg.OpenKey(monitor, instance + "\\Device Parameters") as parameters:
                        raw, _ = winreg.QueryValueEx(parameters, "EDID")
                        size = edid_inches(raw)
                        if size is not None:
                            sizes.append(size)
                except OSError:
                    continue
        # Multiple identical monitor instances cannot be mapped reliably by this API.
        return sizes[0] if len(sizes) == 1 else None
    except (OSError, AttributeError, ValueError):
        return None


@dataclass(frozen=True)
class WindowPlan:
    screen: object
    geometry: QRect
    maximized: bool
    reason: str


def window_plan(screens, preferred, saved: str = "", measure=monitor_inches) -> WindowPlan:
    state = None
    try:
        candidate = json.loads(saved) if saved else None
        if isinstance(candidate, dict) and isinstance(candidate.get("rect"), list) and len(candidate["rect"]) == 4:
            if all(isinstance(v, int) for v in candidate["rect"]):
                state = candidate
    except (ValueError, TypeError):
        pass
    screen = next((s for s in screens if state and s.name() == state.get("screen")), preferred)
    screen = screen or screens[0]
    available = screen.availableGeometry()
    safe = available.adjusted(10, 10, -10, -35)
    if safe.width() < 200 or safe.height() < 200:
        safe = available
    if state:
        x, y, width, height = state["rect"]
        width, height = min(max(400, width), safe.width()), min(max(300, height), safe.height())
        x = max(safe.left(), min(x, safe.right()-width+1))
        y = max(safe.top(), min(y, safe.bottom()-height+1))
        return WindowPlan(screen, QRect(x, y, width, height), bool(state.get("maximized")), "saved")
    diagonal = measure(screen)
    width, height = min(1440, int(safe.width()*0.9)), min(900, int(safe.height()*0.9))
    rect = QRect(0, 0, width, height)
    rect.moveCenter(safe.center())
    return WindowPlan(screen, rect, diagonal is None or diagonal < 21, "unknown_edid" if diagonal is None else "edid")


def show_initial(window):
    screens = QGuiApplication.screens()
    preferred = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    plan = window_plan(screens, preferred, window.store.setting("window_state"), measure=monitor_inches)
    window.setScreen(plan.screen)
    safe = plan.screen.availableGeometry()
    window.setMinimumSize(min(900, max(1, safe.width()-20)), min(580, max(1, safe.height()-45)))
    if safe.width() < 1000 and window.sidebar.width() > 100:
        window.toggle_sidebar()
    window.setGeometry(plan.geometry)
    window.showMaximized() if plan.maximized else window.show()
    window.startup_reason = plan.reason


def save_window_state(window):
    geometry = window.normalGeometry() if window.isMaximized() else window.geometry()
    window.store.set_setting("window_state", json.dumps({
        "screen": window.screen().name(), "rect": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
        "maximized": window.isMaximized(),
    }))
