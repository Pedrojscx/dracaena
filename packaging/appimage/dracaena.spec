from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(root / "lib"))
# O Chromium NÃO entra aqui: o PyInstaller analisaria os ELFs dele e empacotaria as
# bibliotecas de desktop da imagem de build (glib, X11, gbm...). container-build.sh copia
# o navegador para _internal/dracaena-browsers depois do congelamento.
datas = (collect_data_files("dracaena", includes=["**/*.json", "**/*.txt", "**/*.js"])
         + collect_data_files("playwright")
         + [(str(root / "prompts" / name), "prompts")
            for name in ("system.txt", "answer.txt", "invalid.txt", "retry.txt")])
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
