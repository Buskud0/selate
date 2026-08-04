$ErrorActionPreference = 'Stop'

py -m pip install pyinstaller
py -m PyInstaller --noconsole --onefile --name Selate --icon selate.ico --add-data "selate.ico;." --collect-all transformers --collect-all huggingface_hub --collect-all torch --collect-all sentencepiece --hidden-import win32api --hidden-import win32con --hidden-import win32gui --hidden-import win32event --hidden-import win32clipboard --hidden-import winerror --hidden-import pywintypes main.py
