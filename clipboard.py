import re
import time

import win32api
import win32clipboard as wc
import win32con

RETRY_COUNT = 3
RETRY_DELAY = 0.05
CTRL = 0x11
KEY_C = 0x43

_MODIFIER_KEYS = (0x11, 0x10, 0x12, 0x5B)

CF_RTF = wc.RegisterClipboardFormat('Rich Text Format')
CF_HTML = wc.RegisterClipboardFormat('HTML Format')


def read_clipboard():
    return _read()


def get_selected_text():
    """Copy the current selection and return (text, format_info)."""
    _release_all_modifiers()
    old_text = _read()
    old_rich = _read_rich()
    _send_ctrl_c()
    text = _poll_for_change(old_text)
    rich = _read_rich()
    _restore(old_text, old_rich)
    if not text and old_rich:
        return old_text, old_rich
    return text, rich


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


def _restore(old_text, old_rich=None):
    if old_text is not None:
        _write(old_text)
        if old_rich:
            _write_rich(old_rich)


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


def _read_rich():
    """Read the clipboard's rich data (RTF or HTML) as a string, or None."""
    for _ in range(RETRY_COUNT):
        try:
            wc.OpenClipboard()
            try:
                for cfid in (CF_RTF, CF_HTML):
                    if wc.IsClipboardFormatAvailable(cfid):
                        data = wc.GetClipboardData(cfid)
                        return _decode_rich(data)
                return None
            finally:
                wc.CloseClipboard()
        except Exception:
            time.sleep(RETRY_DELAY)
    return None


def _write_rich(data):
    for _ in range(RETRY_COUNT):
        try:
            wc.OpenClipboard()
            try:
                wc.EmptyClipboard()
                wc.SetClipboardData(wc.CF_UNICODETEXT, data.get('text', ''))
                if data.get('rtf'):
                    wc.SetClipboardData(CF_RTF, data['rtf'])
                if data.get('html'):
                    wc.SetClipboardData(CF_HTML, data['html'])
            finally:
                wc.CloseClipboard()
            return
        except Exception:
            time.sleep(RETRY_DELAY)


def _decode_rich(data):
    if isinstance(data, bytes):
        return {'raw': data, 'text': None, 'rtf': None, 'html': None}
    return {'raw': data, 'text': None, 'rtf': None, 'html': None}


def extract_format(data):
    """Parse rich clipboard data (from _read_rich) into a format dict."""
    raw = data.get('raw', '')
    if isinstance(raw, str):
        if raw.lstrip().startswith('{\\rtf'):
            return _parse_rtf(raw)
        return _parse_html(raw)
    return None


def _parse_rtf(rtf):
    fmt = {}
    entries = re.findall(r'\{[^{}]*\\f\d+[^{}]*;}', rtf)
    names = []
    for entry in entries:
        clean = entry.strip('{}')
        tokens = re.split(r'\\[a-zA-Z]+\d*', clean)
        if tokens:
            name = tokens[-1].strip().rstrip(';').strip()
            if name:
                names.append(name)
    if names:
        fmt['family'] = names[0]
    m = re.search(r'\\fs(\d+)', rtf)
    if m:
        fmt['size'] = int(m.group(1)) / 2.0
    fmt['bold'] = bool(re.search(r'\\b\b', rtf))
    fmt['italic'] = bool(re.search(r'\\i\b', rtf))
    fmt['underline'] = bool(re.search(r'\\ul\b', rtf))
    return fmt


def _parse_html(html):
    fmt = {}
    m = re.search(r"font-family:\s*([^;\"]+)", html)
    if m:
        fmt['family'] = m.group(1).strip().strip("'\"")
    m = re.search(r"font-size:\s*(\d+(?:\.\d+)?)pt", html)
    if m:
        fmt['size'] = float(m.group(1))
    else:
        m = re.search(r"font-size:\s*(\d+(?:\.\d+)?)px", html)
        if m:
            fmt['size'] = float(m.group(1)) * 0.75
    fmt['bold'] = bool(re.search(r'<(?:b|strong)\b', html, re.I))
    fmt['italic'] = bool(re.search(r'<(?:i|em)\b', html, re.I))
    fmt['underline'] = bool(re.search(r'<(?:u|ins)\b', html, re.I))
    return fmt
