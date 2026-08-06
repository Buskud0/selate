"""Startup registry management (single responsibility: OS integration)."""

import ctypes
import os
import sys
import winreg

STARTUP_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REGISTRY_NAME = "Selate"
STARTUP_APPROVED_PATH = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
)

# First byte of the StartupApproved value: 0x02/0x03 = disabled, 0x06 = enabled
# (confirmed against known-enabled entries on Windows 11; 0x07 is not read
# as enabled). The value is 12 bytes: status + 3 zero bytes + FILETIME.
_ENABLED_STATUS = 0x06


def sync(enabled):
    if enabled:
        enable()
    else:
        disable()


def enable():
    path = _get_exe_path()
    if not path:
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, STARTUP_REGISTRY_NAME, 0, winreg.REG_SZ, path)
    except OSError:
        pass
    _set_approved(_approved_data(_ENABLED_STATUS))


def disable():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, STARTUP_REGISTRY_NAME)
    except OSError:
        pass
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, STARTUP_REGISTRY_NAME)
    except OSError:
        pass


def _get_exe_path():
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def _approved_data(status):
    ft = ctypes.c_ulonglong()
    ctypes.windll.kernel32.GetSystemTimeAsFileTime(ctypes.byref(ft))
    return bytes([status]) + b'\x00\x00\x00' + int(ft.value).to_bytes(8, 'little')


def _set_approved(data):
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_PATH)
        try:
            winreg.SetValueEx(key, STARTUP_REGISTRY_NAME, 0, winreg.REG_BINARY, data)
        finally:
            winreg.CloseKey(key)
    except OSError:
        pass
