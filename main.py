import os
import queue
import subprocess
import sys
import threading
import time

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
from popup import CoverPopup
from tray import TrayIcon

SINGLE_INSTANCE_MUTEX = "Selate-{8A2B1C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}"

_current_popup = None
_cover_visible = False
_box_queue = queue.Queue()
_cancel_event = threading.Event()
_translating = False
_translating_lock = threading.Lock()
_history = []
_history_lock = threading.Lock()
_current_history_index = 0
HISTORY_MAX = 3
_active_hint = None
_active_hint_lock = threading.Lock()
_translator_mod = None

_model_status = 'checking'
_model_status_lock = threading.Lock()

MODEL_STATUS_POLL_SECONDS = 0.5
MODEL_WAIT_POLL_SECONDS = 0.2
HIDE_POPUP_DELAY_SECONDS = 0.1
TOAST_DURATION_SECONDS = 2.0
SELECT_HINT_TEXT = 'Žymima...'
TRANSLATING_TEXT = 'Verčiama...'
HISTORY_NOT_FOUND_TEXT = 'Vertimas #{num} nerastas'


def _set_model_status(state):
    global _model_status
    with _model_status_lock:
        _model_status = state


def _get_model_status():
    with _model_status_lock:
        return _model_status


def main():
    mutex = ensure_single_instance()
    if mutex is None:
        return
    settings = config.load()
    ensure_hint_popup()
    start_preload()
    start_request_worker()
    tray = build_tray_icon(settings, mutex)
    tray.create()
    tray.run()


def start_preload():
    threading.Thread(target=_preload_import, daemon=True).start()
    threading.Thread(target=_watch_model_loading, daemon=True).start()


def _preload_import():
    try:
        mod = _get_translator()
        _set_model_status(
            'initializing' if mod.is_downloaded() else 'downloading'
        )
        mod.preload()
        while not mod.is_ready():
            if mod.load_failed():
                _set_model_status('error')
                log('startup: model initialization failed')
                return
            time.sleep(MODEL_STATUS_POLL_SECONDS)
        _set_model_status('ready')
    except Exception:
        log_exception('preload_import')


def _get_translator():
    global _translator_mod
    mod = _translator_mod
    if mod is None:
        import translator
        mod = _translator_mod = translator
    return mod


def _model_status_text():
    if _get_model_status() == 'downloading' and _translator_mod is not None:
        try:
            downloaded, total = _translator_mod.get_download_progress()
            if total:
                return (
                    'Atsiunčiamas vertimo modelis... '
                    f'{downloaded / 1024 / 1024:.0f} / {total / 1024 / 1024:.0f} MB'
                )
        except Exception:
            pass
    return {
        'checking': 'Tikrinamas vertimo modelis...',
        'loading': 'Tikrinamas vertimo modelis...',
        'downloading': 'Atsiunčiamas vertimo modelis...',
        'initializing': 'Inicializuojamas vertimo modelis...',
        'error': 'Nepavyko inicializuoti vertimo modelio.',
        'ready': None,
    }.get(_get_model_status(), 'Atsiunčiamas vertimo modelis...')


_LOADING_TEXTS = (
    'Tikrinamas vertimo modelis...',
    'Inicializuojamas vertimo modelis...',
    'Atsiunčiamas vertimo modelis...',
)


def _watch_model_loading():
    global _current_popup, _cover_visible
    while True:
        if not notifications_enabled():
            if _cover_visible and _current_popup is not None and _current_popup.current_text() in _LOADING_TEXTS:
                hide_popup()
            time.sleep(MODEL_STATUS_POLL_SECONDS)
            continue
        text = _model_status_text()
        if text is None:
            with _translating_lock:
                busy = _translating
            if not busy:
                if _current_popup is not None:
                    current_text = _current_popup.current_text()
                    if (
                        current_text in _LOADING_TEXTS
                        or current_text.startswith('Atsiunčiamas vertimo modelis...')
                    ):
                        hide_popup()
            return
        if _get_model_status() == 'error':
            _ensure_popup()
            _current_popup.show_status(text, None, None)
            log('startup: model initialization error shown')
            return
        _ensure_popup()
        if not _cover_visible:
            _current_popup.show_status(text, None, None)
            _cover_visible = True
        elif _current_popup.current_text() != text:
            _current_popup.show_status(text, None, None)
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
        on_history=handle_history,
        get_history=history_snapshot,
        on_restart=lambda: restart_app(tray, mutex),
        history_size=HISTORY_MAX,
    )
    tray.on_box = request_box
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
    ensure_hint_popup()
    with _active_hint_lock:
        popup = _active_hint
    popup.show_status(SELECT_HINT_TEXT, None, None)


