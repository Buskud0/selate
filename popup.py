import ctypes
import math
import threading
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

import screen
from applog import log, log_exception

ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
ACCENT_ENABLE_TRANSPARENTGRADIENT = 2
WCA_ACCENT_POLICY = 19

MAGIC_COLOR = '#010203'
BACKGROUND = '#f0f4fa'
OUTLINE_COLOR = '#b0bccd'
OUTLINE_WIDTH = 1
RADIUS = 10
TEXT_FOREGROUND = '#1a1a1a'
WINDOW_ALPHA = 0.95
MAX_WIDTH = 600
READY_TIMEOUT = 5
TEXT_PADDING = 10
FONT_NAME = 'Segoe UI'
DEFAULT_FONT_SIZE = 12
MIN_FONT_SIZE = 9
MAX_FONT_SIZE = 40
FONT_STEP = 1
ARC_STEPS = 6


class CoverPopup:
    """A single always-centered window with a rounded, outlined, translucent box."""

    def __init__(self, on_hidden=None):
        self._window = None
        self._canvas = None
        self._closed = False
        self._ready = threading.Event()
        self._on_hidden = on_hidden
        self._font_size = DEFAULT_FONT_SIZE
        self._drag_x = 0
        self._drag_y = 0
        self._moved = False
        self._custom_center = None
        self._current_text = ''
        self._current_fmt = None
        self._current_pos = 'center'
        self._current_anchor = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            window = _create_window()
            canvas = _create_canvas(window)
            window.bind('<Control-MouseWheel>', self._on_zoom)
            window.bind('<Button-1>', lambda e: self.hide())
            window.bind('<Escape>', lambda e: self.hide())
            window.bind('<Button-3>', self._on_drag_start)
            window.bind('<B3-Motion>', self._on_drag_move)
            self._window = window
            self._canvas = canvas
            self._ready.set()
            window.mainloop()
        except Exception:
            log_exception('popup_run')
            self._closed = True

    def _on_drag_start(self, event):
        if self._window is None:
            return
        self._drag_x = event.x_root - self._window.winfo_x()
        self._drag_y = event.y_root - self._window.winfo_y()

    def _on_drag_move(self, event):
        if self._window is None:
            return
        width = self._window.winfo_width()
        height = self._window.winfo_height()
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._window.geometry(f'+{int(x)}+{int(y)}')
        self._moved = True
        self._custom_center = (x + width // 2, y + height // 2)

    def _on_zoom(self, event):
        delta = event.delta
        step = FONT_STEP if delta > 0 else -FONT_STEP
        self._font_size = _clamp(self._font_size + step, MIN_FONT_SIZE, MAX_FONT_SIZE)
        self._redraw()

    def cover(self, geometries):
        self._ready.wait(READY_TIMEOUT)
        if self._closed or self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('cover', self._cover_now))
    def show_status(self, text, geometries, anchor=None):
        self._ready.wait(READY_TIMEOUT)
        if self._closed or self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('status', self._show_now, text, None, 'se', anchor))

    def show_translation(self, text, geometries, fmt=None, anchor=None):
        self._ready.wait(READY_TIMEOUT)
        if self._closed or self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('show', self._show_now, text, fmt, 'center', anchor))

    def _cover_now(self):
        self._moved = False
        self._custom_center = None
        self._current_text = ''
        self._current_fmt = None
        self._current_pos = 'center'
        self._current_anchor = None
        self._window.deiconify()
        _center(self._window, 70, 40)
        self._window.update_idletasks()
        _draw_box(self._canvas, '', _make_font(self._window, self._font_size, None), 70, 40, 'center')

    def _show_now(self, text, fmt=None, pos='center', anchor=None):
        self._current_text = text
        self._current_fmt = fmt
        self._current_pos = pos
        self._current_anchor = anchor
        font = _make_font(self._window, self._font_size, fmt)
        width, height = _size_for_text(text, font, TEXT_PADDING)
        if pos == 'se':
            _place_se(self._window, width, height)
        else:
            _place_at(self._window, width, height, anchor)
        self._window.deiconify()
        self._window.update_idletasks()
        _draw_box(self._canvas, text, font, width, height, pos)

    def hide(self, silent=False):
        self._ready.wait(READY_TIMEOUT)
        if self._closed or self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('hide', self._window.withdraw))
        if not silent and self._on_hidden is not None:
            self._on_hidden()

    def _redraw(self):
        if not self._current_text:
            return
        font = _make_font(self._window, self._font_size, self._current_fmt)
        width, height = _size_for_text(self._current_text, font, TEXT_PADDING)
        if self._current_pos == 'se':
            _place_se(self._window, width, height)
        else:
            _place_at(self._window, width, height, self._current_anchor)
        _draw_box(self._canvas, self._current_text, font, width, height, self._current_pos)

    def _safe_call(self, where, fn, *args):
        try:
            fn(*args)
        except Exception:
            log_exception('popup.' + where)

    def current_text(self):
        return self._current_text

    def destroy(self):
        self._ready.wait(READY_TIMEOUT)
        self._closed = True
        if self._window is not None:
            self._window.after(0, self._window.destroy)


