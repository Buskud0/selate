"""Drawing and window plumbing for the Selate popup."""

import ctypes
import math
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

from applog import log
from popup_geom import CORNER, TEXT_PADDING, _text_wrap_width

ACCENT_ENABLE_BLURBEHIND = 3
WCA_ACCENT_POLICY = 19

MAGIC_COLOR = '#010203'
BACKGROUND = '#f0f4fa'
OUTLINE_COLOR = '#b0bccd'
OUTLINE_WIDTH = 1
RADIUS = 7
TEXT_FOREGROUND = '#1a1a1a'
WINDOW_ALPHA = 0.95
FONT_NAME = 'Segoe UI'
DEFAULT_FONT_SIZE = 12
MIN_FONT_SIZE = 5
MAX_FONT_SIZE = 40
FONT_STEP = 1
GRIP_STIPPLE = 'gray12'
HANDLE_COLOR = '#555555'
ARC_STEPS = 6


def _create_window(topmost=True, no_activate=False):
    window = tk.Tk()
    window.withdraw()
    window.overrideredirect(True)
    window.attributes('-topmost', topmost)
    window.attributes('-alpha', WINDOW_ALPHA)
    window.attributes('-transparentcolor', MAGIC_COLOR)
    window.configure(bg=MAGIC_COLOR)
    _enable_blur(window)
    if no_activate:
        _disable_activate(window)
    return window


def _disable_activate(window):
    try:
        hwnd = wintypes.HWND(window.winfo_id())
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000020)
    except Exception:
        pass


def _enable_blur(window):
    class ACCENTPOLICY(ctypes.Structure):
        _fields_ = [
            ('AccentState', wintypes.DWORD),
            ('AccentFlags', wintypes.DWORD),
            ('GradientColor', wintypes.DWORD),
            ('AnimationId', wintypes.DWORD),
        ]

    class WINCOMPATTRDATA(ctypes.Structure):
        _fields_ = [
            ('Attribute', wintypes.DWORD),
            ('Data', ctypes.POINTER(ACCENTPOLICY)),
            ('SizeOfData', ctypes.c_size_t),
        ]

    try:
        accent = ACCENTPOLICY(
            AccentState=ACCENT_ENABLE_BLURBEHIND,
            AccentFlags=0,
            GradientColor=0x00000000,
            AnimationId=0,
        )
        data = WINCOMPATTRDATA(
            Attribute=WCA_ACCENT_POLICY,
            Data=ctypes.pointer(accent),
            SizeOfData=ctypes.sizeof(accent),
        )
        hwnd = wintypes.HWND(window.winfo_id())
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception as e:
        log(f'blur enable error: {e!r}')


def _create_canvas(window):
    canvas = tk.Canvas(
        window,
        bg=MAGIC_COLOR,
        highlightthickness=0,
        bd=0,
        cursor='arrow',
    )
    canvas.pack(fill='both', expand=True)
    return canvas


def _make_font(master, size):
    return tkfont.Font(
        root=master,
        family=FONT_NAME,
        size=size,
        weight='normal',
        slant='roman',
        underline=0,
    )


def _draw_box(canvas, text, font, width, height, pos='center', grips=None):
    """Draw the box and the text. Returns a list of (item, x, y) text items."""
    if canvas is None:
        return []
    canvas.delete('all')
    _rounded_rect(
        canvas, 1, 1, width - 1, height - 1, RADIUS,
        fill=BACKGROUND, outline=OUTLINE_COLOR, width=OUTLINE_WIDTH,
    )
    _draw_corner_grips(canvas, width, height, grips)
    if not text:
        return []
    wrap_width = _text_wrap_width(font, text, width)
    return _draw_plain_text(canvas, text, font, wrap_width)


def _draw_plain_text(canvas, text, font, wrap_width):
    x = TEXT_PADDING
    iid = canvas.create_text(
        x, TEXT_PADDING,
        anchor='nw',
        text=text,
        font=font,
        fill=TEXT_FOREGROUND,
        justify='left',
        width=wrap_width,
    )
    return [(iid, x, TEXT_PADDING)]


def _measure_text(canvas, text, font, wrap_width):
    """Return the real (w, h) of the wrapped text as Tk would render it."""
    if not text:
        return font.measure(''), font.metrics('linespace')
    iid = canvas.create_text(
        -10000, -10000,
        anchor='nw',
        text=text,
        font=font,
        width=wrap_width,
    )
    try:
        bbox = canvas.bbox(iid)
    except Exception:
        bbox = None
    canvas.delete(iid)
    if bbox:
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    return font.measure(text), font.metrics('linespace')


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    r = max(1, min(r, (x2 - x1) // 2, (y2 - y1) // 2))
    points = []
    points.extend(_arc_points(x2 - r, y1 + r, -90, 0, r))
    points.extend(_arc_points(x2 - r, y2 - r, 0, 90, r))
    points.extend(_arc_points(x1 + r, y2 - r, 90, 180, r))
    points.extend(_arc_points(x1 + r, y1 + r, 180, 270, r))
    return canvas.create_polygon(points, smooth=True, **kwargs)


def _arc_points(cx, cy, start_deg, end_deg, r):
    points = []
    for i in range(ARC_STEPS + 1):
        angle = math.radians(start_deg + (end_deg - start_deg) * i / ARC_STEPS)
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def _draw_corner_grips(canvas, width, height, grips=None):
    s = CORNER
    r = min(8, RADIUS)
    if grips is not None:
        grips.clear()
    for name, (x, y) in zip(
        ('nw', 'ne', 'sw', 'se'),
        ((0, 0), (width - s, 0), (0, height - s), (width - s, height - s)),
    ):
        iid = _rounded_rect(
            canvas, x, y, x + s, y + s, r,
            fill=HANDLE_COLOR, outline='', stipple=GRIP_STIPPLE,
        )
        canvas.itemconfig(iid, state='hidden')
        if grips is not None:
            grips[name] = iid
