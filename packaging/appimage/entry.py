"""Entry point do projeto com o Chromium incorporado selecionado no AppImage."""
import logging
import os
from pathlib import Path
import sys


def _restore_library_path():
    """Devolve aos processos filhos o LD_LIBRARY_PATH que o usuário tinha.

    O bootloader do PyInstaller aponta LD_LIBRARY_PATH para as bibliotecas empacotadas
    (construídas sobre a glibc 2.28). Se o Chromium ou outro navegador herdasse isso,
    carregaria, por exemplo, um libglib antigo que não casa com o libpango do host.
    O loader do próprio processo já leu o valor, então só os filhos são afetados.
    """
    if not getattr(sys, "frozen", False):
        return
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        os.environ.pop("LD_LIBRARY_PATH", None)
    else:
        os.environ["LD_LIBRARY_PATH"] = original


def _use_bundled_browser():
    """Aponta o fallback do Playwright para a cópia somente leitura empacotada."""
    if not getattr(sys, "frozen", False):
        return
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "dracaena-browsers"
    if root.is_dir():
        from dracaena.platform import browser
        browser.fallback_dir = lambda: root


_restore_library_path()
_use_bundled_browser()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
from dracaena.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
