"""Selate entry point (composition root): wires the tray, popup, translator
and translation worker together, then owns the app lifecycle."""

import os
import subprocess
import sys
import threading
import time

if getattr(sys, 'frozen', False):
    import os
    import sysconfig
    import tkinter
    import _tkinter

    base_dir = os.path.dirname(sys.executable)
    tcl_root = os.path.join(base_dir, '_internal')
    if not os.path.isdir(tcl_root):
        tcl_root = sysconfig.get_paths().get('stdlib', '')
    if os.path.isdir(tcl_root):
        os.environ['TCL_LIBRARY'] = os.path.join(tcl_root, 'tcl8.6') if os.path.isdir(os.path.join(tcl_root, 'tcl8.6')) else tcl_root
        os.environ['TK_LIBRARY'] = os.path.join(tcl_root, 'tk8.6') if os.path.isdir(os.path.join(tcl_root, 'tk8.6')) else tcl_root
    try:
        tkinter.Tk()
        tkinter.Tk().destroy()
    except Exception:
        pass

import win32api
import win32event
import winerror

from applog import log, log_exception


def _enable_dpi_awareness():
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()

import clipboard
import config
import messages
import screen
import status
from history_store import HistoryStore, HISTORY_MAX
from popup import CoverPopup
from translation_worker import TranslationWorker
from tray import TrayIcon

SINGLE_INSTANCE_MUTEX = "Selate-{8A2B1C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}"

MODEL_STATUS_POLL_SECONDS = 0.5
HIDE_POPUP_DELAY_SECONDS = 0.1
TOAST_DURATION_SECONDS = 2.0


class TranslatorAccessor:
    """Lazy access to the translator module (dependency seam for the worker)."""

    def __init__(self):
        self._mod = None

    def get(self):
        if self._mod is None:
            import translator
            self._mod = translator
        return self._mod

    def loaded(self):
        return self._mod

    def is_ready(self):
        mod = self._mod
        if mod is None:
            return False
        try:
            return mod.is_ready()
        except Exception:
            return False


class PopupController:
    """Popup operations used by the translation worker (dependency seam)."""

    def ensure(self):
        _ensure_popup()

    def hide(self):
        hide_popup()

    def cover(self):
        show_cover()

    def show_placeholder(self, end_x, end_y):
        _show_placeholder(end_x, end_y)

    def show_translation(self, text, end_x, end_y):
        if _current_popup is not None:
            _current_popup.show_translation(text, None, (end_x, end_y))


_current_popup = None
_cover_visible = False
_active_hint = None
_active_hint_lock = threading.Lock()
_hint_shown = False

_model_status = 'checking'
_model_status_lock = threading.Lock()

history = HistoryStore()
translator_accessor = TranslatorAccessor()


def _set_model_status(state):
    global _model_status
    with _model_status_lock:
        _model_status = state


def _get_model_status():
    with _model_status_lock:
        return _model_status


def _model_status_text():
    mod = translator_accessor.loaded()
    progress = None
    if mod is not None:
        progress = lambda: mod.get_download_progress()
    return status.status_text(_get_model_status(), progress)


def notifications_enabled():
    return config.load().get('notifications', True)


def main():
    mutex = ensure_single_instance()
    if mutex is None:
        return
    settings = config.load()
    ensure_hint_popup()
    start_preload()
    translation_worker.start()
    tray = build_tray_icon(settings, mutex)
    tray.create()
    tray.run()


def start_preload():
    threading.Thread(target=_preload_import, daemon=True).start()
    threading.Thread(target=_watch_model_loading, daemon=True).start()


def _preload_import():
    try:
        mod = translator_accessor.get()
        needed_download = not mod.is_downloaded()
        _set_model_status(
            'initializing' if not needed_download else 'downloading'
        )
        mod.preload()
        while not mod.is_ready():
            if mod.load_failed():
                _set_model_status('error')
                log('startup: model initialization failed')
                return
            time.sleep(MODEL_STATUS_POLL_SECONDS)
        _set_model_status('ready')
        if needed_download:
            if _cover_visible and not translation_worker.busy:
                hide_popup()
            show_usage_instructions(force=True)
    except Exception:
        log_exception('preload_import')