def hide_select_hint():
    with _active_hint_lock:
        popup = _active_hint
    if popup is not None:
        popup.hide(silent=True)


def history_snapshot():
    with _history_lock:
        return list(_history[:HISTORY_MAX])


def notifications_enabled():
    return config.load().get('notifications', True)


def toggle_topmost(settings):
    settings['always_on_top'] = not settings.get('always_on_top', True)
    config.save(settings)
    apply_topmost()


def apply_topmost():
    global _current_popup
    if _current_popup is not None:
        _current_popup.set_topmost(config.load().get('always_on_top', True))


def start_request_worker():
    threading.Thread(target=_request_worker_loop, daemon=True).start()


def _request_worker_loop():
    while True:
        try:
            box = _box_queue.get(timeout=1)
        except queue.Empty:
            continue
        try:
            _cancel_event.clear()
            if not _wait_for_model():
                continue
            _handle_box(*box)
        except Exception:
            log_exception('worker_loop')


def _wait_for_model():
    """Block until the translation model is ready, so queued translations do
    not run while the model is still downloading/initializing. Runs on the
    worker thread, never on the mouse-hook thread."""
    try:
        mod = _get_translator()
        mod.reset_cancel()
        while not mod.is_ready():
            if mod.load_failed():
                return False
            if _cancel_event.is_set():
                return False
            time.sleep(MODEL_WAIT_POLL_SECONDS)
        return True
    except Exception:
        return True


def request_box(x, y, width, height, end_x, end_y):
    _cancel_translation()
    _box_queue.queue.clear()
    _box_queue.put((int(x), int(y), int(width), int(height), int(end_x), int(end_y)))


def _handle_box(x, y, width, height, end_x, end_y):
    old = clipboard.read_clipboard()
    text = clipboard.get_selected_text()
    if not text:
        text = old
    if not text:
        return
    hide_popup()
    if notifications_enabled():
        show_cover()
        _show_placeholder(end_x, end_y)
    else:
        _ensure_popup()
    with _translating_lock:
        global _translating
        _translating = True
    try:
        translated = _translate_text(text)
        if not translated or _cancel_event.is_set():
            return
        if _current_popup is not None:
            _current_popup.show_translation(translated, None, (end_x, end_y))
            _push_history(translated)
    finally:
        with _translating_lock:
            _translating = False


def _translate_text(text):
    try:
        translated = _get_translator().translate(text)
    except Exception as e:
        log(f'translate error: {e!r}')
        return None
    if not translated or translated.startswith('[Klaida]'):
        return None
    return translated


def _show_placeholder(end_x, end_y):
    if _current_popup is None or not _cover_visible:
        return
    _current_popup.show_status(TRANSLATING_TEXT, None, (end_x, end_y))


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


def _cancel_translation():
    _cancel_event.set()
    mod = _translator_mod
    if mod is not None:
        try:
            mod.cancel()
        except Exception:
            pass


def cancel_work():
    _cancel_translation()
    _box_queue.queue.clear()


def handle_edited_text(text):
    _update_current_history(text)


def _push_history(text):
    global _current_history_index
    _current_history_index = 0
    with _history_lock:
        if _history and _history[0] == text:
            return
        _history.insert(0, text)
        del _history[HISTORY_MAX:]


def _update_current_history(text):
    global _current_history_index
    with _history_lock:
        if not _history:
            return
        idx = _current_history_index
        if idx < len(_history) and _history[idx] != text:
            _history[idx] = text


def handle_history(num):
    global _current_history_index
    if num < 1 or num > HISTORY_MAX:
        return
    with _history_lock:
        if len(_history) < num:
            text = None
        else:
            text = _history[num - 1]
    if text is None:
        _show_toast(HISTORY_NOT_FOUND_TEXT.format(num=num))
        return
    _current_history_index = num - 1
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
    win32api.CloseHandle(mutex)
    os._exit(0)


def restart_app(tray, mutex):
    destroy_popup()
    tray.destroy()
    win32api.CloseHandle(mutex)
    if getattr(sys, 'frozen', False):
        subprocess.Popen([sys.executable])
    else:
        subprocess.Popen([sys.executable, os.path.abspath(__file__)])
    os._exit(0)


if __name__ == '__main__':
    main()
