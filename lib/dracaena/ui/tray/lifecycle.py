"""Integrações opcionais da UI com a sessão do usuário."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


class SingleInstance:
    """Lock liberado pelo SO, inclusive quando a UI encerra inesperadamente."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = None

    def acquire(self) -> bool:
        if self._file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        try:
            if sys.platform == 'win32':
                import msvcrt
                stream.seek(0, 2)
                if stream.tell() == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self._file = stream
        return True

    def close(self) -> None:
        if self._file is None:
            return
        try:
            if sys.platform == 'win32':
                import msvcrt
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None
        # Não excluir: outro processo pode já ter aberto o mesmo inode.


def set_autostart(enabled: bool, command: list[str], *, config_home: Path | None = None) -> None:
    """Ativa somente por solicitação explícita; não altera serviços do daemon."""
    if not command or any('\n' in arg or '\r' in arg for arg in command):
        raise ValueError('Comando de início automático inválido.')
    if sys.platform == 'win32':
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            if enabled:
                winreg.SetValueEx(key, 'DracaenaUI', 0, winreg.REG_SZ,
                                 subprocess.list2cmdline(command))
            else:
                try:
                    winreg.DeleteValue(key, 'DracaenaUI')
                except FileNotFoundError:
                    pass
        return
    if not sys.platform.startswith('linux'):
        raise RuntimeError('Início automático disponível apenas no Linux e no Windows.')
    root = config_home or Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    path = root / 'autostart' / 'dracaena-ui.desktop'
    if not enabled:
        path.unlink(missing_ok=True)
        return
    def quote(arg: str) -> str:
        # Desktop Entry Exec não usa shell; percentuais são field codes.
        escaped = arg.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
        return '"' + escaped + '"'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[Desktop Entry]\nType=Application\nName=Dracaena\n'
                    'Comment=Assistente Dracaena na bandeja\nExec=' +
                    ' '.join(quote(arg) for arg in command) +
                    '\nTerminal=false\nX-GNOME-Autostart-enabled=true\n', encoding='utf-8')