def _watch_model_loading():
    global _current_popup, _cover_visible
    while True:
        if not notifications_enabled():
            if _cover_visible and _current_popup is not None and _current_popup.current_text() in status.LOADING_TEXTS:
                hide_popup()
            time.sleep(MODEL_STATUS_POLL_SECONDS)
            continue
        if translation_worker.busy:
            time.sleep(MODEL_STATUS_POLL_SECONDS)
            continue
        text = _model_status_text()
        if text is None:
            if _current_popup is not None:
                current_text = _current_popup.current_text()
                if (
                    current_text in status.LOADING_TEXTS
                    or current_text.startswith(messages.TEXT_DOWNLOADING)
                ):
                    hide_popup()
            return
        if _get_model_status() == 'error':
            _ensure_popup()
            _current_popup.show_status(text, None, None)
            log('startup: model initialization error shown')
            return
        if status.should_show_status(text, config.load()):
            _ensure_popup()
            if not _cover_visible:
                _current_popup.show_status(text, None, None)
                _cover_visible = True
            elif _current_popup.current_text() != text:
                _current_popup.show_status(text, None, None)
        else:
            if _cover_visible:
                hide_popup()
        if text == messages.TEXT_DOWNLOADING:
            _current_popup._locked = True
        time.sleep(MODEL_STATUS_POLL_SECONDS)


def ensure_single_instance():
    mutex = win32event.CreateMutex(None, False, SINGLE_INSTANCE_MUTEX)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.MessageBox(
            0, "Selate jau paleistas.\nPažiūrėkite į system tray.",
            "Selate", 0x40
        )
        return None
    return mutex


def build_tray_icon(settings, mutex):
    tray = TrayIcon(
        settings,
        on_quit=lambda: quit_app(tray, mutex),
        on_toggle_startup=lambda: toggle_setting(settings, 'run_at_startup'),
        on_toggle_topmost=lambda: toggle_topmost(settings),
        on_toggle_notifications=lambda: toggle_setting(settings, 'notifications'),
        on_toggle_notification=lambda key: toggle_notification_setting(settings, key),
        on_toggle_save_font_size=lambda: toggle_setting(settings, 'save_font_size'),
        on_usage=lambda: show_usage_instructions(force=True),
        on_history=handle_history,
        get_history=history.snapshot,
        on_restart=lambda: restart_app(tray, mutex),
        history_size=HISTORY_MAX,
    )
    tray.on_box = translation_worker.request
    tray.on_select_start = show_select_hint
    tray.on_select_end = hide_select_hint
    return tray


def ensure_hint_popup():
    global _active_hint
    with _active_hint_lock:
        if _active_hint is None:
            _active_hint = CoverPopup(no_activate=True)
            _active_hint.start()
        popup = _active_hint
    popup.wait_ready(2.0)


def show_select_hint():
    global _hint_shown
    if not status.should_show_status(messages.SELECT_HINT_TEXT, config.load()):
        return
    _hint_shown = True
    ensure_hint_popup()
    with _active_hint_lock:
        popup = _active_hint
    popup.show_status(messages.SELECT_HINT_TEXT, None, None)


def hide_select_hint(box_sent=True):
    global _hint_shown
    with _active_hint_lock:
        popup = _active_hint
    if popup is not None:
        popup.hide(silent=True)
    if not box_sent and _hint_shown:
        _show_toast(messages.SELECTION_TOO_SMALL_TEXT)
    _hint_shown = False


def toggle_notification_setting(settings, key):
    settings[key] = not settings.get(key, False)
    config.save(settings)


