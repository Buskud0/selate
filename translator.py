import gc
import os
import threading
import time

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from transformers import AutoTokenizer, MarianMTModel
from transformers.generation.stopping_criteria import StoppingCriteria
import torch

from applog import log

MODEL_NAME = "Helsinki-NLP/opus-mt-tc-big-en-lt"
IDLE_SECONDS = 180

_tokenizer = None
_model = None
_ready = False
_last_used = 0
_in_use = 0
_model_lock = threading.Lock()
_idle_watcher_started = False
_cancel_event = threading.Event()


class _CancelCriteria(StoppingCriteria):
    def __call__(self, input_ids, scores, **kwargs):
        return _cancel_event.is_set()


def is_cancelled():
    return _cancel_event.is_set()


def cancel():
    _cancel_event.set()


def reset_cancel():
    _cancel_event.clear()


def is_ready():
    return _ready and _model is not None


def is_downloaded():
    """Return True if the model files already exist in the HF cache."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        cache_dir = os.path.join(HF_HUB_CACHE, 'models--' + MODEL_NAME.replace('/', '--'))
        snapshots = os.path.join(cache_dir, 'snapshots')
        if not os.path.isdir(snapshots):
            return False
        for rev in os.listdir(snapshots):
            rev_dir = os.path.join(snapshots, rev)
            if os.path.isdir(rev_dir):
                for fname in ('model.safetensors', 'pytorch_model.bin', 'pytorch_model.bin.index.json'):
                    if os.path.isfile(os.path.join(rev_dir, fname)):
                        return True
        return False
    except Exception:
        return False


def _load_tokenizer():
    global _tokenizer, _ready
    try:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        _ready = True
    except Exception as e:
        print(f"[Selate] Klaida kraunant tokenizer: {e}")


def _load_model():
    global _model
    try:
        torch.set_num_threads(min((os.cpu_count() or 4), 8))
        _model = MarianMTModel.from_pretrained(MODEL_NAME, low_cpu_mem_usage=True)
        _model.eval()
        log(f'model loaded on thread {threading.get_ident()}')
        return True
    except Exception as e:
        log(f'model load error: {e!r}')
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


def preload():
    threading.Thread(target=_preload_worker, daemon=True).start()


def _preload_worker():
    try:
        log(f'preload: start thread={threading.get_ident()}')
        if _tokenizer is None:
            _load_tokenizer()
        with _model_lock:
            if _model is None:
                _load_model()
        log(f'preload: done ready={is_ready()}')
    except Exception as e:
        log(f'preload error: {e!r}')


def translate(text):
    global _last_used, _in_use

    if is_cancelled():
        return None

    if _tokenizer is None:
        return "[Klaida] modelis neįdiegtas"

    with _model_lock:
        if _model is None:
            return "[Klaida] modelis neįkeltas"
        _in_use += 1

    _last_used = time.time()
    _start_idle_watcher()

    try:
        parts = text.split('\n')
        translated_parts = []
        for part in parts:
            if is_cancelled():
                return None
            if not part.strip():
                translated_parts.append('')
                continue
            result = _translate_single(part)
            if result is None:
                return None
            translated_parts.append(result)
        result = '\n'.join(translated_parts)
        log(
            f'translate ok ({threading.get_ident()}): '
            f'input_len={len(text)} result_len={len(result)} result={result[:60]!r}'
        )
        return result
    except Exception as e:
        log(f'translate error in translator: {e!r}')
        return f"[Klaida] {e}"
    finally:
        with _model_lock:
            _in_use -= 1


def _translate_single(text):
    with torch.inference_mode():
        batch = _tokenizer([text], return_tensors="pt", padding=True, truncation=True)
        generated = _model.generate(
            **batch,
            max_new_tokens=512,
            num_beams=2,
            no_repeat_ngram_size=4,
            repetition_penalty=1.3,
            stopping_criteria=[_CancelCriteria()],
        )
        return _tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
