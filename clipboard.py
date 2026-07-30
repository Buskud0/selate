import time

import win32api
import win32clipboard as wc
import win32con

RETRY_COUNT = 3
RETRY_DELAY = 0.05
CTRL = 0x11
KEY_C = 0x43

_MODIFIER_KEYS = (0x11, 0x10, 0x12, 0x5B)


def get_selected_text():
    _release_all_modifiers()
    old = _read()
    _send_ctrl_c()
    text = _poll_for_change(old)
    _restore(old)
    return text


def copy_text_to_clipboard(text):
    _write(text)


def _release_all_modifiers():
    for vk in _MODIFIER_KEYS:
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)


def _send_ctrl_c():
    win32api.keybd_event(CTRL, 0, 0, 0)
    win32api.keybd_event(KEY_C, 0, 0, 0)
    time.sleep(0.1)
    win32api.keybd_event(KEY_C, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(CTRL, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.1)


def _poll_for_change(old):
    for _ in range(5):
        text = _read()
        if text and text != old:
            return text.strip()
        time.sleep(0.1)
    return None


def _restore(old):
    if old is not None:
        _write(old)


def _read():
    for _ in range(RETRY_COUNT):
        try:
            wc.OpenClipboard()
            try:
                if wc.IsClipboardFormatAvailable(wc.CF_UNICODETEXT):
                    return wc.GetClipboardData(wc.CF_UNICODETEXT)
                return None
            finally:
                wc.CloseClipboard()
        except Exception:
            time.sleep(RETRY_DELAY)
    return None


def _write(text):
    for _ in range(RETRY_COUNT):
        try:
            wc.OpenClipboard()
            try:
                wc.EmptyClipboard()
                wc.SetClipboardData(wc.CF_UNICODETEXT, text)
            finally:
                wc.CloseClipboard()
            return
        except Exception:
            time.sleep(RETRY_DELAY)
