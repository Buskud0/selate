import threading
import tkinter as tk

PADX = 14
PADY = 10


class PopupThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._window = None
        self._label = None
        self._result = None
        self._closed = False
        self._ready = threading.Event()
        self.on_close = None

    def run(self):
        w = tk.Tk()
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.configure(bg='#ffffe0')

        lbl = tk.Label(
            w, text="Verčiama…",
            bg='#ffffe0', fg='#000000',
            font=('Segoe UI', 11),
            wraplength=700,
            padx=PADX, pady=PADY,
            cursor='hand2'
        )
        lbl.pack()

        def _close():
            if self._closed:
                return
            self._closed = True
            if w:
                w.quit()
                w.destroy()
            cb = self.on_close
            if cb:
                cb()

        lbl.bind('<Button-1>', lambda e: _close())
        w.focus_set()
        w.bind('<Escape>', lambda e: _close())
        w.protocol("WM_DELETE_WINDOW", _close)

        self._center(w)
        self._window = w
        self._label = lbl
        self._ready.set()
        w.mainloop()

    def _center(self, w):
        w.update_idletasks()
        sw = w.winfo_screenwidth()
        sh = w.winfo_screenheight()
        x = (sw - w.winfo_reqwidth()) // 2
        y = (sh - w.winfo_reqheight()) // 2
        w.geometry(f'+{x}+{y}')

    def update_text(self, text):
        self._result = text
        self._ready.wait()
        if self._window and not self._closed:
            self._window.after(0, lambda: self._update(text))

    def _update(self, text):
        if self._closed or not self._window:
            return
        self._label.config(text=text)
        self._center(self._window)

    def get_text(self):
        return self._result

    def close(self):
        self._ready.wait()
        if self._window and not self._closed:
            self._closed = True
            self._window.after(0, self._window.destroy)

    @property
    def is_closed(self):
        return self._closed
