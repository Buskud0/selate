import os
import queue
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
_hint_shown = False
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
COPY_FAILED_TEXT = 'Nepavyko nuskaityti pasirinkto teksto.'
TRANSLATION_FAILED_TEXT = 'Nepavyko išversti pasirinkto teksto.'
SELECTION_TOO_SMALL_TEXT = 'Pasirinkimas per mažas. Tempkite ilgiau.'


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
            with _translating_lock:
                busy = _translating
            if _cover_visible and not busy:
                hide_popup()
            show_usage_instructions(force=True)
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
        with _translating_lock:
            busy = _translating
        if busy:
            time.sleep(MODEL_STATUS_POLL_SECONDS)
            continue
        text = _model_status_text()
        if text is None:
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
        if _should_show_status(text):
            _ensure_popup()
            if not _cover_visible:
                _current_popup.show_status(text, None, None)
                _cover_visible = True
            elif _current_popup.current_text() != text:
                _current_popup.show_status(text, None, None)
        else:
            if _cover_visible:
                hide_popup()
        if text == 'Atsiunčiamas vertimo modelis...':
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
    global _hint_shown
    if not _should_show_status(SELECT_HINT_TEXT):
        return
    _hint_shown = True
    ensure_hint_popup()
    with _active_hint_lock:
        popup = _active_hint
    popup.show_status(SELECT_HINT_TEXT, None, None)


def hide_select_hint(box_sent=True):
    global _hint_shown
    with _active_hint_lock:
        popup = _active_hint
    if popup is not None:
        popup.hide(silent=True)
    if not box_sent and _hint_shown:
        _show_toast(SELECTION_TOO_SMALL_TEXT)
    _hint_shown = False


def history_snapshot():
    with _history_lock:
        return list(_history[:HISTORY_MAX])


def notifications_enabled():
    return config.load().get('notifications', True)


def _should_show_status(text):
    if not notifications_enabled():
        return False
    settings = config.load()
    if text == 'Tikrinamas vertimo modelis...':
        return settings.get('notify_model_checking', False)
    if text == 'Atsiunčiamas vertimo modelis...':
        return settings.get('notify_model_downloading', True)
    if text == 'Inicializuojamas vertimo modelis...':
        return settings.get('notify_model_initializing', False)
    if text == SELECT_HINT_TEXT:
        return settings.get('notify_selecting', False)
    if text == TRANSLATING_TEXT:
        return settings.get('notify_translating', True)
    return True


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
            text = _begin_translation(box)
            if text is None:
                continue
            if not _wait_for_model():
                hide_popup()
                continue
            _handle_box(box, text)
        except Exception:
            log_exception('worker_loop')
        finally:
            _end_translation()


def _model_is_ready():
    mod = _translator_mod
    if mod is None:
        return False
    try:
        return mod.is_ready()
    except Exception:
        return False


def _begin_translation(box):
    with _translating_lock:
        global _translating
        _translating = True
    end_x, end_y = box[4], box[5]
    hide_popup()
    text = clipboard.get_selected_text()
    if not text:
        hide_popup()
        _show_toast(COPY_FAILED_TEXT)
        return None
    if not _model_is_ready():
        state = _model_status_text()
        if state is not None:
            _show_toast(state)
        _ensure_popup()
    elif _should_show_status(TRANSLATING_TEXT):
        show_cover()
        _show_placeholder(end_x, end_y)
    else:
        _ensure_popup()
    return text


def _end_translation():
    with _translating_lock:
        global _translating
        _translating = False


def _wait_for_model():
    """Block until the translation model is ready, so queued translations do
    not run while the model is still downloading/initializing. Runs on the
    worker thread, never on the mouse-hook thread."""
    try:
        mod = _get_translator()
        mod.reset_cancel()
        if mod.needs_reload():
            mod.preload()
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


def _handle_box(box, text):
    end_x, end_y = box[4], box[5]
    translated = _translate_text(text)
    if not translated or _cancel_event.is_set():
        hide_popup()
        if not _cancel_event.is_set():
            _show_toast(TRANSLATION_FAILED_TEXT)
        return
    if _current_popup is not None:
        _current_popup.show_translation(translated, None, (end_x, end_y))
        _push_history(translated)


def _translate_text(text):
    try:
        translated = _get_translator().translate(text)
    except Exception as e:
        log(f'translate error: {e!r}')
        return None
    if not translated or translated.startswith('[Klaida]'):
        return None
    return translated


def _show_placeholder(end_x, end_y, text=TRANSLATING_TEXT):
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
