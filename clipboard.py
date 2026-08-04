import time

import win32api
import win32clipboard as wc
import win32con

RETRY_COUNT = 5
RETRY_DELAY = 0.08
COPY_POLL_ATTEMPTS = 10
COPY_POLL_DELAY = 0.15
CTRL = 0x11
KEY_C = 0x43

_MODIFIER_KEYS = (0x11, 0x10, 0x12, 0x5B)


def read_clipboard():
    return _read()


def write_clipboard(text):
    _write(text)


def get_selected_text():
    """Copy the current selection and return the selected text."""
    _release_all_modifiers()
    old_text = _read()
    _send_ctrl_c()
    text = _poll_for_change(old_text)
    if text is None:
        time.sleep(COPY_POLL_DELAY)
        text = _read()
        if text and text != old_text:
            text = text.strip()
    _restore(old_text)
    return text


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
    for _ in range(COPY_POLL_ATTEMPTS):
        text = _read()
        if text and text != old:
            return text.strip()
        time.sleep(COPY_POLL_DELAY)
    return None


def _restore(old_text):
    if old_text is not None:
        _write(old_text)


def _normalize_eol(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _read():
    for _ in range(RETRY_COUNT):
        try:
            wc.OpenClipboard()
            try:
                if wc.IsClipboardFormatAvailable(wc.CF_UNICODETEXT):
                    text = wc.GetClipboardData(wc.CF_UNICODETEXT)
                    return _normalize_eol(text) if text else None
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