def _create_window():
    window = tk.Tk()
    window.overrideredirect(True)
    window.attributes('-topmost', True)
    window.attributes('-alpha', WINDOW_ALPHA)
    window.attributes('-transparentcolor', MAGIC_COLOR)
    window.configure(bg=MAGIC_COLOR)
    _enable_blur(window)
    return window


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
        # GradientColor tint: light blue over blurred content.
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
        ok = user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        log(f'blur enabled: ok={bool(ok)} err={ctypes.get_last_error()}')
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


def _draw_box(canvas, text, font, width, height, pos='center'):
    if canvas is None:
        return
    canvas.delete('all')
    _rounded_rect(
        canvas, 1, 1, width - 1, height - 1, RADIUS,
        fill=BACKGROUND, outline=OUTLINE_COLOR, width=OUTLINE_WIDTH,
    )
    if text:
        wrap_width = max(1, min(MAX_WIDTH - 2 * TEXT_PADDING, font.measure(text)))
        if pos == 'se':
            canvas.create_text(
                width - TEXT_PADDING, height - TEXT_PADDING,
                anchor='se',
                text=text,
                font=font,
                fill=TEXT_FOREGROUND,
                justify='right',
            )
        else:
            canvas.create_text(
                width // 2, height // 2,
                anchor='center',
                text=text,
                font=font,
                fill=TEXT_FOREGROUND,
                justify='center',
                width=wrap_width,
            )

def _rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    r = max(1, min(r, (x2 - x1) // 2, (y2 - y1) // 2))
    points = []
    # Top edge, top-right corner, right edge, bottom-right corner,
    # bottom edge, bottom-left corner, left edge, top-left corner.
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


def _make_font(master, size, fmt=None):
    family = FONT_NAME
    weight = 'normal'
    slant = 'roman'
    underline = 0
    if fmt:
        family = fmt.get('family') or FONT_NAME
        weight = 'bold' if fmt.get('bold') else 'normal'
        slant = 'italic' if fmt.get('italic') else 'roman'
        underline = 1 if fmt.get('underline') else 0
    return tkfont.Font(
        root=master,
        family=family,
        size=size,
        weight=weight,
        slant=slant,
        underline=underline,
    )


def _size_for_text(text, font, padding):
    if not text:
        return 70, 40
    wrap_width = min(MAX_WIDTH - 2 * padding, font.measure(text))
    wrap_width = max(1, wrap_width)
    line_height = font.metrics('linespace')
    lines = _count_lines(text, wrap_width, font)
    width = min(wrap_width + 2 * padding, MAX_WIDTH)
    height = max(1, lines) * line_height + 2 * padding
    return width, height


def _count_lines(text, wrap_width, font):
    if not text:
        return 1
    total = 0
    for paragraph in text.split('\n'):
        words = paragraph.split(' ')
        lines = 1
        current = ''
        for word in words:
            candidate = current + (' ' if current else '') + word
            if font.measure(candidate) <= wrap_width or not current:
                current = candidate
            else:
                lines += 1
                current = word
        total += lines
    return total


def _center(window, width, height):
    _place(window, width, height, None)


def _place(window, width, height, center):
    if center is None:
        work = screen.primary_work_area()
        left, top, right, bottom = work
        cx = left + (right - left) // 2
        cy = top + (bottom - top) // 2
    else:
        cx, cy = center
    x = cx - width // 2
    y = cy - height // 2
    window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')


def _place_se(window, width, height):
    try:
        import win32api
        mx, my = win32api.GetCursorPos()
        work = screen.work_area_at(mx, my)
    except Exception:
        work = screen.primary_work_area()
    left, top, right, bottom = work
    x = right - width - 16
    y = bottom - height - 12
    window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')


def _place_at(window, width, height, anchor):
    if anchor:
        ax, ay = anchor
        work = screen.work_area_at(ax, ay)
        left, top, right, bottom = work
        cx = left + (right - left) // 2
        x = cx - width // 2
        y = ay - height // 2
        y = max(top, min(y, bottom - height))
    else:
        work = screen.primary_work_area()
        left, top, right, bottom = work
        x = left + (right - left - width) // 2
        y = top + (bottom - top - height) // 2
    window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')


def _clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))
