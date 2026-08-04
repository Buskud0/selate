import ctypes
import os
import sys
from ctypes import wintypes

import win32api
import win32con
import win32gui

from applog import log

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'selate.ico')
TOOLTIP_TEXT = "Selate (Ctrl + tempti pele)"
HOOK_MIN_DRAG = 2

CMD_STARTUP = 1002
CMD_QUIT = 1003
CMD_RESTART = 1004
CMD_TOP = 1005
CMD_NOTIFICATIONS = 1006
CMD_USAGE = 1008
CMD_HISTORY_BASE = 2000
CMD_NOTIFY_BASE = 1100

NOTIFICATION_ITEMS = [
    ("Tikrinamas vertimo modelis", 'notify_model_checking', False),
    ("Atsisiunčiamas vertimo modelis", 'notify_model_downloading', True),
    ("Inicijuojamas vertimo modelis", 'notify_model_initializing', False),
    ("Žymima", 'notify_selecting', False),
    ("Verčiama", 'notify_translating', True),
]

HISTORY_PREVIEW_LIMIT = 40
HISTORY_PREVIEW_SUFFIX = '...'


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
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), 'selate.ico'))
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidates.append(os.path.join(meipass, 'selate.ico'))
    candidates.append(ICON_PATH)
    candidates.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'selate.ico')))
    for path in candidates:
        try:
            if path and os.path.exists(path):
                return win32gui.LoadImage(
                    0, path, win32con.IMAGE_ICON, 0, 0, win32con.LR_LOADFROMFILE
                )
        except Exception as e:
            log(f'icon load error: {e!r}')
    return win32gui.LoadIcon(0, win32con.IDI_APPLICATION)


class TrayIcon:
    WM_TRAY = win32con.WM_USER + 20

    def __init__(self, settings, on_quit, on_toggle_startup,
                 on_toggle_topmost, on_toggle_notifications,
                 on_toggle_notification, on_usage, on_history,
                 get_history, on_restart, history_size=3):
        self.settings = settings
        self.on_quit = on_quit
        self.on_toggle_startup = on_toggle_startup
        self.on_toggle_topmost = on_toggle_topmost
        self.on_toggle_notifications = on_toggle_notifications
        self.on_toggle_notification = on_toggle_notification
        self.on_usage = on_usage
        self.on_history = on_history
        self.get_history = get_history
        self.on_restart = on_restart
        self.on_box = None
        self.on_select_start = None
        self.on_select_end = None
        self.history_size = history_size
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
            win32api.MessageBox(
                0, f"Nepavyko sukurti lango (GLE={win32api.GetLastError()})",
                "Selate", 0x10
            )
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
            TOOLTIP_TEXT,
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
            if not self._hook_handle:
                log(f'mouse hook failed: error {ctypes.get_last_error()}')
        except Exception as e:
            self._hook_handle = None
            log(f'mouse hook failed: {e!r}')

    def _uninstall_mouse_hook(self):
        if self._hook_handle:
            _user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None

    def _invoke(self, callback, where, *args):
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as e:
            log(f'{where}: {e!r}')

    def _mouse_proc(self, nCode, wParam, lParam):
        try:
            if nCode >= 0:
                if wParam == WM_LBUTTONDOWN:
                    self._on_mouse_down(lParam)
                elif wParam == WM_LBUTTONUP:
                    self._on_mouse_up(lParam)
        except Exception as e:
            log(f'hook error: {e!r}')
        if self._hook_handle:
            return _user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)
        return 0

    def _on_mouse_down(self, lParam):
        ctrl = win32api.GetAsyncKeyState(win32con.VK_CONTROL) & 0x8000
        if not ctrl:
            return
        info = _MSLLHOOKSTRUCT.from_address(lParam)
        self._drag_start = (info.pt.x, info.pt.y)
        self._invoke(self.on_select_start, 'hook: select start error')

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
        self._invoke(self.on_select_end, 'hook: select end error')
        if width >= HOOK_MIN_DRAG and height >= HOOK_MIN_DRAG:
            self._invoke(self.on_box, 'hook: box error', x, y, width, height, end[0], end[1])

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
            if cmd == CMD_STARTUP:
                self.on_toggle_startup()
            elif cmd == CMD_TOP:
                self.on_toggle_topmost()
            elif cmd == CMD_USAGE:
                if self.on_usage is not None:
                    self.on_usage()
            elif CMD_NOTIFY_BASE <= cmd < CMD_NOTIFY_BASE + len(NOTIFICATION_ITEMS):
                if self.on_toggle_notification is not None:
                    key = NOTIFICATION_ITEMS[cmd - CMD_NOTIFY_BASE][1]
                    self.on_toggle_notification(key)
            elif CMD_HISTORY_BASE <= cmd < CMD_HISTORY_BASE + self.history_size:
                self.on_history(cmd - CMD_HISTORY_BASE + 1)
            elif cmd == CMD_QUIT:
                self.on_quit()
            elif cmd == CMD_RESTART:
                self.on_restart()
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _append_check(self, menu, label, command, checked):
        flags = win32con.MF_STRING
        if checked:
            flags |= win32con.MF_CHECKED
        win32gui.AppendMenu(menu, flags, command, label)

    def _history_preview(self, text):
        preview = text.replace('\n', ' ').strip()
        if len(preview) > HISTORY_PREVIEW_LIMIT:
            preview = preview[:HISTORY_PREVIEW_LIMIT] + HISTORY_PREVIEW_SUFFIX
        return preview

    def _show_menu(self):
        menu = win32gui.CreatePopupMenu()
        self._append_check(menu, "Paleisti įjungiant sistemą", CMD_STARTUP,
                           self.settings.get('run_at_startup'))
        self._append_check(menu, "Visada viršuje", CMD_TOP,
                           self.settings.get('always_on_top', True))

        notify_menu = win32gui.CreatePopupMenu()
        for index, (label, key, default) in enumerate(NOTIFICATION_ITEMS):
            self._append_check(
                notify_menu,
                label,
                CMD_NOTIFY_BASE + index,
                self.settings.get(key, default),
            )
        win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_POPUP, notify_menu, "Papildomi pranešimai")

        win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_USAGE, "Naudojimo instrukcija")

        history = self.get_history() if self.get_history else []
        hist_menu = win32gui.CreatePopupMenu()
        for i in range(self.history_size):
            if i < len(history):
                label = f'{i + 1}. {self._history_preview(history[i])}'
                command = CMD_HISTORY_BASE + i
                flags = win32con.MF_STRING
            else:
                label = f'{i + 1}. -'
                command = 0
                flags = win32con.MF_STRING | win32con.MF_GRAYED
            win32gui.AppendMenu(hist_menu, flags, command, label)
        win32gui.AppendMenu(
            menu, win32con.MF_STRING | win32con.MF_POPUP, hist_menu, "Istorija"
        )

        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_RESTART, "Restartuoti")
        win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_QUIT, "Išeiti")

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
