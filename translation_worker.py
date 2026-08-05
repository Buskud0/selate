"""Translation request orchestration (single responsibility: turning a
selection box into a translated popup; dependencies injected for testability)."""

import queue
import threading
import time

from applog import log, log_exception
import config
import messages
import status

MODEL_WAIT_POLL_SECONDS = 0.2


class TranslationWorker:
    """Runs a single worker thread that consumes selection boxes, reads the
    selected text, waits for the model and shows the translation.

    Dependencies are injected (DIP): clipboard, translator access, popup
    actions, a toast function and the history store.
    """

    def __init__(self, clipboard, translator, popup, toast, history, status_text):
        self._clipboard = clipboard
        self._translator = translator
        self._popup = popup
        self._toast = toast
        self._history = history
        self._status_text = status_text
        self._box_queue = queue.Queue()
        self._cancel_event = threading.Event()
        self._translating = False
        self._translating_lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def busy(self):
        with self._translating_lock:
            return self._translating

    def request(self, x, y, width, height, end_x, end_y):
        self.cancel()
        self._box_queue.queue.clear()
        self._box_queue.put((int(x), int(y), int(width), int(height), int(end_x), int(end_y)))

    def cancel(self):
        self._cancel_event.set()
        mod = self._translator.loaded()
        if mod is not None:
            try:
                mod.cancel()
            except Exception:
                pass

    def cancel_all(self):
        self.cancel()
        self._box_queue.queue.clear()

    def _loop(self):
        while True:
            try:
                box = self._box_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._cancel_event.clear()
                text = self._begin(box)
                if text is None:
                    continue
                if not self._wait_for_model():
                    self._popup.hide()
                    continue
                self._handle(box, text)
            except Exception:
                log_exception('worker_loop')
            finally:
                self._end()

    def _begin(self, box):
        with self._translating_lock:
            self._translating = True
        end_x, end_y = box[4], box[5]
        self._popup.hide()
        text = self._clipboard.get_selected_text()
        if not text:
            self._popup.hide()
            self._toast(messages.COPY_FAILED_TEXT)
            return None
        if not self._translator.is_ready():
            mod = self._translator.loaded()
            if mod is not None and mod.needs_reload():
                if status.should_show_status(messages.TRANSLATING_TEXT, config.load()):
                    self._popup.cover()
                    self._popup.show_placeholder(end_x, end_y)
                else:
                    self._popup.ensure()
            else:
                state = self._status_text()
                if state is not None:
                    self._toast(state)
                self._popup.ensure()
        elif status.should_show_status(messages.TRANSLATING_TEXT, config.load()):
            self._popup.cover()
            self._popup.show_placeholder(end_x, end_y)
        else:
            self._popup.ensure()
        return text

    def _end(self):
        with self._translating_lock:
            self._translating = False

    def _wait_for_model(self):
        """Block until the translation model is ready, so queued translations do
        not run while the model is still downloading/initializing. Runs on the
        worker thread, never on the mouse-hook thread."""
        try:
            mod = self._translator.get()
            mod.reset_cancel()
            if mod.needs_reload():
                mod.preload()
            while not mod.is_ready():
                if mod.load_failed():
                    return False
                if self._cancel_event.is_set():
                    return False
                time.sleep(MODEL_WAIT_POLL_SECONDS)
            return True
        except Exception:
            return True

    def _handle(self, box, text):
        end_x, end_y = box[4], box[5]
        translated = self._translate(text)
        if not translated or self._cancel_event.is_set():
            self._popup.hide()
            if not self._cancel_event.is_set():
                self._toast(messages.TRANSLATION_FAILED_TEXT)
            return
        self._popup.show_translation(translated, end_x, end_y)
        self._history.push(translated)

    def _translate(self, text):
        try:
            translated = self._translator.get().translate(text)
        except Exception as e:
            log(f'translate error: {e!r}')
            return None
        if not translated or translated.startswith('[Klaida]'):
            return None
        return translated
