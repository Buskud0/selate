import gc
import os
import threading
import time

os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from transformers import AutoTokenizer, MarianMTModel
import torch

MODEL_NAME = "Helsinki-NLP/opus-mt-tc-big-en-lt"
IDLE_SECONDS = 180

_tokenizer = None
_model = None
_loading_tokenizer = False
_ready = False
_last_used = 0
_in_use = 0
_model_lock = threading.Lock()
_idle_watcher_started = False


def is_ready():
    return _ready and _model is not None


def is_tokenizer_ready():
    return _ready


def ensure_async():
    global _loading_tokenizer
    if _tokenizer is not None or _loading_tokenizer:
        return
    _loading_tokenizer = True
    threading.Thread(target=_load_tokenizer, daemon=True).start()


def _load_tokenizer():
    global _tokenizer, _ready, _loading_tokenizer
    try:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        _ready = True
    except Exception as e:
        print(f"[QuickTranslate] Klaida kraunant tokenizer: {e}")
    _loading_tokenizer = False


def _load_model():
    global _model
    try:
        torch.set_num_threads(2)
        _model = MarianMTModel.from_pretrained(MODEL_NAME, low_cpu_mem_usage=True)
        _model.eval()
        return True
    except Exception as e:
        print(f"[QuickTranslate] Klaida kraunant model: {e}")
        return False


def _unload_model():
    global _model
    with _model_lock:
        if _in_use > 0:
            return
        _model = None
    gc.collect()


def _start_idle_watcher():
    global _idle_watcher_started
    if _idle_watcher_started:
        return
    _idle_watcher_started = True
    def _watch():
        while True:
            time.sleep(30)
            if time.time() - _last_used > IDLE_SECONDS:
                _unload_model()
                break
    t = threading.Thread(target=_watch, daemon=True)
    t.start()


def translate(text):
    global _last_used, _in_use

    if _tokenizer is None:
        _load_tokenizer()
        if _tokenizer is None:
            return "[Klaida] modelis neįdiegtas"

    with _model_lock:
        if _model is None:
            if not _load_model():
                return "[Klaida] modelis neįkeltas"
        _in_use += 1

    _last_used = time.time()
    _start_idle_watcher()

    try:
        with torch.inference_mode():
            batch = _tokenizer([text], return_tensors="pt", padding=True, truncation=True)
            generated = _model.generate(**batch, max_length=512)
            return _tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
    except Exception as e:
        return f"[Klaida] {e}"
    finally:
        with _model_lock:
            _in_use -= 1
