"""Selate popup window: a borderless, always-on-top translation bubble."""

import threading

from applog import log_exception
import config
from popup_draw import (
    DEFAULT_FONT_SIZE, FONT_STEP, MAX_FONT_SIZE, MIN_FONT_SIZE,
    _create_canvas, _create_window, _draw_box, _make_font,
)
from popup_editor import PopupEditor
from popup_geom import (
    MAX_WIDTH, MIN_HEIGHT, MIN_WIDTH, SCROLL_STEP, TEXT_PADDING,
    _center, _clamp, _corner_at, _default_translation_size, _fit_text_size,
    _place_at, _place_se, _resize_cursor, _size_for_text, _target_work_area,
    _text_wrap_width, _text_x_for, _wrap_width,
)

READY_TIMEOUT = 5
EDIT_SLACK = 12


class CoverPopup:
    """A single always-centered window with a rounded, outlined, translucent box."""

    def __init__(self, on_hidden=None, on_edited=None):
        self._window = None
        self._canvas = None
        self._closed = False
        self._ready = threading.Event()
        self._on_hidden = on_hidden
        self._on_edited = on_edited
        self._font_size = DEFAULT_FONT_SIZE
        self._drag_x = 0
        self._drag_y = 0
        self._moved = False
        self._current_text = ''
        self._current_fmt = None
        self._current_pos = 'center'
        self._current_anchor = None
        self._scroll_offset = 0
        self._scroll_max = 0
        self._text_item = None
        self._text_x = 0
        self._resizing = None
        self._dragging = False
        self._resize_geom = None
        self._resize_pos = None
        self._grips = {}
        self._editor = None
        self._locked = False
        self._topmost = config.load().get('always_on_top', True)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            window = _create_window(self._topmost)
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
            self._window = window
            self._canvas = canvas
            self._ready.set()
            window.mainloop()
        except Exception:
            log_exception('popup_run')
            self._closed = True

    def _on_left_press(self, event):
        if self._window is None or self._editor is not None or self._locked:
            return
        mode = _corner_at(event.x, event.y, self._window.winfo_width(), self._window.winfo_height())
        if mode:
            self._resizing = mode
            self._dragging = False
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
        self._moved = True

    def _on_zoom(self, event):
        if self._locked:
            return
        delta = event.delta
        step = FONT_STEP if delta > 0 else -FONT_STEP
        self._font_size = _clamp(self._font_size + step, MIN_FONT_SIZE, MAX_FONT_SIZE)
        width = self._window.winfo_width()
        height = self._window.winfo_height()
        self._draw_content(width, height)

    def _on_scroll(self, event):
        if self._locked:
            return
        if self._text_item is None or self._scroll_max <= 0:
            return
        units = event.delta // 120
        if units == 0:
            units = 1 if event.delta > 0 else -1
        self._scroll_offset = _clamp(
            self._scroll_offset - units * SCROLL_STEP, 0, self._scroll_max
        )
        try:
            self._canvas.coords(self._text_item, self._text_x, TEXT_PADDING - self._scroll_offset)
        except Exception:
            log_exception('popup.scroll')

    def _on_hover(self, event):
        if self._window is None or self._resizing or self._locked:
            return
        mode = _corner_at(event.x, event.y, self._window.winfo_width(), self._window.winfo_height())
        self._window.config(cursor=_resize_cursor(mode))
        for iid in self._grips.values():
            self._canvas.itemconfig(iid, state='normal')

    def _on_leave(self, event):
        if self._window is not None:
            self._window.config(cursor='arrow')
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
        self._font_size = self._fit_font_to_window(self._current_text, w, h)
        self._draw_content(w, h)

    def _fit_font_to_window(self, text, width, height):
        lo = MIN_FONT_SIZE
        hi = MAX_FONT_SIZE
        best = MIN_FONT_SIZE
        while lo <= hi:
            mid = (lo + hi) // 2
            font = _make_font(self._window, mid, self._current_fmt)
            wrap = _text_wrap_width(font, text, width)
            text_w, text_h = _size_for_text(text, font, TEXT_PADDING, wrap)
            if text_w <= width and text_h <= height:
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
        justify = 'right' if self._current_pos == 'se' else 'center'
        editor = PopupEditor(self._window, self._current_text, justify)
        editor.on_change = self._resize_to_fit
        editor.on_commit = self._finish_edit
        editor.on_cancel = self._cancel_edit_now
        editor.on_font_zoom = self._edit_font_zoom
        font = _make_font(self._window, self._font_size, self._current_fmt)
        editor.open(font, self._window.winfo_width(), self._window.winfo_height())
        self._editor = editor

    def _resize_to_fit(self, text):
        if self._window is None:
            return
        work = _target_work_area(self._current_anchor, self._current_pos)
        font = _make_font(self._window, self._font_size, self._current_fmt)
        width = self._window.winfo_width()
        wrap = max(1, width - 2 * TEXT_PADDING)
        _, full_height = _size_for_text(text, font, TEXT_PADDING, wrap)
        left, top, right, bottom = work
        max_h = max(80, bottom - top - 32)
        height = int(min(full_height + EDIT_SLACK, max_h))
        current_w = self._window.winfo_width()
        current_h = self._window.winfo_height()
        if (int(width), int(height)) == (current_w, current_h):
            return
        cx = self._window.winfo_x() + current_w // 2
        cy = self._window.winfo_y() + current_h // 2
        x = cx - width // 2
        y = cy - height // 2
        self._window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')
        self._window.update_idletasks()
        if self._editor is not None:
            self._editor.set_size(int(width), int(height))
        self._text_item = _draw_box(
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
        delta = event.delta
        step = FONT_STEP if delta > 0 else -FONT_STEP
        self._font_size = _clamp(self._font_size + step, MIN_FONT_SIZE, MAX_FONT_SIZE)
        font = _make_font(self._window, self._font_size, self._current_fmt)
        if self._editor is not None:
            self._editor.set_font(font)
            self._redraw_editor_box()

    def _redraw_editor_box(self):
        if self._window is None:
            return
        width = self._window.winfo_width()
        height = self._window.winfo_height()
        font = _make_font(self._window, self._font_size, self._current_fmt)
        if self._editor is not None:
            self._editor.set_size(int(width), int(height))
        text = self._editor.text() if self._editor is not None else self._current_text
        self._text_item = _draw_box(
            self._canvas, text, font, int(width), int(height), self._current_pos, self._grips
        )

    def set_topmost(self, value):
        self._topmost = bool(value)
        if self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('topmost', self._apply_topmost, self._topmost))

    def _apply_topmost(self, value):
        self._window.attributes('-topmost', value)

    def cover(self, geometries):
        self._ready.wait(READY_TIMEOUT)
        if self._closed or self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('cover', self._cover_now))

    def show_status(self, text, geometries, anchor=None):
        self._ready.wait(READY_TIMEOUT)
        if self._closed or self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('status', self._show_now, text, None, 'se', anchor, True))

    def show_translation(self, text, geometries, fmt=None, anchor=None):
        self._ready.wait(READY_TIMEOUT)
        if self._closed or self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('show', self._show_now, text, fmt, 'center', anchor))

    def _cover_now(self):
        self._locked = True
        self._moved = False
        self._current_text = ''
        self._current_fmt = None
        self._current_pos = 'center'
        self._current_anchor = None
        self._scroll_offset = 0
        self._scroll_max = 0
        self._text_item = None
        _center(self._window, 70, 40)
        self._window.update_idletasks()
        _draw_box(self._canvas, '', _make_font(self._window, self._font_size, None), 70, 40, 'center', self._grips)
        self._window.deiconify()

    def _show_now(self, text, fmt=None, pos='center', anchor=None, locked=False):
        self._locked = locked
        self._current_text = text
        self._current_fmt = fmt
        self._current_pos = pos
        self._current_anchor = anchor
        work = _target_work_area(anchor, pos)
        font = _make_font(self._window, self._font_size, fmt)
        if pos == 'center':
            width, height, scroll_max = _default_translation_size(font, text, work)
        else:
            wrap = _wrap_width(font, text, work)
            full_width, full_height = _size_for_text(text, font, TEXT_PADDING, wrap)
            width, height, scroll_max = _fit_text_size(full_width, full_height, work)
        if pos == 'se':
            _place_se(self._window, width, height)
        else:
            _place_at(self._window, width, height, anchor)
        self._window.update_idletasks()
        self._scroll_offset = 0
        self._scroll_max = scroll_max
        self._text_x = _text_x_for(width, pos)
        self._text_item = _draw_box(self._canvas, text, font, width, height, pos, self._grips)
        self._window.deiconify()

    def hide(self, silent=False):
        self._ready.wait(READY_TIMEOUT)
        if self._closed or self._window is None:
            return
        self._window.after(0, lambda: self._safe_call('hide', self._withdraw))
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
        font = _make_font(self._window, self._font_size, self._current_fmt)
        width = self._window.winfo_width()
        wrap = max(1, width - 2 * TEXT_PADDING)
        _, full_height = _size_for_text(self._current_text, font, TEXT_PADDING, wrap)
        left, top, right, bottom = work
        max_h = max(80, bottom - top - 32)
        height = int(_clamp(full_height, MIN_HEIGHT, max_h))
        scroll_max = max(0, full_height - height)
        if self._moved:
            x = self._window.winfo_x()
            y = self._window.winfo_y()
            self._window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')
        elif self._current_pos == 'se':
            _place_se(self._window, width, height)
        else:
            _place_at(self._window, width, height, self._current_anchor)
        self._window.update_idletasks()
        self._scroll_max = scroll_max
        self._scroll_offset = _clamp(self._scroll_offset, 0, self._scroll_max)
        self._draw_content(width, height)

    def _draw_content(self, width, height):
        font = _make_font(self._window, self._font_size, self._current_fmt)
        wrap = _text_wrap_width(font, self._current_text, width)
        _, full_height = _size_for_text(self._current_text, font, TEXT_PADDING, wrap)
        self._scroll_max = max(0, full_height - height)
        self._scroll_offset = _clamp(self._scroll_offset, 0, self._scroll_max)
        self._text_x = _text_x_for(width, self._current_pos)
        self._text_item = _draw_box(self._canvas, self._current_text, font, width, height, self._current_pos, self._grips)

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
