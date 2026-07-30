import os
import sys
import threading

import win32api
import win32event
import winerror

import clipboard
import config
import translator
from popup import PopupThread
from tray import TrayIcon

SINGLE_INSTANCE_MUTEX = "QuickTranslate-{8A2B1C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}"

_current_popup = None


def main():
    mutex = _ensure_single_instance()
    if mutex is None:
        return

    settings = config.load()
    translator.ensure_async()

    tray = _build_tray_icon(settings, mutex)
    tray.create()
    tray.run()


def _ensure_single_instance():
    mutex = win32event.CreateMutex(None, False, SINGLE_INSTANCE_MUTEX)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.MessageBox(
            0, "QuickTranslate jau paleistas.\nPažiūrėkite į system tray.",
            "QuickTranslate", 0x40
        )
        return None
    return mutex


def _build_tray_icon(settings, mutex):
    tray = TrayIcon(
        settings,
        on_quit=lambda: _quit(tray, mutex),
        on_toggle_copy=lambda: _toggle_setting(settings, 'copy_on_close'),
        on_toggle_startup=lambda: _toggle_setting(settings, 'run_at_startup'),
    )
    tray.on_hotkey = lambda: _handle_translate_request(settings)
    return tray


def _handle_translate_request(settings):
    _close_existing_popup()

    selected_text = clipboard.get_selected_text()
    if not selected_text:
        return

    popup = _show_popup()
    _show_loading_message_if_needed(popup)
    _start_translation_thread(popup, selected_text)

    def on_close():
        _copy_translation_if_enabled(popup, settings)
        _clear_popup()

    popup.on_close = on_close


def _close_existing_popup():
    global _current_popup
    if _current_popup and not _current_popup.is_closed:
        _current_popup.close()


def _show_popup():
    global _current_popup
    popup = PopupThread()
    _current_popup = popup
    popup.start()
    return popup


def _show_loading_message_if_needed(popup):
    if not translator.is_ready():
        popup.update_text("Kraunamas modelis…")


def _start_translation_thread(popup, text):
    def translate_and_update():
        result = translator.translate(text)
        if popup and not popup.is_closed:
            popup.update_text(result)

    threading.Thread(target=translate_and_update, daemon=True).start()


def _copy_translation_if_enabled(popup, settings):
    if not settings.get('copy_on_close'):
        return
    text = popup.get_text()
    if text and text not in ("Verčiama…", "Kraunamas modelis…") and not text.startswith("[Klaida"):
        clipboard.copy_text_to_clipboard(text)


def _clear_popup():
    global _current_popup
    _current_popup = None


def _toggle_setting(settings, key):
    settings[key] = not settings.get(key, True if key == 'copy_on_close' else False)
    config.save(settings)


def _quit(tray, mutex):
    _close_existing_popup()
    tray.destroy()
    win32api.CloseHandle(mutex)
    os._exit(0)


if __name__ == '__main__':
    main()
