"""Translation history storage (single responsibility: history)."""

import threading

HISTORY_MAX = 3


class HistoryStore:
    """Thread-safe in-memory history of the last translations."""

    def __init__(self, max_items=HISTORY_MAX):
        self._max = max_items
        self._items = []
        self._current_index = 0
        self._lock = threading.Lock()

    def snapshot(self):
        with self._lock:
            return list(self._items[:self._max])

    def push(self, text):
        with self._lock:
            if self._items and self._items[0] == text:
                return
            self._items.insert(0, text)
            del self._items[self._max:]
        self._current_index = 0

    def update_current(self, text):
        with self._lock:
            if not self._items:
                return
            index = self._current_index
            if index < len(self._items) and self._items[index] != text:
                self._items[index] = text

    def get(self, num):
        with self._lock:
            if num < 1 or num > self._max or len(self._items) < num:
                return None
            return self._items[num - 1]

    def set_current_index(self, index):
        self._current_index = index
