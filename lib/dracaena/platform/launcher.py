"""Comando que um atalho do sistema deve executar para alternar o Dracaena."""
from pathlib import Path
import os
import sys


def _inside_our_appimage(environ, frozen, executable):
    """$APPIMAGE só vale se este processo for o nosso AppImage.

    Um $APPIMAGE herdado de outro aplicativo (terminal aberto a partir dele) não conta:
    exige-se build congelado, $APPDIR definido e o executável dentro de $APPDIR.
    """
    appimage, appdir = environ.get("APPIMAGE", ""), environ.get("APPDIR", "")
    if not (frozen and appimage and appdir and os.path.isabs(appimage)):
        return False
    try:
        return Path(executable).resolve().is_relative_to(Path(appdir).resolve())
    except (OSError, RuntimeError):
        return False


def toggle_command(environ=None, frozen=None, executable=None):
    """Retorna o argv de `toggle` conforme o modo de execução.

    Nosso AppImage tem prioridade, depois build congelado (PyInstaller) e, por fim,
    o ambiente de desenvolvimento.
    """
    environ = os.environ if environ is None else environ
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = sys.executable if executable is None else executable
    if _inside_our_appimage(environ, frozen, executable):
        return [environ["APPIMAGE"], "toggle"]
    if frozen:
        return [executable, "toggle"]
    return [executable, "-m", "dracaena.cli", "toggle"]