def show_usage_instructions(force=False):
    settings = config.load()
    if not force and settings.get('usage_instructions_seen', False):
        return
    settings['usage_instructions_seen'] = True
    config.save(settings)
    popup = CoverPopup(no_activate=True)
    popup.start()
    popup.wait_ready(2.0)
    try:
        cursor_x, cursor_y = win32api.GetCursorPos()
        work = screen.work_area_at(cursor_x, cursor_y)
        cx = (work[0] + work[2]) // 2
        cy = (work[1] + work[3]) // 2
        anchor = (cx, cy)
    except Exception:
        anchor = None
    popup.show_translation(
        'Naudojimo instrukcijos:\n\n'
        '• Laikykite Ctrl ir tempkite pele, kad pažymėtumėte tekstą bei gautumėte vertimą (EN → LT).\n'
        '• Kairiuoju pelės klavišu galite perkelti vertimo langą.\n'
        '• Dešiniuoju pelės klavišu uždarykite vertimo langą.\n'
        '• Dukart spustelėkite vertimo langą, kad galėtumėte redaguoti tekstą.\n'
        '• Tempkite už lango kampų, kad pakeistumėte jo dydį.\n'
        '• Ctrl + pelės ratukas keičia teksto dydį, nekeisdamas lango dydžio.\n'
        '• Sistemos tray (dešinėj apačioj) piktogramoje rasite daugiau nustatymų: istoriją, paleidimą kartu su kompiuteriu, programėlės išjungimą ir kitus veiksmus.',
        None,
        anchor,
    )


def toggle_topmost(settings):
    settings['always_on_top'] = not settings.get('always_on_top', True)
    config.save(settings)
    apply_topmost()


def apply_topmost():
    global _current_popup
    if _current_popup is not None:
        _current_popup.set_topmost(config.load().get('always_on_top', True))


def _show_placeholder(end_x, end_y, text=messages.TRANSLATING_TEXT):
    if _current_popup is None or not _cover_visible:
        return
    _current_popup.show_status(text, None, (end_x, end_y))


def hide_popup():
    global _cover_visible
    if not _cover_visible or _current_popup is None:
        return
    _current_popup.hide(silent=True)
    _cover_visible = False
    time.sleep(HIDE_POPUP_DELAY_SECONDS)


def show_cover():
    global _current_popup, _cover_visible
    _ensure_popup()
    _current_popup.cover(None)
    _cover_visible = True


def _ensure_popup():
    global _current_popup
    if _current_popup is None:
        _current_popup = CoverPopup(on_hidden=cancel_work, on_edited=handle_edited_text)
        _current_popup.on_history = handle_history
        _current_popup.start()


def cancel_work():
    translation_worker.cancel_all()


def handle_edited_text(text):
    history.update_current(text)


def handle_history(num):
    if num < 1 or num > HISTORY_MAX:
        return
    text = history.get(num)
    if text is None:
        _show_toast(messages.HISTORY_NOT_FOUND_TEXT.format(num=num))
        return
    history.set_current_index(num - 1)
    if _current_popup is not None:
        _current_popup.show_history(text)


def _show_toast(text):
    popup = CoverPopup(no_activate=True)
    popup.start()
    popup.show_status(text, None, None)

    def _finish():
        popup.hide(silent=True)
        popup.destroy()

    threading.Timer(TOAST_DURATION_SECONDS, _finish).start()


translation_worker = TranslationWorker(
    clipboard=clipboard,
    translator=translator_accessor,
    popup=PopupController(),
    toast=_show_toast,
    history=history,
    status_text=_model_status_text,
)


def toggle_setting(settings, key):
    settings[key] = not settings.get(key, False)
    config.save(settings)


def destroy_popup():
    global _current_popup, _cover_visible
    if _current_popup is not None:
        _current_popup.destroy()
        _current_popup = None
    _cover_visible = False


def quit_app(tray, mutex):
    destroy_popup()
    tray.destroy()
    try:
        if mutex is not None:
            win32api.CloseHandle(mutex)
    except Exception:
        pass
    raise SystemExit(0)


def restart_app(tray, mutex):
    destroy_popup()
    tray.destroy()
    try:
        if mutex is not None:
            win32api.CloseHandle(mutex)
    except Exception:
        pass
    if getattr(sys, 'frozen', False):
        subprocess.Popen([sys.executable])
    else:
        subprocess.Popen([sys.executable, os.path.abspath(__file__)])
    raise SystemExit(0)


if __name__ == '__main__':
    main()
