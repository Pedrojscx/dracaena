"""Entry point do projeto com o Chromium incorporado selecionado no AppImage."""
import logging
from pathlib import Path
import sys


def _use_bundled_browser():
    """Aponta o fallback do Playwright para a cópia somente leitura empacotada."""
    if not getattr(sys, "frozen", False):
        return
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "dracaena-browsers"
    if root.is_dir():
        from dracaena.platform import browser
        browser.fallback_dir = lambda: root


_use_bundled_browser()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
from dracaena.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
