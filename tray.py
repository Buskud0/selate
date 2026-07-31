import ctypes
import os
from ctypes import wintypes

import win32api
import win32con
import win32gui

from applog import log

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'selate.ico')


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


def _load_icon():
    try:
        if os.path.exists(ICON_PATH):
            return win32gui.LoadImage(
                0, ICON_PATH, win32con.IMAGE_ICON, 0, 0, win32con.LR_LOADFROMFILE
            )
    except Exception as e:
        log(f'icon load error: {e!r}')
    return win32gui.LoadIcon(0, win32con.IDI_APPLICATION)


class TrayIcon:
    WM_TRAY = win32con.WM_USER + 20

    def __init__(self, config, on_quit, on_toggle_copy, on_toggle_startup):
        self.config = config
        self.on_quit = on_quit
        self.on_toggle_copy = on_toggle_copy
        self.on_toggle_startup = on_toggle_startup
        self.on_box = None
        self.hwnd = None
        self._hook_handle = None
        self._hook_proc = None
        self._drag_start = None

    def create(self):
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "SelateTray"
        wc.lpfnWndProc = self._wnd_proc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_WINDOW
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            pass

        self.hwnd = win32gui.CreateWindowEx(
            0, wc.lpszClassName, "Selate",
            win32con.WS_POPUP,
            0, 0, 0, 0, 0, 0,
            win32api.GetModuleHandle(None), None
        )
        if not self.hwnd:
            win32api.MessageBox(0,
                f"Nepavyko sukurti lango (GLE={win32api.GetLastError()})",
                "Selate", 0x10)
            return

        self._add_icon()
        self._install_mouse_hook()

    def _add_icon(self):
        hicon = _load_icon()
        nid = (
            self.hwnd, 0,
            win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
            self.WM_TRAY,
            hicon,
            "Selate (Ctrl + tempimas pele)"
        )
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

    def _remove_icon(self):
        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))

    def _install_mouse_hook(self):
        try:
            self._hook_proc = _HOOKPROC(self._mouse_proc)
            self._hook_handle = _user32.SetWindowsHookExW(
                WH_MOUSE_LL, self._hook_proc, None, 0
            )
            if self._hook_handle:
                log('mouse hook installed')
            else:
                log(f'mouse hook failed: error {ctypes.get_last_error()}')
        except Exception as e:
            self._hook_handle = None
            log(f'mouse hook failed: {e!r}')

    def _uninstall_mouse_hook(self):
        if self._hook_handle:
            _user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None

    def _mouse_proc(self, nCode, wParam, lParam):
        try:
            if nCode >= 0:
                if wParam == WM_LBUTTONDOWN:
                    ctrl = win32api.GetAsyncKeyState(win32con.VK_CONTROL) & 0x8000
                    log(f'hook: down ctrl={bool(ctrl)}')
                    if ctrl:
                        info = _MSLLHOOKSTRUCT.from_address(lParam)
                        self._drag_start = (info.pt.x, info.pt.y)
                elif wParam == WM_LBUTTONUP:
                    log(f'hook: up drag_start={self._drag_start}')
                    if self._drag_start is not None:
                        info = _MSLLHOOKSTRUCT.from_address(lParam)
                        end = (info.pt.x, info.pt.y)
                        start = self._drag_start
                        self._drag_start = None
                        x = min(start[0], end[0])
                        y = min(start[1], end[1])
                        width = abs(end[0] - start[0])
                        height = abs(end[1] - start[1])
                        log(f'hook: box {x},{y} {width}x{height} on_box={self.on_box is not None}')
                        if width >= 2 and height >= 2 and self.on_box:
                            self.on_box(x, y, width, height, end[0], end[1])
        except Exception as e:
            log(f'hook error: {e!r}')
        if self._hook_handle:
            return _user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)
        return 0

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            return self._on_msg(hwnd, msg, wparam, lparam)
        except Exception as e:
            print(f"[Selate] WM error: {e}")
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_msg(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0

        if msg == self.WM_TRAY:
            if lparam == win32con.WM_RBUTTONDOWN:
                self._show_menu()
            return 0

        if msg == win32con.WM_COMMAND:
            cmd = win32gui.LOWORD(wparam)
            if cmd == 1001:
                self.on_toggle_copy()
            elif cmd == 1002:
                self.on_toggle_startup()
            elif cmd == 1003:
                self.on_quit()
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        menu = win32gui.CreatePopupMenu()

        f_copy = win32con.MF_STRING
        if self.config.get('copy_on_close'):
            f_copy |= win32con.MF_CHECKED
        win32gui.AppendMenu(menu, f_copy, 1001, "Kopijuoti uždarant")

        f_start = win32con.MF_STRING
        if self.config.get('run_at_startup'):
            f_start |= win32con.MF_CHECKED
        win32gui.AppendMenu(menu, f_start, 1002, "Paleisti įjungiant sistemą")

        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1003, "Išeiti")

        x, y = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON,
            x, y, 0, self.hwnd, None
        )
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

    def run(self):
        win32gui.PumpMessages()

    def destroy(self):
        self._uninstall_mouse_hook()
        self._remove_icon()
        if self.hwnd:
            win32gui.DestroyWindow(self.hwnd)
