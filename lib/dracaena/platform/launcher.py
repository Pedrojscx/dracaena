"""Comando que um atalho do sistema deve executar para alternar o Dracaena."""
import os
import sys


def toggle_command(environ=None, frozen=None, executable=None):
    """Retorna o argv de `toggle` conforme o modo de execução.

    AppImage ($APPIMAGE) tem prioridade, depois build congelado (PyInstaller) e,
    por fim, o ambiente de desenvolvimento.
    """
    environ = os.environ if environ is None else environ
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = sys.executable if executable is None else executable
    appimage = environ.get("APPIMAGE", "")
    if appimage and os.path.isabs(appimage):
        return [appimage, "toggle"]
    if frozen:
        return [executable, "toggle"]
    return [executable, "-m", "dracaena.cli", "toggle"]
