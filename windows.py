import io
import json
import os
import subprocess
import sys
import winreg
from pathlib import Path
import win32clipboard
import win32con
import win32event
import win32api

TITLE = "chun PDF"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
CONFIG = Path(os.environ["APPDATA"]) / "chunPDF" / "settings.json"


def prefs():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_prefs(values):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(values), encoding="utf-8")
    os.replace(tmp, CONFIG)


def startup_command():
    exe = [sys.executable]
    if not getattr(sys, "frozen", False):
        exe += [str(Path(__file__).with_name("app.py"))]
    return subprocess.list2cmdline(exe + ["--tray"])


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN) as key:
            return bool(winreg.QueryValueEx(key, "chunPDF")[0])
    except FileNotFoundError:
        return False


def set_autostart(enabled):
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, "chunPDF", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, "chunPDF")
            except FileNotFoundError:
                pass


_activate = None


def single():
    global _activate
    lock = win32event.CreateMutex(None, False, r"Local\chunPDF.MainWindow")
    existing = win32api.GetLastError() == 183
    _activate = win32event.CreateEvent(None, False, False, r"Local\chunPDF.Activate")
    if existing:
        win32event.SetEvent(_activate)
        return None
    return lock


def reactivate():
    return _activate is not None and win32event.WaitForSingleObject(_activate, 0) == 0


def copy_image(image):
    data = io.BytesIO()
    image.convert("RGB").save(data, "BMP")
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_DIB, data.getvalue()[14:])
    finally:
        win32clipboard.CloseClipboard()
