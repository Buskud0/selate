import os
import threading
import traceback

import config


def _log_path():
    data_dir = config.get_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "quicktranslate.log")


_LOG_PATH = _log_path()
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
