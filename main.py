import os
import queue
import threading
import time

import win32api
import win32event
import winerror

from applog import log, log_exception

try:
    import torch
except Exception:
    log_exception('torch_import')

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


def main():
    mutex = ensure_single_instance()
    if mutex is None:
        return
    settings = config.load()
    start_preload()
    start_request_worker()
    tray = build_tray_icon(settings, mutex)
    tray.create()
    tray.run()


def start_preload():
    threading.Thread(target=_preload_import, daemon=True).start()
    log('preload started')
    threading.Thread(target=_watch_model_loading, daemon=True).start()


def _preload_import():
    try:
        import translator
        translator.preload()
    except Exception:
        log_exception('preload_import')


def _model_status_text():
    try:
        import translator
        if translator.is_ready():
            return None
        if translator.is_downloaded():
            return 'Inicializuojamas vertimo modelis...'
        return 'Atsiunčiamas vertimo modelis...'
    except Exception:
        return 'Atsiunčiamas vertimo modelis...'


_LOADING_TEXTS = ('Inicializuojamas vertimo modelis...', 'Atsiunčiamas vertimo modelis...')


def _watch_model_loading():
    global _current_popup, _cover_visible
    while True:
        time.sleep(0.5)
        text = _model_status_text()
        if text is None:
            with _translating_lock:
                busy = _translating
            if not busy:
                if _current_popup is not None and _current_popup.current_text() in _LOADING_TEXTS:
                    hide_popup()
                    log('startup: model ready, indicator hidden')
            return
        if _current_popup is None:
            _current_popup = CoverPopup(on_hidden=cancel_work)
            _current_popup.start()
        if not _cover_visible:
            _current_popup.show_status(text, None, None)
            _cover_visible = True
            log('startup: model loading indicator shown')


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
        on_toggle_copy=lambda: toggle_setting(settings, 'copy_on_close'),
        on_toggle_startup=lambda: toggle_setting(settings, 'run_at_startup'),
    )
    tray.on_box = request_box
    return tray


def start_request_worker():
    t = threading.Thread(target=_request_worker_loop, daemon=True)
    t.start()
    log(f'worker thread started: id={t.ident} alive={t.is_alive()}')


def _request_worker_loop():
    log(f'worker loop running ident={threading.get_ident()}')
    while True:
        try:
            box = _box_queue.get(timeout=1)
        except queue.Empty:
            continue
        log(f'worker got: {box}')
        try:
            _handle_box(*box)
        except Exception:
            log_exception('worker_loop')


def request_box(x, y, width, height, end_x, end_y):
    _cancel_event.clear()
    try:
        import translator
        translator.reset_cancel()
    except Exception:
        pass
    _box_queue.queue.clear()
    _box_queue.put((int(x), int(y), int(width), int(height), int(end_x), int(end_y)))
    log(f'request_box ident={threading.get_ident()}: {(int(x), int(y), int(width), int(height), int(end_x), int(end_y))}')


def _handle_box(x, y, width, height, end_x, end_y):
    old = clipboard.read_clipboard()
    log('step: clipboard -> ' + repr(old[:60]) if old else 'step: clipboard -> None')
    picked = clipboard.get_selected_text()
    text, rich = picked if isinstance(picked, tuple) else (picked, None)
    log('step: after ctrl+c -> ' + repr(text[:60]) if text else 'step: after ctrl+c -> None')
    if not text:
        text = old
        log('step: fallback -> ' + repr(text[:60]) if text else 'step: fallback -> None')
    if not text:
        return
    fmt = None
    if rich:
        try:
            fmt = clipboard.extract_format(rich)
            log(f'step: format -> {fmt}')
        except Exception:
            log_exception('format_extract')
    hide_popup()
    show_cover()
    log('step: cover shown')
    _show_placeholder(end_x, end_y)
    with _translating_lock:
        global _translating
        _translating = True
    try:
        translated = _translate_text(text)
        log('step: translated -> ' + repr(translated[:60]) if translated else 'step: translated -> None')
        if not translated or _cancel_event.is_set():
            return
        if _current_popup is not None and _cover_visible:
            _current_popup.show_translation(translated, None, fmt, (end_x, end_y))
            log('step: translation shown')
    finally:
        with _translating_lock:
            _translating = False


def _translate_text(text):
    try:
        import translator
        translated = translator.translate(text)
    except Exception as e:
        log(f'translate error: {e!r}')
        return None
    if not translated or translated.startswith('[Klaida]'):
        return None
    return translated


def _show_placeholder(end_x, end_y):
    if _current_popup is None or not _cover_visible:
        return
    _current_popup.show_status('Verčiama...', None, (end_x, end_y))
    log('step: placeholder -> Verčiama...')


def hide_popup():
    global _cover_visible
    if not _cover_visible or _current_popup is None:
        return
    _current_popup.hide(silent=True)
    _cover_visible = False
    time.sleep(0.1)


def show_cover():
    global _current_popup, _cover_visible
    if _current_popup is None:
        _current_popup = CoverPopup(on_hidden=cancel_work)
        _current_popup.start()
    _current_popup.cover(None)
    _cover_visible = True


def cancel_work():
    _cancel_event.set()
    try:
        import translator
        translator.cancel()
    except Exception:
        pass
    _box_queue.queue.clear()
    log('cancel: work cancelled')


def toggle_setting(settings, key):
    settings[key] = not settings.get(key, True if key == 'copy_on_close' else False)
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


if __name__ == '__main__':
    main()
