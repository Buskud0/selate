"""Selate popup window: a borderless, always-on-top translation bubble."""

import threading

from applog import log_exception
import config
from popup_draw import (
    DEFAULT_FONT_SIZE, FONT_STEP, MAX_FONT_SIZE, MIN_FONT_SIZE,
    _create_canvas, _create_window, _draw_box, _make_font, _measure_text,
)
from popup_editor import PopupEditor
from popup_geom import (
    DEFAULT_WIDTH, EMPTY_POPUP_HEIGHT, EMPTY_POPUP_WIDTH,
    MIN_HEIGHT, MIN_WIDTH, SCROLL_STEP, TEXT_PADDING,
    _center, _clamp, _corner_at, _count_lines, _default_translation_size,
    _fit_text_size, _place_at, _place_se, _resize_cursor, _size_for_text,
    _target_work_area, _text_wrap_width, _wrap_width,
)

READY_TIMEOUT = 5


class CoverPopup:
    """A single always-centered window with a rounded, outlined, translucent box."""

    def __init__(self, on_hidden=None, on_edited=None, no_activate=False):
        self._no_activate = no_activate
        self._window = None
        self._canvas = None
        self._closed = False
        self._ready = threading.Event()
        self._on_hidden = on_hidden
        self._on_edited = on_edited
        self._font_size = DEFAULT_FONT_SIZE
        self._drag_x = 0
        self._drag_y = 0
        self._current_text = ''
        self._current_pos = 'center'
        self._current_anchor = None
        self._scroll_offset = 0
        self._scroll_max = 0
        self._text_items = []
        self._resizing = None
        self._dragging = False
        self._resize_geom = None
        self._resize_pos = None
        self._last_resize_w = None
        self._last_resize_h = None
        self._grips = {}
        self._editor = None
        self._edit_base_w = None
        self._locked = False
        self._topmost = config.load().get('always_on_top', True)
        self.on_history = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def wait_ready(self, timeout=None):
        self._ready.wait(timeout)

    def _run(self):
        try:
            window = _create_window(self._topmost, self._no_activate)
            canvas = _create_canvas(window)
            window.bind('<Control-MouseWheel>', self._on_zoom)
            window.bind('<MouseWheel>', self._on_scroll)
            window.bind('<Motion>', self._on_hover)
            window.bind('<Leave>', self._on_leave)
            window.bind('<Button-1>', self._on_left_press)
            window.bind('<B1-Motion>', self._on_left_drag)
            window.bind('<ButtonRelease-1>', self._on_release)
            window.bind('<Button-3>', lambda e: self.hide())
            window.bind('<Double-Button-1>', self._on_edit_start)
            window.bind('<Escape>', lambda e: self.hide())
            window.bind('<Control-KeyPress-1>', self._on_history)
            window.bind('<Control-KeyPress-2>', self._on_history)
            window.bind('<Control-KeyPress-3>', self._on_history)
            self._window = window
            self._canvas = canvas
            self._ready.set()
            window.mainloop()
        except Exception:
            log_exception('popup_run')
            self._closed = True
            self._ready.set()

    def _on_left_press(self, event):
        if self._window is None or self._editor is not None or self._locked:
            return
        mode = _corner_at(event.x, event.y, self._window.winfo_width(), self._window.winfo_height())
        if mode:
            self._resizing = mode
            self._dragging = False
            self._last_resize_w = None
            self._last_resize_h = None
            self._resize_geom = (
                self._window.winfo_x(), self._window.winfo_y(),
                self._window.winfo_width(), self._window.winfo_height(),
            )
            self._resize_pos = (event.x_root, event.y_root)
            return
        self._dragging = True
        self._resizing = None
        self._drag_x = event.x_root - self._window.winfo_x()
        self._drag_y = event.y_root - self._window.winfo_y()

    def _on_left_drag(self, event):
        if self._window is None:
            return
        if self._resizing:
            self._on_resize(event)
        elif self._dragging:
            self._on_drag_move(event)

    def _on_drag_move(self, event):
        if self._window is None:
            return
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._window.geometry(f'+{int(x)}+{int(y)}')

    def _bump_font_size(self, delta):
        step = FONT_STEP if delta > 0 else -FONT_STEP
        self._font_size = _clamp(self._font_size + step, MIN_FONT_SIZE, MAX_FONT_SIZE)

    def _on_zoom(self, event):
        if self._locked:
            return
        self._bump_font_size(event.delta)
        width = self._window.winfo_width()
        height = self._window.winfo_height()
        self._draw_content(width, height)

    def _on_scroll(self, event):
        if self._locked:
            return
        if not self._text_items or self._scroll_max <= 0:
            return
        units = event.delta // 120
        if units == 0:
            units = 1 if event.delta > 0 else -1
        self._scroll_offset = _clamp(
            self._scroll_offset - units * SCROLL_STEP, 0, self._scroll_max
        )
        try:
            for iid, x, y in self._text_items:
                self._canvas.coords(iid, x, y - self._scroll_offset)
        except Exception:
            log_exception('popup.scroll')

    def _on_hover(self, event):
        if self._window is None or self._resizing or self._locked:
            return
        mode = _corner_at(event.x, event.y, self._window.winfo_width(), self._window.winfo_height())
        self._canvas.config(cursor=_resize_cursor(mode))
        for iid in self._grips.values():
            self._canvas.itemconfig(iid, state='normal')

    def _on_leave(self, event):
        if self._window is not None:
            self._canvas.config(cursor='arrow')
        for iid in self._grips.values():
            try:
                self._canvas.itemconfig(iid, state='hidden')
            except Exception:
                pass

    def _on_resize(self, event):
        if not self._resizing:
            return
        mode = self._resizing
        x0, y0, w0, h0 = self._resize_geom
        sx, sy = self._resize_pos
        dx = event.x_root - sx
        dy = event.y_root - sy
        x, y, w, h = x0, y0, w0, h0
        if 'e' in mode:
            w = max(MIN_WIDTH, w0 + dx)
        if 's' in mode:
            h = max(MIN_HEIGHT, h0 + dy)
        if 'w' in mode:
            w = max(MIN_WIDTH, w0 - dx)
            x = x0 + w0 - w
        if 'n' in mode:
            h = max(MIN_HEIGHT, h0 - dy)
            y = y0 + h0 - h
        self._window.geometry(f'{int(w)}x{int(h)}+{int(x)}+{int(y)}')
        if (w, h) != (self._last_resize_w, self._last_resize_h):
            self._last_resize_w, self._last_resize_h = w, h
            self._font_size = self._fit_font_to_window(self._current_text, w, h)
            self._draw_content(w, h)

    def _fit_font_to_window(self, text, width, height):
        lo = MIN_FONT_SIZE
        hi = MAX_FONT_SIZE
        best = MIN_FONT_SIZE
        max_h = max(1, height - 2 * TEXT_PADDING)
        while lo <= hi:
            mid = (lo + hi) // 2
            font = _make_font(self._window, mid)
            wrap = _text_wrap_width(font, text, width)
            text_w, text_h = _measure_text(self._canvas, text, font, wrap)
            if text_w <= width and text_h <= max_h:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def _on_release(self, event):
        self._resizing = None
        self._dragging = False

    def _on_edit_start(self, event):
        if self._window is None or self._editor is not None or not self._current_text or self._locked:
            return
        if _corner_at(event.x, event.y, self._window.winfo_width(), self._window.winfo_height()):
            return
        self._edit_base_w = self._window.winfo_width()
        editor = PopupEditor(self._window, self._current_text)
        editor.on_change = self._resize_to_fit
        editor.on_commit = self._finish_edit
        editor.on_cancel = self._cancel_edit_now
        editor.on_font_zoom = self._edit_font_zoom
        font = _make_font(self._window, self._font_size)
        editor.open(font, self._window.winfo_width(), self._window.winfo_height())
        self._editor = editor

    def _resize_to_fit(self, text):
        if self._window is None:
            return
        work = _target_work_area(self._current_anchor, self._current_pos)
        font = _make_font(self._window, self._font_size)
        current_w = self._window.winfo_width()
        current_h = self._window.winfo_height()
        left, top, right, bottom = work
        base_w = self._edit_base_w or current_w
        base_w = max(MIN_WIDTH, min(base_w, right - left - 32))
        wrap_limit = max(DEFAULT_WIDTH, base_w)
        if _count_lines(text, wrap_limit - 2 * TEXT_PADDING, font) == 1:
            natural = font.measure(text) + 2 * TEXT_PADDING
            width = max(MIN_WIDTH, min(int(natural), wrap_limit))
        else:
            width = wrap_limit
        wrap = max(1, width - 2 * TEXT_PADDING)
        _, full_height = _size_for_text(text, font, TEXT_PADDING, wrap)
        max_h = max(80, bottom - top - 32)
        height = int(_clamp(full_height, MIN_HEIGHT, max_h))
        if (width, height) == (current_w, current_h):
            return
        if width != current_w:
            x = self._window.winfo_x() + (current_w - width) // 2
        else:
            x = self._window.winfo_x()
        y = self._window.winfo_y()
        self._window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')
        self._window.update_idletasks()
        if self._editor is not None:
            self._editor.set_size(int(width), int(height))
        self._text_items = _draw_box(
            self._canvas, text, font, int(width), int(height), self._current_pos, self._grips
        )

    def _finish_edit(self, text):
        self._editor = None
        if not text.strip():
            self.hide()
            return
        if text != self._current_text:
            self._current_text = text
            self._scroll_offset = 0
            self._redraw()
        if self._on_edited is not None:
            try:
                self._on_edited(text)
            except Exception:
                log_exception('popup.edited')

    def _cancel_edit_now(self):
        self._editor = None
        self._redraw()

    def _edit_font_zoom(self, event):
        if self._window is None or self._locked:
            return
        self._bump_font_size(event.delta)
        font = _make_font(self._window, self._font_size)
        if self._editor is not None:
            self._editor.set_font(font)
            self._redraw_editor_box()

    def _redraw_editor_box(self):
        if self._window is None:
            return
        width = self._window.winfo_width()
        height = self._window.winfo_height()
        font = _make_font(self._window, self._font_size)
        if self._editor is not None:
            self._editor.set_size(int(width), int(height))
        text = self._editor.text() if self._editor is not None else self._current_text
        self._text_items = _draw_box(
            self._canvas, self._current_text, font, width, height, self._current_pos, self._grips
        )

    def set_topmost(self, value):
        self._topmost = bool(value)
        if self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('topmost', self._apply_topmost, self._topmost))

    def _apply_topmost(self, value):
        self._window.attributes('-topmost', value)

    def _dispatch(self, where, fn, *args):
        self._ready.wait(READY_TIMEOUT)
        if self._closed or self._window is None:
            return
        self._window.after(0, lambda: self._safe_call(where, fn, *args))

    def cover(self, geometries):
        self._dispatch('cover', self._cover_now)

    def show_status(self, text, geometries, anchor=None):
        self._dispatch('status', self._show_now, text, 'se', anchor, True)

    def show_translation(self, text, geometries, anchor=None):
        self._dispatch('show', self._show_now, text, 'center', anchor)

    def show_history(self, text):
        self._dispatch('hist', self._show_now, text, 'center', None, False, True)

    def _on_history(self, event):
        if self._window is None or self._editor is not None or self._locked:
            return
        if self.on_history is None:
            return
        num = event.keysym
        if num in ('1', '2', '3'):
            try:
                self.on_history(int(num))
            except Exception:
                log_exception('popup.history')

    def _cover_now(self):
        self._locked = True
        self._current_text = ''
        self._current_pos = 'center'
        self._current_anchor = None
        self._scroll_offset = 0
        self._scroll_max = 0
        self._text_items = []
        _center(self._window, EMPTY_POPUP_WIDTH, EMPTY_POPUP_HEIGHT)
        self._window.update_idletasks()
        _draw_box(
            self._canvas, '',
            _make_font(self._window, self._font_size),
            EMPTY_POPUP_WIDTH, EMPTY_POPUP_HEIGHT, 'center', self._grips,
        )
        self._window.deiconify()

    def _show_now(self, text, pos='center', anchor=None, locked=False, keep_pos=False):
        if not text or not text.strip():
            return
        self._locked = locked
        self._current_text = text
        self._current_pos = pos
        self._current_anchor = anchor
        work = _target_work_area(anchor, pos)
        font = _make_font(self._window, self._font_size)
        if pos == 'center':
            width, height, scroll_max = _default_translation_size(font, text, work)
        else:
            wrap = _wrap_width(font, text, work)
            full_width, full_height = _size_for_text(text, font, TEXT_PADDING, wrap)
            width, height, scroll_max = _fit_text_size(full_width, full_height, work)
        if keep_pos:
            x = self._window.winfo_x()
            y = self._window.winfo_y()
            self._window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')
        elif pos == 'se':
            _place_se(self._window, width, height)
        else:
            _place_at(self._window, width, height, anchor)
        self._window.update_idletasks()
        self._scroll_offset = 0
        self._scroll_max = scroll_max
        self._text_items = _draw_box(self._canvas, text, font, width, height, pos, self._grips)
        self._window.deiconify()
        if not locked:
            try:
                self._window.focus_force()
            except Exception:
                pass

    def hide(self, silent=False):
        self._dispatch('hide', self._withdraw)
        if not silent and self._on_hidden is not None:
            self._on_hidden()

    def _withdraw(self):
        if self._editor is not None:
            self._editor.close()
            self._editor = None
        self._window.withdraw()

    def _redraw(self):
        if not self._current_text:
            return
        work = _target_work_area(self._current_anchor, self._current_pos)
        font = _make_font(self._window, self._font_size)
        width = self._window.winfo_width()
        wrap = max(1, width - 2 * TEXT_PADDING)
        _, full_height = _size_for_text(self._current_text, font, TEXT_PADDING, wrap)
        left, top, right, bottom = work
        max_h = max(80, bottom - top - 32)
        height = int(_clamp(full_height, MIN_HEIGHT, max_h))
        scroll_max = max(0, full_height - height)
        x = self._window.winfo_x()
        y = self._window.winfo_y()
        self._window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')
        self._window.update_idletasks()
        self._scroll_max = scroll_max
        self._scroll_offset = _clamp(self._scroll_offset, 0, self._scroll_max)
        self._draw_content(width, height)

    def _draw_content(self, width, height):
        font = _make_font(self._window, self._font_size)
        wrap = _text_wrap_width(font, self._current_text, width)
        _, full_height = _size_for_text(self._current_text, font, TEXT_PADDING, wrap)
        self._scroll_max = max(0, full_height - height)
        self._scroll_offset = _clamp(self._scroll_offset, 0, self._scroll_max)
        self._text_items = _draw_box(
            self._canvas, self._current_text, font, width, height, self._current_pos, self._grips
        )

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
