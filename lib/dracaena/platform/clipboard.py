"""Clipboard adapters."""
import os
import shutil
import subprocess
import time


def copy(text):
    if os.name == "nt":
        import win32clipboard
        import win32con
        for attempt in range(5):
            try:
                win32clipboard.OpenClipboard()
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(.05)
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        args = ["wl-copy"]
    elif shutil.which("xclip"):
        args = ["xclip", "-selection", "clipboard"]
    else:
        raise RuntimeError("A área de transferência requer wl-copy (Wayland) ou xclip (X11)")
    subprocess.run(args, input=text, text=True, check=True, timeout=5)
