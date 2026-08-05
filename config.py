import json
import os
import threading

import startup


def get_data_dir():
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'Selate')


CONFIG_DIR = get_data_dir()
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')

DEFAULT_CONFIG = {
    'run_at_startup': False,
    'always_on_top': True,
    'notifications': True,
    'notify_model_checking': False,
    'notify_model_downloading': True,
    'notify_model_initializing': False,
    'notify_selecting': False,
    'notify_translating': True,
    'save_font_size': False,
    'usage_instructions_seen': False,
}

_cache = None
_lock = threading.Lock()


def load():
    """Return the current settings merged over the defaults.

    The result is cached in memory and refreshed on every save().
    """
    with _lock:
        global _cache
        if _cache is None:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    allowed = {k: v for k, v in data.items() if k in DEFAULT_CONFIG}
                    _cache = {**DEFAULT_CONFIG, **allowed}
            except (FileNotFoundError, json.JSONDecodeError):
                _cache = dict(DEFAULT_CONFIG)
                _write(_cache)
        return dict(_cache)


def save(config):
    """Persist the given settings and update the in-memory cache."""
    with _lock:
        global _cache
        normalized = {k: v for k, v in config.items() if k in DEFAULT_CONFIG}
        _cache = {**DEFAULT_CONFIG, **normalized}
        _write(_cache)


def _write(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)
    startup.sync(config.get('run_at_startup', False))
