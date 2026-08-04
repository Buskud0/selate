import gc
import os
import threading
import time

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DISABLE_TELEMETRY", "1")


def _limit_cpu_threads():
    n = os.cpu_count() or 4
    return max(1, n // 2)


os.environ.setdefault("RAYON_NUM_THREADS", str(_limit_cpu_threads()))

from transformers import AutoTokenizer, MarianMTModel
from transformers.generation.stopping_criteria import StoppingCriteria
from huggingface_hub import snapshot_download
import torch

torch.set_num_threads(_limit_cpu_threads())
try:
    torch.set_num_interop_threads(_limit_cpu_threads())
except Exception:
    pass

from applog import log

MODEL_NAME = "Helsinki-NLP/opus-mt-tc-big-en-lt"
MODEL_WEIGHTS_BYTES = 472_827_130
DOWNLOAD_POLL_SECONDS = 0.2
MODEL_FILES = (
    'config.json',
    'generation_config.json',
    'model.safetensors',
    'source.spm',
    'special_tokens_map.json',
    'target.spm',
    'tokenizer_config.json',
    'vocab.json',
)
IDLE_SECONDS = 180

_tokenizer = None
_model = None
_ready = False
_last_used = 0
_in_use = 0
_model_lock = threading.Lock()
_idle_watcher_started = False
_cancel_event = threading.Event()
_download_progress = (0, 0)
_download_progress_lock = threading.Lock()
_load_error = None


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


def load_failed():
    return _load_error is not None


def get_download_progress():
    with _download_progress_lock:
        return _download_progress


def _set_download_progress(downloaded, total=MODEL_WEIGHTS_BYTES):
    global _download_progress
    with _download_progress_lock:
        _download_progress = (downloaded, total)


def _model_cache_dir():
    from huggingface_hub.constants import HF_HUB_CACHE
    return os.path.join(
        HF_HUB_CACHE,
        'models--' + MODEL_NAME.replace('/', '--'),
    )


def is_downloaded():
    """Return True if the model files already exist in the HF cache."""
    try:
        snapshots = os.path.join(_model_cache_dir(), 'snapshots')
        if not os.path.isdir(snapshots):
            return False
        for rev in os.listdir(snapshots):
            rev_dir = os.path.join(snapshots, rev)
            if os.path.isdir(rev_dir):
                if all(
                    os.path.isfile(os.path.join(rev_dir, filename))
                    for filename in MODEL_FILES
                ):
                    return True
        return False
    except Exception:
        return False


def _load_tokenizer():
    global _tokenizer, _ready, _load_error
    try:
        _tokenizer = AutoTokenizer.from_pretrained(
            MODEL_NAME,
            local_files_only=True,
        )
        _ready = True
        return True
    except Exception as e:
        _load_error = f'tokenizer load error: {e!r}'
        log(_load_error)
        return False


def _download_model():
    _set_download_progress(0, 0)
    stop_watching = threading.Event()
    watcher = threading.Thread(
        target=_watch_download_progress,
        args=(stop_watching,),
        daemon=True,
    )
    watcher.start()
    try:
        snapshot_download(
            MODEL_NAME,
            allow_patterns=MODEL_FILES,
            max_workers=1,
        )
    finally:
        stop_watching.set()
        watcher.join(timeout=1)


def _watch_download_progress(stop_watching):
    """Watch Hugging Face's growing model file during download."""
    try:
        while not stop_watching.is_set():
            downloaded = _downloaded_model_bytes()
            if downloaded:
                _set_download_progress(downloaded)
            stop_watching.wait(DOWNLOAD_POLL_SECONDS)
    except Exception as e:
        log(f'download progress error: {e!r}')


def _downloaded_model_bytes():
    largest_file = 0
    cache_dir = _model_cache_dir()
    if not os.path.isdir(cache_dir):
        return largest_file
    for directory, _, files in os.walk(cache_dir):
        for filename in files:
            if filename == 'model.safetensors' or filename.endswith('.incomplete'):
                path = os.path.join(directory, filename)
                largest_file = max(largest_file, os.path.getsize(path))
    return largest_file


def _load_model():
    global _model, _load_error
    try:
        torch.set_num_threads(_limit_cpu_threads())
        _model = MarianMTModel.from_pretrained(
            MODEL_NAME,
            low_cpu_mem_usage=True,
            local_files_only=True,
        )
        _model.eval()
        return True
    except Exception as e:
        _load_error = f'model load error: {e!r}'
        log(_load_error)
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
        if not is_downloaded():
            _download_model()
        if _tokenizer is None:
            if not _load_tokenizer():
                return
        with _model_lock:
            if _model is None:
                if not _load_model():
                    return
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
