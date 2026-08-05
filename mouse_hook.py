"""Low-level mouse hooking: turns a Ctrl+drag into a selection box
(single responsibility: input hooking)."""

import ctypes
from ctypes import wintypes

import win32api
import win32con

from applog import log

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
VK_CONTROL = 0x11
HOOK_MIN_DRAG = 2


class _POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('pt', _POINT),
        ('mouseData', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_size_t),
    ]


_HOOKPROC = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, wintypes.INT, wintypes.WPARAM, wintypes.LPARAM
)

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.SetWindowsHookExW.argtypes = [
    wintypes.INT, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD
]
_user32.CallNextHookEx.restype = wintypes.LPARAM
_user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, wintypes.INT, wintypes.WPARAM, wintypes.LPARAM
]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]


class LowLevelMouseHook:
    """Installs a global WH_MOUSE_LL hook and reports Ctrl+drag selections.

    Callbacks:
      on_drag_start()                          — Ctrl+drag began
      on_drag_end(box_sent)                    — drag finished, box_sent = bool
      on_box(x, y, width, height, end_x, end_y) — drag was big enough to select
    """

    def __init__(self, on_drag_start, on_drag_end, on_box):
        self._on_drag_start = on_drag_start
        self._on_drag_end = on_drag_end
        self._on_box = on_box
        self._drag_start = None
        self._handle = None
        self._proc = None

    def install(self):
        try:
            self._proc = _HOOKPROC(self._proc_message)
            self._handle = _user32.SetWindowsHookExW(
                WH_MOUSE_LL, self._proc, None, 0
            )
            if not self._handle:
                log(f'mouse hook failed: error {ctypes.get_last_error()}')
        except Exception as e:
            self._handle = None
            log(f'mouse hook failed: {e!r}')

    def uninstall(self):
        if self._handle:
            _user32.UnhookWindowsHookEx(self._handle)
            self._handle = None

    def _proc_message(self, nCode, wParam, lParam):
        try:
            if nCode >= 0:
                if wParam == WM_LBUTTONDOWN:
                    self._on_mouse_down(lParam)
                elif wParam == WM_LBUTTONUP:
                    self._on_mouse_up(lParam)
        except Exception as e:
            log(f'hook error: {e!r}')
        if self._handle:
            return _user32.CallNextHookEx(self._handle, nCode, wParam, lParam)
        return 0

    def _on_mouse_down(self, lParam):
        ctrl = win32api.GetAsyncKeyState(VK_CONTROL) & 0x8000
        if not ctrl:
            return
        info = _MSLLHOOKSTRUCT.from_address(lParam)
        self._drag_start = (info.pt.x, info.pt.y)
        self._on_drag_start()

    def _on_mouse_up(self, lParam):
        if self._drag_start is None:
            return
        info = _MSLLHOOKSTRUCT.from_address(lParam)
        end = (info.pt.x, info.pt.y)
        start = self._drag_start
        self._drag_start = None
        x = min(start[0], end[0])
        y = min(start[1], end[1])
        width = abs(end[0] - start[0])
        height = abs(end[1] - start[1])
        box_sent = max(width, height) >= HOOK_MIN_DRAG
        self._on_drag_end(box_sent)
        if box_sent:
            self._on_box(x, y, width, height, end[0], end[1])
