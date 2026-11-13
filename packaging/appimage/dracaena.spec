from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(root / "lib"))
a = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(root / "lib")],
    datas=collect_data_files("dracaena", includes=["**/*.json", "**/*.txt"]),
    hiddenimports=["dracaena.platform.launcher"],
    excludes=["playwright", "tkinter", "PySide6", "PyQt6", "PyQt5", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="dracaena", console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="dracaena")
