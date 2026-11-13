"""Windows mouse-only input, constrained to the locally approved display."""
import ctypes
import sys
import threading
from ctypes import wintypes


MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120
INPUT_MOUSE = 0


class POINT(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    )


class INPUT_UNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT),)


class INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = (("type", wintypes.DWORD), ("value", INPUT_UNION))


class MouseController:
    """Inject only mouse actions and keep the cursor inside one display."""

    def __init__(self, region):
        if sys.platform != "win32":
            raise RuntimeError("Mouse control requires Windows")
        self.left = int(region["left"])
        self.top = int(region["top"])
        self.right = self.left + int(region["width"]) - 1
        self.bottom = self.top + int(region["height"]) - 1
        if self.right < self.left or self.bottom < self.top:
            raise ValueError("Invalid approved display")
        self.user32 = ctypes.windll.user32
        self.lock = threading.Lock()
        self.left_down = False

    def _cursor(self):
        point = POINT()
        if not self.user32.GetCursorPos(ctypes.byref(point)):
            raise OSError("Could not read cursor position")
        return point

    def _confine(self):
        point = self._cursor()
        x = min(self.right, max(self.left, point.x))
        y = min(self.bottom, max(self.top, point.y))
        if x != point.x or y != point.y:
            self.user32.SetCursorPos(x, y)

    def _send(self, flags, dx=0, dy=0, data=0):
        packet = INPUT(type=INPUT_MOUSE)
        packet.mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
        if self.user32.SendInput(1, ctypes.byref(packet), ctypes.sizeof(INPUT)) != 1:
            raise OSError("Windows rejected mouse input")

    def apply(self, event):
        with self.lock:
            kind = event[0]
            if kind == "move":
                self._send(MOUSEEVENTF_MOVE, event[1], event[2])
                self._confine()
            elif kind == "position":
                x = round(self.left + event[1] * (self.right - self.left))
                y = round(self.top + event[2] * (self.bottom - self.top))
                if not self.user32.SetCursorPos(x, y):
                    raise OSError("Windows rejected mouse positioning")
            elif kind == "click":
                self._confine()
                if event[1] == "left":
                    self._send(MOUSEEVENTF_LEFTDOWN)
                    self._send(MOUSEEVENTF_LEFTUP)
                else:
                    self._send(MOUSEEVENTF_RIGHTDOWN)
                    self._send(MOUSEEVENTF_RIGHTUP)
            elif kind == "button":
                self._confine()
                if event[2] == "down" and not self.left_down:
                    self._send(MOUSEEVENTF_LEFTDOWN)
                    self.left_down = True
                elif event[2] == "up" and self.left_down:
                    self._send(MOUSEEVENTF_LEFTUP)
                    self.left_down = False
            elif kind == "scroll":
                self._confine()
                self._send(MOUSEEVENTF_WHEEL, data=event[1] * WHEEL_DELTA)

    def release_all(self):
        """Never leave Windows in a held-button state after a disconnect."""
        with self.lock:
            if self.left_down:
                try:
                    self._send(MOUSEEVENTF_LEFTUP)
                finally:
                    self.left_down = False
