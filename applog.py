import os
import threading
import traceback

_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quicktranslate.log")
_LOCK = threading.Lock()


def log(message=""):
    if message and message != "\n":
        message = message.rstrip()
    with _LOCK:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(message + "\n")


def log_exception(where):
    log(f"[{where}]")
    log(traceback.format_exc().rstrip())
