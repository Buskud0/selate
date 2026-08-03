"""In-place text editing for the Selate popup."""

import tkinter as tk

from popup_draw import BACKGROUND, TEXT_FOREGROUND
from popup_geom import _offset_from_index, _sel_range

EDIT_PAD = 8
SELECT_BACKGROUND = '#aed0f5'


class PopupEditor:
    """A tk.Text widget overlaid on the popup canvas for in-place editing."""

    def __init__(self, window, initial_text, justify):
        self._window = window
        self._initial_text = initial_text
        self._justify = justify
        self._widget = None
        self.on_change = None
        self.on_commit = None
        self.on_cancel = None
        self.on_font_zoom = None

    @property
    def active(self):
        return self._widget is not None

    def text(self):
        if self._widget is None:
            return ''
        return self._widget.get('1.0', 'end-1c')

    def open(self, font, width, height):
        widget = tk.Text(
            self._window, wrap='word', undo=True, autoseparators=True,
            font=font,
            bg=BACKGROUND, fg=TEXT_FOREGROUND, bd=0, relief='flat',
            highlightthickness=0, insertbackground=TEXT_FOREGROUND,
            selectbackground=SELECT_BACKGROUND, selectforeground=TEXT_FOREGROUND,
            padx=EDIT_PAD, pady=EDIT_PAD,
        )
        self._widget = widget
        widget.place(x=2, y=2, width=width - 4, height=height - 4)
        widget.insert('1.0', self._initial_text)
        widget.edit_reset()
        if self._justify != 'left':
            widget.tag_configure('just', justify=self._justify)
            widget.tag_add('just', '1.0', 'end')
        widget.tag_add('sel', '1.0', 'end-1c')
        widget.focus_set()
        widget.bind('<Return>', self._commit)
        widget.bind('<Shift-Return>', self._newline)
        widget.bind('<Escape>', self._cancel)
        widget.bind('<FocusOut>', self._commit)
        widget.bind('<KeyRelease>', self._change)
        widget.bind('<KeyPress>', self._press)
        widget.bind('<Control-z>', self._undo)
        widget.bind('<Control-y>', self._redo)
        widget.bind('<Control-Z>', self._redo)
        widget.bind('<Control-Y>', self._redo)
        widget.bind('<Control-MouseWheel>', self._font_zoom)

    def close(self):
        if self._widget is not None:
            self._widget.destroy()
            self._widget = None

    def set_size(self, width, height):
        if self._widget is not None:
            self._widget.place(x=2, y=2, width=width - 4, height=height - 4)

    def set_font(self, font):
        if self._widget is not None:
            self._widget.configure(font=font)

    def _font_zoom(self, event):
        if self.on_font_zoom is not None:
            self.on_font_zoom(event)
        return 'break'

    def _commit(self, event=None):
        if self._widget is None:
            return 'break'
        text = self.text()
        self.close()
        if self.on_commit is not None:
            self.on_commit(text)
        return 'break'

    def _cancel(self, event=None):
        if self._widget is None:
            return 'break'
        self.close()
        if self.on_cancel is not None:
            self.on_cancel()
        return 'break'

    def _newline(self, event):
        if self._widget is not None:
            self._widget.insert('insert', '\n')
        return 'break'

    def _change(self, event=None):
        if self._widget is None:
            return
        if self._justify != 'left':
            self._widget.tag_add('just', '1.0', 'end')
        if self.on_change is not None:
            self.on_change(self.text())

    def _press(self, event):
        if self._widget is None:
            return
        text = self.text()
        next_text = self._predict_next_text(text, event)
        if next_text is not None and self.on_change is not None:
            self.on_change(next_text)

    def _undo(self, event=None):
        if self._widget is not None:
            try:
                self._widget.edit_undo()
            except tk.TclError:
                pass
        return 'break'

    def _redo(self, event=None):
        if self._widget is not None:
            try:
                self._widget.edit_redo()
            except tk.TclError:
                pass
        return 'break'

    def _predict_next_text(self, text, event):
        offset = _offset_from_index(self._widget, 'insert')
        sel = _sel_range(self._widget)
        if sel is not None:
            start, end = sel
            chars = getattr(event, 'char', '') or ''
            if not chars or not chars.isprintable():
                return None
            return text[:start] + chars + text[end:]
        keysym = getattr(event, 'keysym', '')
        if keysym == 'BackSpace':
            if offset > 0:
                return text[:offset - 1] + text[offset:]
            return text
        if keysym == 'Delete':
            if offset < len(text):
                return text[:offset] + text[offset + 1:]
            return text
        chars = getattr(event, 'char', '') or ''
        if chars and chars.isprintable():
            return text[:offset] + chars + text[offset:]
        return None
