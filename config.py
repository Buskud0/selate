import json
import os
import sys
import winreg

APPDATA = os.environ.get('APPDATA', os.path.expanduser('~'))
CONFIG_DIR = os.path.join(APPDATA, 'Selate')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')

DEFAULT_CONFIG = {
    'copy_on_close': True,
    'run_at_startup': False
}


def load():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {**DEFAULT_CONFIG, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        save(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)
    _sync_startup(config.get('run_at_startup', False))


def _sync_startup(enabled):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    name = "Selate"
    if enabled:
        path = _get_exe_path()
        if not path:
            return
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, path)
            winreg.CloseKey(key)
        except Exception:
            pass
    else:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, name)
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        except Exception:
            pass


def _get_exe_path():
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(sys.argv[0])
