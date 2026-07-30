import win32api
import win32con
import win32gui


class TrayIcon:
    WM_TRAY = win32con.WM_USER + 20
    HOTKEY_ID = 1

    def __init__(self, config, on_quit, on_toggle_copy, on_toggle_startup):
        self.config = config
        self.on_quit = on_quit
        self.on_toggle_copy = on_toggle_copy
        self.on_toggle_startup = on_toggle_startup
        self.on_hotkey = None
        self.hwnd = None

    def create(self):
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "QuickTranslateTray"
        wc.lpfnWndProc = self._wnd_proc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_WINDOW
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            pass

        self.hwnd = win32gui.CreateWindowEx(
            0, wc.lpszClassName, "QuickTranslate",
            win32con.WS_POPUP,
            0, 0, 0, 0, 0, 0,
            win32api.GetModuleHandle(None), None
        )
        if not self.hwnd:
            win32api.MessageBox(0,
                f"Nepavyko sukurti lango (GLE={win32api.GetLastError()})",
                "QuickTranslate", 0x10)
            return

        self._add_icon()
        self._register_hotkey()

    def _add_icon(self):
        hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        nid = (
            self.hwnd, 0,
            win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
            self.WM_TRAY,
            hicon,
            "QuickTranslate (Ctrl+Shift+X)"
        )
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

    def _remove_icon(self):
        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))

    MODIFIER = win32con.MOD_CONTROL | win32con.MOD_SHIFT
    VKEY = ord('X')

    def _register_hotkey(self):
        try:
            win32gui.RegisterHotKey(self.hwnd, self.HOTKEY_ID, self.MODIFIER, self.VKEY)
        except Exception as e:
            import traceback
            traceback.print_exc()
            win32api.MessageBox(0, f"Nepavyko užregistruoti Ctrl+Shift+X ({e})", "QuickTranslate", 0x10)

    def _unregister_hotkey(self):
        try:
            win32gui.UnregisterHotKey(self.hwnd, self.HOTKEY_ID)
        except Exception:
            pass

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            return self._on_msg(hwnd, msg, wparam, lparam)
        except Exception as e:
            print(f"[QuickTranslate] WM error: {e}")
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_msg(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0

        if msg == self.WM_TRAY:
            if lparam == win32con.WM_RBUTTONDOWN:
                self._show_menu()
            return 0

        if msg == win32con.WM_HOTKEY:
            if wparam == self.HOTKEY_ID and self.on_hotkey:
                self.on_hotkey()
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
        win32gui.AppendMenu(menu, f_copy, 1001, "Copy on close")

        f_start = win32con.MF_STRING
        if self.config.get('run_at_startup'):
            f_start |= win32con.MF_CHECKED
        win32gui.AppendMenu(menu, f_start, 1002, "Run at startup")

        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1003, "Quit")

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
        self._unregister_hotkey()
        self._remove_icon()
        if self.hwnd:
            win32gui.DestroyWindow(self.hwnd)
