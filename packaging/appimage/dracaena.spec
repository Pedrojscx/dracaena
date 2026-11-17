from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(root / "lib"))
browser_dir = Path(os.environ["DRACAENA_BUNDLED_BROWSERS"])
if not browser_dir.is_dir():
    raise SystemExit(f"Chromium incorporado ausente: {browser_dir}")
datas = (collect_data_files("dracaena", includes=["**/*.json", "**/*.txt", "**/*.js"])
         + collect_data_files("playwright")
         + [(str(browser_dir), "dracaena-browsers")])
a = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(root / "lib")],
    datas=datas,
    hiddenimports=["dracaena.platform.launcher", "playwright.sync_api", "playwright._impl._driver"],
    excludes=[ "tkinter", "PySide6", "PyQt6", "PyQt5", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="dracaena", console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="dracaena")
